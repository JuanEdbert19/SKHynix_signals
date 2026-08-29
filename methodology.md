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

**The Naver signals carry a far worse version of the same artifact**, and the two together
show that the *severity* depends entirely on how quiet the weekend is. Weekend search runs
at **12.4%** of weekday search, against Wikipedia's 73.5%, so under the same `agg="mean"`
Monday's Fri+Sat+Sun bucket lands at 0.42× a weekday where Wikipedia's lands at 0.82×.
Aligned raw means are Mon 2.76 against Tue–Fri 6.52/6.84/7.00/7.03.

Monday's share of the top quintile, both under `agg="mean"`:

| | plain `zscore` | `dow_zscore` |
|---|---|---|
| `wiki_hynix` | 4.3% | 19.5% |
| `naver_hynix` | **0.0%** | 21.1% |

At 0.0% a Monday cannot register as high attention *at all* — mean z by weekday spans 2.02
with Monday at −1.40 against Friday's +0.61. The signal would then be partly encoding "today
is not a Monday", which matters because SK Hynix has a real Monday return effect (+0.58% over
3 days, t = +1.89): a regression would report a calendar artifact as attention.

So `dow_zscore` is a correctness requirement here, not a preference. The general lesson is to
measure the weekday profile of any signal bucketed between market closes before choosing a
transform — the direction and size of the bias are properties of the source, not of the
method. Note Wikipedia's *original* `agg="sum"` bug went the other way entirely (Monday
inflated to 83.5%), so neither sign can be assumed in advance.

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

## Tail evaluation

**Whole-distribution statistics dilute an effect confined to the tail.** Rank IC asks
whether the relationship is monotonic over every day; the HAC fit puts one line through all
of them; the top−bottom spread compares two 20% blocks. If a signal only carries information
when it spikes, the 80% of ordinary days average it away. `stats.tail_test` is the narrow
question instead: mean forward return on days above a cut, versus every other day, as a HAC
dummy regression on the full sample. It is one-sided by design — the hypothesis is "a spike
moves the stock", and a quiet day is the absence of a spike rather than its opposite.

Measured on `naver_hynix` at `dow_zscore > 2.5`: **+1.02% excess over 3 days, HAC t = +2.52,
p = 0.0119, 196 tail days** — against a full-sample rank IC of +0.029 with p = 0.573 on the
same data. The gap between those two numbers is the entire justification for the function.

**The magnitude version of the hypothesis is not supported.** The motivating idea was that an
outlier day produces a large move in *either* direction. `stats.event_metrics` reports
`abs_ratio` — mean |forward return| on event days divided by the same on non-event days — and
at the registered cut it lands at 0.95 (`naver_hynix`), 1.01 (`naver_semi`), 0.96
(`naver_hbm`), 0.86 (`naver_memory`) and 0.87 (`wiki_hynix`). No amplification anywhere, and
two signals are *calmer* on event days. This is why the target stayed signed `fwd_ret` and no
absolute-return target was added.

`abs_ratio` is descriptive and carries no inference, deliberately: an absolute-return
regression would need |cumulative return| as its dependent variable, which is a poor
volatility measure. It correlates only 0.667 with realized volatility over the same window —
2.2% of days sit in the bottom quartile of |cumulative| while in the top quartile of realized
vol, violent paths that happened to end near where they started — and it is contaminated by
drift (`corr(|cum|, cum) = +0.138` against +0.080 for realized vol). Testing magnitude
properly needs a realized-volatility target, not this one.

**The hit rate uses a linear probability model, not a binomial test.** `event_metrics`
regresses the 0/1 outcome "beat the non-event median" on the 0/1 event dummy, so the
coefficient *is* the difference in hit rates and inherits the same HAC correction as
everything else. A binomial test would assume independent trials, which overlapping 3-day
windows are not — the same objection that keeps a p-value off `rank_ic`.

The baseline is the median of *non-event* days rather than of all days, which puts the
comparison group's own hit rate at ~50% by construction and makes the event rate readable
against it. Pinned by a test.

**The hit rate has materially less power than the mean, and must not be read alone.**
Collapsing every return to a 0/1 outcome discards magnitude, so a large number of
barely-above-median days scores identically to a few enormous ones. Measured on the `planted`
fixture (ρ = 0.15): the mean test clears at p = 0.015 while the hit rate on the same data
reaches only p = 0.142, pointing the right way (56.0% vs 50.0%) but far short of
significance. Pinned by `test_the_hit_rate_has_less_power_than_the_mean`.

