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

### Superseded run

An earlier run of the same three signals used `agg="sum"` with plain `zscore` and reported
IC +0.031 / p 0.137 for `wiki_hynix` and p 0.099 for `wiki_semi`. Those numbers were
contaminated by the day-of-week artifact recorded in `methodology.md` — still null, but the
quintile spread described Mondays rather than attention. Do not quote them.
