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

from quant import align, cache, naver, panel, prices, signals, stats, wiki  # noqa: E402

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


def test_evaluate_reports_significance_and_sample_for_the_long_short():
    """The spread's p and its own n must survive `evaluate`.

    Both were computed by long_short and dropped, leaving a t-statistic with no
    significance beside it and the full-sample n, which reads as though the
    spread were measured on every day rather than the extreme buckets.
    """
    res = stats.evaluate(build("planted", seed=0), horizon=3, q=5)
    for k in ("ls_p", "ls_n"):
        assert k in res, f"evaluate dropped {k}"
    assert 0.0 <= res["ls_p"] <= 1.0
    # Two of five buckets, so roughly 40% of the regression sample.
    assert res["ls_n"] < res["n"], "long-short must use fewer days than the full fit"
    assert 0.3 < res["ls_n"] / res["n"] < 0.5, res["ls_n"] / res["n"]


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


# --- Naver search trends: KST day -> trading day -----------------------------

NAVER_SIGNALS = ("naver_hynix", "naver_semi", "naver_hbm", "naver_memory",
                 "naver_samsung")


def _nv(dates, values):
    """A daily search-trend series keyed by KST calendar date."""
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype="float64",
                     name="nv")


def test_daily_kst_stamped_at_the_close_of_its_own_day():
    """A KST day's total is stamped 00:00 KST of the NEXT day.

    That instant is 15:00 UTC on the day itself - 8.5h after the 06:30 UTC KRX
    close, so the value cannot reach the session it would otherwise predict.
    """
    out = align.daily_kst_to_timestamps(_nv(["2024-01-10"], [7.0]))
    assert out.index[0] == pd.Timestamp("2024-01-11 00:00", tz=align.KST)
    assert out.index[0].tz_convert("UTC") == pd.Timestamp("2024-01-10 15:00", tz="UTC")
    assert out.iloc[0] == 7.0


def test_naver_day_lands_on_the_next_trading_day_not_the_same_one():
    """The look-ahead guard, matching the pageview one.

    A Naver day covers 00:00-24:00 KST while the market closes at 15:30 KST, so
    attributing day D to session D would use 8.5h of post-close searching to
    predict that session's own forward return.
    """
    days = _trading_days()
    out = align.align_to_trading_days(
        align.daily_kst_to_timestamps(_nv(["2024-01-08"], [50.0])), days, agg="mean")
    assert pd.isna(out.loc["2024-01-08"]), "KST day D leaked into session D"
    assert out.loc["2024-01-09"] == 50.0


def test_naver_weekend_days_accumulate_into_monday():
    """Monday's bucket spans Fri+Sat+Sun; with agg='mean' it is their average.

    This is what depresses Monday - weekend search runs at ~12% of weekday
    search - and it is why dow_zscore is mandatory for these signals.
    """
    days = _trading_days()
    out = align.align_to_trading_days(
        align.daily_kst_to_timestamps(
            _nv(["2024-01-05", "2024-01-06", "2024-01-07"], [9.0, 1.0, 2.0])),
        days, agg="mean")
    assert out.loc["2024-01-08"] == pytest.approx(4.0)


def test_naver_signals_are_registered_with_mean_and_dow_zscore():
    """dow_zscore is not a preference here: under plain zscore, Monday's share
    of the top quintile measures 0.0% on the real series."""
    for name in NAVER_SIGNALS:
        assert name in signals.SIGNALS
        assert signals.SIGNAL_AGG[name] == "mean"
        assert signals.DEFAULT_TRANSFORM[name] == "dow_zscore"


def _workbook(path, period="일간 : 2019-01-01 ~ 2019-01-03", scope="합계",
              gender="전체(여성,남성)", ages="전체"):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = naver.SHEET
    for row in [("url", "http://datalab.naver.com/keyword/trendResult.naver?hashKey=X"),
                ("주제", "통검"), ("범위", scope), ("기간", period),
                ("성별", gender), ("연령대", ages), ("날짜", "topic"),
                ("2019-01-01", "1.5"), ("2019-01-02", "2.5"), ("2019-01-03", "3.5")]:
        ws.append(row)
    wb.save(path)
    return path


