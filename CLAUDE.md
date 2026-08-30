# CLAUDE.md

## Working Agreement

- **No Git Operations**: Do NOT run any git commands (`git add`, `git commit`, `git push`, `git merge`, `git stash`, `git rebase`, etc.). The developer is solely responsible for staging files and committing. Only make code changes; never touch the git history or index.
- **Discuss Before Implementing**: For changes involving architecture, design patterns, database schemas, new integrations, security, multi-module impact, or PII/PHI handling — **present a plan and discuss with the developer first**. Do not write code until the approach is agreed upon.
- **Raise Concerns**: If you identify ambiguities, edge cases, conflicting patterns, security risks, or performance concerns — **raise them before proceeding**. Never silently assume unclear requirements.
- **Confirm Destructive Changes**: Before significantly altering existing behavior — explicitly confirm with the developer.
- **Explain Trade-offs**: When proposing a solution, briefly explain trade-offs so the developer can make an informed decision. In particular, when a quick fix is possible but a deeper refactor may be more appropriate, **raise the choice to the developer** — compare the band-aid fix vs. a long-term revamp and let the developer decide which path to take.
- **Respect Existing Patterns**: Check how similar functionality is already implemented and follow that pattern. Discuss before deviating.
- **Reuse Before Creating**: Search utils or within the same module for existing implementations before writing new utilities. Duplicating existing functionality is not acceptable.
- **Stay On Task**: Only modify files directly relevant to the current task. Do not make opportunistic fixes or "while I'm here" improvements to unrelated code. Flag issues to the developer separately.

## Code Style

- Keep implementations as simple as possible. No speculative abstraction, no config knobs nobody asked for, no defensive layers for cases that cannot happen.
- Minimal comments. Only where the *why* is genuinely non-obvious — never to restate what the code says.
- Prefer plain functions and dataframes over classes and frameworks until there is a concrete reason otherwise.

## Research Discipline

This is a quantitative research project, so correctness of the *method* matters more than the code.

- **No look-ahead bias**: a feature at time *t* may only use information available at time *t*. Be explicit about timestamp alignment and timezones.
- **State assumptions in the analysis**, not just the code — to sample period, universe, how missing data is handled.
- **Report negative results honestly.** "No significant relationship" is a valid and expected outcome. Never tune a spec until it produces a signal and then present that as a finding.
- Any statistic reported must be reproducible by re-running a script in the repo.

## Project Details

**Goal**: Measure whether public *attention* has a measurable effect on stock prices.

