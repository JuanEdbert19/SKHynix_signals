#!/usr/bin/env python3
"""Measure what a candidate GDELT query would buy, before backfilling it.

A full 2019-2026 backfill is roughly 24 hours of rate-limited requests, and the
sentiment signal's dominant defect is too few headlines per day (median 4, which
leaves ~70% of the daily mean as sampling noise). Adding queries is the only fix
that attacks that directly - but only if the query actually returns on-topic
articles at volume, and nothing in the repo said which candidates do.

This samples three months per query instead of ninety, so the decision costs
minutes rather than a day. It reports articles/day and on-topic share ONLY.
Deliberately no return relationship: queries are chosen on coverage, before the
specification is frozen, so that choice cannot leak into the test.

    python scripts/probe_gdelt.py
    python scripts/probe_gdelt.py --queries "DRAM" "NAND flash"
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from quant import gdelt, sentiment, signals  # noqa: E402

# One month per regime: pre-boom, the HBM ramp, and recent. A query that only
# looks good in 2026 is a query whose history cannot support the sample.
SAMPLE_MONTHS = ("2021-03-01", "2024-03-01", "2026-03-01")

CANDIDATES = ("DRAM", "NAND flash", "SK Hynix", "memory chip", "semiconductor memory")


def probe(query, months):
    rows = []
    for m in months:
        m0 = pd.Timestamp(m)
        m1 = m0 + pd.offsets.MonthBegin(1)
        arts = gdelt.load_articles(query, m0, m1)
        if arts.empty:
            rows.append({"month": m0.strftime("%Y-%m"), "n": 0, "per_day": 0.0,
                         "on_topic": float("nan"), "english": float("nan")})
            continue
        clean = arts["title"].map(sentiment.clean_headline)
        rows.append({
            "month": m0.strftime("%Y-%m"),
            "n": len(arts),
            "per_day": len(arts) / m0.days_in_month,
            "on_topic": clean.str.contains(signals.ON_TOPIC).mean(),
            "english": (arts["language"].str.lower() == "english").mean(),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queries", nargs="+", default=list(CANDIDATES))
    ap.add_argument("--months", nargs="+", default=list(SAMPLE_MONTHS))
    args = ap.parse_args()

    print(f"sampling {len(args.months)} month(s) per query: {', '.join(args.months)}")
    print(f"on-topic regex: {signals.ON_TOPIC.pattern[:70]}...\n")

    summary = []
    for q in args.queries:
        print(f"--- {q!r}")
        df = probe(q, args.months)
        for _, r in df.iterrows():
            print(f"    {r['month']}  {int(r['n']):>4} articles  "
                  f"{r['per_day']:>5.1f}/day  on-topic {r['on_topic']:>6.1%}  "
                  f"english {r['english']:>6.1%}")
        summary.append({"query": q, "per_day": df["per_day"].mean(),
                        "on_topic": df["on_topic"].mean(),
                        "usable_per_day": (df["per_day"] * df["on_topic"]).mean()})

    out = pd.DataFrame(summary).sort_values("usable_per_day", ascending=False)
    print("\n=== ranked by ON-TOPIC articles per day (what actually reduces noise) ===")
    print(f"{'query':<24}{'art/day':>9}{'on-topic':>10}{'usable/day':>12}")
    for _, r in out.iterrows():
        print(f"{r['query']:<24}{r['per_day']:>9.1f}{r['on_topic']:>10.1%}"
              f"{r['usable_per_day']:>12.1f}")

    print(f"\ncurrent {signals.GDELT_QUERIES[0]!r} sits at ~4 on-topic/day.")
    print("A candidate worth 24h of backfill should add meaningfully to that;")
    print("one that overlaps heavily on url will add far less than it appears to.")


if __name__ == "__main__":
    main()
