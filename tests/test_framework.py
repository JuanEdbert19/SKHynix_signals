"""Acceptance criteria for the testing framework.

These are not unit tests for coverage's sake. They are the checks that decide
whether a null result on a real signal means "no effect" or "broken pipeline".
Tests run against a synthetic price series so they need no network.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant import align, cache, panel, prices, signals, stats, wiki  # noqa: E402

N_DAYS = 1200


def fake_px(seed=42, n=N_DAYS):
    """A random-walk price series on a business-day calendar."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-02", periods=n, name="date")
    ret = rng.standard_normal(n) * 0.02
    close = 100 * np.exp(np.cumsum(ret))
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close,
        "volume": rng.lognormal(15, 0.4, n),
    }, index=idx)


def build(sig_name, seed=0, transform="raw", px=None, horizon=3):
    px = fake_px() if px is None else px
    seeded = sig_name in ("noise", "planted")
    sig = signals.SIGNALS[sig_name](px, None, **({"seed": seed} if seeded else {}))
    return panel.build_panel(px, sig, transform_kind=transform, horizon=horizon)


# --- false positives: noise must read null ----------------------------------


def test_noise_false_positive_rate():
    """Across many seeds, noise should clear p<0.05 about 5% of the time.

    If HAC is misconfigured the rate blows out well past nominal, which is
    exactly what this catches.
    """
    hits = 0
    trials = 40
    for seed in range(trials):
        pnl = build("noise", seed=seed)
        res = stats.ols_hac(pnl["fwd_ret_3"], pnl["signal"], maxlags=3)
        hits += res["p"] < 0.05

    rate = hits / trials
    assert rate <= 0.20, f"false positive rate {rate:.2f} far above nominal 0.05"


def test_noise_ic_near_zero():
    pnl = build("noise", seed=7)
    assert abs(stats.rank_ic(pnl["signal"], pnl["fwd_ret_3"])) < 0.08


# --- false negatives: planted must be detected ------------------------------


def test_planted_detected_at_target_horizon():
    """The framework must see a known rho=0.15 effect at h=3."""
    pnl = build("planted", seed=0)
    ic = stats.rank_ic(pnl["signal"], pnl["fwd_ret_3"])
    res = stats.ols_hac(pnl["fwd_ret_3"], pnl["signal"], maxlags=3)

    assert ic > 0, f"planted signal detected with wrong sign (ic={ic:.3f})"
    assert abs(ic - signals.PLANTED_RHO) < 0.07, f"ic {ic:.3f} far from planted 0.15"
    assert res["p"] < 0.05, f"known effect not detected (p={res['p']:.3f})"


def test_planted_strongest_at_its_own_horizon():
    """The fixture must peak at the horizon it was built from, not elsewhere.

    Kept even though the harness now tests a single fixed horizon: it is what
    confirms the machinery localises an effect in time rather than smearing it.
    """
    px = fake_px()
    ics = {}
    for h in (1, 3, 5, 10):
        pnl = build("planted", seed=0, px=px, horizon=h)
        ics[h] = stats.rank_ic(pnl["signal"], pnl[f"fwd_ret_{h}"])

    best = max(ics, key=ics.get)
    assert best == signals.PLANTED_HORIZON, f"peak IC at h={best}, expected 3"


def test_planted_long_short_spread_positive():
    pnl = build("planted", seed=0)
    ls = stats.long_short(pnl["signal"], pnl["fwd_ret_3"], maxlags=3)
    assert ls["spread"] > 0 and ls["t"] > 1.5


# --- HAC actually corrects --------------------------------------------------


def _ar1(phi, index, seed=5):
    rng = np.random.default_rng(seed)
    x = np.zeros(len(index))
    for i in range(1, len(x)):
        x[i] = phi * x[i - 1] + rng.standard_normal()
    return pd.Series(x, index=index)


