# Findings

Results produced so far. Moved out of CLAUDE.md on 2026-08-20 to keep that file about
structure. Add here, not there.

Every number below is reproducible with `scripts/run_test.py --signal <name>`, which also
writes a JSON record to `results/`. That directory is git-ignored, so this file is the
only committed record of them.

## Harness validation (fixtures)

At the primary spec, h=3. These decide whether a null on a real signal means "no effect"
or "broken pipeline":

| Fixture | Result | Reads as |
|---|---|---|
| `noise` | IC −0.028, p = 0.62 | null, as required — guards against false positives |
| `planted` (ρ=0.15) | IC 0.168, HAC t = 7.51, monotone quintile ramp | detected, as required — guards against false negatives |
| `past_return` | forward p = 0.52; reverse-causality t = 17.9 | no forward predictability, fires hard on the reverse check by design |

`test_planted_strongest_at_its_own_horizon` confirms the fixture peaks at h=3 across
1/3/5/10, even though the CLI no longer scans horizons.

Price data is live: 1,865 trading days of SK Hynix, 2019-01-02 → 2026-08-06.

## Wikipedia pageviews — first real signal (2026-08-20)

All three signals read **null** at the primary spec (`dow_zscore` / `fwd_ret` / h=3),
n = 1,841 over 1,865 trading days, 2019-01-02 → 2026-08-06:

| Signal | rank IC | HAC t | HAC p | top−bottom | Verdict |
|---|---|---|---|---|---|
| `wiki_hynix` (primary) | −0.006 | +0.22 | 0.828 | −0.0000 (t=−0.01) | no significant relationship |
| `wiki_semi` | −0.011 | +0.08 | 0.933 | −0.0014 (t=−0.30) | no significant relationship |
| `wiki_hbm` | −0.021 | −0.65 | 0.517 | −0.0006 (t=−0.13) | no significant relationship |

**This is a real negative result, not an underpowered one.** At n = 1,841 the harness can
detect ρ ≈ 0.05–0.15; the observed ICs sit at 0.01–0.02 with quintile tables that do not
ramp monotonically. Attention, as measured by pageviews, does not predict SK Hynix 3-day
forward returns over this sample.

**Reverse causality is also null** for `wiki_hynix` (past 1-day t = −0.51, p = 0.61;
past 3-day t = +0.51, p = 0.61). Worth recording because the expectation going in was that
attention chases price — it does not measurably do so here either.

## Naver search trends — second attention instrument (2026-08-24)

Naver replaced Wikipedia as the attention instrument on a construct argument made *before*
running: a Wikipedia lookup is encyclopedic curiosity, while these keyword groups include
`주가` and the ticker, so they capture Korean retail investors looking up a stock. Naver is
~60% of Korean search. `naver_hynix` was declared primary and `naver_samsung` a control in
advance; see CLAUDE.md.

Primary spec (`dow_zscore` / `fwd_ret` / h=3), n = 1,841 over 1,865 trading days,
2019-01-02 → 2026-08-06:

| Signal | rank IC | HAC t | HAC p | top−bottom | spread t | spread p |
|---|---|---|---|---|---|---|
| `naver_hynix` (**primary**) | +0.029 | +0.56 | 0.573 | +0.0034 | +0.73 | 0.463 |
| `naver_semi` | +0.021 | +0.89 | 0.373 | +0.0084 | +1.67 | 0.095 |
| `naver_hbm` | +0.001 | +1.08 | 0.281 | +0.0044 | +0.96 | 0.337 |
| `naver_memory` | +0.033 | +1.39 | 0.163 | +0.0047 | +1.08 | 0.280 |
| `naver_samsung` (control) | +0.016 | +0.53 | 0.598 | +0.0027 | +0.57 | 0.572 |

**The primary reads null.** Attention as measured by Korean search does not predict SK Hynix
3-day forward returns over this sample. Every secondary is null too, and none approaches
significance once the correction required for quoting more than one is applied.

