# Findings

Results produced so far. `results/*.json` is git-ignored, so this file is the only committed
record. Every number is reproducible with `scripts/run_test.py`.

**Specification: `dow_zscore` / `fwd_ret` / h=1 / 2023-01-01 → 2026-08-06**, 876 trading days.

Two results below are included as calibration for how much a p-value is worth in this
setting: a demonstrated false positive (§2) and a fixture that only just validates (§1).

---

## 1. Harness validation

These decide whether a null means "no effect" or "broken pipeline":

| Fixture | Result | Reads as |
|---|---|---|
| `noise` | IC +0.006, p = 0.43 | null, as required — guards against false positives |
| `planted` (ρ=0.15) | IC +0.087, t = +2.04, **p = 0.0418** | detected, but only just |
| `past_return` | forward p = 0.72; reverse p < 0.0001 | no forward predictability, fires hard on the reverse check by design |

**`planted` clearing 0.05 only narrowly is important context for everything below.** It is
constructed to be detectable, so a sample that barely resolves it can only resolve effects of
roughly ρ ≈ 0.15 or larger. Two consequences: every null here means *"no large effect"* rather
than *"no effect"*, and `naver_hynix`'s IC of +0.063 is **smaller** than the planted effect's
+0.087 — a real signal weaker than the one the harness struggles to see.

---

## 2. Attention signals — primary spec

| Signal | rank IC | HAC t | HAC p | top−bottom | ls p |
|---|---|---|---|---|---|
| **`naver_hynix`** (primary) | **+0.0633** | **+2.01** | **0.0444** | +0.71% | 0.100 |
| `naver_samsung` (control) | +0.0357 | +0.81 | 0.417 | +0.43% | 0.280 |
| `naver_hbm` | +0.0351 | +1.21 | 0.226 | +0.53% | 0.173 |
| `naver_memory` | +0.0209 | **+2.28** | **0.0228** | +0.22% | 0.549 |
| `naver_semi` | +0.0175 | +0.69 | 0.493 | +0.25% | 0.529 |
| `wiki_semi` | −0.0002 | +0.38 | 0.701 | +0.24% | 0.562 |
| `wiki_hbm` | −0.0285 | +0.16 | 0.870 | +0.05% | 0.907 |
| ⚠️ `wiki_hynix` | **−0.0433** | **+2.22** | **0.0265** | −0.26% | 0.531 |

**`naver_hynix` clears 0.05** at p = 0.0444, the largest IC in the table.

**So does `wiki_hynix`, at p = 0.0265 — and it is a false positive.** Its rank IC is *negative*
while its t is *positive*. Rank IC is outlier-immune and OLS is not, so a sign disagreement
between them means the t-statistic is carried by a handful of extreme days rather than the
bulk of the sample — the fat-tail behaviour documented in `methodology.md`. Wikipedia pageviews
of an encyclopedia article have no mechanism for predicting a Korean stock's next-day return.

It is kept in the table deliberately. It is the yardstick for what p ≈ 0.03 is worth in this
setting, and it applies to `naver_hynix` too.

**The control is close.** `naver_samsung` carries an IC of +0.0357 — 56% of the primary's. Not
significant (p = 0.42), so a company-specific reading survives, but not comfortably.

---

## 3. Tail test — where the effect concentrates

Days above `dow_zscore > 2.5` (the top ~10.6%) against all others:

| Signal | excess | HAC p | tail days | mean event | mean other | hit rate | hit p |
|---|---|---|---|---|---|---|---|
| **`naver_hynix`** | **+0.94%** | **0.0351** | 106 | **+1.15%** | +0.21% | 52.8% | 0.543 |
| `naver_semi` | +0.76% | 0.053 | 95 | +1.00% | +0.24% | 55.8% | 0.278 |
| `naver_memory` | +0.61% | 0.083 | 87 | +0.87% | +0.26% | 56.3% | 0.245 |
| `naver_hbm` | +0.42% | 0.188 | 106 | +0.69% | +0.27% | 56.6% | 0.160 |
| `naver_samsung` (control) | +0.34% | 0.371 | 94 | +0.62% | +0.29% | 55.3% | 0.313 |
| `wiki_hynix` | +0.50% | 0.266 | 102 | +0.76% | +0.27% | 51.0% | 0.843 |
| `wiki_semi` | +0.37% | 0.466 | 74 | +0.66% | +0.29% | 52.7% | 0.653 |
| `wiki_hbm` | −0.09% | 0.806 | 89 | +0.24% | +0.33% | 50.6% | 0.918 |

