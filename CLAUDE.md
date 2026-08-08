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

**Stack**: Python. Nothing chosen beyond that yet.

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

- Nothing implemented yet. No data source chosen.
- `data-sources.md` — evaluation of tweet-count sources only, with whether each can yield a raw tweet count. Analysis only; no decisions made. Deliberately excludes sentiment/media-analytics vendors, price data, and attention proxies.
- `price-data.md` — OHLCV source options for `000660.KS` and KOSPI. pykrx recommended; not yet implemented.

## Maintenance Rule

Whenever you learn something about this project that isn't obvious from reading the code — a new module's purpose, a new convention, a gotcha, a completed/blocked piece of work — update this file in the same session, not as an afterthought. Keep the Project Details section current rather than letting it drift.
