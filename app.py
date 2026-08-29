"""Signal testing dashboard.

Every number here comes from the same functions scripts/run_test.py calls, so
anything on screen is reproducible from the command line. Nothing is computed
in this file.
"""

import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from quant import panel as panel_mod
from quant import prices, signals, stats

SERIES = "#2a78d6"
ACCENT = "#eb6834"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e6e5e1"
SURFACE = "#fcfcfb"

st.set_page_config(page_title="Signal Test — SK Hynix", layout="wide")

TARGET_LABEL = {
    "fwd_ret": "Forward return (raw log)",
    "fwd_exret": "Forward return (KOSPI-excess, β=1)",
}
TARGET_SHORT = {
    "fwd_ret": "Forward return",
    "fwd_exret": "Forward excess return",
}


def configured(chart):
    """The shared visual theme. Separate from `styled` because configure_* is only
    valid on a top-level chart, and a vconcat cannot take a `height`."""
    return (
        chart.configure_view(stroke=None)
        .configure_axis(
            grid=True, gridColor=GRID, gridWidth=1, domainColor=GRID,
            tickColor=GRID, labelColor=MUTED, titleColor=MUTED,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
        )
        .configure_title(color=INK, fontSize=13, fontWeight=600, anchor="start")
    )


def styled(chart, height=300):
    return configured(chart.properties(height=height, background=SURFACE))


@st.cache_data(show_spinner="Loading prices…")
def get_prices(start, end):
    return prices.load_prices(start=start, end=end), prices.load_index(
        start=start, end=end
    )


@st.cache_data(show_spinner="Loading overlay…")
def get_quote(symbol, start, end):
    return prices.load_quote(symbol, start=start, end=end)["close"]


# Overlay shortcuts. yfinance symbols: a ".KS" suffix is a KOSPI-listed stock
# (".KQ" for KOSDAQ) and the digits are the KRX code, while a "^" prefix is an
# index rather than a security. Add rows here and they appear in the dashboard.
PEERS = {
    "005930.KS": "Samsung Electronics — KRX memory rival",
    "NVDA": "Nvidia — largest HBM customer",
    "MU": "Micron — the third HBM supplier",
    "TSM": "TSMC — foundry, packages HBM stacks",
    "ASML": "ASML — lithography, upstream of everyone",
    # Upstream suppliers. SK Siltron (wafers) and NAMICS (underfill) belong here
    # on the supply chain but are privately held, so there is nothing to plot.
    "4063.T": "Shin-Etsu Chemical — silicon wafers, Tokyo listed",
    "LIN": "Linde — process gases for fab and etch",
    "357780.KQ": "Soulbrain — process chemicals; listed 2020-08",
    "102710.KQ": "ENF Technology — high-purity process chemicals",
    "^KS11": "KOSPI index — the Korean market itself",
}
# The name is carried inside the option string rather than through format_func,
# which corrupts free-text entries under accept_new_options. Both a picked
# option and a typed symbol are read back the same way: take the first word.
PEER_OPTIONS = [f"{sym}  ·  {name}" for sym, name in PEERS.items()]
# Legend wants the company, not the "why it's here" half.
PEER_NAME = {sym: name.split(" — ")[0] for sym, name in PEERS.items()}

# SK Hynix is pinned to SERIES so it stays identifiable whatever else is on.
PALETTE = [SERIES, ACCENT, "#3d9970", "#8e5ea2", "#d1495b", "#7a7a76",
           "#2e8b8b", "#b5651d", "#6a5acd", "#4f772d", "#c9184a", "#1b6ca8"]

# A foreign exchange's first session of the year can fall a few days after the
# KRX's, which is a calendar difference, not a different starting point. Only a
# gap wider than this means the ticker genuinely was not listed yet.
LATE_START_DAYS = 15


# --- controls ---------------------------------------------------------------

_names = sorted(signals.SIGNALS)


def _pick(label, default, key):
    """A signal picker defaulting to `default` rather than whatever sorts first.

    gdelt_sent_semi sorts first and needs a hand-run backfill, so an alphabetical
    default made a fresh clone fail on page load.
    """
    return st.sidebar.selectbox(
        label, _names, key=key,
        index=_names.index(default) if default in _names else 0)


# --- SIGNAL: what is being analysed -----------------------------------------
# Construction lives here, not in a tab. Both branches produce one `sig`, so
# there is a single analysis path downstream and nothing is rendered twice.
st.sidebar.header("Signal")
source = st.sidebar.radio(
    "Source", ["Single", "Combined"], horizontal=True,
    help="Combined folds an attention signal and a sentiment one into a single "
         "series. How they are folded is the Rule control below.")

combine_rule, combine_weight = "product", 0.0
if source == "Single":
    sig_name = _pick("Signal", "naver_hynix", "sig_one")
    att_name = sen_name = None
    default_t = signals.DEFAULT_TRANSFORM.get(sig_name, "zscore")