High-attention days return **+1.15% in a single day** against **+0.21%** on ordinary days —
more than five times the baseline.

**The hit rate does not corroborate it: 52.8%, p = 0.543.** The mean says the effect is there;
the count-based test does not. Since the hit rate discards magnitude entirely, the disagreement
means the mean is driven by a minority of large days rather than a broad tilt across event
days. Both statistics agreeing would be much stronger evidence than one of them.

### Robustness

Across twelve alternative specifications, the tail excess for `naver_hynix` stays in
**+0.64% to +1.84%, median +1.35%, and is positive in every one.** The estimate does not
depend on the specification chosen — only its significance does, and that tracks sample size.
An effect that holds its magnitude while the specification moves is the strongest evidence in
this document; noise would vary in size, not only in p.

### The magnitude hypothesis is rejected

Mean |return| on event days runs **0.90–1.18×** ordinary days. High attention does not make the
stock move *further*, only (perhaps) *upward*. Directional only.

---

## 4. News sentiment — null on every specification

`gdelt_sent_semi`, FinBERT on GDELT headlines, `raw` transform:

| Target | n | rank IC | HAC p | top−bottom | ls p |
|---|---|---|---|---|---|
| `fwd_exret` (registered) | 783 | −0.012 | 0.281 | −0.29% | 0.281 |
| `fwd_ret` | 784 | −0.040 | 0.271 | −0.49% | 0.197 |

At a cut matched to the same top 10.6% (score > 0.521, since sentiment is bounded [−1,+1] and
`TAIL_Z = 2.5` selects zero days): excess **−0.38%** (p = 0.27) on `fwd_ret`, **−0.20%**
(p = 0.37) on `fwd_exret`, across 98 event days.

**Sentiment does not predict returns at any target or cut tried.** Signs lean negative — the
"already priced in" direction — but nothing approaches significance.

---

## 5. Combined signal — null

`trailing_pct_rank(naver_hynix) × gdelt_sent_semi`: attention as a [0,1] weight, sentiment as
the sign, so the product is signed by the news and scaled by how much attention was on it.
Rank IC **+0.005**, HAC p **0.81**.

The interaction hypothesis — that sentiment matters more when attention is high — is not
supported. Reproduce with `run_test.py --combine naver_hynix,gdelt_sent_semi`.

---

## What this project has established

1. **A validated harness** — `noise` null, `planted` detected, though only narrowly here.
   Every null means "no *large* effect" rather than "broken pipeline".
2. **Two day-of-week artifacts found and corrected** — 83.5% Monday domination on pageviews,
   0.0% on Naver. Either would have manufactured a false result. See `methodology.md`.
3. **A demonstrated false positive** (`wiki_hynix`, p = 0.0265), which calibrates every other
   p-value here.
4. **Wikipedia pageviews measure the wrong construct** — encyclopedic curiosity rather than
   investor intent; Naver's `주가` and ticker keywords measure a better one.
5. **Sentiment adds nothing**, alone or interacted with attention.
6. **A tail effect in Korean search attention with a robust effect size** — the one result that
   does not move when the specification does.

**The only honest next step is out-of-sample.** Fix the specification now and run it once on
data not used here: a different Korean semiconductor stock, or SK Hynix after 2026-08.
Everything in this document is a hypothesis generated by this sample, and cannot also be its
own test.

---

## Superseded

An earlier Wikipedia run used `agg="sum"` with plain `zscore`, reporting IC +0.031 for
`wiki_hynix`. Those numbers were contaminated by the day-of-week artifact recorded in
`methodology.md` — still null, but the quintile spread described Mondays rather than attention.
Do not quote them.
