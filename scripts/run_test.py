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
                    help="combination of two registered signals. Alternative to "
                         "--signal; see --combine-rule for how they are folded.")
    ap.add_argument("--combine-rule", default="product", dest="combine_rule",
                    choices=panel_mod.COMBINE_RULES,
                    help="product: the two transformed signals multiplied. "
                         "linear: z(attention) + w*z(sentiment), w signed and "
                         "set by --combine-weight. linear_wf: the same sum with "
                         "w fitted walk-forward by OLS on history only.")
    ap.add_argument("--att-transform", default=None, dest="att_transform",
                    choices=panel_mod.TRANSFORMS,
                    help="transform for the attention leg of --combine; "
                         "default is per rule, see panel.COMBINE_DEFAULTS")
    ap.add_argument("--sen-transform", default=None, dest="sen_transform",
                    choices=panel_mod.TRANSFORMS,
                    help="transform for the sentiment leg of --combine; "
                         "default is per rule. `raw` keeps the product's sign "
                         "meaningful, a centred one makes neg x neg positive")
    ap.add_argument("--combine-weight", type=float, default=None,
                    dest="combine_weight",
                    help="SIGNED coefficient on sentiment for --combine-rule "
                         "linear. 0 reduces to attention alone; negative is "
                         "meaningful, the two signals were measured pointing "
                         "opposite ways. Ignored by the product rule. Default "
                         "is per rule, see panel.COMBINE_DEFAULTS.")
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

    wsum = None
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
        if args.combine_rule == "linear_wf" and args.combine_weight is not None:
            ap.error("--combine-weight cannot be used with --combine-rule "
                     "linear_wf; the weight is fitted, not set")
        # Defaults come from the rule, not the signal: the two rules need
        # different things from sentiment. One source of truth with the app.
        d = panel_mod.COMBINE_DEFAULTS[args.combine_rule]
        att_t = args.att_transform or d["attention"]
        sen_t = args.sen_transform or d["sentiment"]
        weight = None if args.combine_rule == "linear_wf" else (
            d["weight"] if args.combine_weight is None else args.combine_weight
        )
        res = panel_mod.assemble_signal(
            px, kospi,
            att=signals.load_signal(att_name, px, kospi),
            sen=signals.load_signal(sen_name, px, kospi),
            combine_rule=args.combine_rule,
            att_t=att_t, sen_t=sen_t,
            combine_weight=weight,
            window=args.window, horizon=args.horizon,
        )
        wsum = res.wsum
        args.signal = (f"combine({att_name}[{att_t}]x{sen_name}[{sen_t}],"
                       f"{args.combine_rule}"
                       + (f",w={res.weight:g}"
                          if args.combine_rule == "linear" else "") + ")")
    else:
        tkind = args.transform or signals.DEFAULT_TRANSFORM.get(args.signal, "zscore")
        res = panel_mod.assemble_signal(
            px, kospi,
            sig=signals.load_signal(args.signal, px, kospi),
            tkind=tkind, window=args.window, horizon=args.horizon,
        )

    pnl = res.pnl
    tkind = res.tkind
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

    if wsum is not None:
        # clipped and zeroed are the honest part: they say how often the ratio
        # had to be rescued rather than estimated.
        print(f"\nfitted weight — rolling {panel_mod.WF_WINDOW}-observation OLS, "
              f"history only")
        print(f"  first fit     {wsum['first'].date()}  ({wsum['n']:,} days weighted)")
        print(f"  w             mean {wsum['mean']:+.3f}  "
              f"range {wsum['min']:+.3f}..{wsum['max']:+.3f}")
        print(f"  clipped       {wsum['clipped']:.1%} of days at "
              f"±{panel_mod.WF_CLIP:g}")
        print(f"  fell back     {wsum['zeroed']:.1%} of days to w=0 "
              "(attention coefficient not positive)")

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
        "fitted_weight": (None if wsum is None
                          else {**wsum, "first": str(wsum["first"].date()),
                                "window": panel_mod.WF_WINDOW,
                                "min_obs": panel_mod.WF_MIN_OBS,
                                "clip": panel_mod.WF_CLIP}),
        "run_utc": stamp,
    }, indent=2, default=float))
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
