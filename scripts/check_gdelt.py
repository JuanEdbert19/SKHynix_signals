#!/usr/bin/env python3
"""Audit the GDELT cache for gaps, then refetch them.

Two kinds of gap, and only the first is visible from the file listing:

  * A missing month file - the fetch failed and was skipped.
  * A run of days with no articles inside a month that IS cached. Some of these
    are real (coverage was ~1 article/day before 2024, so empty days are
    expected) and some would be truncation. The difference matters: a real gap
    is a NaN signal day, a truncation is silent data loss.

Run with --fetch to refetch missing months. Safe to re-run; cached months are
untouched.

    python scripts/check_gdelt.py
    python scripts/check_gdelt.py --fetch
"""

import argparse
import sys
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
    ap.add_argument("--fetch", action="store_true", help="refetch missing months")
    ap.add_argument("--gap-days", type=int, default=14,
                    help="flag runs of empty days at least this long")
    args = ap.parse_args()

    root = gdelt.CACHE_DIR / "gdelt"
    slug = "".join(c if c.isalnum() else "_" for c in args.query)[:40]
    months = pd.date_range(pd.Timestamp(args.start).normalize().replace(day=1),
                           pd.Timestamp(args.end) - pd.to_timedelta(1, unit="ns"),
                           freq="MS")

    missing = [m for m in months if not (root / f"{slug}_{m:%Y%m}.parquet").exists()]
    print(f"months expected {len(months)}   cached {len(months)-len(missing)}   "
          f"missing {len(missing)}")
    if missing:
        print("  " + ", ".join(f"{m:%Y-%m}" for m in missing))

    if missing and args.fetch:
        print("\nrefetching...")
        gdelt.load_articles(args.query, args.start, args.end)
        missing = [m for m in months
                   if not (root / f"{slug}_{m:%Y%m}.parquet").exists()]
        print(f"\nstill missing after retry: {len(missing)}")
        if missing:
            print("  " + ", ".join(f"{m:%Y-%m}" for m in missing))

    if missing:
        print("\nCannot audit day-level gaps until every month is present.")
        return

    arts = gdelt.load_articles(args.query, args.start, args.end, allow_fetch=False)
    per_day = (arts.set_index("seendate").resample("D").size()
               .reindex(pd.date_range(args.start, args.end, freq="D", tz="UTC"),
                        fill_value=0))
    print(f"\n{len(arts):,} articles over {len(per_day):,} calendar days")
    print(f"days with zero articles: {(per_day == 0).sum():,} "
          f"({(per_day == 0).mean():.0%})")

    # Runs of consecutive empty days - long ones suggest a fetch problem rather
    # than genuinely quiet news.
    empty = per_day == 0
    runs, start = [], None
    for day, is_empty in empty.items():
        if is_empty and start is None:
            start = day
        elif not is_empty and start is not None:
            runs.append((start, day - pd.Timedelta(days=1)))
            start = None
    if start is not None:
        runs.append((start, empty.index[-1]))
    long_runs = [(a, b) for a, b in runs if (b - a).days + 1 >= args.gap_days]

    print(f"\nempty runs of >= {args.gap_days} days: {len(long_runs)}")
    for a, b in long_runs:
        print(f"   {a.date()} .. {b.date()}  ({(b-a).days+1} days)")
    if not long_runs:
        print("   none - remaining empty days are scattered, consistent with "
              "genuinely sparse early coverage")

    print("\narticles/day by year:")
    yearly = per_day.groupby(per_day.index.year).mean()
    for y, v in yearly.items():
        print(f"   {y}   {v:5.1f}/day")


if __name__ == "__main__":
    main()