**`TAIL_Z = 2.5` was chosen after inspecting results, and that is a real limitation.**
Sixteen signal × threshold combinations were run before the value was picked; a Bonferroni
threshold across them is 0.0031, which p = 0.0119 fails. The mitigation is structural rather
than a disclaimer: `stats.tail_curve` reports the whole grid and is rendered unconditionally
beside the headline number, so a reader sees whether the cut sits on a plateau (2.0–3.5 are
all significant for `naver_hynix`, which is reassuring) or on an isolated spike (which would
not be). **No tail result is a finding until it is tested on data the threshold was not
chosen on.**

Two further cautions. `dow_zscore` has sd 3.84 rather than 1.0, so a fixed z is not a fixed
percentile and `n_tail` must be read alongside any tail statistic. And the effect does not
survive halving the sample — ≤2024 gives +0.72% (p = 0.092), 2025–26 gives +1.26%
(p = 0.187) — which is equally consistent with a weak real effect and with a borderline
full-sample result.

## News sentiment

**FinBERT was chosen by measurement, not by reputation.** On 84 real GDELT semiconductor
headlines:

| Model | pos / neutral / neg | Mean confidence |
|---|---|---|
| `ProsusAI/finbert` | 43 / 35 / 23 | **0.824** |
| `cardiffnlp/twitter-roberta-base-sentiment-latest` | 32 / **52** / 16 | 0.701 |
| `yiyanghkust/finbert-tone` | fails to load — no `model_type` in `config.json` | — |

The two working models disagree on **40%** of headlines, and FinBERT is right on the
financially loaded ones: *"CXMT Could Threaten Samsung and SK Hynix"* reads negative to it
and neutral to twitter-roberta; *"AMD Stock Jumps as Earnings Reignite AI Chip Trade"* reads
positive vs neutral. Twitter-roberta has no weight for *threaten*, *reignite* or *crisis*, so
it defaults to neutral — and its 52% neutral share is a direct loss of signal variance.

Used zero-shot. FinBERT was further-pretrained on Reuters TRC2 and fine-tuned on Financial
PhraseBank, both financial *news sentences* — the same register as a headline — so a
fine-tune has no obvious domain gap to close. `yiyanghkust/finbert-tone`, trained on analyst
reports, is the genuinely formal one and is the wrong fit here even before it fails to load.

**Score is `P(pos) − P(neg)`, not the argmax label.** A headline the model calls positive at
0.51 should not count the same as one it calls positive at 0.99, and a neutral headline lands
near 0 rather than being discarded.

**Headlines are all GDELT provides**, and the query is an industry one for that reason.
GDELT matches the article *body* but returns only the *title*, so `"SK Hynix"` yields
headlines about other companies that mention it in passing — **15%** of titles named the
company, against **58%** on-topic for `HBM memory`. Scraping article bodies would not fix
this: an article about Amazon that mentions SK Hynix once is still about Amazon. The unit
that would fix it is entity-level sentiment, which is a different pipeline.

**Target is `fwd_exret`, the only signal for which that is true.** 17% of headlines are
market-wide coverage — *"Dow Just Lost 1,100 Points"*, *"Chip Stocks Lose $1 Trillion"*.
That contamination correlates with the market, and so does SK Hynix, so on `fwd_ret` it could
produce a relationship through beta rather than information. The KOSPI-excess target
differences it out of both sides.

**Coverage grows ~8× across the sample and the early years are thin** — 1.0 articles/day in
June 2019, 2.0 in 2021, 8.3+/day in 2026. The consequence is measurement error in the
regressor on sparse days, which attenuates the pooled coefficient. Simulated at a realistic
noise level: reliability 0.74 at one headline/day against 0.96 at eight, shrinking a
standardized coefficient about **14%** — while the extra ~900 days *raise* the t-statistic
(+12.71 pooled vs +10.11 on the clean half alone). So the full 2019–2026 sample is kept: the
noise costs precision, the sample size more than repays it, and narrowing to 2023+ is a
sidebar setting rather than a fetch decision.

Days with **zero** articles are NaN, not zero. An absent headline is an undefined sentiment,
not a neutral one.

### Most of the daily signal was sampling noise (measured 2026-08-29)

The signal is the mean of a day's headline scores, and the median day supplied **4
headlines** against a per-headline sd of 0.53. Decomposing the daily series into what varies
because the news changed and what varies because of *which articles GDELT happened to index*:

