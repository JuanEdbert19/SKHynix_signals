"""Forward-return targets and signal transforms.

Everything here obeys one rule: a column dated t may only use information
available at the 15:30 KST close of t. The `fwd_*` target columns are the sole
exception — they are deliberately forward-looking, which is what makes them
targets, and they are never used as inputs to a transform.
"""

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


COMBINE_RULES = ("product", "linear")

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
COMBINE_DEFAULTS = {
    "product": {"attention": "dow_zscore", "sentiment": "raw", "weight": 0.0},
    "linear": {"attention": "dow_zscore", "sentiment": "zscore", "weight": 1.0},
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

    `linear` - z(attention) + weight * z(sentiment), `weight` SIGNED.
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