def test_hac_inflates_se_for_persistent_signal_on_overlapping_target():
    """A persistent signal against an overlapping target must inflate the SE.

    This is the configuration that matters in practice: attention signals are
    sticky, so their HAC correction is large. Catches a silently ignored
    cov_type, which would leave every t-stat in the project overstated.
    """
    px = fake_px()
    pnl = panel.add_targets(px, horizon=3)
    sig = _ar1(0.8, px.index)

    res = stats.ols_hac(pnl["fwd_ret_3"], sig, maxlags=3)
    assert res["se"] > res["se_ols"] * 1.20, (
        f"HAC se {res['se']:.5f} not meaningfully above OLS se {res['se_ols']:.5f}"
    )


def test_hac_correction_grows_with_horizon():
    px = fake_px()
    sig = _ar1(0.8, px.index)

    ratios = []
    for h in (1, 3, 10):
        fwd = panel.add_targets(px, horizon=h)[f"fwd_ret_{h}"]
        res = stats.ols_hac(fwd, sig, maxlags=h)
        ratios.append(res["se"] / res["se_ols"])
    assert ratios[0] < ratios[1] < ratios[2], f"non-monotonic correction: {ratios}"


def test_hac_correction_is_small_for_serially_uncorrelated_signal():
    """Overlap alone does NOT inflate the SE — the signal must be persistent too.

    Pinning this down because it is counter-intuitive: the Newey-West correction
    acts on the autocovariance of signal x residual, so a near-iid signal barely
    moves even when the target windows overlap heavily. Any real count-based
    signal will be persistent, so the correction will matter there.
    """
    px = fake_px()
    pnl = panel.add_targets(px, horizon=3)
    sig = _ar1(0.0, px.index)

    res = stats.ols_hac(pnl["fwd_ret_3"], sig, maxlags=3)
    assert 0.9 < res["se"] / res["se_ols"] < 1.1


def test_evaluate_regresses_return_on_signal_not_the_reverse(monkeypatch):
    """The forward return must be the dependent variable.

    A swap leaves rank IC identical and still yields a plausible HAC t (7.5 vs
    4.6 on the planted fixture), so nothing `evaluate` returns identifies which
    direction was run. This bug was shipped once and was caught only by the
    coefficient magnitude, which is no longer reported. The check therefore
    inspects the call arguments directly rather than anything downstream.
    """
    pnl = build("planted", seed=0)
    seen = {}
    real = stats.ols_hac

    def spy(y, x, *a, **k):
        seen.setdefault("first_call", (y.name, x.name))
        return real(y, x, *a, **k)

    monkeypatch.setattr(stats, "ols_hac", spy)
    stats.evaluate(pnl, horizon=3)

    assert seen["first_call"] == ("fwd_ret_3", "signal"), (
        f"regressed {seen['first_call'][0]} on {seen['first_call'][1]} — reversed"
    )
    # A per-1sd coefficient on a daily log return must be of return magnitude.
    assert abs(real(pnl["fwd_ret_3"], pnl["signal"], maxlags=3)["coef"]) < 0.05


def test_hac_and_ols_agree_on_non_overlapping_target():
    """At h=1 there is no overlap, so the correction should be small."""
    pnl = build("noise", seed=3, horizon=1)
    res = stats.ols_hac(pnl["fwd_ret_1"], pnl["signal"], maxlags=1)
    assert res["se"] < res["se_ols"] * 1.5


# --- no look-ahead in transforms -------------------------------------------


