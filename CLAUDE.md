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
- **State assumptions in the analysis**, not just the code — sample period, universe, how missing data is handled.
- **Report negative results honestly.** "No significant relationship" is a valid and expected outcome. Never tune a spec until it produces a signal and then present that as a finding.
- Any statistic reported must be reproducible by re-running a script in the repo.

## Project Details

**Goal**: Measure whether public *attention* has a measurable effect on stock prices.

Originally framed as Twitter/X activity. Changed on 2026-08-20 (developer's call) because
no free tweet source exists any more — see Open Questions and `data-sources.md`. The
substitute is Wikipedia pageviews, which measure people **looking a company up** rather than
**discussing it**: a related but distinct construct, stated here rather than quietly
swapped.

**Current scope (Phase 1)**: The simplest possible version of the question — does *attention
frequency* (daily pageview count for a topic) relate to SK Hynix price behavior? Sentiment,
content, and author quality are explicitly out of scope for now.

**Target**: SK Hynix — KRX ticker `000660.KS`. Note it trades on the Korea Exchange (KST, 09:00–15:30), while tweet volume is global and 24h. Aligning tweet windows to trading sessions is the core methodological problem of Phase 1.

**Intended direction**:
1. Collect daily tweet counts mentioning SK Hynix over some history.
2. Collect matching daily OHLCV for `000660.KS`.
3. Align the two into one daily panel, with tweet counts attributed to the correct trading day.
4. Look at the relationship between tweet count (and its changes/abnormality vs. a rolling baseline) and next-period returns, volatility, and volume.

**Stack**: Python 3.13 in `.venv`. pandas / numpy / statsmodels / pykrx / yfinance /
streamlit / altair. `pip install -r requirements.txt`.

### Testing Framework

A signal-agnostic harness for the general question "does signal X predict SK Hynix
price behaviour?" — built before any real signal exists so the tweet-source decision
stops gating progress. Tweet counts, Google Trends and anything else all reduce to
one number per trading day, which is the only interface it requires.

| Module | Role |
|---|---|
| `quant/cache.py` | `CACHE_DIR` + `cached(path, fetch)` — the parquet cache, shared by every loader |
| `quant/prices.py` | OHLCV for `000660` (pykrx) and KOSPI (`^KS11`, yfinance) |
| `quant/wiki.py` | Wikipedia pageviews per UTC calendar day; the real signal source |
| `quant/align.py` | UTC signal timestamps → KRX trading date. **The only module with timezone logic** |
| `quant/panel.py` | Forward-return targets and signal transforms |
| `quant/signals.py` | Signal registry + the three validation fixtures |
| `quant/stats.py` | Rank IC, quantile buckets, Newey-West regressions, reverse causality |
| `scripts/run_test.py` | CLI; writes a JSON record to `results/` |
| `app.py` | Streamlit dashboard — a thin caller of the same functions, so it cannot drift |

**Adding a real signal**: write a function `(px, kospi) -> Series` keyed by trading
date, register it in `SIGNALS`, `SIGNAL_AGG` and `DEFAULT_TRANSFORM` (`"zscore"` for
count-style signals). If it arrives as UTC timestamps, run it through
`align.align_to_trading_days` first. `signals._pageview_signal` is the worked example.
Nothing else changes — `app.py` and `run_test.py` populate their choices from `SIGNALS`.

**Real signals (Wikipedia pageviews, English):**

| Signal | Article | Role |
|---|---|---|
| `wiki_hynix` | `en:SK_Hynix` | **primary** — company attention, fixed before running |
| `wiki_semi` | `en:Semiconductor` | secondary — industry attention |
| `wiki_hbm` | `en:High_Bandwidth_Memory` | secondary — product-story attention |

Naming one primary in advance is what keeps "one fixed specification means one test" true
with three signals registered. If all three are ever quoted as findings, the Bonferroni
correction removed alongside the horizon grid has to come back with them.

**UTC day → trading day.** The pageviews API returns one integer per UTC calendar day; KRX
closes at 06:30 UTC. `align.daily_utc_to_timestamps` stamps each day at `(D+1) 00:00 UTC` —
the first instant its total exists — and `align_to_trading_days` then attributes UTC day *D*
to trading day *D+1*, summing Fri/Sat/Sun into Monday. Verified: signal[t] equals the sum of
raw pageviews over `[previous session, t−1 day]`, with **zero same-day leaks across 1,864
trading days**.

**Primary specification** — fix this before looking, to keep specification search
honest: `zscore` transform, `fwd_ret` target (raw), horizon 3. Everything else is
explicitly secondary.

**Deliberately narrow output.** Phase 1 reports rank IC, HAC t, HAC p, the
top-minus-bottom quintile spread, n, the quintile table and the reverse-causality
panel — nothing else. Scope was cut on 2026-08-10 (developer's call) by removing the
multi-horizon grid, the Bonferroni threshold, `coef`, `t_ols_naive`, the cumulative
long-short curve, the `fwd_vol` / `fwd_volrat` targets and the `diff` / `logdiff` /
`pctrank` transforms. Two targets remain (`fwd_ret`, `fwd_exret`) and two transforms
(`raw`, `zscore`). `stats.evaluate` replaced `stats.horizon_grid` and returns a dict
for a single specification. Consequences worth knowing before re-adding anything:

- Bonferroni went with the horizon grid and is *not* an oversight — one fixed
  specification means one test. If multi-horizon ever returns, the correction has to
  return with it.
- Dropping `fwd_vol`/`fwd_volrat` removes the targets where attention data most
  plausibly shows an effect (volume and turbulence rather than direction). If tweet
  counts read null on returns, this is the first thing to add back.
- `ols_hac` still computes `coef` and `se_ols` internally; they are used by
  `long_short` and by the HAC-correction tests, just not displayed.

#### Non-obvious things learned building it

- **HAC inflation needs a *persistent signal*, not just an overlapping target.**
  Newey-West acts on the autocovariance of signal × residual, so a near-iid signal
  barely moves even at h=10 (se ratio 1.13) while an AR(0.8) signal inflates 2.2×.
  Pinned by tests.
- **…but the `zscore` transform destroys that persistence, so HAC barely moves on
  the real signals.** Corrected 2026-08-20; this file previously predicted the
  opposite ("real attention signals are sticky, so the correction will matter").
  Measured: raw aligned pageview series have AR(1) of 0.46 / 0.03 / 0.29, and after
  z-scoring **−0.09 / −0.15 / −0.08**. Subtracting a 20-day rolling mean is a
  high-pass filter — it removes exactly the low-frequency persistence HAC exists to
  correct. Observed se/se_ols ratios are 0.85–0.93, i.e. HAC is slightly *smaller*
  than naive OLS, so on `wiki_semi` the naive t is 1.41 while the HAC t is 1.65.
  HAC remains the right default (it costs nothing when unneeded, and the `raw`
  transform preserves persistence), but do not expect it to rescue a borderline
  result on a z-scored signal.
- **Autocorrelation is different before and after trading-day alignment.** The
  calendar-daily `en:SK_Hynix` series has AR(1) 0.775; the same series aligned to
  trading days has 0.463, because summing Fri+Sat+Sun into Monday breaks up the
  short-lag structure. Both are correct measurements of different series — quote
  the aligned one when reasoning about the regression.
- **`ols_hac(y, x)` argument order is load-bearing and a swap is nearly invisible.**
  Plain-OLS t is exactly symmetric under swapping y and x in a bivariate regression;
  under HAC the t merely changes to another plausible value (7.5 → 4.6 on `planted`),
  and rank IC is unchanged either way. The coefficient is the only clear tell — it
  rescales by 1/σ(return) ≈ 30×. This bug was shipped and caught only by hand-checking
  that magnitude. **`coef` is no longer reported**, so the guard moved into the test
  suite: `test_evaluate_regresses_return_on_signal_not_the_reverse` monkeypatches
  `stats.ols_hac` and asserts the first call is `(fwd_ret_3, signal)`. Nothing in the
  output would catch a reintroduction.
- **`rank_ic` deliberately returns no p-value.** A Spearman p-value assumes
  independent observations, which overlapping forward returns are not. All inference
  routes through `ols_hac`.
- **pykrx's index endpoint requires KRX login** (`KRX_ID`/`KRX_PW`) and fails without
  it, so the KOSPI comes from yfinance `^KS11` instead. The stock OHLCV endpoint still
  works without auth.
- **`pd.Timedelta("15h30m")` emits a numpy DeprecationWarning** under numpy 2; use
  `pd.to_timedelta(..., unit="m")`.
- Streamlit's `st.info(icon=...)` accepts only real emoji, not shapes like `○`.

### Open Questions

Unresolved — do not assume answers to these. Full analysis of the data-source options
lives in `data-sources.md`; read it before proposing anything here.

- **Tweet data source — no free option currently exists** (re-verified 2026-08-20, full detail in `data-sources.md`). This is a change of status, not of preference:
  - **Option B (IA 1% Spritzer), previously the working default, is BLOCKED.** Every item in `collection:twitterstream` now carries `access-restricted-item: true`; anonymous download returns 401 (403 on the direct storage node, 401 even on the torrents). The metadata API is still open, which is how everything below was established. **Whether a free archive.org account lifts the restriction is untested and is the cheapest open question in the project.**
  - Even if unblocked, Option B carries: a hard **2023-01-30 end date** (the grab stopped ~2 weeks before Twitter killed free API access; the live successor collection `twitterarchive` is WARC data, private, and 403), **~3.6 TB** for a 2019–2023 sample, **125 missing days** in four multi-week blocks (2021-01, 2021-04, 2022-11/12), and five different container formats with item identifiers that do not match their contents.
  - The 2023-01 cutoff excludes the entire HBM/AI cycle — the period where SK Hynix attention is most likely to carry information.
  - **A 2–3 month window is affordable but not accessible.** Three gap-free candidates are worked out in `data-sources.md` (cheapest: 2019-06-01 → 08-31, ~184 GB, containing the July 2019 Japanese export controls). The 401 is per-request, not per-byte, so a short window does not route around it. Note also that 40–60 trading days can only detect ρ ≈ 0.36 against a realistic 0.05–0.15, so a short sample demonstrates the pipeline but **cannot** answer the research question — an underpowered null must never be reported as a finding.
  - Option A remains Enterprise-priced (~$42k/mo) and its deletion bias is now quantified: Sequiera & Lin (2017) measured **18.5% of tweets deleted within four years**. The same paper measured the IA capture rate at **95.2%** of a dedicated crawler, so the Spritzer scaling factor is ~105, not 100.
- The **SK Hynix tweet base rate is still unknown** and is now unmeasurable without solving the access problem — the probe specified in `data-sources.md` requires the blocked data.
- **Free attention sources were probed live on 2026-08-20** and are catalogued in `data-sources.md` with reproduce commands. None chosen. Adopting any would change the research question from Twitter activity to attention more broadly, which must be stated explicitly rather than substituted quietly.
  - **Confirmed, no auth:** Wikimedia pageviews — 2,775 consecutive days, 2019-01-01 → 2026-08-06, **zero missing days**, `en:SK_Hynix` mean 383/day, `ko:SK하이닉스` 75, `en:Semiconductor` 1,755. A **census, not a sample**, so the low-base-rate problem that makes Option B unusable for a company-specific query does not arise. Daily only (hourly endpoint returns 400), which `quant.align` handles by labelling each UTC day at its closing edge.
  - **Confirmed, no auth:** GDELT DOC 2.0 — daily news-coverage share, verified at both ends of the sample. Rate limit 1 req/5s, enforced with extended blocks. Its earliest date and its Korean-language coverage are **unverified** and matter before it could be relied on.
  - **Works but disqualified:** Google Trends returns a per-window-rescaled 0–100 index, not a count, and gives daily data only for windows under ~9 months — 2019–2026 daily would need ~30 stitched windows. `pytrends` is unmaintained and breaks against urllib3 2.x.
  - **Blocked:** Reddit (403, Pushshift moderator-only since 2023), StockTwits (403 Cloudflare), Bluesky (403, and no pre-2023 history). **Too sparse:** Hacker News works but yields 137 SK Hynix stories total since 2019.
  - **Free with registration, untested:** Naver DataLab — likely the highest-value source here, since Naver is ~60% of Korean search and therefore matches the audience that actually trades this stock.
- Search terms defining "a tweet about SK Hynix" (English vs. Korean, `$000660` cashtags, `SK하이닉스`, plain "SK Hynix", HBM-related chatter).
- Sample period and data granularity (daily vs. intraday).
- Whether returns should be raw or market-excess (e.g. vs. KOSPI).

### Status

- **Testing framework: built and validated.** `pytest` (31 tests) passes; the network pageview and
  price cross-checks pass under `pytest -m slow`. Price data is live: 1,865 trading
  days of SK Hynix, 2019-01-02 → 2026-08-06.
- **Framework validation results** at the primary spec, h=3 (reproduce with
  `scripts/run_test.py --signal <name>`): `noise` reads null (IC −0.028, p = 0.62);
  `planted` (ρ=0.15 fixture) is detected with IC 0.168, HAC t = 7.51, and a monotone
  quintile ramp; `past_return` shows no forward predictability (p = 0.52) but fires
  hard on the reverse-causality check (t = 17.9) as designed. The harness
  distinguishes signal from noise. `test_planted_strongest_at_its_own_horizon` still
  confirms the fixture peaks at h=3 across 1/3/5/10, even though the CLI no longer
  scans horizons.
- **First real signal implemented and run (2026-08-20): Wikipedia pageviews.** All three
  signals read **null** at the primary spec (zscore / `fwd_ret` / h=3), over 1,865 trading
  days, 2019-01-02 → 2026-08-06, n=1,841. Reproduce with `scripts/run_test.py --signal <name>`:

  | Signal | rank IC | HAC t | HAC p | top−bottom | Verdict |
  |---|---|---|---|---|---|
  | `wiki_hynix` (primary) | +0.031 | +1.49 | 0.137 | +0.0055 (t=1.47) | no significant relationship |
  | `wiki_semi` | +0.021 | +1.65 | 0.099 | +0.0028 (t=0.73) | no significant relationship |
  | `wiki_hbm` | +0.034 | +1.27 | 0.203 | +0.0056 (t=1.30) | no significant relationship |

  **This is a real negative result, not an underpowered one.** At n=1,841 the harness can
  detect ρ ≈ 0.05–0.15; the observed ICs sit at 0.02–0.03 with quintile tables that do not
  ramp monotonically. Attention, as measured by pageviews, does not predict SK Hynix 3-day
  forward returns over this sample.
- **Reverse causality is also null** for `wiki_hynix` (past 1-day t = −0.51, p = 0.61;
  past 3-day t = +0.51, p = 0.61). Worth noting because the expectation going in was that
  attention chases price — it does not measurably do so here either.
- **No tweet source is obtainable.** Unchanged; see Open Questions. Wikipedia was adopted
  as the substitute, which is why the Phase 1 goal above now reads *attention* not *tweets*.
- `data-sources.md` — evaluation of tweet-count sources only, with whether each can yield a raw tweet count. Analysis only; no decisions made. Deliberately excludes sentiment/media-analytics vendors and price data. Rewritten 2026-08-20 with verified access findings; it now carries one out-of-scope section recording the Wikimedia pageviews measurement, because that measurement is the direct consequence of every tweet option closing. Each finding states how to reproduce it.
- `price-data.md` — OHLCV source options for `000660.KS` and KOSPI. Implemented; note the pykrx index-endpoint limitation recorded there.

## Maintenance Rule

Whenever you learn something about this project that isn't obvious from reading the code — a new module's purpose, a new convention, a gotcha, a completed/blocked piece of work — update this file in the same session, not as an afterthought. Keep the Project Details section current rather than letting it drift.
