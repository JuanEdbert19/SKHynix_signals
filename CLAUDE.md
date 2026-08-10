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

**Goal**: Measure whether Twitter/X activity has a measurable effect on stock prices.

**Current scope (Phase 1)**: The simplest possible version of the question — does *tweet frequency* (count of tweets per period mentioning SK Hynix) relate to SK Hynix price behavior? Sentiment, content, and author quality are explicitly out of scope for now.

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
| `quant/prices.py` | OHLCV for `000660` (pykrx) and KOSPI (`^KS11`, yfinance); parquet cache in `data/` |
| `quant/align.py` | UTC signal timestamps → KRX trading date. **The only module with timezone logic** |
| `quant/panel.py` | Forward-return targets and signal transforms |
| `quant/signals.py` | Signal registry + the three validation fixtures |
| `quant/stats.py` | Rank IC, quantile buckets, Newey-West regressions, reverse causality |
| `scripts/run_test.py` | CLI; writes a JSON record to `results/` |
| `app.py` | Streamlit dashboard — a thin caller of the same functions, so it cannot drift |

**Adding a real signal**: write a function `(px, kospi) -> Series` keyed by trading
date, register it in `SIGNALS`, and set its `DEFAULT_TRANSFORM` (`"zscore"` for
count-style signals). If it arrives as UTC timestamps, run it through
`align.align_to_trading_days` first. Nothing else changes.

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
  Real attention signals are sticky, so the correction will matter — but do not
  expect to see it with a synthetic iid signal. Pinned by tests.
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

- Tweet data source. Four candidates evaluated in `data-sources.md` (official X API counts endpoint, Internet Archive 1% Spritzer, third-party resellers, published tweet-ID datasets) — none chosen. This decision constrains the achievable history length and query granularity, so it gates everything else.
- No option is simultaneously free, exact, and unbiased: the only source giving a true tweet count (official X API) is deletion-biased and Enterprise-priced; the only affordable unbiased source (IA 1% Spritzer) can only estimate counts by scaling a sample.
- The **SK Hynix tweet base rate is unknown** and gates the tweet-source decision. Probe it before anything else — see `data-sources.md`.
- Search terms defining "a tweet about SK Hynix" (English vs. Korean, `$000660` cashtags, `SK하이닉스`, plain "SK Hynix", HBM-related chatter).
- Sample period and data granularity (daily vs. intraday).
- Whether returns should be raw or market-excess (e.g. vs. KOSPI).

### Status

- **Testing framework: built and validated.** `pytest` (24 tests) passes; the network
  price cross-check passes under `pytest -m slow`. Price data is live: 1,865 trading
  days of SK Hynix, 2019-01-02 → 2026-08-06.
- **Framework validation results** at the primary spec, h=3 (reproduce with
  `scripts/run_test.py --signal <name>`): `noise` reads null (IC −0.028, p = 0.62);
  `planted` (ρ=0.15 fixture) is detected with IC 0.168, HAC t = 7.51, and a monotone
  quintile ramp; `past_return` shows no forward predictability (p = 0.52) but fires
  hard on the reverse-causality check (t = 17.9) as designed. The harness
  distinguishes signal from noise. `test_planted_strongest_at_its_own_horizon` still
  confirms the fixture peaks at h=3 across 1/3/5/10, even though the CLI no longer
  scans horizons.
- **No real signal implemented.** No tweet source chosen — that decision is still
  blocked on the base-rate probe in `data-sources.md`.
- `data-sources.md` — evaluation of tweet-count sources only, with whether each can yield a raw tweet count. Analysis only; no decisions made. Deliberately excludes sentiment/media-analytics vendors, price data, and attention proxies.
- `price-data.md` — OHLCV source options for `000660.KS` and KOSPI. Implemented; note the pykrx index-endpoint limitation recorded there.

## Maintenance Rule

Whenever you learn something about this project that isn't obvious from reading the code — a new module's purpose, a new convention, a gotcha, a completed/blocked piece of work — update this file in the same session, not as an afterthought. Keep the Project Details section current rather than letting it drift.
