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

st.sidebar.header("Specification")
sig_name = st.sidebar.selectbox("Signal", sorted(signals.SIGNALS))
default_t = signals.DEFAULT_TRANSFORM.get(sig_name, "zscore")
tkind = st.sidebar.selectbox(
    "Transform", panel_mod.TRANSFORMS, index=panel_mod.TRANSFORMS.index(default_t)
)
window = st.sidebar.number_input("Z-score baseline window (days)", 5, 250, 20)
target = st.sidebar.selectbox(
    "Target", list(TARGET_LABEL), format_func=TARGET_LABEL.__getitem__
)
horizon = st.sidebar.number_input("Forward horizon (days)", 1, 20,
                                  panel_mod.HORIZON)
start = st.sidebar.text_input("Start", "2019-01-01")
end = st.sidebar.text_input("End", "2026-08-06")
quantiles = st.sidebar.slider("Quantile buckets", 3, 10, 5)

st.sidebar.caption(
    "Primary specification for this project is **zscore / forward return (raw) / "
    "h=3**, fixed in advance. Anything else is an explicitly secondary test."
)
st.sidebar.caption(
    "Signal, Transform, Window, Target, Horizon and Quantiles affect the **Signal "
    "test** tab only. The **Price** tab depends on Start and End alone."
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
sig = signals.load_signal(sig_name, px, kospi)
pnl = panel_mod.build_panel(px, sig, transform_kind=tkind, window=int(window),
                            kospi=kospi, horizon=horizon)

fwd_col = f"{target}_{horizon}"
res = stats.evaluate(pnl, horizon=horizon, target=target, q=quantiles)
qt = stats.quantile_table(pnl["signal"], pnl[fwd_col], q=quantiles)

tab_signal, tab_price = st.tabs(["Signal test", "Price"])

with tab_signal:
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
    c[3].metric("Top−bottom spread", f"{res['ls_spread']:+.4f}",
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
    tail_z = st.slider("Outlier threshold (signal units)", lo, hi, default, step,
                       help="Days above this count as outliers. The range follows "
                            "the selected transform, so it is comparable only "
                            "within one transform.")

    tail = stats.tail_test(tl["signal"], tl["fwd"], maxlags=horizon,
                           threshold=tail_z)
    tl["outlier"] = tl["signal"] > tail_z
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
    tc[0].metric(f"Excess return (>{tail_z:g})", f"{tail['excess']:+.4f}",
                 help="Mean forward return on tail days minus mean on all other "
                      "days, from a HAC dummy regression on the full sample.")
    tc[1].metric("HAC t-stat", f"{tail['t']:+.2f}")
    tc[2].metric("p (HAC)", f"{tail['p']:.4f}",
                 delta="significant" if tail["p"] < stats.ALPHA
                       else "not significant",
                 delta_color="normal" if tail["p"] < stats.ALPHA else "off")
    tc[3].metric("Tail days", f"{tail['n_tail']:,}",
                 help=f"{tail['n_tail'] / max(len(tl), 1):.1%} of the {len(tl):,} "
                      "usable days. The rest form the comparison group.")

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
    if len(marks):
        up = (marks["direction"] == "up").mean()
        st.caption(
            f"**{up:.0%} of tail days were followed by a gain** over {horizon} days "
            f"(vs {(tl['fwd'] >= 0).mean():.0%} across all days). Mixed colours mean "
            "the spikes carry no directional information; a one-sided cluster means "
            "they do."
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
                             thresholds=grid)
    st.dataframe(
        curve.rename(columns={"threshold": "cut", "excess": "excess return",
                              "t": "HAC t", "p": "HAC p",
                              "n_tail": "tail days", "n_rest": "other days"})
        .style.format({"cut": "{:g}", "excess return": "{:+.4f}", "HAC t": "{:+.2f}",
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