def test_loader_reads_a_kst_keyed_series(tmp_path, monkeypatch):
    monkeypatch.setattr(naver, "CACHE_DIR", tmp_path)
    monkeypatch.setitem(naver.FILES, "hynix", "wb.xlsx")
    _workbook(tmp_path / "wb.xlsx")

    s = naver.load_trend("hynix")
    assert list(s.index) == list(pd.DatetimeIndex(
        ["2019-01-01", "2019-01-02", "2019-01-03"]))
    assert s.tolist() == [1.5, 2.5, 3.5]
    assert s.index.tz is None, "calendar dates, not timestamps - align.py converts"


@pytest.mark.parametrize("bad,field", [
    ({"period": "주간 : 2019-01-01 ~ 2019-01-03"}, "기간"),
    ({"scope": "모바일"}, "범위"),
    ({"gender": "남성"}, "성별"),
    ({"ages": "20-29"}, "연령대"),
])
def test_loader_rejects_a_wrongly_exported_workbook(tmp_path, monkeypatch, bad, field):
    """The settings are hand-set toggles in a web UI.

    A weekly or device-filtered export loads, aligns and regresses without
    complaint, producing a result for a different question than the one asked.
    Nothing downstream would reveal it, so it is caught at the door.
    """
    monkeypatch.setattr(naver, "CACHE_DIR", tmp_path)
    monkeypatch.setitem(naver.FILES, "hynix", "wb.xlsx")
    _workbook(tmp_path / "wb.xlsx", **bad)

    with pytest.raises(ValueError, match=field):
        naver.load_trend("hynix")


