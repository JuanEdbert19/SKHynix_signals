"""Map signal timestamps onto KRX trading dates.

This is the only module in the project that does timezone arithmetic. Prices are
keyed by naive KST trading dates; signals arrive in UTC and run 24h a day, 365
days a year. Getting this join wrong produces look-ahead bias that is completely
invisible downstream — the numbers still look reasonable — so all of the risk is
deliberately concentrated in one small tested function.

A signal value is attributed to trading day t if its timestamp falls in
(close(t-1), close(t)], where close is 15:30 KST. Weekend and holiday activity
therefore accumulates into the next session, which is the first moment it could
have been traded on.
"""

import pandas as pd

KST = "Asia/Seoul"
# pd.to_timedelta rather than pd.Timedelta("15h30m"): the latter emits a numpy
# timedelta DeprecationWarning under numpy 2.
CLOSE = pd.to_timedelta(15 * 60 + 30, unit="m")


def session_closes(trading_days):
    """UTC timestamps of the 15:30 KST close for each trading day."""
    naive = pd.DatetimeIndex(trading_days).tz_localize(None).normalize() + CLOSE
    return naive.tz_localize(KST).tz_convert("UTC")


def daily_utc_to_timestamps(sig):
    """A series keyed by UTC calendar date -> tz-aware timestamps at each day's
    closing edge, ready for align_to_trading_days.

    A daily count covers 00:00-24:00 UTC, so it is not knowable until the day
    ends. Stamping it at 00:00 UTC of the *next* day is therefore the earliest
    instant it could be acted on, and align_to_trading_days then attributes UTC
    day D to trading day D+1 (or the next session after a weekend or holiday).

    The +1 day is load-bearing. Without it, UTC day D is stamped inside day D and
    lands on trading day D — attributing a full 24h count, 17.5h of which occur
    after the 06:30 UTC close, to a day whose forward return it then predicts.
    That is look-ahead, and nothing downstream would reveal it.
    """
    idx = pd.DatetimeIndex(sig.index).tz_localize("UTC") + pd.to_timedelta(1, unit="D")
    return pd.Series(sig.to_numpy(), index=idx, name=sig.name)


def align_to_trading_days(sig, trading_days, agg="sum"):
    """Aggregate a UTC-timestamped signal onto the KRX trading calendar.

    agg: "sum" for counts, "mean" for levels.

    Observations at or before the first session close are dropped — that day's
    window has no defined start, so keeping it would let an arbitrary amount of
    prior history land in a single bucket. Observations after the last close are
    dropped for the same reason.
    """
    sig = sig.sort_index()
    days = pd.DatetimeIndex(trading_days).tz_localize(None).normalize()

    if sig.index.tz is None:
        # Already keyed by trading date; nothing to convert.
        return sig.reindex(days)

    closes = session_closes(days)
    ts = sig.index.tz_convert("UTC")

    # First close >= ts, i.e. the session this observation could first be acted on.
    pos = closes.searchsorted(ts, side="left")
    keep = (pos > 0) & (pos < len(closes))
    sig, pos = sig[keep], pos[keep]

    assigned = days[pos]
    grouped = sig.groupby(assigned)
    out = grouped.sum() if agg == "sum" else grouped.mean()

    _assert_no_lookahead(sig, assigned, days, closes)
    return out.reindex(days)


def _assert_no_lookahead(sig, assigned, days, closes):
    latest = sig.index.tz_convert("UTC").to_series(index=assigned).groupby(level=0).max()
    limit = pd.Series(closes, index=days).reindex(latest.index)
    bad = latest > limit
    if bad.any():
        raise AssertionError(
            f"look-ahead in alignment: {int(bad.sum())} trading day(s) were assigned "
            f"observations timestamped after their own 15:30 KST close, "
            f"first offender {latest.index[bad][0].date()}"
        )