else:
    att_name = _pick("Attention", "naver_hynix", "sig_att")
    sen_name = _pick("Sentiment", "gdelt_sent_semi", "sig_sen")
    combine_rule = st.sidebar.radio(
        "Rule", panel_mod.COMBINE_RULES, horizontal=True,
        help="product: attention as a trailing percentile rank in [0,1] times "
             "sentiment, which supplies the sign. linear: z(attention) + w × "
             "z(sentiment), with w signed.")
    if combine_rule == "linear":
        # Signed, and the negative half is the point: on their own top-25 days
        # attention ran +0.94% and sentiment -0.97%, so a non-negative weight
        # makes them cancel. w=0 is attention alone, which anchors the sweep.
        combine_weight = st.sidebar.slider(
            "Weight on sentiment", -1.0, 1.0, 0.0, 0.05,
            help="Signed. 0 reduces to attention alone. Negative is meaningful "
                 "— the two signals were measured pointing opposite ways.")
    sig_name = f"{att_name} × {sen_name}"
    # Both rules already return a bounded, stationary series.
    default_t = "raw"

# --- SPECIFICATION ----------------------------------------------------------
st.sidebar.header("Specification")
tkind = st.sidebar.selectbox(
    "Transform", panel_mod.TRANSFORMS, index=panel_mod.TRANSFORMS.index(default_t)
)
window = st.sidebar.number_input("Z-score baseline window (days)", 5, 250, 20)
target = st.sidebar.selectbox(
    "Target", list(TARGET_LABEL), format_func=TARGET_LABEL.__getitem__
)
# Dashboard defaults, set by the developer on 2026-08-29. These are NOT the
# pre-registered specification: panel_mod.HORIZON is 3 and the recorded sample
# starts 2019-01-01, which is what run_test.py and findings.md still use. The
# two are deliberately allowed to differ so browsing does not overwrite the
# record, but a number read off this page is not comparable to findings.md
# unless the horizon and start are put back.
DEFAULT_HORIZON = 1
DEFAULT_START = "2023-01-01"

horizon = st.sidebar.number_input("Forward horizon (days)", 1, 20, DEFAULT_HORIZON)
quantiles = st.sidebar.slider("Quantile buckets", 3, 10, 5)

# --- SAMPLE -----------------------------------------------------------------
st.sidebar.header("Sample")
start = st.sidebar.text_input("Start", DEFAULT_START)
end = st.sidebar.text_input("End", "2026-08-06")

st.sidebar.caption(
    "Primary specification for this project is **zscore / forward return (raw) / "
    "h=3 / from 2019-01-01**, fixed in advance — that is what `findings.md` and "
    f"`run_test.py` report. This page defaults to **h={DEFAULT_HORIZON} / from "
    f"{DEFAULT_START}**, so anything read off it is an explicitly secondary "
    "result until the horizon and start are set back."
)

if sig_name == "planted":
    st.warning(
        "**`planted` is a test fixture, not a signal.** It is constructed from the "
        "future 3-day return, so it must show a strong result — that is how it "
        "validates the harness. It is never a finding.",
        icon="⚠️",
    )

# --- compute ---------------------------------------------------------------

horizon = int(horizon)
px, kospi = get_prices(start, end)

try:
    if source == "Single":
        sig = signals.load_signal(sig_name, px, kospi)
    else:
        # Each component gets its own registered transform first, then combine
        # folds them by the selected rule. Identical to what
        # `run_test.py --combine` does, so the two agree by construction.
        att = panel_mod.transform(
            signals.load_signal(att_name, px, kospi),
            kind=signals.DEFAULT_TRANSFORM.get(att_name, "zscore"),
            window=int(window))
        sen = panel_mod.transform(
            signals.load_signal(sen_name, px, kospi),
            kind=signals.DEFAULT_TRANSFORM.get(sen_name, "raw"),
            window=int(window))
        sig = panel_mod.combine(att, sen, window=int(window),
                                rule=combine_rule, weight=combine_weight)
except FileNotFoundError as exc:
    # Hand-acquired sources (Naver .xlsx, GDELT backfill) are gitignored and
    # absent on a fresh clone. Their loaders raise with the recovery command;
    # show that rather than a traceback.
    st.error(f"**`{sig_name}` has no data yet.**\n\n{exc}", icon="📥")
    st.info("Pick another signal in the sidebar to carry on in the meantime.")
    st.stop()

pnl = panel_mod.build_panel(px, sig, transform_kind=tkind, window=int(window),
                            kospi=kospi, horizon=horizon)

fwd_col = f"{target}_{horizon}"
res = stats.evaluate(pnl, horizon=horizon, target=target, q=quantiles)
qt = stats.quantile_table(pnl["signal"], pnl[fwd_col], q=quantiles)