def test_loader_names_the_recovery_path_when_a_workbook_is_missing(tmp_path, monkeypatch):
    """The files are gitignored and the API is closed, so a clone hits this."""
    monkeypatch.setattr(naver, "CACHE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="data-sources.md"):
        naver.load_trend("hynix")


@pytest.mark.slow
def test_naver_dow_artifact_is_real_and_dow_zscore_fixes_it():
    """Pins the measurement that decided the transform. Needs data/.

    Under plain zscore Monday never reaches the top quintile at all, because its
    bucket averages Fri+Sat+Sun and weekend search is ~12% of weekday search.
    """
    from quant import prices

    px = prices.load_prices()
    sig = signals.load_signal("naver_hynix", px)

    def monday_share(kind):
        z = panel.transform(sig, kind=kind, window=20).dropna()
        return (z[z >= z.quantile(0.8)].index.dayofweek == 0).mean()

    assert monday_share("zscore") < 0.05, "expected Monday to be locked out"
    assert 0.15 < monday_share("dow_zscore") < 0.25


# --- tail (outlier) evaluation ----------------------------------------------


def test_tail_test_detects_the_planted_effect():
    """A fixture built to be detectable must fire here too."""
    pnl = build("planted", seed=0)
    r = stats.tail_test(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    assert r["excess"] > 0 and r["p"] < 0.05, r


def test_tail_test_reads_null_on_noise():
    pnl = build("noise", seed=11)
    r = stats.tail_test(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    assert r["p"] > 0.05, r


def test_tail_test_uses_the_whole_sample_unlike_long_short():
    """long_short throws away the middle; this must not."""
    pnl = build("planted", seed=0)
    r = stats.tail_test(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    full = stats.ols_hac(pnl["fwd_ret_3"], pnl["signal"], maxlags=3)
    assert r["n_tail"] + r["n_rest"] == full["n"]


def test_tail_test_finds_what_rank_ic_dilutes():
    """The reason the function exists.

    A signal whose top decile carries a large effect and whose remaining 90% is
    pure noise: rank IC averages the effect away across the flat majority, while
    the tail test looks only where the effect lives.
    """
    px = fake_px()
    pnl = panel.add_targets(px, horizon=3)
    rng = np.random.default_rng(0)

    sig = pd.Series(rng.standard_normal(len(px)), index=px.index)
    fwd = pd.Series(rng.standard_normal(len(px)) * 0.02, index=px.index)
    spike = sig > sig.quantile(0.90)
    fwd[spike] += 0.05                      # effect ONLY in the tail

    ic = abs(stats.rank_ic(sig, fwd))
    tail = stats.tail_test(sig, fwd, maxlags=3, threshold=sig.quantile(0.90))
    assert ic < 0.25, f"rank IC {ic:.3f} — the dilution premise does not hold"
    assert tail["p"] < 0.001, tail
    assert tail["excess"] > 0.03, tail


def test_tail_test_returns_nan_when_the_tail_is_empty():
    """A threshold above every observation must not raise."""
    pnl = build("noise", seed=3)
    r = stats.tail_test(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=99.0)
    assert r["n_tail"] == 0 and np.isnan(r["excess"])


def test_tail_curve_covers_the_grid_and_shrinks_monotonically():
    pnl = build("planted", seed=0)
    c = stats.tail_curve(pnl["signal"], pnl["fwd_ret_3"], maxlags=3)
    assert list(c["threshold"]) == list(stats.TAIL_GRID)
    assert c["n_tail"].is_monotonic_decreasing, c[["threshold", "n_tail"]]


def test_evaluate_exposes_the_tail_result():
    res = stats.evaluate(build("planted", seed=0), horizon=3, tail_z=1.0)
    for k in ("tail_z", "tail_excess", "tail_t", "tail_p", "tail_n"):
        assert k in res, f"evaluate dropped {k}"
    assert res["tail_z"] == 1.0
    assert res["tail_n"] < res["n"]


# --- event metrics for outlier days -----------------------------------------


def test_event_metrics_uses_the_whole_sample():
    pnl = build("planted", seed=0)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    full = stats.ols_hac(pnl["fwd_ret_3"], pnl["signal"], maxlags=3)
    assert e["n_events"] + e["n_rest"] == full["n"]


def test_event_mean_difference_agrees_with_tail_test():
    """Two functions computing the same quantity must not disagree."""
    pnl = build("planted", seed=0)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    t = stats.tail_test(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    assert e["mean_event"] - e["mean_rest"] == pytest.approx(t["excess"], abs=1e-9)


def test_hit_diff_is_the_difference_in_hit_rates():
    """The LPM coefficient must be the hit-rate difference, not something else.

    This is what makes the HAC t and p attach to the number on screen. A
    misspecified regression would still return a plausible t.
    """
    pnl = build("planted", seed=0)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    assert e["hit_diff"] == pytest.approx(e["hit_rate"] - e["base_rate"], abs=1e-9)


def test_base_rate_is_a_half_by_construction():
    """The baseline is the non-event median, so ~50% of them beat it.

    Pinned because it is what makes hit_rate readable: any departure from 50%
    on the comparison group means the baseline is not what it claims to be.
    """
    for name, seed in (("planted", 0), ("noise", 5), ("past_return", 0)):
        pnl = build(name, seed=seed)
        e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3,
                                threshold=pnl["signal"].quantile(0.9))
        assert abs(e["base_rate"] - 0.5) < 0.02, (name, e["base_rate"])


def test_event_metrics_detect_the_planted_effect():
    pnl = build("planted", seed=0)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    assert e["mean_event"] > e["mean_rest"]
    assert e["hit_rate"] > e["base_rate"]


def test_the_hit_rate_has_less_power_than_the_mean():
    """Measured, and a caveat worth pinning rather than discovering later.

    Collapsing every return to a 0/1 "beat the median" throws away magnitude, so
    the same known rho=0.15 effect that the mean test clears at p=0.015 leaves
    the hit rate at p=0.142 on identical data. The hit rate is a supporting
    statistic, never a headline one.
    """
    pnl = build("planted", seed=0)
    mean_test = stats.tail_test(pnl["signal"], pnl["fwd_ret_3"], maxlags=3,
                                threshold=1.0)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)

    assert mean_test["p"] < 0.05, "the mean test should detect the fixture"
    assert e["hit_rate"] > e["base_rate"], "the hit rate should still point the right way"
    assert e["hit_p"] > mean_test["p"], (
        f"hit rate p={e['hit_p']:.4f} was not weaker than mean p={mean_test['p']:.4f}"
    )


def test_event_metrics_read_null_on_noise():
    pnl = build("noise", seed=11)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=1.0)
    assert e["hit_p"] > 0.05
    assert abs(e["hit_rate"] - e["base_rate"]) < 0.1


def test_event_metrics_return_nan_when_no_events():
    """Reachable: a raw-transform signal whose values all sit above the cut."""
    pnl = build("noise", seed=3)
    e = stats.event_metrics(pnl["signal"], pnl["fwd_ret_3"], maxlags=3, threshold=99.0)
    assert e["n_events"] == 0
    assert np.isnan(e["hit_rate"]) and np.isnan(e["abs_ratio"])


def test_evaluate_exposes_the_event_metrics():
    res = stats.evaluate(build("planted", seed=0), horizon=3, tail_z=1.0)
    for k in ("ev_n_events", "ev_mean_event", "ev_mean_rest", "ev_hit_rate",
              "ev_base_rate", "ev_hit_p", "ev_abs_ratio"):
        assert k in res, f"evaluate dropped {k}"
    assert res["ev_n_events"] + res["ev_n_rest"] == res["n"]


# --- GDELT fetcher and headline sentiment ------------------------------------


def _articles(n, start="2024-06-01T00:00:00Z"):
    """n fake GDELT article dicts with the real field names."""
    t0 = pd.Timestamp(start)
    # url must be unique across calls: load_articles dedupes on it, so a helper
    # reusing urls would silently drop every month after the first.
    return [{"url": f"http://x/{t0:%Y%m%d}/{i}", "url_mobile": "",
             "title": f"headline {i}",
             "seendate": (t0 + pd.to_timedelta(i, unit="m")).strftime("%Y%m%dT%H%M%SZ"),
             "socialimage": "", "domain": "x.com", "language": "English",
             "sourcecountry": "US"} for i in range(n)]


def test_full_page_splits_the_window(monkeypatch):
    """The fetcher's core correctness property.

    GDELT caps at 250 and returns the NEWEST first, so a full page means the
    oldest articles in that window were silently dropped. Not splitting would
    left-censor every chunk, which looks like low news volume rather than a bug.
    """
    from quant import gdelt

    calls = []

    def fake_get(query, start, end):
        calls.append((start, end))
        # full page only for the first (widest) request
        return _articles(gdelt.MAXRECORDS if len(calls) == 1 else 3)

    monkeypatch.setattr(gdelt, "_get", fake_get)
    out = []
    gdelt._walk("q", pd.Timestamp("2024-06-01"), pd.Timestamp("2024-07-01"), out)

    assert len(calls) == 3, f"expected split into 2 halves, got {len(calls)} calls"
    assert calls[1][1] == calls[2][0], "halves must meet at the midpoint"
    assert len(out) == 6


def test_partial_page_does_not_split(monkeypatch):
    from quant import gdelt

    calls = []

    def fake_get(query, start, end):
        calls.append((start, end))
        return _articles(10)

    monkeypatch.setattr(gdelt, "_get", fake_get)
    out = []
    gdelt._walk("q", pd.Timestamp("2024-06-01"), pd.Timestamp("2024-07-01"), out)
    assert len(calls) == 1 and len(out) == 10


def test_splitting_stops_at_the_floor(monkeypatch):
    """A single day busier than the cap cannot be fixed by halving.

    It must terminate and warn rather than recurse forever.
    """
    from quant import gdelt

    monkeypatch.setattr(gdelt, "_get",
                        lambda q, s, e: _articles(gdelt.MAXRECORDS))
    out = []
    gdelt._walk("q", pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-02"), out)
    assert len(out) > 0


def test_rate_limit_body_is_not_parsed_as_data(monkeypatch):
    """GDELT refuses with plain text and a 200 status.

    Treating a non-empty response as success caches an error string as if it
    were articles - the exact mistake that lost a measurement while planning.
    """
    import io

    from quant import gdelt

    monkeypatch.setattr(gdelt.time, "sleep", lambda _: None)
    monkeypatch.setattr(gdelt.urllib.request, "urlopen",
                        lambda *a, **k: io.BytesIO(
                            gdelt.LIMIT_MARK.encode() + b" to one every 5 seconds"))
    assert gdelt._get("q", pd.Timestamp("2024-06-01"), pd.Timestamp("2024-07-01")) is None


def test_unreachable_gdelt_raises_rather_than_caching_nothing(monkeypatch):
    from quant import gdelt

    monkeypatch.setattr(gdelt, "_get", lambda *a: None)
    with pytest.raises(RuntimeError, match="unreachable"):
        gdelt._walk("q", pd.Timestamp("2024-06-01"), pd.Timestamp("2024-07-01"), [])


def test_month_cache_is_not_refetched(monkeypatch, tmp_path):
    from quant import gdelt

    monkeypatch.setattr(gdelt, "CACHE_DIR", tmp_path)
    calls = []

    def fake_walk(query, start, end, out):
        calls.append(start)
        out.extend(_articles(5, start=f"{start:%Y-%m-%d}T00:00:00Z"))

    monkeypatch.setattr(gdelt, "_walk", fake_walk)
    a = gdelt.load_articles("q", "2024-06-01", "2024-07-01")
    assert len(calls) == 1 and len(a) == 5

    b = gdelt.load_articles("q", "2024-06-01", "2024-07-01")
    assert len(calls) == 1, "second call refetched a cached month"
    assert len(b) == 5


@pytest.mark.parametrize("raw,want", [
    ("Micron , SK hynix , Oracle", "Micron, SK hynix, Oracle"),
    ("12 . 8 Gbps , Inching Closer", "12.8 Gbps, Inching Closer"),
    ("Apple Is Facing A Shift ; Memory", "Apple Is Facing A Shift; Memory"),
    ("clean headline", "clean headline"),
])
def test_gdelt_punctuation_spacing_is_undone(raw, want):
    """GDELT pre-tokenises titles; FinBERT was not trained on that spacing."""
    from quant import sentiment

    assert sentiment.clean_headline(raw) == want


@pytest.mark.slow
def test_finbert_reads_obvious_financial_headlines(tmp_path, monkeypatch):
    """Loads the real model. Signs must be right or the pipeline is wrong."""
    from quant import sentiment

    monkeypatch.setattr(sentiment, "CACHE", tmp_path / "s.parquet")
    monkeypatch.setattr(sentiment, "CACHE_DIR", tmp_path)
    s = sentiment.score_headlines(pd.Series([
        "Memory prices surge as DRAM demand beats expectations",
        "Chipmaker plunges after slashing guidance on weak demand",
    ]))
    assert s.iloc[0] > 0.2, s.tolist()
    assert s.iloc[1] < -0.2, s.tolist()


def test_signal_never_triggers_a_backfill(monkeypatch, tmp_path):
    """Opening the dashboard must not start an hour of rate-limited fetching.

    gdelt_sent_semi sorts first in SIGNALS, so it is the app's default
    selection. With allow_fetch defaulting to True a page load would kick off
    the whole backfill; the signal must read the cache and say what to run.
    """
    from quant import gdelt

    monkeypatch.setattr(gdelt, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(gdelt, "_walk",
                        lambda *a: pytest.fail("signal attempted a network fetch"))
    with pytest.raises(FileNotFoundError, match="fetch_gdelt"):
        gdelt.load_articles("q", "2024-06-01", "2024-07-01", allow_fetch=False)


def test_one_unreachable_month_does_not_abort_the_backfill(monkeypatch, tmp_path, capsys):
    """A 91-month backfill must survive a throttled month.

    Nothing is written for the failure, so a re-run retries it, and the skip is
    printed rather than swallowed. The analysis path refuses missing months
    separately, so a gap cannot reach a regression as "no news".
    """
    from quant import gdelt

    monkeypatch.setattr(gdelt, "CACHE_DIR", tmp_path)

    def flaky(query, start, end, out):
        if start.month == 2:
            raise RuntimeError("GDELT unreachable")
        out.extend(_articles(4, start=f"{start:%Y-%m-%d}T00:00:00Z"))

    monkeypatch.setattr(gdelt, "_walk", flaky)
    got = gdelt.load_articles("q", "2024-01-01", "2024-04-01")

    assert len(got) == 8, "January and March should still be present"
    assert not (tmp_path / "gdelt" / "q_202402.parquet").exists(), \
        "a failed month must not be cached, or a re-run would skip it"
    assert "2024-02" in capsys.readouterr().out


def test_dashboard_default_signal_needs_no_hand_fetched_data():
    """A fresh clone must be able to open the app.

    gdelt_sent_semi sorts first and needs a hand-run backfill, so an
    alphabetical default meant opening the page raised FileNotFoundError.
    The default is the declared primary instead.
    """
    src = (ROOT / "app.py").read_text()
    assert '_pick("Signal", "naver_hynix"' in src, \
        "the single-signal picker no longer defaults to naver_hynix"
    assert sorted(signals.SIGNALS)[0] == "gdelt_sent_semi", \
        "the alphabetical-first signal changed; re-check the default is still safe"


def test_missing_runs_finds_gaps_but_ignores_scattered_nans():
    """Scattered NaNs are ordinary for a sparse source; a run is a source gap.

    Only the run should be reported, or the coverage panel becomes noise on
    exactly the signals that need it most.
    """
    idx = pd.bdate_range("2024-01-01", periods=40, name="date")
    s = pd.Series(1.0, index=idx)
    s.iloc[3] = np.nan                 # isolated
    s.iloc[10] = np.nan                # isolated
    s.iloc[20:28] = np.nan             # an 8-day run

    runs = panel.missing_runs(s, min_len=3)
    assert len(runs) == 1, runs
    assert runs.iloc[0]["trading_days"] == 8
    assert runs.iloc[0]["from"] == idx[20] and runs.iloc[0]["to"] == idx[27]


def test_missing_runs_handles_a_gap_at_the_end():
    idx = pd.bdate_range("2024-01-01", periods=10, name="date")
    s = pd.Series(1.0, index=idx)
    s.iloc[7:] = np.nan
    runs = panel.missing_runs(s, min_len=3)
    assert len(runs) == 1 and runs.iloc[0]["to"] == idx[-1]


def test_missing_runs_is_empty_for_a_complete_signal():
    idx = pd.bdate_range("2024-01-01", periods=20, name="date")
    assert panel.missing_runs(pd.Series(1.0, index=idx)).empty


def test_score_cache_round_trips(tmp_path, monkeypatch):
    """Scoring twice must hit the cache, not raise.

    The first write named the value column `0` instead of `score`, because
    pd.concat drops a Series name when the other operand is unnamed. Writing
    succeeded and the read-back raised KeyError('score') - invisible to any
    test that only calls score_headlines once.
    """
    from quant import sentiment

    monkeypatch.setattr(sentiment, "CACHE", tmp_path / "s.parquet")
    monkeypatch.setattr(sentiment, "CACHE_DIR", tmp_path)

    calls = []

    class FakePipe:
        def __call__(self, texts):
            calls.append(len(texts))
            return [[{"label": "positive", "score": 0.8},
                     {"label": "negative", "score": 0.1},
                     {"label": "neutral", "score": 0.1}] for _ in texts]

    monkeypatch.setattr(sentiment, "_pipeline", lambda: FakePipe())

    titles = pd.Series(["Memory prices surge", "Chipmaker cuts guidance"])
    first = sentiment.score_headlines(titles)
    assert first.tolist() == pytest.approx([0.7, 0.7])
    assert sum(calls) == 2, "first call should score both headlines"

    # The line that used to raise.
    second = sentiment.score_headlines(titles)
    assert second.tolist() == pytest.approx([0.7, 0.7])
    assert sum(calls) == 2, "second call re-scored instead of hitting the cache"

    stored = pd.read_parquet(tmp_path / "s.parquet")
    assert list(stored.columns) == ["key", "score"], stored.columns.tolist()


def test_unusable_sentiment_cache_rebuilds_instead_of_crashing(tmp_path, monkeypatch,
                                                               capsys):
    """A cache is an optimisation; a broken one must cost time, not break.

    The first release wrote the value column as `0`, and the read raised
    KeyError deep inside the signal - which reached the user as a dashboard
    traceback with no indication that deleting one file would fix it.
    """
    from quant import sentiment

    cache = tmp_path / "s.parquet"
    pd.DataFrame({"key": ["abc"], "0": [0.5]}).to_parquet(cache, index=False)
    monkeypatch.setattr(sentiment, "CACHE", cache)
    monkeypatch.setattr(sentiment, "CACHE_DIR", tmp_path)

    class FakePipe:
        def __call__(self, texts):
            return [[{"label": "positive", "score": 0.9},
                     {"label": "negative", "score": 0.05},
                     {"label": "neutral", "score": 0.05}] for _ in texts]

    monkeypatch.setattr(sentiment, "_pipeline", lambda: FakePipe())

    out = sentiment.score_headlines(pd.Series(["Memory prices surge"]))
    assert out.iloc[0] == pytest.approx(0.85)
    assert "unusable" in capsys.readouterr().out
    assert list(pd.read_parquet(cache).columns) == ["key", "score"]


def test_coverage_reports_the_signals_real_span():
    """A window set wider than the data just yields NaN and says nothing.

    coverage() is what tells the reader the requested period and the period
    with data are different.
    """
    idx = pd.bdate_range("2024-01-01", periods=30, name="date")
    s = pd.Series(np.nan, index=idx)
    s.iloc[10:20] = 1.0                       # data only in the middle

    cov = panel.coverage(s)
    assert cov["first"] == idx[10]
    assert cov["last"] == idx[19]
    assert cov["n_have"] == 10 and cov["n_total"] == 30


def test_coverage_handles_a_signal_with_no_data():
    idx = pd.bdate_range("2024-01-01", periods=10, name="date")
    cov = panel.coverage(pd.Series(np.nan, index=idx))
    assert cov["first"] is None and cov["last"] is None and cov["n_have"] == 0


# --- combining signals -------------------------------------------------------


def test_trailing_rank_cannot_see_the_future():
    """THE test for this feature.

    A full-sample percentile rank passes every other check here while encoding
    tomorrow in today's value. Changing everything after t must leave the rank
    at t untouched.
    """
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=200, name="date")
    s = pd.Series(rng.standard_normal(200), index=idx)

    base = panel.trailing_pct_rank(s, window=20)
    tampered = s.copy()
    tampered.iloc[120:] = 999.0                    # rewrite the entire future
    after = panel.trailing_pct_rank(tampered, window=20)

    pd.testing.assert_series_equal(base.iloc[:120], after.iloc[:120])


def test_trailing_rank_bounds_and_warmup():
    idx = pd.bdate_range("2024-01-01", periods=60, name="date")
    rising = pd.Series(np.arange(60.0), index=idx)
    falling = pd.Series(np.arange(60.0)[::-1], index=idx)

    r = panel.trailing_pct_rank(rising, window=20)
    f = panel.trailing_pct_rank(falling, window=20)
    assert r.iloc[:19].isna().all(), "no trailing history yet"
    assert (r.dropna() == 1.0).all(), "a rising series is always a new high"
    assert (f.dropna() == 0.0).all(), "a falling series is always a new low"


def test_combine_sign_always_follows_sentiment():
    """The 110-day case that motivated the design.

    A plain product makes negative x negative positive, so low attention plus
    bad news would score like high attention plus good news.
    """
    idx = pd.bdate_range("2024-01-01", periods=60, name="date")
    rng = np.random.default_rng(1)
    att = pd.Series(rng.standard_normal(60), index=idx)
    sen = pd.Series(rng.standard_normal(60), index=idx).clip(-1, 1)

    out = panel.combine(att, sen, window=20).dropna()
    both_neg = (att < 0) & (sen < 0)
    assert both_neg.sum() > 0, "fixture must contain the case being tested"

    # Where attention ranks above its window's floor, the sign is the
    # sentiment's. A rank of exactly 0 zeroes the product, which is correct
    # (no attention at all) and the only permitted exception.
    weight = panel.trailing_pct_rank(att, window=20)[out.index]
    nonzero = weight > 0
    assert nonzero.sum() > 10, "fixture too degenerate to test signs"
    assert (np.sign(out[nonzero]) == np.sign(sen[out.index][nonzero])).all()
    assert (out[~nonzero] == 0).all()

    # The specific failure the design exists to prevent.
    checked = both_neg[out.index] & nonzero
    assert checked.sum() > 0, "no double-negative day survived to be checked"
    assert (out[checked] < 0).all(), "negative x negative came out positive"


def test_combine_is_nan_where_either_input_is_missing():
    idx = pd.bdate_range("2024-01-01", periods=60, name="date")
    att = pd.Series(1.0, index=idx)
    sen = pd.Series(0.5, index=idx)
    sen.iloc[30:35] = np.nan

    out = panel.combine(att, sen, window=20)
    assert out.iloc[30:35].isna().all(), "missing sentiment must not become zero"


def test_a_single_attention_outlier_cannot_dominate():
    """dow_zscore reaches +50.65 on real data; a raw multiplier would swamp all."""
    idx = pd.bdate_range("2024-01-01", periods=80, name="date")
    rng = np.random.default_rng(2)
    att = pd.Series(rng.standard_normal(80), index=idx)
    att.iloc[50] = 50.65
    sen = pd.Series(0.5, index=idx)

    out = panel.combine(att, sen, window=20).dropna()
    assert out.max() <= 0.5 + 1e-9, "rank is bounded, so the product is too"
    assert out.iloc[out.index.get_loc(idx[50])] <= 0.5 + 1e-9


def test_signal_correlation_uses_the_intersection():
    idx = pd.bdate_range("2024-01-01", periods=100, name="date")
    a = pd.Series(np.arange(100.0), index=idx)
    b = a.copy()
    b.iloc[:60] = np.nan                       # b only exists for 40 days

    r = stats.signal_correlation(a, b)
    assert r["n_overlap"] == 40, "must count shared days, not the union"
    assert r["n_a"] == 100 and r["n_b"] == 40
    assert r["pearson"] == pytest.approx(1.0)
    assert stats.signal_correlation(b, a)["n_overlap"] == 40


def test_describe_reports_the_shape_of_a_signal():
    """Kurtosis is the one that matters: dow_zscore reaches the hundreds, which
    is why rank IC and the HAC t can disagree in sign."""
    idx = pd.bdate_range("2024-01-01", periods=200, name="date")
    rng = np.random.default_rng(0)
    s = pd.Series(rng.standard_normal(200), index=idx)
    s.iloc[100] = 50.0                       # one extreme day

    d = panel.describe(s)
    assert d["n"] == 200
    assert d["max"] == pytest.approx(50.0)
    assert d["kurtosis"] > 50, "one extreme day should show up as fat tails"
    assert d["p99"] < d["max"], "the 99th percentile must sit below an isolated outlier"


def test_describe_handles_an_empty_signal():
    idx = pd.bdate_range("2024-01-01", periods=10, name="date")
    d = panel.describe(pd.Series(np.nan, index=idx))
    assert d["n"] == 0 and np.isnan(d["sd"])


def test_single_and_combined_paths_yield_the_same_panel_shape():
    """The restructure's premise: one analysis path serves both signal sources.

    If the combined branch produced a differently shaped panel, the Test tab
    would need its own rendering again - which is the duplication the layout
    change removed.
    """
    px = fake_px()
    one = signals.SIGNALS["noise"](px, None, seed=0)
    two = panel.combine(signals.SIGNALS["noise"](px, None, seed=1),
                        signals.SIGNALS["noise"](px, None, seed=2), window=20)

    a = panel.build_panel(px, one, transform_kind="raw", horizon=3)
    b = panel.build_panel(px, two, transform_kind="raw", horizon=3)
    assert list(a.columns) == list(b.columns)
    assert a.index.equals(b.index)
    for frame in (a, b):
        assert {"signal", "signal_raw", "fwd_ret_3"} <= set(frame.columns)


@pytest.mark.parametrize("side,expected", [
    ("upper", [False, False, False, True, True]),
    ("lower", [True, True, False, False, False]),
    ("both", [True, True, False, True, True]),
])
def test_tail_mask_picks_the_right_side(side, expected):
    x = pd.Series([-4.0, -3.0, 0.0, 3.0, 4.0])
    assert stats.tail_mask(x, 2.5, side).tolist() == expected


def test_tail_mask_rejects_an_unknown_side():
    with pytest.raises(ValueError, match="unknown side"):
        stats.tail_mask(pd.Series([1.0]), 2.5, "sideways")


def test_lower_tail_finds_a_planted_negative_effect():
    """A signal whose LOW days predict gains must be invisible to `upper`.

    This is the case the side selector exists for: a one-sided test looking the
    wrong way reports nothing, which reads identically to no effect at all.
    """
    px = fake_px()
    pnl = panel.add_targets(px, horizon=3)
    rng = np.random.default_rng(0)
    sig = pd.Series(rng.standard_normal(len(px)), index=px.index)
    fwd = pnl["fwd_ret_3"].copy()
    fwd[sig < -2.0] += 0.05                      # effect ONLY in the low tail

    lower = stats.tail_test(sig, fwd, maxlags=3, threshold=2.0, side="lower")
    upper = stats.tail_test(sig, fwd, maxlags=3, threshold=2.0, side="upper")
    assert lower["p"] < 0.01 and lower["excess"] > 0.03, lower
    assert upper["p"] > 0.05, "the upper tail should see nothing"


def test_both_sides_is_the_union_of_the_two():
    px = fake_px()
    pnl = build("noise", seed=3)
    x = pnl["signal"]
    n_up = stats.tail_mask(x, 1.5, "upper").sum()
    n_dn = stats.tail_mask(x, 1.5, "lower").sum()
    n_both = stats.tail_mask(x, 1.5, "both").sum()
    assert n_both == n_up + n_dn, "both must be exactly the two disjoint tails"


def test_evaluate_threads_the_side_through():
    pnl = build("planted", seed=0)
    for side in stats.SIDES:
        res = stats.evaluate(pnl, horizon=3, tail_z=1.0, tail_side=side)
        assert res["tail_side"] == side
    up = stats.evaluate(pnl, horizon=3, tail_z=1.0, tail_side="upper")
    dn = stats.evaluate(pnl, horizon=3, tail_z=1.0, tail_side="lower")
    assert up["tail_excess"] != dn["tail_excess"], "side had no effect on the result"