Originally framed as Twitter/X activity. Changed on 2026-08-20 (developer's call) because
no free tweet source exists any more — see `data-sources.md`. The substitute is Wikipedia
pageviews, which measure people **looking a company up** rather than **discussing it**: a
related but distinct construct, stated here rather than quietly swapped.

**Current scope (Phase 1)**: The simplest possible version of the question — does *attention
frequency* (daily pageview count for a topic) relate to SK Hynix price behavior? Sentiment,
content, and author quality are explicitly out of scope for now.

**Target**: SK Hynix — KRX ticker `000660.KS`. It trades on the Korea Exchange
(KST, 09:00–15:30) while attention data is global and 24h, so aligning attention windows
to trading sessions is the core methodological problem of Phase 1.

**Stack**: Python 3.13 in `.venv`. pandas / numpy / statsmodels / pykrx / yfinance /
streamlit / altair. `pip install -r requirements.txt`.

### Testing Framework

A signal-agnostic harness for the general question "does signal X predict SK Hynix
price behaviour?" — built before any real signal existed, so the unresolved data-source
question could not gate progress. Pageviews, search volume, news volume and anything else
all reduce to one number per trading day, which is the only interface it requires.

| Module | Role |
|---|---|
| `quant/cache.py` | `CACHE_DIR` + `cached(path, fetch)` — the parquet cache, shared by every loader |
| `quant/prices.py` | OHLCV for `000660` (pykrx), KOSPI and any yfinance symbol; plus `rebase` |
| `quant/wiki.py` | Wikipedia pageviews per UTC calendar day |
| `quant/naver.py` | Naver search trends per KST calendar day, read from hand-exported `.xlsx` |
| `quant/gdelt.py` | News headlines from GDELT DOC 2.0 — adaptive windowing, resumable per month |
| `quant/sentiment.py` | FinBERT headline scoring, `P(pos) − P(neg)`, cached by headline hash |
| `quant/align.py` | UTC **and KST** signal timestamps → KRX trading date. **The only module with timezone logic** |
| `quant/panel.py` | Forward-return targets, signal transforms, `combine`, coverage and distribution summaries |
| `quant/signals.py` | Signal registry + the three validation fixtures |
| `quant/stats.py` | Rank IC, quantile buckets, Newey-West regressions, reverse causality |
| `scripts/probe_gdelt.py` | Measures articles/day and on-topic share for a candidate GDELT query, before committing to a backfill |
| `scripts/run_test.py` | CLI; writes a JSON record to `results/` |
| `app.py` | Streamlit dashboard, three tabs — a thin caller of the same functions, so it cannot drift |

**Dashboard.** Three tabs, each answering one question. *Signal* describes what the thing
is — coverage and gaps, the series over time, its distribution (sd, skew, kurtosis, extremes)
and its correlation with any other signal. No forward returns appear there, deliberately: a
signal should be judged trustworthy before it is judged useful. *Price* is the log-axis
close chart with overlays.

*Test* runs two named tests, in this order, then reverse causality and the sample footer:

1. **Signal spike test** — the outlier-day event test, and the tab's focal point. Leads
   because these signals are fat-tailed: `naver_hynix` has kurtosis 49.5 and 12.4% of days
   beyond z=2.5 against 0.6% for a normal, so the effect lives in the tail. Threshold and
   tail-side controls, event metrics, the marked signal-over-time chart, and the sensitivity
   grid all live here.
2. **Monotonic relationship test** — rank IC, the HAC fit, the top-minus-bottom spread, the
   quantile chart and the scatter. Secondary by construction: it is diluted by ordinary days
   when the effect is confined to spikes, and rank IC is outlier-immune, so it cannot see a
   tail effect at all. Ordering it second is deliberate and is pinned by
   `test_spike_test_leads_the_test_tab`.

The "no significant relationship" notice belongs to test 2 — it reports `p_hac` — and is
rendered inside that section rather than at the top of the tab.

**Signal construction lives in the sidebar, not in a tab.** The Source toggle picks a single
registered signal or a *combined* one, and a **Rule** control picks how the pair is folded —
`panel.COMBINE_RULES`:

- `product` — the two transformed signals multiplied, nothing else.
- `linear` — `attention + w · sentiment`, each arm put on a common scale by
  `panel._unit_scale` (an expanding, history-only sd), with **w signed** and exposed as a
  slider. `w = 0` is attention alone.

**Neither rule transforms its inputs.** Each leg is transformed by the caller, and the
transform is picked **per signal** — `Attention transform` / `Sentiment transform` in the
sidebar, `--att-transform` / `--sen-transform` on the CLI.

Defaults come from **`panel.COMBINE_DEFAULTS`, keyed by rule**, not from the signals'
`DEFAULT_TRANSFORM`, because the two rules need different things from sentiment. `app.py` and
`run_test.py` both read that one table, so they cannot drift:

| rule | attention | sentiment | weight |
|---|---|---|---|
| `product` | `dow_zscore` | `raw` | — |
| `linear` | `dow_zscore` | `zscore` | 1.0 |

`raw` sentiment for the product is load-bearing: with two centred transforms negative ×
negative reads positive, and raw sentiment is the only pairing that kept a testable tail.

Either branch produces one `sig`, so there is a single analysis path and nothing is rendered
twice. This replaced a Combine tab that re-implemented a subset of the Test tab's output.

`trailing_pct_rank` was **removed on 2026-08-30** (developer's call). It had bounded the
product's magnitude and guaranteed sentiment supplied the sign, but it flattened attention's
kurtosis from 49 to −1 and left the product with one day above z=2.5 on 2023+, so the tail
test could not run. Both costs of removing it are pinned by tests. The combined pair is not
registered in `SIGNALS`;
`run_test.py --combine A,B --combine-rule R --combine-weight W` is what keeps a combined
result reproducible. See `methodology.md`.

Sidebar groups: **Signal** (source, pickers, combine rule and weight), **Specification**
(transform, target, horizon, window, quantiles), **Sample** (start, end).

**Adding a real signal**: write a function `(px, kospi) -> Series` keyed by trading
date and register it in `SIGNALS`, `SIGNAL_AGG` and `DEFAULT_TRANSFORM`. If it arrives as
UTC timestamps, run it through `align.align_to_trading_days` first.
`signals._pageview_signal` is the worked example. Nothing else changes — `app.py` and
`run_test.py` populate their choices from `SIGNALS`.

`panel.transform` takes `min_periods`, defaulting to `MIN_BASELINE = 10` **capped at the
window**. Without it `rolling()` requires a fully non-NaN window, which discarded 73% of the
available days on the one signal that has gaps. The cap is what keeps `dow_zscore`'s
4-observation baseline from being relaxed to 2. See `methodology.md`.

Pick `DEFAULT_TRANSFORM` by how the signal is bucketed: `"dow_zscore"` if it accumulates
between market closes (Monday's bucket spans the weekend, so a mixed baseline reads it as
abnormal every week), `"zscore"` for a count-style signal that does not, `"raw"` if it is
already stationary. See `methodology.md`.

**Real signals (Wikipedia pageviews, English):**

| Signal | Article | Role |
|---|---|---|
| `wiki_hynix` | `en:SK_Hynix` | **primary** — company attention, fixed before running |
| `wiki_semi` | `en:Semiconductor` | secondary — industry attention |
| `wiki_hbm` | `en:High_Bandwidth_Memory` | secondary — product-story attention |

**Real signals (Naver search trends, Korean):**

| Signal | Topic | Role |
|---|---|---|
| `naver_hynix` | SK하이닉스 + 주가 + ticker | **primary** — investor attention, fixed before running |
| `naver_semi` | 반도체 | secondary — industry attention |
| `naver_hbm` | HBM | secondary — product-story attention |
| `naver_memory` | D램 / 낸드 | secondary — the earnings driver |
| `naver_samsung` | 삼성전자 | **CONTROL — never a finding.** Registered only to be inspectable |

The source `.xlsx` files in `data/` are downloaded by hand and **gitignored**, so a fresh
clone has none of them. `data-sources.md` holds the query permalinks that regenerate them,
and what the 0–100 index is.

Naming one primary per family in advance is what keeps "one fixed specification means one
test" true with eight real signals registered. If more than one is ever quoted as a
finding, the Bonferroni correction removed alongside the horizon grid has to come back
with them.

**Sentiment signal (GDELT news, English):**

| Signal | Query | Role |
|---|---|---|
| `gdelt_sent_semi` | `HBM memory` | secondary — **sentiment, not attention** |

The first signal measuring whether the news is *good or bad* rather than how much of it
there is, and the only one registered against **`fwd_exret`** rather than `fwd_ret`: 17% of
the headlines are market-wide coverage ("Dow Just Lost 1,100 Points"), which correlates with
the market on both sides and could manufacture a result through beta. The KOSPI-excess
target differences that out.

An industry query, not a company one — GDELT matches the article *body* but returns only the
*title*, so `"SK Hynix"` yields 15% on-topic headlines against 58% for `HBM memory`. It
therefore measures **international semiconductor sentiment**, not SK Hynix sentiment.

`GDELT_QUERIES` is a tuple and the results are **pooled**, deduplicated on `url`; more
on-topic headlines per day is the only fix for the sampling noise that dominates this signal.
`signals.load_gdelt_articles` is the single entry point — it pools, dedupes, and applies the
two filters (English only, `signals.ON_TOPIC`) that every consumer must see. Its transform is
`zscore`, not `raw`: FinBERT scores this corpus positive on 86% of days, so the uncentred
version broke both the tail test's `lower`/`both` sides and `combine`'s sign premise. See
`methodology.md`.

**Article timestamps need no stamping function.** GDELT's `seendate` is a full UTC instant,
so articles go straight into `align.align_to_trading_days` — unlike the pageview and Naver
sources, which are calendar days needing a closing-edge convention.

**KST day → trading day.** Naver returns one number per **KST** calendar day.
`align.daily_kst_to_timestamps` stamps each at `(D+1) 00:00 KST` — 8.5h after the 06:30 UTC
close — so day *D* lands on trading day *D+1*, averaging Fri/Sat/Sun into Monday. Verified:
signal[t] equals the mean of raw values over `[previous session, t−1 day]`, with **zero
same-day leaks across 1,864 trading days**. Its docstring records why it exists rather than
reusing the UTC function.

**UTC day → trading day.** The pageviews API returns one integer per UTC calendar day; KRX
closes at 06:30 UTC. `align.daily_utc_to_timestamps` stamps each day at `(D+1) 00:00 UTC` —
the first instant its total exists — and `align_to_trading_days` then attributes UTC day *D*
to trading day *D+1*, summing Fri/Sat/Sun into Monday. Verified: signal[t] equals the sum of
raw pageviews over `[previous session, t−1 day]`, with **zero same-day leaks across 1,864
trading days**.

**Primary specification** — fix this before looking, to keep specification search
honest: `fwd_ret` target (raw), horizon 3, and the signal's registered
`DEFAULT_TRANSFORM` (`zscore` for the fixtures, `dow_zscore` for the pageview
signals). Everything else is explicitly secondary.

**Deliberately narrow output.** Phase 1 reports rank IC, HAC t, HAC p, the
top-minus-bottom quintile spread with its own HAC t, p and n, the full-sample n, the
quintile table, the tail test with its event metrics, and the reverse-causality panel — nothing else. The spread's
`ls_n` is reported because that test uses only the extreme buckets (~40% of the days), so
quoting it beside the full-sample `n` would misstate what it was measured on.

**The tail test is one-sided by default and exploratory.** `stats.tail_test` compares days
beyond `TAIL_Z` against *all* others — `side=` picks which tail (`upper`, `lower`, `both`),
and `lower`/`both` assume a signal centred on zero, which `raw` is not — full sample, unlike the spread — because it asks whether a
spike moves the stock, not whether the relationship is monotonic. `TAIL_Z = 2.5` was chosen
after inspecting results, so `stats.tail_curve` reports the whole threshold grid and both
the dashboard and `run_test.py` render it unconditionally beside the headline number. Never
quote a tail p-value without it. See `methodology.md`. Scope was cut on 2026-08-10 (developer's call) by removing the
multi-horizon grid, the Bonferroni threshold, `coef`, `t_ols_naive`, the cumulative
long-short curve, the `fwd_vol` / `fwd_volrat` targets and the `diff` / `logdiff` /
`pctrank` transforms. Two targets remain (`fwd_ret`, `fwd_exret`). Transforms were cut to two
(`raw`, `zscore`) and a third, `dow_zscore`, was added back on 2026-08-20 — not a
reversal of the cut but a correctness fix for the day-of-week artifact recorded below. `stats.evaluate` replaced `stats.horizon_grid` and returns a dict
for a single specification. Consequences worth knowing before re-adding anything:

- Bonferroni went with the horizon grid and is *not* an oversight — one fixed
  specification means one test. If multi-horizon ever returns, the correction has to
  return with it.
- Dropping `fwd_vol`/`fwd_volrat` removes the targets where attention data most
  plausibly shows an effect — volume and turbulence rather than direction. All three
  pageview signals have since read null on returns, so this is now the obvious next
  thing to add back.
- `ols_hac` still computes `coef` and `se_ols` internally; they are used by
  `long_short` and by the HAC-correction tests, just not displayed.

### Companion docs

| File | Holds |
|---|---|
| `methodology.md` | Decisions not obvious from the code, and the measurements behind them |
| `findings.md` | Results. `results/*.json` is git-ignored, so this is their only committed record |
| `data-sources.md` | Signal-source options, what is obtainable, and open source decisions |
| `price-data.md` | OHLCV source options for `000660.KS` and KOSPI |

## Maintenance Rule

Keep this file about **structure**: what each file is for, how they interact, and any
naming or convention that is not standard. Update it in the same session, not as an
afterthought.

Everything else goes elsewhere — do not grow this file with it:

- a result, a statistic, a run's output → `findings.md`
- a methodological decision or the measurement justifying it → `methodology.md`
- a library or environment quirk → a comment at the code that works around it
- anything about where data comes from or whether it is obtainable → `data-sources.md` /
  `price-data.md`
