"""Forward-return targets and signal transforms.

Everything here obeys one rule: a column dated t may only use information
available at the 15:30 KST close of t. The `fwd_*` target columns are the sole
exception — they are deliberately forward-looking, which is what makes them
targets, and they are never used as inputs to a transform.
"""

import numpy as np
import pandas as pd

HORIZON = 3


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


def transform(sig, kind="zscore", window=20):
    """Apply a stationarity transform to a raw signal series.

    kind:
      raw          as-is, for signals that are already stationary
      zscore       abnormality vs a rolling baseline that EXCLUDES today
      dow_zscore   same, but the baseline is the same weekday only
    """
    if kind == "raw":
        return sig.astype(float)
    if kind == "zscore":
        # .shift(1) is load-bearing: without it day t sits in its own baseline,
        # which leaks the very deviation the z-score is meant to measure.
        base = sig.rolling(window).mean().shift(1)
        sd = sig.rolling(window).std().shift(1)
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
        out = {}
        for _, g in sig.groupby(sig.index.dayofweek):
            base = g.rolling(n).mean().shift(1)
            sd = g.rolling(n).std().shift(1)
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
