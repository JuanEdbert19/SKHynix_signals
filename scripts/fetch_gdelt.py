#!/usr/bin/env python3
"""Backfill GDELT headlines for the sentiment signal.

Separate from run_test.py because this is slow and ban-prone: GDELT allows one
request per five seconds and enforces it by IP block, so a 2019-2026 pull is a
few hundred requests over roughly an hour. Fetching it inline from the dashboard
or the CLI test would make every run hostage to that.

Resumable. Each month is cached to its own parquet, so an interrupted run picks
up where it stopped and a ban costs one month rather than the backfill.

    python scripts/fetch_gdelt.py                     # 2019-01-01 .. 2026-08-06
    python scripts/fetch_gdelt.py --start 2023-01-01  # a shorter window
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from quant import gdelt, signals  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", default=signals.GDELT_QUERY)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-08-06")
    ap.add_argument("--refresh", action="store_true",
                    help="refetch months already cached")
    args = ap.parse_args()

    print(f"query   {args.query!r}")
    print(f"window  {args.start} .. {args.end}")
    print(f"cache   {gdelt.CACHE_DIR / 'gdelt'}\n")

    t0 = time.time()
    arts = gdelt.load_articles(args.query, args.start, args.end, refresh=args.refresh)
    mins = (time.time() - t0) / 60

    if arts.empty:
        print("\nno articles returned")
        return

    print(f"\n{len(arts):,} articles in {mins:.1f} min")
    per_year = arts.set_index("seendate").resample("YE").size()
    print("\narticles per year (the sparsity record — quote this in findings.md):")
    for ts, n in per_year.items():
        days = min(365, (min(ts, pd.Timestamp(args.end, tz='UTC'))
                         - max(ts - pd.offsets.YearEnd(1),
                               pd.Timestamp(args.start, tz='UTC'))).days) or 1
        print(f"   {ts.year}   {n:>6,}   {n/days:>5.1f}/day")

    langs = arts["language"].value_counts().head(4)
    print(f"\nlanguages: {dict(langs)}")
    print(f"unique headlines: {arts['title'].nunique():,} of {len(arts):,} "
          f"({arts['title'].nunique()/len(arts):.0%} — the rest are syndication)")


if __name__ == "__main__":
    main()
