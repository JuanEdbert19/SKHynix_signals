"""Signal registry.

A signal is a function of (px, kospi) returning a Series keyed by trading date.
Real signals get added as new entries in SIGNALS; there is no plugin machinery.

The three entries below exist to validate the framework, not to answer the
research question. `noise` must come back null and `planted` must come back
detected — until both hold, a null result on a real signal cannot be
distinguished from a broken pipeline.
"""

import re

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


def gdelt_sent_semi(px, kospi=None):
    """FinBERT sentiment of semiconductor news headlines. SECONDARY.

    The first signal here measuring sentiment rather than attention, and the
    first whose source carries a real timestamp: GDELT's `seendate` is a full
    UTC instant, so articles go straight into align_to_trading_days with no
    daily rounding and no stamping function.

    Query is "HBM memory", not "SK Hynix": GDELT matches the article body but
    returns only the title, so a company query yields headlines about other
    companies that mention SK Hynix in passing (15% of titles named it, against
    58% on-topic for the industry query). What this measures is therefore
    international semiconductor sentiment, not SK Hynix sentiment.

    Registered against fwd_exret rather than fwd_ret - see CLAUDE.md.
    """
    from quant import sentiment

    arts = load_gdelt_articles(px.index[0], px.index[-1])
    if arts.empty:
        return pd.Series(np.nan, index=px.index, name="gdelt_sent_semi")
    scored = pd.Series(sentiment.score_headlines(arts["title"]).to_numpy(),
                       index=pd.DatetimeIndex(arts["seendate"]))
    return align.align_to_trading_days(
        scored, px.index, agg=SIGNAL_AGG["gdelt_sent_semi"]
    ).rename("gdelt_sent_semi")


# Queries are pooled, not alternatives. The signal's dominant defect is too few
# headlines per day - the median day had 4, leaving ~70% of the daily mean as
# sampling noise (reliability 0.30, and 0.14 once syndicated duplicates are
# removed). More on-topic articles per day is the only fix that attacks that
# rather than averaging around it. Candidates were chosen by
# scripts/probe_gdelt.py on coverage alone, before the specification was frozen.
GDELT_QUERIES = ("HBM memory",)

# Which headlines belong to the construct. GDELT matches the article *body* but
# returns only the title, so a body-relevant match routinely arrives as a title
# about something else: 30.5% of the corpus was off-topic - Radeon GPU reviews,
# TikTok, CAE toolkits - and only 13.2% named SK Hynix at all. Filtering to this
# vocabulary raised reliability from 0.30 to 0.48, the single largest measured
# improvement. See methodology.md.
ON_TOPIC = re.compile(
    r"hynix|hbm|dram|nand|memory|micron|samsung|semiconductor|chip|"
    r"foundry|tsmc|wafer|nvidia",
    re.I,
)


def load_gdelt_articles(start, end, allow_fetch=False):
    """Pooled, filtered headlines for the sentiment signal.

    allow_fetch=False by default: the backfill is hundreds of rate-limited
    requests and belongs to scripts/fetch_gdelt.py. Without it, opening the
    dashboard would start one.

    Two filters, both correctness rather than taste. Non-English articles (2.6%)
    are scored by an English-only model, which collapses them toward neutral
    (sd 0.05-0.18 against 0.53 for English) and dilutes the daily mean. Off-topic
    articles are noise in the construct by definition.
    """
    from quant import gdelt

    frames = [gdelt.load_articles(q, start, end, allow_fetch=allow_fetch)
              for q in GDELT_QUERIES]
    arts = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if arts.empty:
        return arts
    # Pooled queries overlap heavily - the same article matches "HBM memory" and
    # "DRAM" - and a duplicate would weight that story once per query it hit.
    arts = arts.drop_duplicates("url").sort_values("seendate").reset_index(drop=True)

    clean = arts["title"].map(_clean_title)
    keep = (arts["language"].str.lower() == "english") & clean.str.contains(ON_TOPIC)
    return arts[keep].reset_index(drop=True)


def _clean_title(t):
    from quant import sentiment

    return sentiment.clean_headline(t)

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
    "gdelt_sent_semi": gdelt_sent_semi,
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
              "naver_memory": "mean", "naver_samsung": "mean",
              # Sentiment is a mean of scores, not a count, so Monday's
              # three-day bucket is not mechanically biased the way the
              # attention signals are. Measured before choosing below.
              "gdelt_sent_semi": "mean"}

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
                     "naver_samsung": "dow_zscore",
                     # Was "raw" and marked PROVISIONAL. Two measurements settled
                     # it. First, raw is not centred: FinBERT scores this corpus
                     # positive on 86% of days (mean +0.199), which makes the
                     # tail test's `lower` and `both` sides meaningless and
                     # breaks combine()'s premise that sentiment supplies a sign.
                     # zscore centres it to ~50%. Second, plain zscore rather
                     # than dow_zscore because the weekday diagnostic came back
                     # clean - a mean of bounded scores does not accumulate
                     # between closes, so Monday's three-day bucket carries no
                     # mechanical bias. This default was unusable until
                     # panel.transform grew min_periods; see methodology.md.
                     "gdelt_sent_semi": "zscore"}


def load_signal(name, px, kospi=None, **kwargs):
    if name not in SIGNALS:
        raise KeyError(f"unknown signal {name!r}; available: {sorted(SIGNALS)}")
    return SIGNALS[name](px, kospi, **kwargs)