Worth recording that **all five signs are positive** — every IC, every t, every spread. That
is not five independent confirmations: the series correlate 0.86–0.93 with each other, so
this is closer to one positive draw than to five. It is consistent with a weak positive
effect the sample cannot resolve, and equally consistent with noise.

### Reverse causality — the one direction that fires

Regressing the signal on *past* returns, the sign is positive throughout and three of five
clear p < 0.05 individually at the 3-day lag:

| Signal | past 1d | past 3d |
|---|---|---|
| `naver_hynix` | t=+1.56, p=0.118 | t=+1.64, p=0.102 |
| `naver_semi` | t=+0.83, p=0.409 | **t=+2.17, p=0.030** |
| `naver_hbm` | t=−0.05, p=0.960 | **t=+2.24, p=0.025** |
| `naver_memory` | t=+1.00, p=0.317 | t=−0.13, p=0.893 |
| `naver_samsung` | t=+1.02, p=0.306 | **t=+2.12, p=0.034** |

**Do not quote these as significant.** Ten tests were run across five highly correlated
signals; a Bonferroni threshold would be 0.005 and none passes. What survives is the
*direction*, which is consistent across every signal: **attention follows price rather than
leading it.**

For the primary, the reverse |t| = 1.64 exceeds the forward |t| = 0.56, which is the
condition the dashboard warns on. This is the outcome flagged as most likely before running,
and it is the opposite of what Wikipedia showed — where both directions were null.

### What the control says

`naver_samsung` behaves almost identically to `naver_hynix` on every statistic. Given the
0.86 same-weekday correlation between them, that is the expected result and it carries a
consequence: what these series measure is largely **sector-wide Korean attention**, not
company-specific attention. Had `naver_hynix` come back significant, the control would have
been necessary to establish whether the finding was about SK Hynix at all.

## Tail test — EXPLORATORY, not a finding (2026-08-25)

**Read the caveat before the table.** The threshold was chosen after inspecting results, so
the p-values below overstate the evidence and none of this is pre-registered. It is recorded
because it is the first thing in this project that is not flat null, and because the honest
next step depends on it.

Days with `dow_zscore > 2.5` versus all other days, HAC dummy regression on the full sample,
`fwd_ret` h=3:

| Signal | excess | HAC t | HAC p | tail days | cuts significant of 6 |
|---|---|---|---|---|---|
| `naver_hynix` (primary) | **+0.0102** | **+2.52** | **0.0119** | 196 | **4** |
| `naver_memory` | +0.0075 | +1.95 | 0.0512 | 196 | 1 |
| `naver_semi` | +0.0064 | +1.47 | 0.1427 | 213 | 0 |
| `naver_hbm` | +0.0014 | +0.35 | 0.7287 | 186 | 0 |
| `naver_samsung` (control) | **−0.0040** | −0.87 | 0.3853 | 194 | 0 |
| `wiki_hynix` | −0.0002 | −0.06 | 0.9512 | 204 | 0 |
| `wiki_semi` | +0.0045 | +0.93 | 0.3531 | 155 | 0 |
| `wiki_hbm` | −0.0022 | −0.52 | 0.6014 | 178 | 0 |

For `naver_hynix` the same day-level data gives rank IC +0.029 with p = 0.573 across all
1,841 days. The tail test finds +1.02% on 196 of them. That gap is the point of the test:
a whole-distribution statistic averages a tail effect away.

### Event metrics at the same cut

The excess above is a difference; these are the two sides of it, plus the hit rate against
the median return of non-event days (so the comparison group sits at ~50% by construction):

