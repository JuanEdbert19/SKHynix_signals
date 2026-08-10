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


SIGNALS = {
    "noise": noise,
    "planted": planted,
    "past_return": past_return,
}

# Counts are aggregated by sum when aligned; level-like signals by mean.
SIGNAL_AGG = {"noise": "mean", "planted": "mean", "past_return": "mean"}

# The three fixtures are already stationary, so their natural transform is the
# identity. Count-style signals (tweet volume, search volume) should default to
# "zscore" — abnormality vs a rolling baseline — because raw counts on a growing
# platform are non-stationary enough to produce a trend that looks like signal.
DEFAULT_TRANSFORM = {"noise": "raw", "planted": "raw", "past_return": "raw"}


def load_signal(name, px, kospi=None, **kwargs):
    if name not in SIGNALS:
        raise KeyError(f"unknown signal {name!r}; available: {sorted(SIGNALS)}")
    return SIGNALS[name](px, kospi, **kwargs)
