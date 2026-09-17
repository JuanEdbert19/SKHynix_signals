# Does public attention move a stock?

A quantitative research project testing whether public attention and news sentiment predict
price behaviour in **SK Hynix** (KRX `000660`), using Naver search trends, Wikipedia
pageviews, and FinBERT sentiment over GDELT news headlines.

---
## Motivation

The project started in a different repo with finetuning a BERT model to extract sentiment from tweets. The sentiment model worked but the main problem was getting/scraping the tweets themselves.
Without them, I wasn't able to check whether or not these extracted sentiments carry any predictive powercan on stock returns.  

**Tweets turned out to be quite unobtainable.** Every route was blocked, and I checked
all of them before giving up:

| route | outcome |
|---|---|
| Official X API | ~$42k/month for the tier with historical counts |
| Internet Archive 1% Spritzer | `401 Unauthorized` even with a real account — privilege-gated |
| Third-party resellers | Cheap, but they censor exactly the volume peaks the signal needs |
| Published tweet-ID datasets | Need the X API to rehydrate, so gated behind the first row |

The Spritzer was the painful one. It was the best *design* available. As an unbiased 1% random sample of the full public stream, it has a fixed, known sampling mechanism, which means you can measure the sampling variance of any topic's frequency count. That matters: if SK Hynix attention spikes on a given day and you observe it in your 1% slice, you can calculate how much of the day-to-day variation in your count is just random sampling noise versus a real change in underlying frequency. Without that, you cannot tell whether a quiet day represents genuine low attention or an unlucky draw from the sample. It was privilege-gated.

Third-party resellers fail on this exact dimension, but worse: they selectively suppress the volume peaks, precisely the days this signal depends on. Because the censoring rule is unknown, there is no way to recover the true frequency or bound the error. The bias is unquantifiable, and it is highest exactly where the signal should be strongest.


So I decided to look into other forms of attention. Attention doesn't only live on Twitter, and if the goal is measuring attention, there are other instruments for it
that I can actually get:

- **Naver search trends** — what Korean retail investors are looking up. This is the closest
  substitute and arguably better than tweets for a Korean stock: the keyword group includes
  `주가` and the ticker, so it captures *investor* lookup rather than general chatter.
- **Wikipedia pageviews** — global, 24h, free, and unlimited history.
- **GDELT news headlines + FinBERT** — the sentiment half of the original idea, applied to
  news instead of tweets.


### What I care about getting right

- **No look-ahead.** A feature at time *t* may only use information available at *t*. Signal
  timestamps are aligned to KRX trading sessions explicitly, and verified — zero same-day
  leaks across 1,864 trading days.
- **Negative results get reported.** "No significant relationship" is a valid outcome and
  most of what I've found so far. `findings.md` records a demonstrated *false positive*
  alongside the real results, as a calibration point for how easily this sample manufactures
  a p-value below 0.05.

---

## Available signals

### Individual signals

**Wikipedia pageviews** (UTC calendar day → next KRX trading session)

| Signal | Article | Role | Transform |
|---|---|---|---|
| `wiki_hynix` | `en:SK_Hynix` | **Primary** — company attention | `dow_zscore` |
| `wiki_semi` | `en:Semiconductor` | Secondary — industry attention | `dow_zscore` |
| `wiki_hbm` | `en:High_Bandwidth_Memory` | Secondary — product-story attention | `dow_zscore` |

**Naver search trends** (KST calendar day → next KRX trading session, hand-exported `.xlsx`)

| Signal | Topic | Role | Transform |
|---|---|---|---|
| `naver_hynix` | SK하이닉스 + 주가 + ticker 000660 | **Primary** — investor attention | `dow_zscore` |
| `naver_semi` | 반도체 | Secondary — industry attention | `dow_zscore` |
| `naver_hbm` | HBM | Secondary — product-story attention | `dow_zscore` |
| `naver_memory` | D램 / 낸드 | Secondary — the earnings driver | `dow_zscore` |
| `naver_samsung` | 삼성전자 | **Control — never a finding** | `dow_zscore` |

**GDELT news headlines + FinBERT** (UTC timestamp → same KRX session)

| Signal | Query | Role | Transform |
|---|---|---|---|
| `gdelt_sent_semi` | `HBM memory` (pooled) | Secondary — international semiconductor sentiment | `zscore` |

`gdelt_sent_semi` measures sentiment (`P(pos) − P(neg)`) not attention, and is registered against `fwd_exret` rather than `fwd_ret` to remove market-beta noise from sector-wide headlines.

**Validation fixtures** (not findings)

| Signal | Purpose |
|---|---|
| `noise` | Pure iid noise — must return null |
| `planted` | Constructed look-ahead (ρ ≈ 0.15) — must return detected |
| `past_return` | Trailing 3-day return — reverse-causality check should fire |

---

### Combined signals

A combined signal pairs one attention signal with `gdelt_sent_semi` under one of three rules, selected with `--combine-rule` on the CLI or the Rule picker in the dashboard.

| Rule | Expression | Attention transform | Sentiment transform | Weight |
|---|---|---|---|---|
| `product` | `att × sen` | `dow_zscore` | `raw` | — |
| `linear` | `att + w · sen` | `dow_zscore` | `zscore` | slider (default 1.0) |
| `linear_wf` | `att + w(t) · sen` | `dow_zscore` | `zscore` | walk-forward OLS fit |

`raw` sentiment for `product` is load-bearing: with both legs centred, negative × negative reads positive on ~24% of days; keeping sentiment on its original positive-biased scale preserves a meaningful sign.

`linear_wf` fits `w(t)` by regressing the forward return on both unit-scaled arms in a rolling 200-day window (min 60 observations), using only rows whose return was already realised (`d + horizon ≤ t`). The fitted ratio `β_sentiment / β_attention` is clipped to ±2 to bound the noise from dividing two noisy coefficients.

Combined results are not registered in `SIGNALS`; use `run_test.py --combine A,B --combine-rule R` to keep them reproducible.

---

## Files

| file | holds |
|---|---|
| `CLAUDE.md` | structure — what each module does and how they fit |
| `findings.md` | results |
| `methodology.md` | decisions not obvious from the code, and the measurements behind them |
| `data-sources.md` | signal-source options, what is obtainable, and the tweet post-mortem |
| `price-data.md` | OHLCV source options for `000660.KS` and KOSPI |

```bash
streamlit run app.py                                    # dashboard
python scripts/run_test.py --signal naver_hynix         # one specification, one JSON record
pytest -q                                               # 115 tests
```