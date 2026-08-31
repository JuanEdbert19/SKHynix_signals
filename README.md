# Does public attention move a stock?

A quantitative research project testing whether public attention and news sentiment predict
price behaviour in **SK Hynix** (KRX `000660`), using Naver search trends, Wikipedia
pageviews, and FinBERT sentiment over GDELT news headlines.

---
## Motivation

It started in a different repo. In `twitter_signals` I fine-tuned a BERT model to classify
emotion in tweets, with the intention of aggregating per-tweet sentiment into a daily trading
signal. The model worked. The data did not.

**Tweets turned out to be quite unobtainable.** Every route was blocked, and I checked
all of them before giving up:

| route | outcome |
|---|---|
| Official X API | ~$42k/month for the tier with historical counts |
| Internet Archive 1% Spritzer | `401 Unauthorized` even with a real account — privilege-gated |
| Third-party resellers | Cheap, but they censor exactly the volume peaks the signal needs |
| Published tweet-ID datasets | Need the X API to rehydrate, so gated behind the first row |

The Spritzer was the painful one. It was the best *design* available — an unbiased 1% sample
you count yourself — and it was free until it wasn't. I made an archive.org account
specifically to test whether that lifted the restriction. It didn't.

So I decided to look into other forms of attention. Attention doesn't only live on Twitter, and if the goal is measuring attention, there are instruments for it
that I can actually get:

- **Naver search trends** — what Korean retail investors are looking up. This is the closest
  substitute and arguably better than tweets for a Korean stock: the keyword group includes
  `주가` and the ticker, so it captures *investor* lookup rather than general chatter.
- **Wikipedia pageviews** — global, 24h, free, and unlimited history.
- **GDELT news headlines + FinBERT** — the sentiment half of the original idea, applied to
  news instead of tweets.

**I want to be explicit that this changed the construct, not just the plumbing.** Tweets
measure people *discussing* a company. Search volume and pageviews measure people *looking it
up*. Those are related but not identical, and pretending otherwise would quietly change what
the results mean. It is stated here rather than buried.

The pivot cost less than it should have, because of one decision made early: **the testing
framework was built signal-agnostic, before any real data source existed.** Every signal —
tweets, pageviews, search volume, news sentiment — reduces to one number per trading day,
which is the only interface the harness requires. When the tweet source collapsed, nothing in
`quant/stats.py`, `quant/panel.py` or the dashboard had to change. Only the loader did.

### What I care about getting right

This is a research project, so **the method matters more than the result.** Three rules I
hold myself to, because they're what separate a finding from a coincidence:

- **No look-ahead.** A feature at time *t* may only use information available at *t*. Signal
  timestamps are aligned to KRX trading sessions explicitly, and verified — zero same-day
  leaks across 1,864 trading days.
- **One fixed specification, chosen before looking.** Otherwise you're not testing a
  hypothesis, you're shopping for one.
- **Negative results get reported.** "No significant relationship" is a valid outcome and
  most of what I've found so far. `findings.md` records a demonstrated *false positive*
  alongside the real results, as a calibration point for how easily this sample manufactures
  a p-value below 0.05.

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

