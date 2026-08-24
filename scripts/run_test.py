#!/usr/bin/env python3
"""Run the signal test from the command line and record the result.

Every number the dashboard shows comes from these same functions, so anything on
screen can be reproduced with one of these commands. The JSON written to
results/ is the reproducibility record for anything quoted in an analysis.

    python scripts/run_test.py --signal planted
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant import panel as panel_mod  # noqa: E402
from quant import prices, signals, stats  # noqa: E402

RESULTS = ROOT / "results"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signal", required=True, choices=sorted(signals.SIGNALS))
    ap.add_argument("--transform", default=None, choices=panel_mod.TRANSFORMS,
                    help="default is per-signal; 'zscore' for count-style signals")
    ap.add_argument("--horizon", type=int, default=panel_mod.HORIZON)
    ap.add_argument("--target", default="fwd_ret", choices=["fwd_ret", "fwd_exret"])
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-08-06")
    ap.add_argument("--window", type=int, default=20, help="z-score baseline window")
    ap.add_argument("--quantiles", type=int, default=5)
    args = ap.parse_args()

    tkind = args.transform or signals.DEFAULT_TRANSFORM.get(args.signal, "zscore")

    px = prices.load_prices(start=args.start, end=args.end)
    kospi = prices.load_index(start=args.start, end=args.end)
    sig = signals.load_signal(args.signal, px, kospi)

    pnl = panel_mod.build_panel(px, sig, transform_kind=tkind, window=args.window,
                                kospi=kospi, horizon=args.horizon)
    res = stats.evaluate(pnl, horizon=args.horizon, target=args.target,
                         q=args.quantiles)
    qt = stats.quantile_table(pnl["signal"], pnl[f"{args.target}_{args.horizon}"],
                              q=args.quantiles)
    rev = stats.reverse_causality(pnl["signal"], panel_mod.past_returns(pnl))

    print(f"\nsignal={args.signal}  transform={tkind}  target={args.target}  "
          f"horizon={args.horizon}")
    print(f"sample={pnl.index[0].date()}..{pnl.index[-1].date()}  "
          f"trading days={len(pnl)}")

    print(f"\n  rank IC       {res['ic']:+.4f}")
    print(f"  HAC t         {res['t_hac']:+.2f}")
    print(f"  HAC p         {res['p_hac']:.4f}")
    print(f"  top-bottom    {res['ls_spread']:+.4f}  (t={res['ls_t']:+.2f}  "
          f"p={res['ls_p']:.4f}  n={int(res['ls_n']):,} extreme-bucket days)")
    print(f"  observations  {res['n']:,}")
    print("\n  " + ("significant at p<0.05" if res["p_hac"] < stats.ALPHA
                    else "no significant relationship"))

    print("\nmean forward return by signal quantile")
    for row in qt.to_dict(orient="records"):
        print(f"  q{int(row['bucket'])}  mean={row['mean']:+.5f}  "
              f"se={row['se']:.5f}  n={int(row['n'])}")

    print("\nreverse causality — does past price predict the signal?")
    for k, v in rev.items():
        if v["degenerate"]:
            print(f"  {k:<12} identity — the signal IS this variable (R²=1)")
        else:
            print(f"  {k:<12} t_hac={v['t']:+.2f}  p={v['p']:.4f}")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{args.signal}_{tkind}_{args.target}_{stamp}.json"
    out.write_text(json.dumps({
        "params": {**vars(args), "transform": tkind},
        "sample": {"start": str(pnl.index[0].date()), "end": str(pnl.index[-1].date()),
                   "trading_days": len(pnl)},
        "result": res,
        "quantiles": qt.to_dict(orient="records"),
        "reverse_causality": rev,
        "run_utc": stamp,
    }, indent=2, default=float))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