@pytest.mark.parametrize("kind", panel.TRANSFORMS)
def test_transform_uses_no_future_data(kind):
    """Truncating the input after day t must not change the value at day t."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2020-01-01", periods=600)
    sig = pd.Series(rng.lognormal(3, 0.5, 600), index=idx)

    cut = 400
    full = panel.transform(sig, kind=kind)
    truncated = panel.transform(sig.iloc[: cut + 1], kind=kind)

    a, b = full.iloc[cut], truncated.iloc[cut]
    assert np.isclose(a, b, equal_nan=True), (
        f"{kind} leaks future data: {a} with full series vs {b} truncated at t"
    )


def test_zscore_baseline_excludes_today():
    """A single spike must not damp its own z-score by entering the baseline."""
    idx = pd.bdate_range("2020-01-01", periods=60)
    sig = pd.Series(1.0, index=idx)
    sig.iloc[-1] = 100.0
    # Constant history has zero std, so a correct implementation yields inf/NaN
    # rather than a finite value computed from a baseline containing the spike.
    z = panel.transform(sig, kind="zscore", window=20)
    assert not np.isfinite(z.iloc[-1])


# --- targets are arithmetically what they claim ----------------------------


def test_forward_return_matches_hand_calculation():
    px = fake_px()
    pnl = panel.add_targets(px, horizon=3)
    i = 500
    expected = np.log(px["close"].iloc[i + 3] / px["close"].iloc[i])
    assert np.isclose(pnl["fwd_ret_3"].iloc[i], expected)


def test_forward_return_tail_is_nan():
    """The last h rows cannot have a forward return."""
    pnl = panel.add_targets(fake_px(), horizon=3)
    assert pnl["fwd_ret_3"].iloc[-3:].isna().all()


def test_excess_return_removes_market():
    """If the stock IS the market, the excess return must be zero."""
    px = fake_px()
    pnl = panel.add_targets(px, kospi=px, horizon=3)
    assert pnl["fwd_exret_3"].abs().max() < 1e-10


# --- alignment -------------------------------------------------------------


def _trading_days():
    # A Mon-Fri week, with Wed 2024-01-03 removed to stand in for a holiday.
    days = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-04",
                             "2024-01-05", "2024-01-08", "2024-01-09"])
    return days


def _aligned(timestamps_kst, values=None, agg="sum"):
    idx = pd.DatetimeIndex(timestamps_kst).tz_localize("Asia/Seoul").tz_convert("UTC")
    sig = pd.Series(values if values is not None else [1.0] * len(idx), index=idx)
    return align.align_to_trading_days(sig, _trading_days(), agg=agg)


def test_before_close_lands_on_same_day():
    out = _aligned(["2024-01-05 15:29"])
    assert out.loc["2024-01-05"] == 1.0


def test_at_close_lands_on_same_day():
    out = _aligned(["2024-01-05 15:30"])
    assert out.loc["2024-01-05"] == 1.0


def test_one_minute_after_close_lands_on_next_trading_day():
    out = _aligned(["2024-01-05 15:31"])
    assert np.isnan(out.loc["2024-01-05"]) or out.loc["2024-01-05"] == 0
    assert out.loc["2024-01-08"] == 1.0


def test_weekend_accumulates_into_next_session():
    out = _aligned(["2024-01-06 10:00", "2024-01-07 22:00", "2024-01-08 09:00"])
    assert out.loc["2024-01-08"] == 3.0


def test_holiday_accumulates_into_next_session():
    """2024-01-03 is absent from the calendar; its activity belongs to the 4th."""
    out = _aligned(["2024-01-03 11:00", "2024-01-04 10:00"])
    assert out.loc["2024-01-04"] == 2.0


def test_utc_timestamp_near_midnight_kst_maps_correctly():
    """23:00 UTC on the 4th is 08:00 KST on the 5th — before the 5th's close."""
    idx = pd.DatetimeIndex(["2024-01-04 23:00"]).tz_localize("UTC")
    out = align.align_to_trading_days(pd.Series([1.0], index=idx), _trading_days())
    assert out.loc["2024-01-05"] == 1.0


def test_mean_aggregation():
    out = _aligned(["2024-01-06 10:00", "2024-01-07 10:00"], values=[2.0, 4.0],
                   agg="mean")
    assert out.loc["2024-01-08"] == 3.0


def test_naive_index_passes_through():
    days = _trading_days()
    sig = pd.Series(range(len(days)), index=days, dtype=float)
    out = align.align_to_trading_days(sig, days)
    pd.testing.assert_series_equal(out, sig)


# --- rebasing and comparison quotes (dashboard overlay) ---------------------


def _series(values, start="2024-01-02"):
    return pd.Series(values, dtype="float64",
                     index=pd.bdate_range(start, periods=len(values), name="date"))


