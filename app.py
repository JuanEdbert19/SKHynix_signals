"""Signal testing dashboard.

Every number here comes from the same functions scripts/run_test.py calls, so
anything on screen is reproducible from the command line. Nothing is computed
in this file.
"""

import sys
from pathlib import Path

import altair as alt
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
    c[3].metric("Top−bottom spread", f"{res['ls_spread']:+.4f}", help=f"HAC t = {res['ls_t']:+.2f}")
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

    pr = px[["close", "volume"]].reset_index()
    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    tips = [alt.Tooltip("date:T", title="Date"),
            alt.Tooltip("close:Q", title="Close", format=",.0f"),
            alt.Tooltip("volume:Q", title="Volume", format=",.0f")]

    line = alt.Chart(pr).mark_line(color=SERIES, strokeWidth=1.4).encode(
        x=alt.X("date:T", title=None),
        # Log, not linear: the stock has multiplied several times over the sample,
        # so on a linear axis 2019 is a flat line and a 10% move then looks smaller
        # than a 10% move in 2026.
        y=alt.Y("close:Q", title="Close (KRW)",
                scale=alt.Scale(type="log", nice=False, zero=False),
                axis=alt.Axis(format=",.0f")),
        tooltip=tips,
    ).properties(height=340, title="Close, log scale").add_params(zoom)

    bars = alt.Chart(pr).mark_bar(color=SERIES, opacity=0.5).encode(
        x=alt.X("date:T", title=None),
        # Linear: the informative feature in volume is the spikes, which log flattens.
        y=alt.Y("volume:Q", title="Volume", axis=alt.Axis(format="~s")),
        tooltip=tips,
    ).properties(height=110)

    st.altair_chart(
        configured(
            alt.vconcat(line, bars, spacing=8)
            .resolve_scale(x="shared")
            .properties(background=SURFACE)
        ),
        width="stretch",
    )
    st.caption(
        "Close on a **log axis**, so equal percentage moves are equal vertical "
        "distances. Unadjusted KRX close (pykrx) — **not** back-adjusted for "
        "dividends or splits, so this is a price chart, not a total-return chart. "
        "Volume in shares. Scroll or drag to zoom; both panels share the date axis."
    )