tab_describe, tab_test, tab_price = st.tabs(["Signal", "Test", "Price"])

# --- signal: what the thing IS ----------------------------------------------
# Deliberately no forward returns here. A reader should be able to judge whether
# a signal is trustworthy before seeing whether it "worked".

with tab_describe:
    st.title(f"`{sig_name}`")
    st.caption(f"transform `{tkind}` · {start} → {end}"
               + (f" · attention × sentiment, rank-weighted" if source == "Combined" else ""))

    cov = panel_mod.coverage(pnl["signal_raw"])
    gaps, have = cov["gaps"], cov["n_have"]
    span = (f"{cov['first']:%Y-%m-%d} → {cov['last']:%Y-%m-%d}"
            if cov["first"] is not None else "no data in this window")
    label = (f"Data coverage — `{sig_name}` spans {span} · {have:,} of "
             f"{len(pnl):,} trading days"
             + (f" · {len(gaps)} gap(s)" if len(gaps) else " · no gaps"))
    with st.expander(label, expanded=bool(len(gaps))):
        if cov["first"] is not None:
            asked = f"{pnl.index[0]:%Y-%m-%d} → {pnl.index[-1]:%Y-%m-%d}"
            st.caption(f"Requested window **{asked}** · signal has data "
                       f"**{span}**.")
            short_start = (cov["first"] - pnl.index[0]).days
            short_end = (pnl.index[-1] - cov["last"]).days
            if short_start > 30 or short_end > 30:
                st.warning(
                    f"The signal starts {short_start} day(s) after the window opens "
                    f"and ends {short_end} day(s) before it closes. Those stretches "
                    "contribute nothing — narrow Start/End to match if you want the "
                    "sample size to mean what it says.",
                    icon="📐",
                )
        if len(gaps):
            st.caption(
                "Stretches where the source has nothing. A window spanning one of "
                "these measures fewer days than its date range implies, so it is "
                "worth choosing **Start** and **End** around them."
            )
            st.dataframe(
                gaps.assign(**{"from": gaps["from"].dt.date, "to": gaps["to"].dt.date}),
                width="stretch", hide_index=True,
            )
        miss = len(pnl) - have
        if miss:
            st.caption(
                f"{miss:,} trading days ({miss/len(pnl):.0%}) have no signal value. "
                "Scattered single days are ordinary for a sparse source — GDELT "
                "news runs about one article a day before 2024 — and they are left "
                "as NaN rather than filled, so they drop out of every statistic "
                "instead of being counted as zero."
            )

    # --- the series itself --------------------------------------------------

    ser = pnl["signal"].dropna().rename("value").reset_index()
    ser.columns = ["date", "value"]
    st.altair_chart(
        styled(alt.Chart(ser).mark_line(color=SERIES, strokeWidth=1).encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("value:Q", title=f"Signal ({tkind})"),
            tooltip=[alt.Tooltip("date:T", title="Date"),
                     alt.Tooltip("value:Q", title="Signal", format=".3f")],
        ).properties(title="Signal over time"), height=220),
        width="stretch")

    # --- distribution -------------------------------------------------------

    desc = panel_mod.describe(pnl["signal"])
    dc = st.columns(5)
    dc[0].metric("Std dev", f"{desc['sd']:.2f}",
                 help="A z-score should sit near 1.0. Much above means the "
                      "rolling baseline is collapsing on some days.")
    dc[1].metric("Skew", f"{desc['skew']:+.2f}")
    dc[2].metric("Kurtosis", f"{desc['kurtosis']:.0f}",
                 help="Normal is 0. Large values mean a few days dominate any "
                      "level-based statistic — prefer rank IC over the HAC t "
                      "when this is high. See methodology.md.")
    dc[3].metric("Min / Max", f"{desc['min']:.1f} / {desc['max']:.1f}")
    dc[4].metric("1st / 99th pct", f"{desc['p01']:.1f} / {desc['p99']:.1f}",
                 help="Compare against Min/Max: a wide gap means the extremes "
                      "are isolated outliers rather than a fat shoulder.")

    hist = alt.Chart(ser).mark_bar(color=SERIES, opacity=0.75).encode(
        x=alt.X("value:Q", bin=alt.Bin(maxbins=60), title=f"Signal ({tkind})"),
        y=alt.Y("count():Q", title="Days"),
    )
    st.altair_chart(styled(hist.properties(title="Distribution"), height=200),
                    width="stretch")

    # --- how the two components relate, when combining ----------------------
    # Only for a combined signal, where it answers a real question: multiplying
    # two near-identical series gives something closer to a square than to an
    # interaction. For a single signal there is no second series the reader
    # cares about, so this section does not appear.

    if source == "Combined":
        st.divider()
        st.subheader("How the two components relate")
        st.caption(
            f"`{att_name}` and `{sen_name}`. Under `product` they are not an "
            "interaction if they largely measure the same thing; under `linear` "
            "a near-zero correlation is what makes the signed weight meaningful."
        )
        corr = stats.signal_correlation(att, sen)
        kc = st.columns(4)
        kc[0].metric("Pearson", f"{corr['pearson']:+.3f}",
                     help="No p-value: both series are autocorrelated, so a "
                          "textbook correlation p-value assumes an independence "
                          "that is not there.")
        kc[1].metric("Spearman", f"{corr['spearman']:+.3f}", help="Rank-based.")
        kc[2].metric("Overlapping days", f"{corr['n_overlap']:,}",
                     help="The product is only defined here; everything else is NaN.")
        kc[3].metric("Coverage", f"{corr['n_a']:,} / {corr['n_b']:,}",
                     help="attention days / sentiment days, before intersecting.")

        if corr["n_overlap"] < 200:
            st.warning(f"Only {corr['n_overlap']:,} shared days — the combined "
                       "signal inherits that limit.", icon="⚠️")
        elif abs(corr["spearman"]) > 0.7:
            st.warning(f"These correlate {corr['spearman']:+.2f}: they largely "
                       "measure the same thing, so the product is closer to a "
                       "square than to an interaction.", icon="⚠️")

        pair = pd.concat([att.rename("a"), sen.rename("b")], axis=1).dropna().reset_index()
        pair.columns = ["date", "a", "b"]
        psc = alt.Chart(pair).mark_circle(size=22, color=SERIES, opacity=0.4).encode(
            x=alt.X("a:Q", title=att_name, scale=alt.Scale(nice=True, zero=False)),
            y=alt.Y("b:Q", title=sen_name, scale=alt.Scale(nice=True, zero=False)),
            tooltip=[alt.Tooltip("date:T", title="Date"),
                     alt.Tooltip("a:Q", format=".2f"), alt.Tooltip("b:Q", format=".2f")],
        )
        st.altair_chart(
            styled((psc + psc.transform_regression("a", "b")
                    .mark_line(color=ACCENT, strokeWidth=2))
                   .properties(title="The two components against each other"), height=250),
            width="stretch")