def test_rebase_starts_at_100_and_preserves_ratios():
    s = _series([250.0, 500.0, 125.0])
    out = prices.rebase(s)
    assert out.iloc[0] == 100.0
    # The whole point: shape is untouched, only the level moves.
    np.testing.assert_allclose(out / out.iloc[0], s / s.iloc[0])


def test_rebase_anchors_on_the_first_observed_value():
    """A US ticker reindexed onto the KRX calendar can start on a US holiday."""
    s = _series([np.nan, np.nan, 400.0, 800.0])
    out = prices.rebase(s)
    assert np.isnan(out.iloc[0])
    assert out.iloc[2] == 100.0
    assert out.iloc[3] == 200.0


def test_rebase_on_degenerate_input_is_nan_not_inf():
    for bad in ([np.nan, np.nan], [0.0, 5.0]):
        out = prices.rebase(_series(bad))
        assert out.isna().all(), f"{bad} produced {out.tolist()}"


def test_invalid_symbol_is_rejected_before_any_fetch_or_cache_write(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("cache/network must not be reached")

    monkeypatch.setattr(prices, "cached", explode)
    for bad in ("../../etc/passwd", "", "A" * 16, "NV DA", "a;b"):
        with pytest.raises(ValueError, match="invalid symbol"):
            prices.load_quote(bad)


def test_empty_download_raises_rather_than_caching_emptiness(monkeypatch, tmp_path):
    """yfinance answers a bad-but-well-formed symbol with an empty frame."""
    import time
    import types

    monkeypatch.setattr(prices, "CACHE_DIR", tmp_path)
    calls = []
    fake = types.SimpleNamespace(
        download=lambda *a, **k: calls.append(1) or pd.DataFrame()
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with pytest.raises(ValueError, match="no data for"):
        prices.load_quote("NOTATICKER")
    assert len(calls) == 2, "an empty result must be retried once before giving up"
    assert not list(tmp_path.glob("*.parquet")), "an empty frame was cached"


def test_a_throttled_first_attempt_is_retried_not_reported_as_missing(monkeypatch,
                                                                     tmp_path):
    """The failure that made Shin-Etsu look like it had no data."""
    import time
    import types

    monkeypatch.setattr(prices, "CACHE_DIR", tmp_path)
    good = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [7.0],
         "Volume": [10]},
        index=pd.DatetimeIndex(["2024-01-02"]),
    )
    tries = []

    def flaky(*a, **k):
        tries.append(1)
        return pd.DataFrame() if len(tries) == 1 else good

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=flaky))
    monkeypatch.setattr(time, "sleep", lambda _: None)

    out = prices.load_quote("4063.T")
    assert len(tries) == 2
    assert out["close"].tolist() == [7.0]


# --- price cross-check (network) -------------------------------------------


@pytest.mark.slow
def test_load_quote_returns_a_real_peer_series():
    px = prices.load_prices(start="2024-01-01", end="2024-12-31")
    peer = prices.load_quote("005930.KS", start="2024-01-01", end="2024-12-31")
    assert not peer.empty
    overlap = px.index.intersection(peer.index)
    assert len(overlap) > 200, f"only {len(overlap)} overlapping days"
    assert (peer["close"] > 0).all()


@pytest.mark.slow
def test_pykrx_matches_yfinance():
    """Sanity-check the price source against an independent one, once."""
    import yfinance as yf

    from quant import prices

    px = prices.load_prices(start="2024-01-01", end="2024-12-31")
    yf_px = yf.download("000660.KS", start="2024-01-01", end="2024-12-31",
                        progress=False, auto_adjust=False)
    yclose = yf_px["Close"].squeeze()
    yclose.index = pd.DatetimeIndex(yclose.index).tz_localize(None).normalize()

    common = px.index.intersection(yclose.index)
    assert len(common) > 200, f"only {len(common)} overlapping days"

    rng = np.random.default_rng(0)
    sample = common[rng.choice(len(common), 20, replace=False)]
    diff = (px.loc[sample, "close"] - yclose.loc[sample]).abs() / yclose.loc[sample]
    assert diff.max() < 0.01, f"close prices disagree by up to {diff.max():.2%}"


