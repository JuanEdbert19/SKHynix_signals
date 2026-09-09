"""Forward-return targets and signal transforms.

Everything here obeys one rule: a column dated t may only use information
available at the 15:30 KST close of t. The `fwd_*` target columns are the sole
exception — they are deliberately forward-looking, which is what makes them
targets, and they are never used as inputs to a transform.
"""

from typing import NamedTuple

import numpy as np
import pandas as pd

HORIZON = 3

# Fewest observations a rolling baseline may be computed from. Both a mean and a
# standard deviation are estimated from it, and the sd is what makes a z-score
# explode when it collapses toward zero.
MIN_BASELINE = 10


def add_targets(px, kospi=None, horizon=HORIZON):
    """Forward return and forward excess return over `horizon` trading days.

    Returns a frame indexed like `px` with the price columns plus:
      fwd_ret_{h}     log return from close(t) to close(t+h)
      fwd_exret_{h}   the same minus the KOSPI log return over the same window
                      (beta = 1 assumed, not estimated)
    """
    out = px.copy()
    logc = np.log(out["close"])
    out["ret"] = logc.diff()

    out[f"fwd_ret_{horizon}"] = logc.shift(-horizon) - logc

    if kospi is not None:
        mkt = np.log(kospi["close"].reindex(out.index)).diff()
        out["mkt_ret"] = mkt
        mkt_fwd = mkt.rolling(horizon).sum().shift(-horizon)
        out[f"fwd_exret_{horizon}"] = out[f"fwd_ret_{horizon}"] - mkt_fwd

    return out


