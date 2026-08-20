"""Daily Wikipedia pageviews as an attention signal.

Chosen over tweet counts because no free tweet source exists: the Internet
Archive Spritzer now requires an account, stops at 2023-01 and has 125 missing
days, and every other option is priced out or censors its own peaks. See
data-sources.md.

The advantage is not merely availability. Pageviews are a *census* — every view
counted, none sampled — so unlike a 1% sample there is no Poisson error and no
scaling factor, and a low-volume topic stays measurable. Coverage over
2019-2026 is complete: zero missing days across every article used here.

What it measures is people looking a company up, not people discussing it.
That is a related but distinct construct from tweet volume.

Series here are keyed by UTC calendar date. Converting them to trading dates is
quant.align's job, not this module's.
"""

import pandas as pd

from quant.cache import CACHE_DIR, cached

API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

# Wikimedia rejects requests without a descriptive User-Agent.
UA = "SKHynix-attention-research/0.1 (852healthkare@gmail.com)"

ARTICLES = {
    "hynix": ("en.wikipedia", "SK_Hynix"),
    "semi": ("en.wikipedia", "Semiconductor"),
    "hbm": ("en.wikipedia", "High_Bandwidth_Memory"),
    # Korean editions carry 4-14x less traffic, so small moves are integer
    # noise. Kept available but not registered as signals.
    "hynix_ko": ("ko.wikipedia", "SK하이닉스"),
    "semi_ko": ("ko.wikipedia", "반도체"),
}

# The signal for trading day t comes from the UTC day before it, so the fetch
# must start early enough to cover the longest Korean market closure (Seollal
# and Chuseok run 3-5 days).
LEAD_DAYS = 10


def load_pageviews(key, start, end):
    """Daily pageviews for one article, keyed by UTC calendar date.

    Returns a Series over every calendar day in the range. Days the API omits
    come back as NaN rather than 0 — an outage is not the same as nobody
    reading the article, and it must stay visible downstream.
    """
    if key not in ARTICLES:
        raise KeyError(f"unknown article {key!r}; available: {sorted(ARTICLES)}")

    project, article = ARTICLES[key]
    first = pd.Timestamp(start).normalize() - pd.to_timedelta(LEAD_DAYS, unit="D")
    last = pd.Timestamp(end).normalize()
    path = CACHE_DIR / f"wiki_{key}_{first.date()}_{last.date()}.parquet"

    def fetch():
        import json
        import urllib.parse
        import urllib.request

        url = (f"{API}/{project}/all-access/user/"
               f"{urllib.parse.quote(article, safe='')}/daily/"
               f"{first:%Y%m%d}/{last:%Y%m%d}")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        items = json.load(urllib.request.urlopen(req, timeout=60))["items"]
        raw = pd.Series(
            {pd.Timestamp(i["timestamp"][:8]): i["views"] for i in items},
            dtype="float64",
        ).sort_index()
        return raw.reindex(pd.date_range(first, last, freq="D")).to_frame("views")

    out = cached(path, fetch)["views"]
    out.index.name = "date"
    return out.rename(key)