# --- Wikipedia pageviews: UTC day -> trading day ----------------------------


def _pv(dates, views):
    """A daily pageview series keyed by UTC calendar date."""
    return pd.Series(views, index=pd.DatetimeIndex(dates), dtype="float64",
                     name="pv")


def test_daily_utc_stamped_at_the_close_of_its_own_day():
    """A UTC day's count is stamped 00:00 UTC of the NEXT day.

    That is the first instant the day's total exists. Anything earlier would be
    claiming knowledge of views that had not happened yet.
    """
    out = align.daily_utc_to_timestamps(_pv(["2024-01-10"], [7.0]))
    assert out.index[0] == pd.Timestamp("2024-01-11 00:00", tz="UTC")
    assert out.iloc[0] == 7.0


def test_pageviews_land_on_the_next_trading_day_not_the_same_one():
    """The load-bearing +1 day in daily_utc_to_timestamps.

    Without it, UTC day D lands on trading day D, so a count covering all 24h of
    D — 17.5h of which fall after the 06:30 UTC close — would be used to predict
    D's own forward return. Nothing in the output would show it; results would
    simply look better. Remove the `+ pd.to_timedelta(1, unit="D")` and this fails.
    """
    days = pd.DatetimeIndex(["2024-01-09", "2024-01-10", "2024-01-11"])
    out = align.align_to_trading_days(
        align.daily_utc_to_timestamps(_pv(["2024-01-09", "2024-01-10"], [5.0, 9.0])),
        days, agg="sum",
    )
    assert out["2024-01-10"] == 5.0    # views from the 9th
    assert out["2024-01-11"] == 9.0    # views from the 10th
    assert np.isnan(out["2024-01-09"]) # nothing known before the window starts


def test_weekend_pageviews_accumulate_into_monday():
    """Fri/Sat/Sun UTC days are all first tradeable at Monday's close."""
    days = pd.DatetimeIndex(["2024-01-11", "2024-01-12", "2024-01-15"])  # Thu Fri Mon
    out = align.align_to_trading_days(
        align.daily_utc_to_timestamps(
            _pv(["2024-01-12", "2024-01-13", "2024-01-14"], [1.0, 2.0, 4.0])),
        days, agg="sum",
    )
    assert out["2024-01-15"] == 7.0


def test_holiday_pageviews_accumulate_into_next_session():
    """A gap in the trading calendar rolls its pageviews forward, not away."""
    days = pd.DatetimeIndex(["2024-02-08", "2024-02-13"])  # Seollal closure between
    out = align.align_to_trading_days(
        align.daily_utc_to_timestamps(
            _pv(["2024-02-09", "2024-02-10", "2024-02-11"], [3.0, 3.0, 3.0])),
        days, agg="sum",
    )
    assert out["2024-02-13"] == 9.0


def test_pageview_signal_matches_previous_utc_day(monkeypatch, tmp_path):
    """End to end through signals.wiki_hynix, with the fetch stubbed out.

    Asserts the identity the whole design rests on: the signal on trading day t
    is the pageview count of the UTC day before t.
    """
    px = fake_px(n=40)
    raw = pd.Series(
        np.arange(len(px) + 40, dtype="float64"),
        index=pd.date_range(px.index[0] - pd.to_timedelta(20, unit="D"), periods=len(px) + 40,
                            freq="D"),
    )
    monkeypatch.setattr(wiki, "load_pageviews", lambda key, start, end: raw.rename(key))

    sig = signals.SIGNALS["wiki_hynix"](px, None)
    t = px.index[10]
    prev = t - pd.to_timedelta(1, unit="D")
    if t.dayofweek == 0:                       # Monday sums Fri+Sat+Sun
        expected = raw[t - pd.to_timedelta(3, unit="D"):prev].sum()
    else:
        expected = raw[prev]
    assert sig[t] == expected
    assert sig.name == "wiki_hynix"