| | variance | sd |
|---|---|---|
| observed daily mean | 0.0820 | 0.286 |
| sampling noise | 0.0578 | 0.240 |
| true tone | 0.0242 | 0.156 |

**Reliability = 0.30** — about 70% of the day-to-day movement carried no information about
the news. A true correlation is attenuated to `sqrt(0.30) = 0.54x`. And 0.30 is the
optimistic reading: 19.6% of titles are exact syndicated duplicates, which inflate the
effective sample size, and deduping first gives **0.14**.

Corroborated independently by persistence. A real news narrative lasts days, so a good
measurement should correlate with yesterday's: the attention signals run **+0.7** at lag 1,
this one ran **+0.20**.

**Three fixes, all measured rather than assumed:**

| Change | Reliability |
|---|---|
| as it shipped | 0.30 |
| + English only (2.6% were scored by an English-only model) | 0.33 |
| + on-topic filter | **0.48** |

The relevance filter is the large one and it removes real junk, not borderline cases:
**30.5%** of the corpus was off-topic — *"AMD Radeon VII review: Is 4K gaming enough?"*,
*"Goodbye to my Chinese spy TikTok"*, *"Tech Soft 3D Launches CEETRON Toolkits"* — against
4.5% market-wide macro. Only **13.2%** of titles named SK Hynix at all. `signals.ON_TOPIC`
is the memory/chip vocabulary that survives.

**The signal was not centred**, which broke two things silently. FinBERT scores this corpus
positive on **86%** of days (mean +0.199), so `stats.tail_test`'s `lower` and `both` sides
were meaningless on it, and `combine`'s premise that sentiment supplies a *sign* was false —
it was a nearly-always-positive multiplier. `DEFAULT_TRANSFORM` moved from `raw` to `zscore`,
which centres it to **51.8%**. That default was unusable until the `min_periods` bug below
was fixed.

### The `min_periods` bug (found 2026-08-29)

`panel.transform` called `rolling(window)` with no `min_periods`, and pandas then requires
the window to be **entirely non-NaN**. On a signal with gaps that is catastrophic and silent:

```
gdelt_sent_semi available on   1,435 of 1,865 trading days (77%)
after zscore(window=20)          393 days   -> 73% of available days discarded
```

Nothing in the output said so. It survived undetected because **only gappy signals are
affected** — every attention signal has essentially full coverage — and the one signal that
has gaps was the one pinned to `raw`, so its `zscore` path was never exercised.

The fix is `MIN_BASELINE = 10`, **capped at the window**. The cap is the load-bearing half:
`dow_zscore`'s window is only `window // 5 = 4` same-weekday observations, and relaxing that
to 2 makes the sd `|x1-x2|/sqrt(2)`, which is not a baseline — this transform already reaches
z = +124.7 when its sd collapses. So `zscore(20)` relaxes to 10 and `dow_zscore` keeps its
full 4; the gap fix is confined to long windows, where the bug actually was.

**This choice moves a headline number, and the reasoning is deliberately not about that.**
Relaxing `dow_zscore` to 2 would add 10 warm-up days to `naver_hynix` at h=1 and move it from
**p 0.0444 to p 0.0520** — across 0.05. The cap was chosen on baseline quality, which is an
argument that would read the same if the p-value moved the other way. What the sensitivity
shows is that the headline p is fragile to ten days at the start of the sample, and that is
worth knowing regardless of which side it lands on.

## Combining signals

**A plain product of attention and sentiment inverts on 8% of days.** Attention as
`dow_zscore` is negative on 55% of the overlapping sample and sentiment on 14%; on **110 of
1,420 days both are negative**, and negative × negative is positive — so *low attention plus
bad news* would score identically to *high attention plus good news*.

`panel.combine` therefore puts attention in as a **non-negative weight** and lets sentiment
carry the sign: `trailing_pct_rank(attention) × sentiment`, with the rank in [0, 1] and
sentiment in [−1, +1]. A second hazard disappears with it — `dow_zscore` reaches **+50.65**
on this data, so as a raw multiplier one day would dominate the entire series; a rank cannot.

**The rank is trailing, and that is load-bearing.** A percentile rank computed over the whole
sample lets day *t*'s value depend on days *t+1…T*, which is look-ahead of exactly the kind
`align.py` and the `.shift(1)` in `transform` exist to prevent — and it is invisible
downstream, since the resulting signal looks entirely well-behaved. Day *t* is ranked only
against the previous `window` observations. Pinned by
`test_trailing_rank_cannot_see_the_future`, which rewrites the entire future and asserts the
past is unchanged.

