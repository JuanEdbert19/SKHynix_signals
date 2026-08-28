"""News headlines from the GDELT DOC 2.0 API.

GDELT hands back only the article *title* — there is no body field and no
parameter that returns one. That constrains what a sentiment signal built on it
can be, and it decides the query: matching is done against the article body, so
a company query like "SK Hynix" returns headlines about Amazon that mention the
company in passing (15% of titles named it, measured 2026-08-26), while an
industry query returns headlines that are on-topic for an industry construct
without naming anyone (58%). See data-sources.md.

Two API behaviours drive the design here, and both fail silently if ignored:

  * maxrecords caps at 250 and the API returns the *most recent* within the
    window, so a fixed date chunk quietly loses articles in busy periods. The
    fetcher halves its window and recurses whenever it sees a full page.
  * The rate limit is one request per five seconds, enforced by IP ban, and the
    refusal comes back as plain text with a 200 status. Parsing it as data, or
    treating a non-empty response as success, silently caches nothing useful.
"""

import json
import time
import urllib.parse
import urllib.request

import pandas as pd

from quant.cache import CACHE_DIR

API = "https://api.gdeltproject.org/api/v2/doc/doc"
MAXRECORDS = 250
# The refusal body is plain text with a 200 status, not an error code.
LIMIT_MARK = "Please limit requests"
# Documented limit is 1 request / 5s; 6 leaves headroom without being slow.
SPACING_S = 6.0
# Observed in practice: GDELT throttles harder during a sustained backfill than
# the documented 1-req/5s implies, so the backoff is long and the retry count
# generous. A month that still fails after this is skipped, not fatal.
BACKOFF_S = 60.0
MAX_TRIES = 8
# A window narrower than this returning a full page means the day itself is
# busier than the cap, which no amount of halving fixes. Reported, not hidden.
MIN_WINDOW_H = 6

COLUMNS = ["seendate", "title", "domain", "language", "url"]


def _get(query, start, end):
    """One API call. Returns a list of articles, or None if it never got through."""
    params = urllib.parse.urlencode({
        "query": query, "mode": "artlist", "maxrecords": MAXRECORDS,
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
        "sort": "datedesc", "format": "json",
    })
    for _ in range(MAX_TRIES):
        time.sleep(SPACING_S)
        try:
            with urllib.request.urlopen(f"{API}?{params}", timeout=120) as r:
                body = r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(BACKOFF_S)
            continue
        if LIMIT_MARK in body or not body.lstrip().startswith("{"):
            time.sleep(BACKOFF_S)
            continue
        return json.loads(body).get("articles", [])
    return None


def _walk(query, start, end, out):
    """Fetch [start, end), splitting the window whenever the page comes back full.

    A full page means the window was truncated, and because results are sorted
    newest-first the lost articles are the oldest ones - a silent left-censoring
    that would look like low news volume in the early part of every chunk.
    """
    arts = _get(query, start, end)
    if arts is None:
        raise RuntimeError(f"GDELT unreachable for {start:%Y-%m-%d}..{end:%Y-%m-%d}")

    # pd.to_timedelta rather than pd.Timedelta(hours=...): the latter emits a
    # numpy timedelta DeprecationWarning under numpy 2, same as in align.py.
    if len(arts) >= MAXRECORDS and (end - start) > pd.to_timedelta(MIN_WINDOW_H, unit="h"):
        mid = start + (end - start) / 2
        _walk(query, start, mid, out)
        _walk(query, mid, end, out)
        return

    if len(arts) >= MAXRECORDS:
        print(f"  WARNING {start:%Y-%m-%d %H:%M} +{MIN_WINDOW_H}h still full at "
              f"{MAXRECORDS} records; older articles in this window are lost")
    out.extend(arts)


def load_articles(query, start, end, refresh=False, allow_fetch=True):
    """Headlines for `query` over [start, end), cached one parquet per month.

    Chunked by month rather than fetched whole so a ban or a crash costs one
    month, not the whole backfill. A 2019-2026 pull is hundreds of requests.

    allow_fetch=False reads the cache and raises on a gap. Signals use it: the
    dashboard picks a default signal on load, and with this one sorting first
    alphabetically, an inline fetch would start an hour of rate-limited network
    traffic just from opening the page. Backfilling is scripts/fetch_gdelt.py's
    job, not a side effect of rendering a chart.
    """
    root = CACHE_DIR / "gdelt"
    root.mkdir(parents=True, exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in query)[:40]

    # end is exclusive: without the nudge, an end that lands on a month start
    # (2024-07-01) would fetch all of July for a June-only request.
    months = pd.date_range(pd.Timestamp(start).normalize().replace(day=1),
                           pd.Timestamp(end) - pd.to_timedelta(1, unit="ns"),
                           freq="MS")
    frames, failed = [], []
    for m0 in months:
        m1 = m0 + pd.offsets.MonthBegin(1)
        path = root / f"{slug}_{m0:%Y%m}.parquet"
        if path.exists() and not refresh:
            frames.append(pd.read_parquet(path))
            continue
        if not allow_fetch:
            raise FileNotFoundError(
                f"no cached GDELT articles for {m0:%Y-%m} ({path.name}). "
                f"Backfill first:  python scripts/fetch_gdelt.py "
                f"--start {m0:%Y-%m-%d}"
            )

        got = []
        try:
            _walk(query, m0, m1, got)
        except RuntimeError as exc:
            # Skip and keep going: one throttled month must not cost the other
            # ninety. Nothing is written, so a re-run retries it, and the
            # analysis path (allow_fetch=False) refuses a missing month outright
            # rather than letting the gap read as "no news that month".
            failed.append(m0)
            print(f"  {m0:%Y-%m}: SKIPPED — {exc}")
            continue
        df = pd.DataFrame(got, columns=None if got else COLUMNS)
        if not df.empty:
            df = df.reindex(columns=COLUMNS)
            df["seendate"] = pd.to_datetime(df["seendate"], format="%Y%m%dT%H%M%SZ",
                                            utc=True)
            df = df.drop_duplicates("url").sort_values("seendate")
        df.to_parquet(path)
        print(f"  {m0:%Y-%m}: {len(df):,} articles")
        frames.append(df)

    if failed:
        print(f"\n  {len(failed)} month(s) unfetched: "
              f"{', '.join(f'{m:%Y-%m}' for m in failed)}")
        print("  Re-run the same command to retry only those.")

    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    if out.empty:
        return out
    out = out.drop_duplicates("url").sort_values("seendate").reset_index(drop=True)
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC")
    return out[(out["seendate"] >= lo) & (out["seendate"] < hi)].reset_index(drop=True)