def transform(sig, kind="zscore", window=20, min_periods=None):
    """Apply a stationarity transform to a raw signal series.

    kind:
      raw          as-is, for signals that are already stationary
      zscore       abnormality vs a rolling baseline that EXCLUDES today
      dow_zscore   same, but the baseline is the same weekday only

    Without min_periods pandas requires the window to be entirely non-NaN, which
    silently guts any signal with gaps: gdelt_sent_semi has values on 1,435 of
    1,865 trading days, and a bare rolling(20) left 393 of them - 73% of the
    available days discarded, with nothing in the output saying so.

    The default is MIN_BASELINE, capped at the window itself. A window already
    at or below that floor is required in full rather than relaxed, because the
    cure would be worse than the disease: dow_zscore's window is 4 same-weekday
    observations, and methodology.md records it reaching z = +124.7 when that sd
    collapses. Allowing 2 makes the sd |x1-x2|/sqrt(2), which is not a baseline.
    So zscore(20) relaxes to 10 and dow_zscore keeps its full 4 - the gap bug is
    a long-window problem and the fix is confined to long windows.
    """
    if kind == "raw":
        return sig.astype(float)
    if kind == "zscore":
        mp = min_periods if min_periods is not None else min(window, MIN_BASELINE)
        # .shift(1) is load-bearing: without it day t sits in its own baseline,
        # which leaks the very deviation the z-score is meant to measure.
        base = sig.rolling(window, min_periods=mp).mean().shift(1)
        sd = sig.rolling(window, min_periods=mp).std().shift(1)
        return (sig - base) / sd.replace(0.0, np.nan)
    if kind == "dow_zscore":
        # For a signal accumulated between market closes, Monday's bucket spans
        # the weekend while Tuesday's spans one day. Against a mixed baseline
        # Monday clears the bar nearly every week: with plain zscore, 83.5% of
        # top-quintile days were Mondays (20% would be neutral) and mean z by
        # weekday ranged over 2.09. Comparing each weekday only against recent
        # values of the same weekday removes that; the same measurements come
        # back at 19.5% and 0.35.
        #
        # window is in trading days, so window // 5 same-weekday observations
        # span the same calendar period as the plain zscore baseline.
        n = max(window // 5, 2)
        mp = min_periods if min_periods is not None else min(n, MIN_BASELINE)
        out = {}
        for _, g in sig.groupby(sig.index.dayofweek):
            base = g.rolling(n, min_periods=mp).mean().shift(1)
            sd = g.rolling(n, min_periods=mp).std().shift(1)
            out[_] = (g - base) / sd.replace(0.0, np.nan)
        return pd.concat(out.values()).sort_index()
    raise ValueError(f"unknown transform: {kind}")


TRANSFORMS = ("raw", "zscore", "dow_zscore")


def build_panel(px, sig, transform_kind="zscore", window=20, kospi=None,
                horizon=HORIZON):
    """Assemble targets plus the transformed signal into one aligned frame.

    `sig` must already be keyed by trading date — see quant.align.
    """
    panel = add_targets(px, kospi=kospi, horizon=horizon)
    panel["signal_raw"] = sig.reindex(panel.index)
    panel["signal"] = transform(
        panel["signal_raw"], kind=transform_kind, window=window
    )
    return panel


COMBINE_RULES = ("product", "linear", "linear_wf")

# Walk-forward fit of the linear rule's weight. See walk_forward_weight.
WF_WINDOW = 200    # most observations one fit may use
WF_MIN_OBS = 60    # fewest before any weight is emitted
WF_CLIP = 2.0      # matches the manual slider's range

# Per-rule defaults for the two legs and the weight. They differ by rule because
# the rules need different things from sentiment, which is the whole reason the
# transform is picked per signal rather than per pair:
#
#   product  wants `raw` sentiment. With the rank gone, two centred inputs make
#            negative x negative read positive on ~24% of days; raw sentiment is
#            positive on 77% of them, so the sign stays meaningful. This pairing
#            is also the only product variant that kept a testable tail
#            (22 days above z=2.5, against 1 for a centred sentiment).
#
#   linear   wants `zscore` sentiment. Addition has no sign-inversion problem,
#            and a centred arm is what makes `weight` interpretable as relative
#            importance rather than as a shift.
#
# Set by the developer on 2026-08-30. Both are starting points in the UI, not
# fixed specifications - run_test.py takes explicit flags for a recorded result.
#   linear_wf  same arms as linear, but `weight` is fitted rather than set, so
#            the entry carries None. A caller seeing None must call
#            walk_forward_weight; there is no sensible fallback number.
COMBINE_DEFAULTS = {
    "product": {"attention": "dow_zscore", "sentiment": "raw", "weight": 0.0},
    "linear": {"attention": "dow_zscore", "sentiment": "zscore", "weight": 1.0},
    "linear_wf": {"attention": "dow_zscore", "sentiment": "zscore", "weight": None},
}


def combine(attention, sentiment, window=20, rule="product", weight=0.0):
    """Fold an attention signal and a sentiment signal into one series.

    Both rules return NaN wherever either input is missing. The combination of a
    known sentiment and an unknown attention is unknown, not zero.

    `product` - a plain elementwise product of the two transformed signals.

      Attention used to enter as trailing_pct_rank(attention) in [0, 1] so that
      sentiment always supplied the sign. That was removed on 2026-08-30 by the
      developer's call, having measured what the rank was costing: it flattened
      attention's kurtosis from 49 to -1 and left the product with ONE day above
      z=2.5 on 2023+, so the tail test could not run at all. Without it the
      product keeps attention's fat tail (22 such days).

      Two consequences the rank existed to prevent are now live, and are the
      price of that. Negative x negative reads positive, on ~24% of days with
      two centred inputs, so "low attention plus bad news" scores like "high
      attention plus good news" - choose a `raw` sentiment transform if the sign
      should stay meaningful. And one day can dominate: dow_zscore reaches
      +38.9, giving a single observation ~82x the median magnitude.

    `linear` / `linear_wf` - z(attention) + weight * z(sentiment), SIGNED.
      One expression serves both rules, which is deliberate: it is what makes a
      weight fitted by walk_forward_weight mean exactly what a weight set on the
      slider means. They differ only in where `weight` comes from, and
      `linear_wf` passes a Series rather than a float - one weight per day,
      aligned on the index, NaN through the burn-in.
      The sign matters because the two signals were measured pointing opposite
      ways: on their own top-25 days attention ran +0.94% and sentiment -0.97%,
      at a mutual correlation of -0.03. A non-negative weight makes them cancel,
      which is what the product cannot express and this can. weight = 0 reduces
      exactly to attention alone, which is what makes a weight sweep readable.

      Each arm is put on a common scale by _unit_scale first, or `weight` would
      not mean what it says: the transforms produce very different spreads, and
      dow_zscore leaves attention around sd 3.2 against a zscore's 1.1.

    Known limitation, measured rather than assumed: attention's effect lives in
    a fat tail (kurtosis 9.9) and sentiment is near-Gaussian (0.4), so ANY
    blending thins the tail the effect depends on - a 50/50 linear mix left 5
    outlier days above z=2.5 where attention alone had 26. See methodology.md.

    Neither rule transforms its inputs. Both arrive already transformed by the
    caller, which is what makes the per-signal transform pickers meaningful -
    and is why an earlier version standardising them here was double-counting.
    """
    if rule not in COMBINE_RULES:
        raise ValueError(f"unknown rule {rule!r}; expected one of {COMBINE_RULES}")

    if rule == "product":
        both = pd.concat([attention.rename("a"), sentiment.rename("s")], axis=1)
        return (both["a"] * both["s"]).rename("combined")

    both = pd.concat([_unit_scale(attention).rename("a"),
                      _unit_scale(sentiment).rename("s")], axis=1)
    return (both["a"] + weight * both["s"]).rename("combined")


def walk_forward_weight(attention, sentiment, fwd, horizon=1, window=WF_WINDOW,
                        min_obs=WF_MIN_OBS, clip=WF_CLIP):
    """Fit the linear rule's sentiment weight from history only, one w per day.

    Regresses the forward return on both arms and returns the ratio of their
    coefficients, so the result plugs straight into `combine(rule="linear_wf")`
    and reads on the same scale as the manual slider:

        fwd ~ c + b_a * a + b_s * s        ->        w = b_s / b_a

    Fitted on the UNIT-SCALED arms, because those are what `combine` adds. A
    ratio fitted on the untransformed arms would be in the wrong units, and
    dow_zscore attention runs at sd ~3.2 against a zscore's ~1.1, so the error
    would be a factor of three rather than a rounding difference.

    Only rows whose forward return had already been REALISED are eligible: a
    fwd_ret_h dated d is first known at the close of d+h, so day t may fit on
    rows with d + h <= t and no others. That inequality is the whole difference
    between a walk-forward weight and a look-ahead one, and is pinned by tests
    at h=1 and h=3.

    The window is capped at `window` observations rather than expanding, at the
    developer's request: behaviour in the early years differs enough that a
    2019 observation should not still be steering a 2026 weight. With the
    default 200 the cap first binds on 2024-03-15. `min_obs` is what decides
    when the series starts - only 74 usable rows exist before 2023, so 60 is
    what gets a weight in place (2022-11-25) before the 2023-01-01 sample the
    results are reported on, without demanding data that is not there.

    Two guards, because a ratio of two noisy coefficients is not bounded:
      b_a <= 0   -> w = 0, i.e. fall back to attention alone. A non-positive
                   attention coefficient means the fit has lost the arm the
                   weight is expressed relative to, and the ratio's sign stops
                   meaning anything.
      otherwise  -> clip to +/-clip. How often this binds is the diagnostic
                   that says whether the ratio form is usable at all; both
                   callers report it.
    """
    df = pd.concat([_unit_scale(attention).rename("a"),
                    _unit_scale(sentiment).rename("s"),
                    fwd.rename("y")], axis=1).dropna()

    cal = attention.index
    if df.empty:
        return pd.Series(np.nan, index=cal, name="w")

    # Position on the trading calendar, not the calendar date: `horizon` counts
    # trading days, so the eligibility test has to as well.
    pos = pd.Series(np.arange(len(cal)), index=cal).reindex(df.index).to_numpy()
    design = np.column_stack([np.ones(len(df)), df["a"], df["s"]])
    y = df["y"].to_numpy()

    out = np.full(len(cal), np.nan)
    k = 0  # rows of df realised as of the current day
    for i in range(len(cal)):
        while k < len(pos) and pos[k] + horizon <= i:
            k += 1
        if k < min_obs:
            continue
        lo = max(0, k - window)
        beta = np.linalg.lstsq(design[lo:k], y[lo:k], rcond=None)[0]
        b_a, b_s = beta[1], beta[2]
        out[i] = 0.0 if b_a <= 0 else float(np.clip(b_s / b_a, -clip, clip))

    return pd.Series(out, index=cal, name="w")


def weight_summary(w, clip=WF_CLIP):
    """Descriptive summary of a fitted weight series, for the app and the CLI.

    `clipped` and `zeroed` are the ones that matter: they say how often the
    ratio needed rescuing rather than estimating.
    """
    x = w.dropna()
    if x.empty:
        return {"n": 0, "first": None, "mean": np.nan, "min": np.nan,
                "max": np.nan, "clipped": np.nan, "zeroed": np.nan}
    return {
        "n": int(len(x)),
        "first": x.index[0],
        "mean": float(x.mean()),
        "min": float(x.min()),
        "max": float(x.max()),
        "clipped": float((x.abs() >= clip - 1e-12).mean()),
        "zeroed": float((x == 0.0).mean()),
    }


class AssemblyResult(NamedTuple):
    pnl: pd.DataFrame
    tkind: str
    att: object   # pd.Series | None — transformed attention leg (combined path)
    sen: object   # pd.Series | None — transformed sentiment leg (combined path)
    weight: object  # pd.Series | float | None — weight used (combined path)
    wsum: object    # dict | None — weight diagnostics (linear_wf only)


def assemble_signal(
    px,
    kospi,
    *,
    sig=None,
    tkind="zscore",
    att=None,
    sen=None,
    combine_rule="product",
    att_t=None,
    sen_t=None,
    combine_weight=None,
    window=20,
    horizon=HORIZON,
):
    """Assemble a ready-to-analyse panel behind a single call.

    Single-signal path: pass `sig` and `tkind`. Returns the panel from
    build_panel.

    Combined path: pass `att` and `sen` (raw Series keyed by trading date),
    plus combine options. Transforms each leg, optionally fits the
    walk-forward weight, combines, and calls build_panel.

    Returns an AssemblyResult. att/sen/weight/wsum are None on the
    single-signal path.
    """
    if sig is not None:
        pnl = build_panel(px, sig, transform_kind=tkind, window=window,
                          kospi=kospi, horizon=horizon)
        return AssemblyResult(pnl, tkind, None, None, None, None)

    d = COMBINE_DEFAULTS[combine_rule]
    att_t = att_t or d["attention"]
    sen_t = sen_t or d["sentiment"]
    att_s = transform(att, kind=att_t, window=window)
    sen_s = transform(sen, kind=sen_t, window=window)

    wsum = None
    if combine_rule == "linear_wf":
        fwd = add_targets(px, kospi=kospi, horizon=horizon)[f"fwd_ret_{horizon}"]
        weight = walk_forward_weight(att_s, sen_s, fwd, horizon=horizon)
        wsum = weight_summary(weight)
    else:
        weight = d["weight"] if combine_weight is None else combine_weight

    combined_sig = combine(att_s, sen_s, window=window,
                           rule=combine_rule, weight=weight)
    pnl = build_panel(px, combined_sig, transform_kind="raw",
                      window=window, kospi=kospi, horizon=horizon)
    return AssemblyResult(pnl, "raw", att_s, sen_s, weight, wsum)


def _unit_scale(sig):
    """Rescale to ~unit variance using history only.

    Both inputs arrive already transformed by their registered DEFAULT_TRANSFORM,
    so running a rolling zscore here standardises them TWICE - which it did:
    sentiment was z-scored by the caller and again inside combine. What `weight`
    needs is not a second abnormality measure but a common SCALE, because
    dow_zscore leaves attention at sd ~3.2 against sentiment's ~1.1. Under the
    old code the two arms still ended up at sd 1.89 and 1.18, so a slider set to
    0.50 gave sentiment an effective weight of 0.31.

    Expanding rather than a whole-sample std: a global constant would peek at
    the full sample. It only changes units and never the ordering within a day,
    but the .shift(1) in transform exists for exactly this reason, and this is
    not the place to start an exception.
    """
    sd = sig.expanding(min_periods=MIN_BASELINE).std()
    return sig / sd.replace(0.0, np.nan)


def describe(sig):
    """Shape of a signal's distribution, before any return is involved.

    Kurtosis earns its place here: dow_zscore has a 4-observation baseline whose
    standard deviation occasionally collapses, producing values like z = +124.7
    with kurtosis in the hundreds. That is what makes the HAC t outlier-sensitive
    while rank IC is not, and a reader should meet it while looking at the signal
    rather than infer it from a sign-flipping t-statistic. See methodology.md.
    """
    x = sig.dropna().astype(float)
    if x.empty:
        keys = ("n", "mean", "sd", "skew", "kurtosis", "min", "p01", "p50", "p99", "max")
        return dict.fromkeys(keys, np.nan) | {"n": 0}
    return {
        "n": int(len(x)),
        "mean": float(x.mean()),
        "sd": float(x.std()),
        "skew": float(x.skew()),
        "kurtosis": float(x.kurtosis()),
        "min": float(x.min()),
        "p01": float(x.quantile(0.01)),
        "p50": float(x.median()),
        "p99": float(x.quantile(0.99)),
        "max": float(x.max()),
    }


def coverage(sig, min_gap=3):
    """Where a signal actually has data, and where it does not.

    `first`/`last` are the real extent of the source, which can be much narrower
    than the requested window - a sample period set wider than the data just
    produces NaN, and nothing else in the output says so.
    """
    have = sig.notna()
    return {
        "first": sig.index[have.argmax()] if have.any() else None,
        "last": sig.index[len(have) - 1 - have.to_numpy()[::-1].argmax()]
                if have.any() else None,
        "n_have": int(have.sum()),
        "n_total": len(sig),
        "gaps": missing_runs(sig, min_len=min_gap),
    }


def missing_runs(sig, min_len=3):
    """Stretches of consecutive trading days where a signal has no value.

    Scattered NaNs are ordinary for a sparse source - GDELT news runs about one
    article a day before 2024, so many single days are genuinely empty. A long
    *run* is different in kind: it means the source has nothing for a period,
    and any window spanning it is measuring fewer days than it appears to.
    Surfaced so a sample period can be chosen around it rather than over it.
    """
    missing = sig.isna().to_numpy()
    idx = sig.index
    runs, start = [], None
    for i, gap in enumerate(missing):
        if gap and start is None:
            start = i
        elif not gap and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(missing) - 1))

    rows = [{"from": idx[a], "to": idx[b], "trading_days": b - a + 1,
             "calendar_days": (idx[b] - idx[a]).days + 1}
            for a, b in runs if b - a + 1 >= min_len]
    return pd.DataFrame(rows, columns=["from", "to", "trading_days",
                                       "calendar_days"])


def past_returns(panel, lags=(1, 3)):
    """Trailing cumulative returns, for the reverse-causality check."""
    logc = np.log(panel["close"])
    return pd.DataFrame(
        {f"past_ret_{k}": logc - logc.shift(k) for k in lags}, index=panel.index
    )