`trailing_pct_rank` is deliberately **not** in `TRANSFORMS`. `pctrank` was removed in the
2026-08-10 scope cut; re-registering it would reverse that decision, so it exists only inside
`combine`.

**The combination is defined on the intersection**, which is the binding constraint: 1,420
overlapping days of 1,865, limited by GDELT's thin pre-2024 coverage, and fewer still after
the rank's 20-day warm-up.

**`signal_correlation` reports the overlap alongside the coefficient**, because the two are
not separable: 0.9 across 40 shared days and 0.9 across 1,400 are different claims. It ships
no p-value, for the same reason `rank_ic` does not — both series are autocorrelated.

Measured for the pair the tab defaults to: `naver_hynix` × `gdelt_sent_semi` correlate
**−0.007 Pearson, +0.013 Spearman**. Near-independent, so the product is not double-counting
one quantity, and the interaction is the only reason to expect anything from it.

### Why blending underperforms either signal (measured 2026-08-29)

Two mechanisms, both structural rather than small-sample.

**Blending destroys the fat tail the attention effect lives in.** Attention is violently
fat-tailed and sentiment is near-Gaussian, so their sum is closer to Gaussian than the
attention signal is — and the tail test then has nothing left to test:

| rule | outlier days at z>2.5 | kurtosis |
|---|---|---|
| attention alone | 26 | 9.9 |
| linear 0.75 / 0.25 | 16 | 7.6 |
| linear 0.50 / 0.50 | 5 | 2.1 |
| product `rank(att) × sen` | 4 | 3.7 |
| sentiment alone | 0 | 0.4 |

Re-measured after the sentiment fixes above, the **product falls to a single outlier day** on
2023+ — it is not a rule that can be evaluated on this data, and keeping it is a choice to
preserve the interaction hypothesis rather than an expectation that it will work.

**This mechanism is invisible to rank IC**, which is what made the first pass through this
investigation reach the wrong conclusion. Rank IC is computed on all days and is immune to
outliers by construction, so a rule that quietly deletes the outliers scores no worse on it.
Anything comparing combination rules must be judged on the tail test.

**Rules must be compared at equal event counts.** Each rule produces a differently-shaped
distribution, so a fixed `z > 2.5` compares 26 days against 5 — a power difference, not a
result. Comparisons use the top-*k* days instead.

### The linear rule, and why its weight is signed

`combine(rule="linear")` is `z(attention) + w · z(sentiment)` with **w signed**. Both inputs
are standardised first because `dow_zscore` attention and `zscore` sentiment have very
different scales; unstandardised, the sum would be attention plus a rounding error. `w = 0`
reduces exactly to attention alone, which is what makes a weight sweep readable.

The sign exists because, during diagnosis, the two signals appeared to point **opposite**
ways — attention +0.94% and sentiment −0.97% on their own top-25 days, at a mutual
correlation of −0.03. A non-negative weight makes opposing signals cancel, which the product
cannot express and this can.

**That apparent asymmetry did not survive the corrected construction.** Re-run with the
filtered, `zscore`-centred sentiment (h=1, 2023+, `fwd_exret`, top-*k* equal counts):

| w on sentiment | rank IC | tail excess | n_tail |
|---|---|---|---|
| −1.0 | +0.0356 | +0.54% | 51 |
| −0.5 | +0.0440 | +0.87% | 38 |
| **0.0** | **+0.0839** | **+1.22%** | 33 |
| +0.5 | +0.0763 | +0.96% | 31 |
| +1.0 | +0.0592 | +0.92% | 38 |

The optimum is at **zero weight on sentiment** in both directions. The earlier negative-weight
result was an artifact of the ad-hoc 60-day centring used while diagnosing, and is recorded
here as a **false positive that the corrected pipeline killed** — which is precisely why the
definition changes had to land before the rule was chosen.

### A documented false positive: the "gated" rule

While sweeping combination rules, *sentiment restricted to high-attention days* came back at
**p = 0.033** on `fwd_exret`, h=1, 2023+. It is not a finding and must never be quoted as one:

- it is one of **18 specifications** tried on that sample; a Bonferroni threshold is ≈0.0028
- its sign says **good news predicts negative excess returns**, which was not the hypothesis
- it did not survive the corrected sentiment construction

It belongs beside `wiki_hynix` as a calibration point for how easily this sample manufactures
a sub-0.05 p-value.