def test_missing_pageview_day_is_nan_not_zero(tmp_path):
    """An API gap must not read as 'nobody looked at the article'."""
    def fetch():
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        return pd.Series([5.0, np.nan, 7.0], index=idx).to_frame("views")

    got = cache.cached(tmp_path / "pv.parquet", fetch)["views"]
    assert np.isnan(got.iloc[1])
    assert got.iloc[0] == 5.0


def test_wiki_signals_are_registered():
    for name in ("wiki_hynix", "wiki_semi", "wiki_hbm"):
        assert name in signals.SIGNALS


@pytest.mark.slow
def test_pageviews_fetch_is_live_and_complete():
    """The real API returns every calendar day in the window."""
    s = wiki.load_pageviews("hynix", "2024-01-01", "2024-03-31")
    assert s.notna().all()
    assert s.index[-1] == pd.Timestamp("2024-03-31")
    assert (s > 0).all()


# --- dow_zscore: the day-of-week baseline -----------------------------------


def _weekly_cycle(n=120, monday_multiple=10.0, seed=1):
    """A series with a strong Monday level effect and ordinary daily noise.

    Noise matters: a perfectly constant series has zero rolling std, which the
    transform maps to NaN, so the tests would pass vacuously.
    """
    idx = pd.bdate_range("2024-01-01", periods=n, name="date")
    rng = np.random.default_rng(seed)
    level = np.where(idx.dayofweek == 0, monday_multiple, 1.0) * 100
    return pd.Series(level * rng.lognormal(0, 0.15, n), index=idx)


def test_dow_zscore_compares_against_the_same_weekday():
    """Baseline for a Monday is the preceding Mondays, not the preceding 20 days.

    With Mondays 10x every other day, a plain z-score calls every Monday
    abnormal. dow_zscore should call them ordinary — because they are ordinary
    *for a Monday*.
    """
    s = _weekly_cycle()
    plain = panel.transform(s, "zscore", window=20).dropna()
    dow = panel.transform(s, "dow_zscore", window=20).dropna()

    # Medians, not means: a 4-observation std occasionally collapses and throws
    # a huge z, which drags a mean around without saying anything about bias.
    assert plain[plain.index.dayofweek == 0].median() > 1.5
    assert abs(dow[dow.index.dayofweek == 0].median()) < 0.5
    # and no weekday is systematically favoured
    assert dow.groupby(dow.index.dayofweek).median().abs().max() < 0.5


def test_dow_zscore_still_detects_a_genuine_spike():
    """Flattening the weekday cycle must not flatten real news."""
    s = _weekly_cycle()
    spike = s.index[80]
    s.loc[spike] *= 4                            # a real 4x jump

    dow = panel.transform(s, "dow_zscore", window=20)
    assert dow[spike] > 2.0
    assert dow[spike] > dow.drop(spike).abs().max()


def test_dow_zscore_removes_the_monday_bias_on_real_signal_shape():
    """The artifact this transform exists for.

    Monday accumulates a weekend, so under a mixed baseline it dominates the
    top quintile. Asserted on the same statistic quoted in CLAUDE.md.
    """
    idx = pd.bdate_range("2020-01-01", periods=600, name="date")
    rng = np.random.default_rng(3)
    base = np.where(idx.dayofweek == 0, 3.0, 1.0) * 400
    s = pd.Series(base * rng.lognormal(0, 0.25, len(idx)), index=idx)

    def monday_share(z):
        z = z.dropna()
        return (z[z >= z.quantile(0.8)].index.dayofweek == 0).mean()

    assert monday_share(panel.transform(s, "zscore", 20)) > 0.60
    assert 0.10 < monday_share(panel.transform(s, "dow_zscore", 20)) < 0.32


def test_wiki_signals_use_mean_and_dow_zscore():
    """Neither setting fixes the weekday artifact alone; both are required."""
    for name in ("wiki_hynix", "wiki_semi", "wiki_hbm"):
        assert signals.SIGNAL_AGG[name] == "mean"
        assert signals.DEFAULT_TRANSFORM[name] == "dow_zscore"