# --- test: does it predict returns ------------------------------------------

with tab_test:
    st.title("Signal → forward price behaviour")
    st.caption(
        f"SK Hynix 000660 · signal `{sig_name}` · transform `{tkind}` · "
        f"target `{target}` · horizon {horizon}d"
    )

    # --- headline ----------------------------------------------------------

    c = st.columns(5)
    c[0].metric("Rank IC", f"{res['ic']:+.3f}", help="Spearman. Descriptive only — no p-value, because overlapping returns violate its independence assumption.")
    c[1].metric("HAC t-stat", f"{res['t_hac']:+.2f}", help=f"Newey-West, maxlags={horizon}. The only inference path in the project.")
    c[2].metric("p (HAC)", f"{res['p_hac']:.4f}",
                delta="significant" if res["p_hac"] < stats.ALPHA else "not significant",
                delta_color="normal" if res["p_hac"] < stats.ALPHA else "off")
    c[3].metric("Top−bottom spread", f"{res['ls_spread']:+.2%}",
                help=f"Extreme buckets only — HAC t = {res['ls_t']:+.2f}, "
                     f"p = {res['ls_p']:.4f}, n = {int(res['ls_n']):,}. "
                     f"This is a different sample from the {int(res['n']):,} "
                     "observations shown at right.")
    c[4].metric("Observations", f"{int(res['n']):,}")

    if res["p_hac"] >= stats.ALPHA:
        st.info(
            f"No significant relationship at h={horizon} (p = {res['p_hac']:.4f}). "
            "A null result is a valid outcome."
        )

    st.divider()

    # --- quantiles + scatter -----------------------------------------------

    left, right = st.columns(2)

    with left:
        if qt.empty:
            st.warning("Not enough observations for quantile buckets.")
        else:
            qt = qt.assign(lo=qt["mean"] - qt["se"], hi=qt["mean"] + qt["se"])
            base = alt.Chart(qt).encode(
                x=alt.X("bucket:O", title="Signal quantile (1 = lowest)",
                        axis=alt.Axis(labelAngle=0)),
            )
            bars = base.mark_bar(color=SERIES, cornerRadiusEnd=4, size=34).encode(
                y=alt.Y("mean:Q",
                        title=f"Mean {TARGET_SHORT[target].lower()} ({horizon}d)",
                        axis=alt.Axis(format=".2%")),
                tooltip=[alt.Tooltip("bucket:O", title="Quantile"),
                         alt.Tooltip("mean:Q", title="Mean", format=".4f"),
                         alt.Tooltip("se:Q", title="Std error", format=".4f"),
                         alt.Tooltip("n:Q", title="Days")],
            )
            err = base.mark_rule(color=INK, opacity=0.55, strokeWidth=2).encode(
                y="lo:Q", y2="hi:Q"
            )
            st.altair_chart(
                styled((bars + err).properties(
                    title="Mean forward return by signal quantile"
                )),
                width="stretch",
            )
            st.caption(
                "Monotonic progression across buckets is stronger evidence than a large "
                "end-to-end spread, which one outlier bucket can produce alone. "
                "Bars show ±1 standard error."
            )

    with right:
        pts = pnl[["signal", fwd_col]].dropna().reset_index()
        pts.columns = ["date", "signal", "fwd"]
        sc = alt.Chart(pts).mark_circle(size=26, color=SERIES, opacity=0.45).encode(
            x=alt.X("signal:Q", title=f"Signal ({tkind})",
                    axis=alt.Axis(tickCount=8), scale=alt.Scale(nice=True, zero=False)),
            y=alt.Y("fwd:Q", title=f"{TARGET_SHORT[target]} ({horizon}d)",
                    axis=alt.Axis(format=".1%")),
            tooltip=[alt.Tooltip("date:T", title="Date"),
                     alt.Tooltip("signal:Q", format=".3f"),
                     alt.Tooltip("fwd:Q", title="Forward", format=".4f")],
        )
        fit = sc.transform_regression("signal", "fwd").mark_line(
            color=ACCENT, strokeWidth=2
        )
        st.altair_chart(
            styled((sc + fit).properties(title="Signal vs forward return, with fit")),
            width="stretch",
        )
        st.caption(
            "Check whether the fitted line is carried by the bulk of the sample or by a "
            "handful of extreme days at the edges."
        )

    st.divider()

    # --- tail (outlier) test -------------------------------------------------

    st.subheader("Tail test — do outlier days behave differently?")
    st.caption(
        "Rank IC, the HAC fit and the quantile spread all measure a relationship "
        "across the whole distribution, so an effect confined to spikes is diluted "
        "by the ordinary days around it. This asks a narrower question: over the "
        f"{horizon}-day window after a day above the threshold, is the mean return "
        "different from every other day?"
    )

    tl = pnl[["signal", fwd_col]].dropna().reset_index()
    tl.columns = ["date", "signal", "fwd"]

    # The cut is in signal units, so its usable range depends entirely on the
    # transform: dow_zscore spans roughly -6..+20, while raw naver spans 4..84.
    # A fixed 1.0-4.0 range put every raw day in the tail, leaving no comparison
    # group and an unexplained NaN. Bounds therefore come from the data.
    lo = float(tl["signal"].quantile(0.50))
    hi = float(tl["signal"].quantile(0.999))
    default = stats.TAIL_Z if lo < stats.TAIL_Z < hi else float(
        tl["signal"].quantile(0.90))
    step = max(round((hi - lo) / 40, 4), 1e-4)
    # The unit depends on the transform: a z-score under zscore/dow_zscore, but
    # the signal's own units under raw — Naver's 0-100 index, Wikipedia's view
    # counts. Naming it after the actual transform avoids implying a z-score
    # when the slider is reading 11.68 to 75.62.
    UNIT = {"zscore": "z-score", "dow_zscore": "z-score vs same weekday",
            "raw": "raw signal units"}
    unit = UNIT.get(tkind, "signal units")

    sc_, tc_ = st.columns([1, 2])
    SIDE_LABEL = {"High only": "upper", "Low only": "lower", "Both tails": "both"}
    side_label = sc_.radio("Which tail", list(SIDE_LABEL), horizontal=True,
                           help="Low and Both compare against -threshold, so they "
                                "assume a signal centred on zero. True for a "
                                "z-score, not for `raw`.")
    tail_side = SIDE_LABEL[side_label]
    with tc_:
        tail_z = st.slider(f"Outlier threshold ({unit})", lo, hi, default, step,
                           help=f"Measured in {unit} because the transform is "
                                f"`{tkind}`, so the cut is comparable only "
                                "within one transform.")

    # `raw` is not centred on zero - Naver's index runs 0-100 - so a symmetric
    # cut selects nothing or everything. Say so rather than showing an empty test.
    if tkind == "raw" and tail_side != "upper":
        st.warning(
            f"`{side_label}` compares against **-{tail_z:g}**, but the `raw` "
            "transform is not centred on zero, so that cut is meaningless here. "
            "Switch the transform to a z-score, or use High only.", icon="⚠️")

    tail = stats.tail_test(tl["signal"], tl["fwd"], maxlags=horizon,
                           threshold=tail_z, side=tail_side)
    tl["outlier"] = stats.tail_mask(tl["signal"], tail_z, tail_side)
    marks = tl[tl["outlier"]].assign(
        direction=lambda f: np.where(f["fwd"] >= 0, "up", "down"))

    if not np.isfinite(tail["excess"]):
        st.warning(
            f"No usable split at this threshold — {tail['n_tail']:,} tail days and "
            f"{tail['n_rest']:,} others. The test needs at least 20 days on the tail "
            "side and at least one on the other, so move the slider.",
            icon="⚠️",
        )

    tc = st.columns(4)
    # No threshold in the label: "(>2.5)" next to a percentage reads as a return
    # above 2.5%, when 2.5 is a signal-units cut. It belongs in the help text.
    tc[0].metric("Excess return, event days", f"{tail['excess']:+.2%}",
                 help=f"Mean forward return on days with signal > {tail_z:g} "
                      f"({unit}, not a return), minus the mean on all other "
                      "days. HAC dummy regression on the full sample.")
    tc[1].metric("HAC t-stat", f"{tail['t']:+.2f}")
    tc[2].metric("p (HAC)", f"{tail['p']:.4f}",
                 delta="significant" if tail["p"] < stats.ALPHA
                       else "not significant",
                 delta_color="normal" if tail["p"] < stats.ALPHA else "off")
    tc[3].metric("Tail days", f"{tail['n_tail']:,}",
                 help=f"{tail['n_tail'] / max(len(tl), 1):.1%} of the {len(tl):,} "
                      "usable days. The rest form the comparison group.")

    ev = stats.event_metrics(tl["signal"], tl["fwd"], maxlags=horizon,
                             threshold=tail_z, side=tail_side)
    ec = st.columns(4)
    ec[0].metric("Mean return, event days", f"{ev['mean_event']:+.2%}",
                 help=f"{ev['n_events']:,} days above the threshold.")
    ec[1].metric("Mean return, other days", f"{ev['mean_rest']:+.2%}",
                 help=f"{ev['n_rest']:,} days. The difference between these two is "
                      "the excess return above.")
    ec[2].metric("Hit rate, event days", f"{ev['hit_rate']:.1%}",
                 delta=f"{ev['hit_diff']:+.1%} vs baseline",
                 delta_color="normal" if ev["hit_p"] < stats.ALPHA else "off",
                 help=f"Share of event days beating the median return of "
                      f"non-event days ({ev['median_rest']:+.2%}). HAC "
                      f"t = {ev['hit_t']:+.2f}, p = {ev['hit_p']:.4f}.")
    ec[3].metric("Hit rate, other days", f"{ev['base_rate']:.1%}",
                 help="~50% by construction — the baseline is these days' own "
                      "median, which is what makes the event rate readable.")
    st.caption(
        f"Mean |return| on event days is **{ev['abs_ratio']:.2f}×** that of other "
        "days — descriptive only, no test is run on it. Above 1 would support "
        "outliers acting as volatility catalysts; at or below 1 they do not. "
        "The hit rate discards magnitude entirely, so read it beside the mean "
        "rather than alone."
    )

    sig_line = alt.Chart(tl).mark_line(color=MUTED, strokeWidth=0.7,
                                       opacity=0.7).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("signal:Q", title=f"Signal ({tkind})"),
    )
    cut = alt.Chart(pd.DataFrame({"y": [tail_z]})).mark_rule(
        color=INK, strokeDash=[4, 3], strokeWidth=1).encode(y="y:Q")
    pts = alt.Chart(marks).mark_point(size=45, filled=True, opacity=0.85).encode(
        x="date:T", y="signal:Q",
        color=alt.Color("direction:N", title=None,
                        scale=alt.Scale(domain=["up", "down"],
                                        range=["#3d9970", "#d1495b"]),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("date:T", title="Date"),
                 alt.Tooltip("signal:Q", title="Signal", format=".2f"),
                 alt.Tooltip("fwd:Q", title=f"Forward {horizon}d", format=".2%")],
    )
    st.altair_chart(
        styled((sig_line + cut + pts).properties(
            title=f"Signal over time — {len(marks):,} days above {tail_z:g}, "
                  "coloured by the return that followed"), height=260),
        width="stretch",
    )
    st.caption(
        "Green marks are event days followed by a gain, red by a loss. A mixed "
        "scatter means the spikes carry no directional information; a one-sided "
        "cluster means they do. The hit rate above measures this against the "
        "baseline median rather than against zero."
    )

    st.markdown("**Threshold sensitivity**")
    # Same scale problem as the slider: the registered grid is in z units, so it
    # is used only when it actually lands inside this signal's range.
    grid = stats.TAIL_GRID
    if not (lo < min(grid) and max(grid) < hi):
        grid = tuple(round(float(tl["signal"].quantile(q)), 3)
                     for q in (0.50, 0.70, 0.80, 0.90, 0.95, 0.98))
        st.caption(f"Grid taken from this signal's own percentiles — the standard "
                   f"{min(stats.TAIL_GRID):g}–{max(stats.TAIL_GRID):g} grid is in "
                   "z units and does not fit the selected transform.")
    curve = stats.tail_curve(tl["signal"], tl["fwd"], maxlags=horizon,
                             thresholds=grid, side=tail_side)
    st.dataframe(
        curve.rename(columns={"threshold": "cut", "excess": "excess return",
                              "t": "HAC t", "p": "HAC p",
                              "n_tail": "tail days", "n_rest": "other days"})
        .style.format({"cut": "{:g}", "excess return": "{:+.2%}", "HAC t": "{:+.2f}",
                       "HAC p": "{:.4f}", "tail days": "{:,.0f}",
                       "other days": "{:,.0f}"}),
        width="stretch", hide_index=True,
    )
    st.caption(
        f"⚠️ **The default cut of {stats.TAIL_Z:g} was chosen after inspecting results, "
        "so its p-value overstates the evidence** — a Bonferroni threshold across the "
        "16 combinations examined would be 0.0031. Read the column above as a whole: "
        "a result holding across neighbouring cuts is worth more than a lone "
        "significant row, and either way this is exploratory until tested on data "
        "the threshold was not chosen on."
    )

    st.divider()

    # --- reverse causality --------------------------------------------------

    st.subheader("Reverse causality")
    st.caption(
        "Does past price predict the signal? Attention data typically chases price. "
        "If this direction is stronger than the forward one, the causal story runs "
        "backwards and any forward result is suspect."
    )
    rev = stats.reverse_causality(pnl["signal"], panel_mod.past_returns(pnl))
    rev_df = pd.DataFrame(rev).T[["t", "p", "n", "degenerate"]]
    rev_df.index = [f"Past {i.split('_')[-1]}-day return → signal" for i in rev_df.index]
    if rev_df["degenerate"].any():
        st.error(
            "This signal **is** one of the trailing-return variables, so the "
            "regression is an identity (R²=1) and its t-statistic is meaningless.",
            icon="⚠️",
        )
    st.dataframe(
        rev_df.drop(columns="degenerate").style.format(
            {"t": "{:+.2f}", "p": "{:.4f}", "n": "{:,.0f}"}
        ),
        width="stretch",
    )
    live = [v for v in rev.values() if not v["degenerate"]]
    fwd_t = abs(res["t_hac"])
    rev_t = max((abs(v["t"]) for v in live), default=0.0)
    if rev_t > fwd_t:
        st.warning(
            f"Reverse direction is stronger (|t|={rev_t:.2f}) than the forward "
            f"direction (|t|={fwd_t:.2f}). The signal looks more like a response to "
            "price than a predictor of it.",
            icon="⚠️",
        )

    # --- footer -------------------------------------------------------------

    st.divider()
    usable = pnl[["signal", fwd_col]].dropna()
    st.caption(
        f"**Sample** {pnl.index[0].date()} → {pnl.index[-1].date()} · "
        f"{len(pnl):,} trading days · {len(usable):,} usable after transform warm-up and "
        f"forward-window truncation ({len(pnl) - len(usable):,} dropped). "
        "Inference is Newey-West HAC throughout, maxlags = horizon. "
        "**Prices** pykrx (KRX official). **β=1** assumed in the excess-return target."
    )