| Signal | events | mean, event | mean, other | hit rate | vs baseline | HAC p | mean \|ret\| ratio |
|---|---|---|---|---|---|---|---|
| `naver_hynix` | 196 | **+1.40%** | +0.39% | **58.2%** | **+8.2pp** | **0.037** | 0.95 |
| `naver_memory` | 196 | +1.16% | +0.42% | 57.1% | +7.2pp | 0.107 | 0.86 |
| `naver_semi` | 213 | +1.06% | +0.42% | 49.8% | −0.2pp | 0.956 | 1.01 |
| `naver_hbm` | 186 | +0.62% | +0.48% | 50.5% | +0.6pp | 0.891 | 0.96 |
| `naver_samsung` (control) | 194 | +0.14% | +0.54% | 44.8% | −5.1pp | 0.261 | 1.00 |
| `wiki_hynix` | 204 | +0.47% | +0.50% | 46.6% | −3.4pp | 0.390 | 0.87 |
| `wiki_semi` | 155 | +0.91% | +0.46% | 52.9% | +2.9pp | 0.518 | 0.97 |
| `wiki_hbm` | 178 | +0.29% | +0.52% | 46.1% | −3.9pp | 0.343 | 0.99 |

For `naver_hynix` the split is +1.40% against +0.39% — the excess is not a small edge on a
large base, it is roughly 3.5× the ordinary-day return. The hit rate agrees in direction and
clears 0.05 on its own, which the other signals do not.

**The magnitude hypothesis is not supported by any signal.** The `mean |ret| ratio` column is
0.86–1.01 throughout: event days carry moves the same size as or *smaller* than ordinary
days. Whatever these spikes do, they do not make the stock move further. That column is
descriptive and carries no test — see `methodology.md` for why an absolute-return regression
would need a realized-volatility target rather than |cumulative return|.

**The hit rate is the weaker of the two statistics** and should not be read alone: on the
`planted` fixture the mean test clears at p = 0.015 where the hit rate reaches only p = 0.142
on identical data, because collapsing returns to a 0/1 outcome discards magnitude.

**What supports it**

- **The cut is on a plateau, not a spike.** Every threshold from 2.0 to 3.5 is significant
  (p = 0.024 / 0.012 / 0.016 / 0.048), and the excess rises monotonically 1.0 → 3.0 before
  flattening. A single lucky cut would not look like this.
- **The control points the other way.** `naver_samsung` is *negative*. If this were sector
  attention or a market-wide calendar artifact, the control should carry it too.
- **Wikipedia stays null at every cut**, so it is not an artifact of the method itself.
- **Tail days occur in every year** (6–20% of each) and beat their own year's baseline in 6
  of 8, so it is not purely the 2025–26 AI boom.
- 61% of tail days were followed by a gain, against 55% of all days.

**What undercuts it**

- **16 combinations were examined before the threshold was chosen.** Bonferroni across them
  is 0.0031; p = 0.0119 fails it. This alone makes the result exploratory.
- **It does not survive halving the sample** — ≤2024 gives +0.72% (p = 0.092), 2025–26 gives
  +1.26% (p = 0.187). Consistent with a weak real effect *and* with a borderline artifact.
- **`naver_memory` and `naver_semi` are not independent confirmation** — they correlate
  0.86–0.93 with `naver_hynix`, so this is closer to one observation seen three times.
- The magnitude hypothesis that motivated the test was **rejected** — outlier days show
  0.83–1.02× normal |return|, i.e. no amplification. Only the signed effect is present.

**The defensible claim** is "a tail effect is suggested and warrants a pre-registered test",
not "attention predicts returns above z = 2.5". The threshold is now burned on this sample;
a clean test needs a different asset or a future period, with the cut fixed at 2.5 in
advance and one test run.

### Superseded run

An earlier run of the same three signals used `agg="sum"` with plain `zscore` and reported
IC +0.031 / p 0.137 for `wiki_hynix` and p 0.099 for `wiki_semi`. Those numbers were
contaminated by the day-of-week artifact recorded in `methodology.md` — still null, but the
quintile spread described Mondays rather than attention. Do not quote them.
