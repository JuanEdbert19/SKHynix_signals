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
    ap.add_argument("--signal", choices=sorted(signals.SIGNALS))
    ap.add_argument("--combine", metavar="ATTENTION,SENTIMENT",
                    help="multiplicative combination of two registered signals: "
                         "attention enters as a trailing percentile rank in [0,1], "
                         "sentiment supplies the sign. Alternative to --signal.")
    ap.add_argument("--transform", default=None, choices=panel_mod.TRANSFORMS,
                    help="default is per-signal; 'zscore' for count-style signals")
    ap.add_argument("--horizon", type=int, default=panel_mod.HORIZON)
    ap.add_argument("--target", default="fwd_ret", choices=["fwd_ret", "fwd_exret"])
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-08-06")
    ap.add_argument("--window", type=int, default=20, help="z-score baseline window")
    ap.add_argument("--quantiles", type=int, default=5)
    ap.add_argument("--tail-z", type=float, default=stats.TAIL_Z, dest="tail_z",
                    help="outlier cut for the tail test, in transformed-signal units")
    args = ap.parse_args()
    if bool(args.signal) == bool(args.combine):
        ap.error("give exactly one of --signal or --combine")

    px = prices.load_prices(start=args.start, end=args.end)
    kospi = prices.load_index(start=args.start, end=args.end)

    if args.combine:
        # The Combine tab picks its pair in the UI, so nothing is registered in
        # SIGNALS. This flag is what keeps a combined result reproducible from
        # the repo rather than existing only on screen.
        parts = [s.strip() for s in args.combine.split(",")]
        if len(parts) != 2:
            ap.error("--combine takes exactly two signal names, comma-separated")
        att_name, sen_name = parts
        for n in parts:
            if n not in signals.SIGNALS:
                ap.error(f"unknown signal {n!r}; available: {sorted(signals.SIGNALS)}")
        att = panel_mod.transform(
            signals.load_signal(att_name, px, kospi),
            kind=signals.DEFAULT_TRANSFORM.get(att_name, "zscore"),
            window=args.window)
        sen = panel_mod.transform(
            signals.load_signal(sen_name, px, kospi),
            kind=signals.DEFAULT_TRANSFORM.get(sen_name, "raw"),
            window=args.window)
        sig = panel_mod.combine(att, sen, window=args.window)
        args.signal = f"combine({att_name}x{sen_name})"
        tkind = "raw"   # the product is already bounded and stationary
    else:
        tkind = args.transform or signals.DEFAULT_TRANSFORM.get(args.signal, "zscore")
        sig = signals.load_signal(args.signal, px, kospi)

    pnl = panel_mod.build_panel(px, sig, transform_kind=tkind, window=args.window,
                                kospi=kospi, horizon=args.horizon)
    res = stats.evaluate(pnl, horizon=args.horizon, target=args.target,
                         q=args.quantiles, tail_z=args.tail_z)
    curve = stats.tail_curve(pnl["signal"], pnl[f"{args.target}_{args.horizon}"],
                             maxlags=args.horizon)
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

    print(f"\ntail test — days with signal > {args.tail_z:g} vs all others")
    print(f"  excess ret    {res['tail_excess']:+.4f}")
    print(f"  HAC t         {res['tail_t']:+.2f}")
    print(f"  HAC p         {res['tail_p']:.4f}")
    print(f"  tail days     {int(res['tail_n']):,} of {int(res['n']):,}")

    print("\n  event metrics")
    print(f"    events        {int(res['ev_n_events']):,} vs {int(res['ev_n_rest']):,} others")
    print(f"    mean return   {res['ev_mean_event']:+.4f} on events, "
          f"{res['ev_mean_rest']:+.4f} otherwise")
    print(f"    hit rate      {res['ev_hit_rate']:.1%} vs {res['ev_base_rate']:.1%} baseline "
          f"(diff {res['ev_hit_diff']:+.1%}, t={res['ev_hit_t']:+.2f}, "
          f"p={res['ev_hit_p']:.4f})")
    print(f"    baseline      median return on non-event days = {res['ev_median_rest']:+.4f}")
    print(f"    mean |return| {res['ev_abs_ratio']:.2f}x that of other days "
          "(descriptive, untested)")

    print("\n  threshold sensitivity (the cut was chosen after inspecting results,")
    print("  so judge it against this column, not on its own):")
    print("     cut   excess       t        p   tail   rest")
    for row in curve.to_dict(orient="records"):
        print(f"    {row['threshold']:4.2f}  {row['excess']:+.4f}  {row['t']:+6.2f}  "
              f"{row['p']:7.4f}  {int(row['n_tail']):5d}  {int(row['n_rest']):5d}")

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
        "tail_curve": curve.to_dict(orient="records"),
        "reverse_causality": rev,
        "run_utc": stamp,
    }, indent=2, default=float))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
