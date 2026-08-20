# Methodology

Decisions that are not obvious from the code, and the measurements behind them. Each
entry records what was chosen, why, and what it costs. Statistics quoted here are
reproducible with `scripts/run_test.py`.

## Inference

**All inference uses Newey-West HAC standard errors, with no second path.**
A 3-day forward return measured on consecutive days shares 2 of its 3 days with its
neighbour, so residuals are autocorrelated by construction and ordinary OLS errors are
understated. `maxlags = horizon`, since the mechanical overlap ends exactly there.

**HAC only corrects when the *regressor* is persistent, not merely the target.**
Newey-West acts on the autocovariance of signal × residual, so a near-iid signal barely
moves even at h=10 (se ratio 1.13) while an AR(0.8) signal inflates 2.2×. Pinned by tests.

**The `zscore` transform removes that persistence, so HAC barely moves on the real
signals.** Subtracting a 20-day rolling mean is a high-pass filter. Measured: aligned
pageview series have AR(1) of 0.46 / 0.03 / 0.29 raw, and −0.09 / −0.15 / −0.08 after
z-scoring. Observed se/se_ols is 0.85–0.93 — HAC is slightly *smaller* than naive OLS, so
on `wiki_semi` the naive t is 1.41 against a HAC t of 1.65. HAC remains the default (it
costs nothing when unneeded, and `raw` preserves persistence), but it will not rescue a
borderline result on a z-scored signal.

**`rank_ic` returns no p-value, deliberately.** A Spearman p-value assumes independent
observations, which overlapping forward returns are not. Shipping one would invite it to
be quoted.

**`ols_hac(y, x)` argument order is load-bearing and a swap is nearly invisible.**
Plain-OLS t is exactly symmetric under swapping y and x in a bivariate regression; under
HAC the t merely changes to another plausible value (7.5 → 4.6 on `planted`), and rank IC
is unchanged either way. The coefficient is the only clear tell, rescaling by
1/σ(return) ≈ 30×. This was shipped once and caught only by hand-checking that magnitude.
Since `coef` is no longer reported, the guard lives in the test suite:
`test_evaluate_regresses_return_on_signal_not_the_reverse` monkeypatches `stats.ols_hac`
and asserts the first call is `(fwd_ret_3, signal)`. Nothing in the output would catch a
reintroduction.

## Signal construction

**Rolling baselines exclude the current day.** `x.rolling(20).mean()` puts day *t* inside
its own baseline, leaking the deviation the z-score is meant to measure. The `.shift(1)`
in `panel.transform` is the fix, and is covered by a look-ahead test parametrized over
every transform.

**Signals accumulated between market closes acquire a day-of-week artifact.**
Monday's bucket spans Fri+Sat+Sun; Tuesday's spans one day. Under `agg="sum"` Monday
averaged 1,042 pageviews against ~455 for every other weekday, and against a mixed 20-day
baseline it cleared the bar nearly every week: **83.5% of top-quintile days were Mondays**
where 20% is neutral, with mean z by weekday spanning 2.09. The quintile spread was
therefore closer to "Monday minus non-Monday" than to "high attention minus low attention".

Aggregation alone does not fix it — measured Monday shares: `sum` 83.5%, `mean` 4.3%
(overcorrects, since weekend traffic is ~73% of a weekday), previous-calendar-day 2.7%,
previous-weekday 11.9%. **The baseline is the fix**: every aggregation paired with
`dow_zscore` lands at 19.5–20.9%. Resolved as `agg="mean"` + `dow_zscore`.

**`dow_zscore` has fat tails, by construction.** Its baseline is `window // 5`
same-weekday observations — 4 at the default window of 20. A 4-point standard deviation
occasionally collapses, and a real spike then divides by almost nothing: 2025-12-05 had
2,061 views against prior Fridays of 439/468/455/464 (sd 12.87), giving z = +124.7. The
distribution has sd 4.45 and kurtosis 428, against 1.47 and 74 for plain `zscore`.

Consequence for interpretation: **rank IC is unaffected** (rank-based; −0.0055 vs −0.0053
under ±5 clipping) but the **HAC t is not** — it moves from +0.22 to −0.53 under clipping,
a sign flip, because OLS is outlier-sensitive. **Prefer rank IC over the HAC t when reading
a `dow_zscore` result.** Winsorization was considered and rejected as an unrequested knob;
a wider `window` reduces but does not remove the effect. Revisit if a result ever comes
back significant.

**Autocorrelation differs before and after trading-day alignment.** The calendar-daily
`en:SK_Hynix` series has AR(1) 0.775; aligned to trading days it has 0.463, because
summing Fri+Sat+Sun into Monday breaks up the short-lag structure. Both are correct
measurements of different series — quote the aligned one when reasoning about the
regression.

## Timing

**A one-day lag is correct for a research claim; a tradeable claim needs more.**
The two constraints are distinct:

- *Contamination.* A UTC day runs 00:00–24:00 while KRX closes at 06:30 UTC, so 73% of
  day *t* occurs after the decision point and may react to the session being predicted.
  Using day *t−1* removes this. Non-negotiable, and enforced by
  `align.daily_utc_to_timestamps`.
- *Retrievability.* Day *t−1* is complete but not necessarily published. Wikimedia's own
  delay is unmeasured: day *D−1* is confirmed available by 14:27 UTC, but whether it lands
  before the 06:30 close is unestablished.

The first is a bias and can manufacture a result; the second cannot, because publication
timing has no plausible correlation with returns. So Phase 1 uses one day. The research
result is an upper bound on the tradeable one (measured: IC +0.031 at lag 1 versus +0.029
at lag 2). Establish the true publication time before quoting any spread as achievable.

## Multiple testing

**One fixed specification means one test**, which is why there is no Bonferroni
correction. The specification — `fwd_ret`, h=3, the signal's registered
`DEFAULT_TRANSFORM` — is fixed before running rather than scanned. Three signals are
registered, so `wiki_hynix` is declared primary in advance and the other two are
explicitly secondary. If the horizon grid returns, or if all three signals are quoted as
findings, the correction has to return with them.
