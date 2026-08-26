"""Inference for overlapping forward returns.

A 3-day forward return measured on consecutive days shares 2 of its 3 days with
its neighbour, so the residuals are strongly autocorrelated by construction and
ordinary OLS standard errors are badly understated. Every t-statistic and p-value
in this module comes from Newey-West HAC errors with maxlags = horizon. There is
deliberately no other inference path.
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm

ALPHA = 0.05

# Cut defining a "tail" day for tail_test, in transformed-signal units.
#
# CHOSEN AFTER INSPECTING RESULTS - 16 signal x threshold combinations were run
# before this value was picked, so a p-value from it alone overstates the
# evidence (a Bonferroni threshold across those is 0.0031). tail_curve exists as
# the mitigation and is reported alongside it, never instead of it.
TAIL_Z = 2.5
TAIL_GRID = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5)


def _pair(x, y):
    df = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    return df["x"], df["y"]


def rank_ic(sig, fwd):
    """Spearman rank correlation. Descriptive only — no p-value.

    A Spearman p-value would be wrong here (it assumes independent observations,
    which overlapping returns are not), so it is not returned. Inference comes
    from ols_hac.
    """
    x, y = _pair(sig, fwd)
    if len(x) < 10:
        return np.nan
    return float(x.corr(y, method="spearman"))


def ols_hac(y, x, maxlags, standardize=True):
    """Regress y on x with Newey-West standard errors.

    With standardize=True the coefficient reads as "change in y per one
    cross-sectional standard deviation of x", which makes magnitudes comparable
    across transforms.
    """
    xx, yy = _pair(x, y)
    if len(xx) < 30:
        return {"coef": np.nan, "se": np.nan, "t": np.nan, "p": np.nan,
                "n": len(xx), "r2": np.nan, "se_ols": np.nan, "degenerate": False}

    sd = xx.std()
    if standardize and sd > 0:
        xx = xx / sd

    design = sm.add_constant(xx.to_frame("x"))
    fit = sm.OLS(yy, design).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags, "use_correction": True}
    )
    plain = sm.OLS(yy, design).fit()

    r2 = float(fit.rsquared)
    return {
        "coef": float(fit.params["x"]),
        "se": float(fit.bse["x"]),
        "t": float(fit.tvalues["x"]),
        "p": float(fit.pvalues["x"]),
        "n": int(fit.nobs),
        "r2": r2,
        "se_ols": float(plain.bse["x"]),
        # y and x are the same variable up to scale — the t-statistic explodes to
        # a meaningless magnitude. Happens for real in the reverse-causality
        # check when the signal *is* a past return.
        "degenerate": r2 > 1 - 1e-8,
    }


def quantile_table(sig, fwd, q=5):
    """Mean forward return per signal quantile, with standard errors.

    Monotonicity across buckets is stronger evidence than a big top-minus-bottom
    spread, which a single outlier bucket can produce on its own.
    """
    x, y = _pair(sig, fwd)
    if len(x) < q * 5:
        return pd.DataFrame(columns=["bucket", "mean", "se", "n"])

    buckets = pd.qcut(x, q, labels=False, duplicates="drop")
    g = y.groupby(buckets)
    return pd.DataFrame({
        "bucket": [int(b) + 1 for b in g.groups],
        "mean": g.mean().values,
        "se": (g.std() / np.sqrt(g.count())).values,
        "n": g.count().values,
    })


def long_short(sig, fwd, maxlags, q=5):
    """Top-minus-bottom quantile spread, with a HAC t-statistic.

    Fitted as a regression of the forward return on a top/bottom dummy over the
    extreme buckets only, so the spread inherits the same overlap correction as
    every other number here.
    """
    x, y = _pair(sig, fwd)
    if len(x) < q * 10:
        return {"spread": np.nan, "t": np.nan, "p": np.nan, "n": 0}

    buckets = pd.qcut(x, q, labels=False, duplicates="drop")
    top, bottom = buckets.max(), buckets.min()
    mask = buckets.isin([top, bottom])
    dummy = (buckets[mask] == top).astype(float)

    res = ols_hac(y[mask], dummy, maxlags=maxlags, standardize=False)
    return {"spread": res["coef"], "t": res["t"], "p": res["p"], "n": res["n"]}


def tail_test(sig, fwd, maxlags, threshold=TAIL_Z):
    """Mean forward return on high-signal days versus every other day.

    Two deliberate differences from long_short, and both are why this exists:

    One-sided. long_short compares the top quantile against the *bottom* one,
    which is the right test for a monotonic relationship. If instead the
    hypothesis is "a spike moves the stock", quiet days are the absence of a
    spike rather than its opposite, so the comparison is tail vs everything.

    Full sample. long_short discards the middle 60%; this keeps every day, so
    n_tail + n_rest equals the n reported elsewhere.
    """
    x, y = _pair(sig, fwd)
    dummy = (x > threshold).astype(float)
    n_tail = int(dummy.sum())
    if n_tail < 20 or n_tail == len(x):
        return {"excess": np.nan, "t": np.nan, "p": np.nan,
                "n_tail": n_tail, "n_rest": len(x) - n_tail}

    res = ols_hac(y, dummy, maxlags=maxlags, standardize=False)
    return {"excess": res["coef"], "t": res["t"], "p": res["p"],
            "n_tail": n_tail, "n_rest": len(x) - n_tail}


def tail_curve(sig, fwd, maxlags, thresholds=TAIL_GRID):
    """tail_test across a grid of cuts.

    Not a convenience wrapper. TAIL_Z was chosen after inspecting results, so a
    single p-value from it overstates the evidence; showing the whole curve is
    what lets a reader see whether the chosen cut sits on a plateau or on a
    lone spike. It is rendered unconditionally for that reason.
    """
    rows = [{"threshold": t, **tail_test(sig, fwd, maxlags, threshold=t)}
            for t in thresholds]
    return pd.DataFrame(rows)


def reverse_causality(sig, past, maxlags=3):
    """Does price predict the signal? Regress the signal on trailing returns.

    Attention data typically chases price. If this direction is the stronger of
    the two, a forward-looking result is more likely reflecting feedback than
    prediction.
    """
    out = {}
    for col in past.columns:
        out[col] = ols_hac(sig, past[col], maxlags=maxlags)
    return out


def evaluate(panel, horizon=3, target="fwd_ret", q=5, tail_z=TAIL_Z):
    """The headline result for one specification.

    One horizon, one target, one transform — the specification is fixed before
    running rather than scanned, so there is no multiple-comparison correction
    here to make.
    """
    sig = panel["signal"]
    fwd = panel[f"{target}_{horizon}"]
    # Argument order matters: forward return is the dependent variable. The
    # t-statistic is symmetric under a swap, so a reversed call produces
    # plausible-looking t's off a meaningless regression. Nothing in this
    # function's output would reveal it — test_evaluate_regresses_return_on_
    # signal_not_the_reverse inspects the call arguments instead.
    reg = ols_hac(fwd, sig, maxlags=horizon)
    ls = long_short(sig, fwd, maxlags=horizon, q=q)
    tail = tail_test(sig, fwd, maxlags=horizon, threshold=tail_z)
    return {
        "horizon": horizon,
        "target": target,
        "ic": rank_ic(sig, fwd),
        "t_hac": reg["t"],
        "p_hac": reg["p"],
        "ls_spread": ls["spread"],
        "ls_t": ls["t"],
        "ls_p": ls["p"],
        # The long-short test runs on the extreme buckets only, so its sample is
        # much smaller than `n`. Reporting the spread beside the full-sample n
        # implies it was measured on all of it.
        "ls_n": ls["n"],
        # Tail: one-sided, full sample. Exploratory - see TAIL_Z.
        "tail_z": tail_z,
        "tail_excess": tail["excess"],
        "tail_t": tail["t"],
        "tail_p": tail["p"],
        "tail_n": tail["n_tail"],
        "n": reg["n"],
    }
