"""Signal registry.

A signal is a function of (px, kospi) returning a Series keyed by trading date.
Real signals get added as new entries in SIGNALS; there is no plugin machinery.

The three entries below exist to validate the framework, not to answer the
research question. `noise` must come back null and `planted` must come back
detected — until both hold, a null result on a real signal cannot be
distinguished from a broken pipeline.
"""

import numpy as np
import pandas as pd

from quant import align, naver, wiki

PLANTED_RHO = 0.15
PLANTED_HORIZON = 3


def noise(px, kospi=None, seed=0):
    """Pure iid noise. Expected result: no significant relationship at any horizon."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.standard_normal(len(px)), index=px.index, name="noise")


def planted(px, kospi=None, seed=0, rho=PLANTED_RHO, horizon=PLANTED_HORIZON):
    """TEST FIXTURE — contains look-ahead by construction. Never a finding.

    Built as rho * standardize(future h-day return) + sqrt(1-rho^2) * noise, so
    it is known to predict the h-day forward return with correlation ~rho. Its
    only purpose is to confirm the harness can detect an effect of known size.
    """
    logc = np.log(px["close"])
    fwd = (logc.shift(-horizon) - logc)
    z = (fwd - fwd.mean()) / fwd.std()

    rng = np.random.default_rng(seed + 1)
    eps = pd.Series(rng.standard_normal(len(px)), index=px.index)

    sig = rho * z + np.sqrt(1 - rho**2) * eps
    return sig.rename("planted")


def past_return(px, kospi=None, lookback=3):
    """Trailing 3-day return as a signal.

    Not synthetic. Tests the machinery against short-horizon reversal — a real,
    documented effect — and gives the reverse-causality check something it should
    fire loudly on.
    """
    logc = np.log(px["close"])
    return (logc - logc.shift(lookback)).rename("past_return")


def _pageview_signal(px, key, name):
    """Wikipedia pageviews for one article, mapped onto KRX trading days.

    The date window comes from the price panel because load_signal receives no
    --start/--end; that is a gap in the calling code, not a design choice.
    """
    raw = wiki.load_pageviews(key, px.index[0], px.index[-1])
    stamped = align.daily_utc_to_timestamps(raw)
    return align.align_to_trading_days(
        stamped, px.index, agg=SIGNAL_AGG[name]
    ).rename(name)


def wiki_hynix(px, kospi=None):
    """Pageviews of en:SK_Hynix. The primary real signal.

    Company-specific attention, which is the question this project set out to
    ask. Fixed as primary before running; wiki_semi and wiki_hbm are secondary.
    """
    return _pageview_signal(px, "hynix", "wiki_hynix")


def wiki_semi(px, kospi=None):
    """Pageviews of en:Semiconductor. Secondary — industry attention.

    A much flatter series than wiki_hynix (CV 0.32 vs 1.02, max only 4x its
    median vs 36x), so it measures broad slow interest rather than news spikes.
    """
    return _pageview_signal(px, "semi", "wiki_semi")


def wiki_hbm(px, kospi=None):
    """Pageviews of en:High_Bandwidth_Memory. Secondary — product-story attention."""
    return _pageview_signal(px, "hbm", "wiki_hbm")


def _naver_signal(px, key, name):
    """One Naver search-trend series, mapped onto KRX trading days.

    Same shape as _pageview_signal, but the source is keyed by KST calendar date
    rather than UTC, so it goes through the KST stamping function.
    """
    raw = naver.load_trend(key)
    stamped = align.daily_kst_to_timestamps(raw)
    return align.align_to_trading_days(
        stamped, px.index, agg=SIGNAL_AGG[name]
    ).rename(name)


def naver_hynix(px, kospi=None):
    """Naver searches for SK Hynix. The primary real signal.

    Keyword group includes `주가` variants and the ticker 000660, so this is
    investor lookup rather than general curiosity — the construct wiki_hynix
    was reaching for and missing.
    """
    return _naver_signal(px, "hynix", "naver_hynix")


def naver_semi(px, kospi=None):
    """Naver searches for 반도체 and related. Secondary — industry attention.

    One day dominates its scale: 2019-05-01 sits at 100.0 against 58.8 for the
    next highest.
    """
    return _naver_signal(px, "semi", "naver_semi")


def naver_hbm(px, kospi=None):
    """Naver searches for HBM. Secondary — product-story attention.

    Keyword composition shifts over the sample: HBM3/HBM3E/HBM4 have no volume
    before each generation existed, so expect a transient around each launch
    until the rolling baseline catches up.
    """
    return _naver_signal(px, "hbm", "naver_hbm")


def naver_memory(px, kospi=None):
    """Naver searches for DRAM/NAND. Secondary — the earnings driver.

    Memory pricing is what actually moves SK Hynix earnings, so this is the
    most fundamentally motivated of the industry terms and has no Wikipedia
    counterpart.
    """
    return _naver_signal(px, "memory", "naver_memory")


def naver_samsung(px, kospi=None):
    """Naver searches for Samsung Electronics. CONTROL — never a finding.

    Registered so it is inspectable, not so it can be tested. Sector-wide
    Korean attention hits both stocks; company-specific attention does not.

    Note it correlates 0.86 with naver_hynix on a same-weekday baseline (0.93 on
    weekday-only log changes) against 0.42 for the Wikipedia equivalents, so it
    is nearly collinear with the primary and differencing leaves a thin residual.
    """
    return _naver_signal(px, "samsung", "naver_samsung")


SIGNALS = {
    "noise": noise,
    "planted": planted,
    "past_return": past_return,
    "wiki_hynix": wiki_hynix,
    "wiki_semi": wiki_semi,
    "wiki_hbm": wiki_hbm,
    "naver_hynix": naver_hynix,
    "naver_semi": naver_semi,
    "naver_hbm": naver_hbm,
    "naver_memory": naver_memory,
    "naver_samsung": naver_samsung,
}

# Counts are aggregated by sum when aligned; level-like signals by mean.
#
# The pageview signals use "mean" despite being counts. Summing makes Monday's
# bucket (Fri+Sat+Sun) 2.3x every other day, which is a property of the calendar
# rather than of attention. Mean gives average daily attention since the last
# close, which is comparable across weekdays. Paired with the dow_zscore
# transform below - neither fixes the artifact alone.
#
# The Naver signals use "mean" for the same reason, and need it more: weekend
# search runs at 12.4% of weekday search, so Monday's Fri+Sat+Sun bucket is
# depressed rather than inflated - the mirror of the pageview artifact.
SIGNAL_AGG = {"noise": "mean", "planted": "mean", "past_return": "mean",
              "wiki_hynix": "mean", "wiki_semi": "mean", "wiki_hbm": "mean",
              "naver_hynix": "mean", "naver_semi": "mean", "naver_hbm": "mean",
              "naver_memory": "mean", "naver_samsung": "mean"}

# The three fixtures are already stationary, so their natural transform is the
# identity. Count-style signals (tweet volume, search volume) should default to
# "zscore" — abnormality vs a rolling baseline — because raw counts on a growing
# platform are non-stationary enough to produce a trend that looks like signal.
#
# The Naver signals must use dow_zscore, not merely should: under plain zscore
# Monday's share of the top quintile measures 0.0% - Monday can never register
# as high attention - against 21.2% under dow_zscore, where 20% is neutral.
# "raw" is meaningless for them regardless; they are a 0-100 index, not a count.
DEFAULT_TRANSFORM = {"noise": "raw", "planted": "raw", "past_return": "raw",
                     "wiki_hynix": "dow_zscore", "wiki_semi": "dow_zscore",
                     "wiki_hbm": "dow_zscore",
                     "naver_hynix": "dow_zscore", "naver_semi": "dow_zscore",
                     "naver_hbm": "dow_zscore", "naver_memory": "dow_zscore",
                     "naver_samsung": "dow_zscore"}


def load_signal(name, px, kospi=None, **kwargs):
    if name not in SIGNALS:
        raise KeyError(f"unknown signal {name!r}; available: {sorted(SIGNALS)}")
    return SIGNALS[name](px, kospi, **kwargs)
