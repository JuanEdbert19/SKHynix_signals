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

from quant import align, wiki

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


SIGNALS = {
    "noise": noise,
    "planted": planted,
    "past_return": past_return,
    "wiki_hynix": wiki_hynix,
    "wiki_semi": wiki_semi,
    "wiki_hbm": wiki_hbm,
}

# Counts are aggregated by sum when aligned; level-like signals by mean.
SIGNAL_AGG = {"noise": "mean", "planted": "mean", "past_return": "mean",
              "wiki_hynix": "sum", "wiki_semi": "sum", "wiki_hbm": "sum"}

# The three fixtures are already stationary, so their natural transform is the
# identity. Count-style signals (tweet volume, search volume) should default to
# "zscore" — abnormality vs a rolling baseline — because raw counts on a growing
# platform are non-stationary enough to produce a trend that looks like signal.
DEFAULT_TRANSFORM = {"noise": "raw", "planted": "raw", "past_return": "raw",
                     "wiki_hynix": "zscore", "wiki_semi": "zscore",
                     "wiki_hbm": "zscore"}


def load_signal(name, px, kospi=None, **kwargs):
    if name not in SIGNALS:
        raise KeyError(f"unknown signal {name!r}; available: {sorted(SIGNALS)}")
    return SIGNALS[name](px, kospi, **kwargs)