# --- price ------------------------------------------------------------------

with tab_price:
    st.title("SK Hynix price")
    st.caption(f"000660 · {px.index[0].date()} → {px.index[-1].date()} · "
               f"{len(px):,} trading days")

    # No format_func: with accept_new_options=True Streamlit feeds the formatted
    # label back as the value, so a typed "INTC" would arrive as "INTC (INTC)".
    picked = st.multiselect(
        "Overlay tickers", options=PEER_OPTIONS, accept_new_options=True,
        placeholder="Type any yfinance ticker (e.g. INTC, 000155.KS) or pick below",
        help="This box accepts free text — type a symbol and press Enter to add it. "
             "The listed companies are only shortcuts.",
    )

    # A slider, not an interactive zoom. Vega keeps selection state per chart
    # element across Streamlit reruns, and a stale or empty scale-bound domain
    # clips the axis with no gesture from the user — which looks exactly like
    # missing data. A window computed in Python renders the same every time.
    d0, d1 = px.index[0].date(), px.index[-1].date()
    lo, hi = st.slider("Window", min_value=d0, max_value=d1, value=(d0, d1),
                       format="YYYY-MM-DD")
    win = px.loc[(px.index >= pd.Timestamp(lo)) & (px.index <= pd.Timestamp(hi))]
    if len(win) < 2:
        # The Price tab is the last thing rendered, so stopping here costs nothing
        # and avoids indenting the rest of the tab behind an else.
        st.warning("Pick a window covering at least two trading days.")
        st.stop()

    lines, spans = {}, {}
    for choice in picked:
        sym = choice.split()[0] if choice.split() else ""
        try:
            peer = get_quote(sym, start, end)
        except Exception as exc:
            # Loud, because the alternative symptom is a legend entry with no
            # line, which reads as "this company has no data for the period".
            st.error(f"**`{sym}` is not plotted.** {exc}", icon="🚫")
            continue
        label = f"{PEER_NAME[sym]} ({sym})" if sym in PEER_NAME else sym
        # Span of genuine observations, before any filling, for the notices below.
        spans[label] = (peer.index.min(), peer.index.max())
        # Fill across the whole calendar first so the window's first day inherits
        # the last price known before it, then cut to the window.
        lines[label] = peer.reindex(px.index).ffill().loc[win.index]

    # With no overlay there is nothing to compare against, so raw KRW is strictly
    # more informative than an index. The axis title says which is shown.
    rebased = bool(lines)
    lines = {"SK Hynix (000660)": win["close"], **lines}
    if rebased:
        # Rebase after windowing, so every line is 100 at the window start and
        # narrowing the window re-anchors the comparison.
        lines = {k: prices.rebase(s) for k, s in lines.items()}
    y_title = (f"Rebased to 100 at {win.index[0].date()}" if rebased
               else "Close (KRW)")

    # Both ends matter. A ticker listed mid-window has no line before it existed;
    # one that stops early gets its last price carried forward by the ffill above,
    # which draws a flat line indistinguishable from a real quiet period.
    notes = []
    for k, (first, last) in spans.items():
        if (first - win.index[0]).days > LATE_START_DAYS:
            notes.append(f"**{k}** starts {first.date()}")
        if (win.index[-1] - last).days > LATE_START_DAYS:
            notes.append(f"**{k}** ends {last.date()} — the flat tail after that "
                         "is its last price carried forward, not real trading")
    if notes:
        st.info("Not every line covers the whole window: " + " · ".join(notes),
                icon="ℹ️")

    pr = pd.concat(
        [s.rename("value").reset_index().assign(series=k) for k, s in lines.items()]
    )
    vol = win[["volume"]].reset_index()

    line = alt.Chart(pr).mark_line(strokeWidth=1.4).encode(
        x=alt.X("date:T", title=None),
        # Log, not linear: the stock has multiplied several times over the sample,
        # so on a linear axis 2019 is a flat line and a 10% move then looks smaller
        # than a 10% move in 2026. Log also makes rebasing a pure vertical shift,
        # so each line's shape survives it exactly.
        y=alt.Y("value:Q", title=y_title,
                scale=alt.Scale(type="log", nice=False, zero=False),
                axis=alt.Axis(format=",.0f")),
        color=alt.Color("series:N", title=None,
                        # Cycled, so more overlays than colours repeats a colour
                        # rather than leaving a line unstyled.
                        scale=alt.Scale(domain=list(lines),
                                        range=[PALETTE[i % len(PALETTE)]
                                               for i in range(len(lines))]),
                        legend=alt.Legend(orient="top") if rebased else None),
        tooltip=[alt.Tooltip("date:T", title="Date"),
                 alt.Tooltip("series:N", title="Series"),
                 alt.Tooltip("value:Q", title=y_title, format=",.1f")],
    ).properties(height=340, title="Close, log scale")

    bars = alt.Chart(vol).mark_bar(color=SERIES, opacity=0.5).encode(
        x=alt.X("date:T", title=None),
        # Linear: the informative feature in volume is the spikes, which log flattens.
        y=alt.Y("volume:Q", title="Volume", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("date:T", title="Date"),
                 alt.Tooltip("volume:Q", title="Volume", format=",.0f")],
    ).properties(height=110)

    st.altair_chart(
        configured(
            alt.vconcat(line, bars, spacing=8)
            .resolve_scale(x="shared")
            .properties(background=SURFACE)
        ),
        width="stretch",
    )
    caption = (
        "Close on a **log axis**, so equal percentage moves are equal vertical "
        "distances. Unadjusted close — **not** back-adjusted for dividends or "
        "splits, so this is a price chart, not a total-return chart. "
        "Use the **Window** slider to narrow the date range — both panels always "
        "show the same span."
    )
    if rebased:
        caption += (
            "\n\nEach line is divided by its own first value, so all start at 100 "
            "and the axis reads as percentage growth — which is why no FX "
            "conversion is needed to compare a KRW line with a USD one. Peers are "
            "forward-filled onto the KRX calendar, and a US close lands ~13.5h "
            "after the Korean close of the same date, so day-to-day alignment is "
            "approximate. **Volume is SK Hynix only** — share counts are not "
            "comparable across companies."
        )
    st.caption(caption)