### An untested hypothesis: sentiment may be contrarian

The same sweep produced a coherent-looking pattern in the *opposite* direction to the
project's hypothesis — high sentiment followed by **lower** excess returns, decaying with k
the way a genuine tail effect does (h=1, `fwd_exret`, 2023+, top-k days):

| top-k | excess | t | p |
|---|---|---|---|
| 25 | −0.97% | −1.69 | 0.091 |
| 50 | −0.89% | −2.52 | 0.012 |
| 100 | −0.34% | −1.31 | 0.191 |

**Not a finding, and not testable on this data.** It was found by trying 21 specifications on
2023+, so that sample can no longer evaluate it — the direction was chosen after seeing it.

To test it: `gdelt_sent_semi`, `zscore`/20, `fwd_exret`, h=1, upper tail, direction fixed
**negative**, run **once** on **2019-2022** — the years the sweep never touched. A significant
result with a positive sign is a fail, not a discovery. Note in advance that those years are
thin (~530 articles/year against 3,228 in 2026), so a null there is weak evidence either way.

## Reverse causality is mislabelled — UNRESOLVED (found 2026-08-29)

**`stats.reverse_causality` does not test causal ordering, and `findings.md` and the dashboard
both present it as though it does.** The problem is that its "past" returns are not past
relative to when the signal's information was generated, and the offset differs per signal.

`past_returns` computes `past_ret_k[t] = logc[t] − logc[t−k]`, so `past_ret_1[t]` spans
close(t−1) → close(t). Compare that against each signal's actual information window:

| Signal | Information window | vs `past_ret_1[t]` |
|---|---|---|
| `gdelt_sent_semi` | close(t−1) → close(t) — articles carry real UTC timestamps and go straight into `align_to_trading_days` | **identical window** — fully contemporaneous |
| `naver_hynix` and every calendar-aggregated signal | 00:00 → 24:00 KST on day *t−1* | return window starts **after** most of the signal |

For a Tuesday, Naver's signal is Monday's search, the bulk of it before Monday's 15:30 close,
while `past_ret_1` runs Monday 15:30 → Tuesday 15:30. A positive coefficient there cannot mean
"the return caused the attention" — the attention came first. It is closer to a near-term
*forward* test.

Measured on `naver_hynix` (2023–2026, h=1), the harness's regressor and a genuinely-prior one
disagree and are barely related:

| Regressor | corr with signal | HAC p |
|---|---|---|
| `past_ret_1` — what the harness uses, close(t−1)→close(t) | +0.049 | 0.103 |
| close(t−2)→close(t−1) — actually before the search window | +0.071 | 0.222 |

with a correlation of only **−0.088** between the two regressors. Different windows, different
questions.

**There is no lag shift that fixes both signals**, because the misalignment differs in kind.
Worse, for a calendar-aggregated signal the question is not cleanly answerable at daily
resolution at all: the price move most likely to send someone searching is *that same session's*
move, which sits **inside** the signal's own window. A return strictly prior would have to end
at close(t−2), by which point it is no longer the mechanism of interest.

**What the feedback actually looks like.** Regressing the signal on the return realised *during*
its own window: the **signed** move explains little (corr +0.071, p = 0.22) but the **absolute**
move explains a great deal — **corr +0.312, HAC t = +5.40, p < 0.0001**, the strongest
relationship measured anywhere in this project. People search after the stock moves *sharply*,
not after it moves *up*. That asymmetry is why the momentum confound is weaker than it first
appears: a large move in either direction does not indicate tomorrow's direction.

**Proposed fix, not yet implemented.** Replace the causal framing with a joint regression,
`fwd_ret ~ signal + recent returns`, which asks whether the signal carries information *beyond*
recent returns rather than which came first. That is valid whatever window a signal covers, so
it needs no per-signal reasoning about alignment. Measured on `naver_hynix` (2023–2026, h=1),
the signal survives it:

| Specification | signal coefficient | p |
|---|---|---|
| signal alone | +0.00238 | 0.044 |
| + yesterday's move | +0.00252 | 0.038 |
| + yesterday's move + 5-day trend | +0.00240 | 0.052 |

The coefficient does not shrink when trend is controlled for, which is what the confound
"uptrend causes attention, uptrend continues" would require. Both trend terms are themselves
null (p = 0.27 and 0.91).

**Until this is fixed**, read the reverse-causality panel as *"is this signal a proxy for the
return realised up to the decision point?"* — a real and useful question — and not as evidence
about which came first.

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
