# Data Sources — Tweet Count per Topic

Options for obtaining **daily tweet counts mentioning SK Hynix**. Nothing else.
Status: **no source chosen yet.** This document records analysis, not a decision.

Sentiment-vendor products (MarketPsych, RavenPack, Bloomberg, Brandwatch, Sometrend) are
deliberately excluded — they are sentiment/media-analytics products, not tweet-count
sources.

Last reviewed: 2026-08-02.

---

## How much history is needed

Required sample size for a regression of next-day return on abnormal tweet volume is
approximately `n ≈ 7.85 / ρ²` (80% power, α = 0.05):

| Effect size ρ | Trading days needed | ≈ Calendar |
|---|---|---|
| 0.20 | ~200 | 10 months |
| 0.15 | ~350 | 1.4 years |
| 0.10 | ~785 | 3 years |

Realistic effect sizes in this literature sit at the low end, so **2–4 years of daily
history is the target**. This rules out any 7-day or 30-day search window (5 and ~20
observations) — those are not weak samples, they are incapable of distinguishing any
plausible effect from noise.

---

## Option A — Official X API (`/2/tweets/counts/all`)

**Mechanism.** Send a query plus time range; X runs it against its own authoritative
search index and returns bucketed counts. Server-side count, no sampling, no crawling.

### Raw tweet count available?

**Yes — directly, and this is the only option that returns a true count as a first-class
product.**

- `/2/tweets/counts/all` returns an exact integer per time bucket for your query.
  No estimation, no extrapolation.
- Granularity: minute / hour / day. Use **hour** and rebucket into KST trading windows —
  `day` buckets are UTC and do not align to KRX sessions.
- Raw tweet *bodies* are separately available via `/2/tweets/search/all`, but that
  consumes read quota and is unnecessary for Phase 1.

**Important qualification:** the count is of what *currently exists in the index*, not
what was *posted*. See deletion decay below.

**Positives**
- True census, not a sample. No sampling noise.
- Counts-only response is cheap in data volume — exactly what Phase 1 needs.
- Hourly granularity solves the KST alignment problem cleanly.

**Drawbacks**
- **Enterprise-gated.** ~$42,000/month. Basic and Pro closed to new signups as of
  Feb 2026; pay-per-use does not include full-archive access.
- **Deletion decay.** Deleted posts, suspended accounts, and newly-private accounts are
  absent from the index. Older days are systematically undercounted → **fake upward
  trend in attention.**
- **Bot purges make the decay lumpy**, not smooth. Cashtags attract promo bots; a mass
  suspension wipes a cohort at once, producing a cliff in historical counts that is not
  a real change in attention. Harder to detect than a gentle trend.
- **Not reproducible.** The same query run a year apart returns different numbers for the
  same historical day.
- Retweets match the query and count as separate posts — inflates counts via
  amplification rather than origination. Needs an explicit `-is:retweet` decision.
- Korean tokenization of `SK하이닉스` and `lang:ko` reliability on short posts are opaque
  and would need validation.

**Error profile:** low variance, **downward bias increasing with age**, lumpy.

**Mitigations if used**
- Snapshot raw responses to disk with query + pull timestamp; analysis reads the
  snapshot, never the live API.
- Pull a **matched control series** (e.g. Samsung Electronics, or a broad semiconductor
  term). Deletion decay and bot purges hit both; SK Hynix-specific attention does not.
  Differencing removes much of the artifact.

---

## Option B — Internet Archive Twitter sample stream (1% Spritzer)

**Mechanism.** Not a search. Twitter's `statuses/sample` endpoint pushed ~1% of all public
tweets worldwide in real time. Archive Team held that connection open for years and wrote
everything received to disk as gzipped JSON. You download the tarballs, iterate over
**every** tweet object, and apply your own keyword match locally.

**What the 1% is.** Kergl et al. (2014) reverse-engineered the rule: tweet IDs embed a
millisecond creation timestamp, and the Spritzer contains tweets created within a fixed
**~10ms window of every second** (10/1000 = 1%). Systematic sampling on creation time,
not random sampling.

### Raw tweet count available?

**No — you get a sampled count that must be scaled, not a true count.**

- You receive **raw tweet objects** (full JSON, text included) for ~1% of all tweets.
- You count matches yourself, then multiply by ~100 to estimate the true daily count.
- The estimate carries Poisson error — see the table below. It is an *estimate with a
  known error distribution*, not a measurement.
- The scaling factor is **not exactly 100** and drifts, because capture rate varies.
  Must be estimated per-period from the archive's own daily totals.

So: raw *tweets* yes (1% of them), true *count* no.

**Positives**
- **Free.**
- **Immune to deletion decay.** Tweets were captured as posted, so a post deleted in 2023
  is still in the 2021 file. More faithful to what was actually posted than Option A.
- **Sampling error is unbiased** — symmetric noise, not a trend. It cannot manufacture a
  signal. It attenuates regression coefficients toward zero (classical measurement error),
  costing statistical power but not validity.
- **Fully auditable.** You can measure the gaps yourself.
- **You control the matcher** — transparent substring matching on `SK하이닉스` in your own
  code rather than an uninspectable tokenizer. Material for a Korean-language study.
- Sampling happens upstream of any notion of the query, so it cannot be biased toward or
  against our topic.

**Drawbacks**
- **Poisson noise scales badly at low base rates.** Observed ≈ `Poisson(0.01 × N)`:

  | True tweets/day | Observed | Std dev | Relative noise |
  |---|---|---|---|
  | 5,000 | 50 | 7.1 | 14% |
  | 2,000 | 20 | 4.5 | 22% |
  | 500 | 5 | 2.2 | 45% |
  | 200 | 2 | 1.4 | 71% |

  Below ~1,000 true tweets/day this stops being a measurement.
- **Coverage is discontinuous across collections.** The original Archive Team Stream Grab
  ran ~2011–2022. A successor collection ("Twitter sample stream data" crawls) continues
  through 2024+. Different collections, likely different capture characteristics — do not
  assume one homogeneous series across the boundary. Some months missing entirely.
- **Effective rate is not exactly 1%.** The streaming API dropped messages under load, and
  the collector had outages and lag. Capture rate drifts below 1%, occasionally to zero.
- **Automation bias.** Bots and scheduled posts fire at clustered milliseconds rather than
  arbitrary ones, so automated content is over- or under-represented. Roughly constant
  *level* distortion — shifts the baseline, does not create day-to-day signal.
- Deterministic public rule means the sample is manipulable in principle (Pfeffer et al.).
- **Storage/compute.** ~5M tweets/day in the sample at peak; monthly collections run to
  tens of GB compressed.

**Error profile:** high variance, **near-zero bias**, hard gaps.

**Mandatory diagnostic if used**
Count *total* tweets per day in the archive and plot it before looking at SK Hynix at all.
That series is the effective capture rate and the true scaling denominator. Any dip or
flatline is a period where the SK Hynix count is depressed for reasons unrelated to
SK Hynix. Normalize by it or exclude those windows, and document which.

---

## Option C — Third-party resellers (twitterapi.io, Sorsa, Data365, Apify)

**Mechanism.** No firehose access exists at these prices. They build a private index by
running fleets of automated logged-in sessions against X's own search and timeline
endpoints, harvesting results into their own database. Your query hits their crawl, or
triggers a live scrape on demand.

### Raw tweet count available?

**Nominally yes, but the number is not trustworthy as a count.**

- Some providers expose a count endpoint; others require paginating raw tweets and
  counting them yourself.
- Either way the number is **whatever their crawler managed to collect**, not what was
  posted. There is no way to distinguish "200 tweets existed" from "200 tweets were
  successfully scraped before the limit hit."
- **This is the disqualifying property** — see truncation below.

**Positives**
- Cheap relative to Enterprise (per-request or per-tweet pricing).
- Claim full-archive reach back to 2006.
- Currently maintained.

**Drawbacks**
- **Truncation is disqualifying for a frequency study.** X's search endpoints paginate and
  cap results per session, and crawlers hit rate limits. Every day whose true volume
  exceeds the ceiling returns *the ceiling*. A quiet day (200 tweets) and an earnings-day
  explosion (20,000) can both come back as ~1,000. **The series saturates exactly where
  the signal lives**, and the result looks clean while being wrong.
- **Inherits X's deletion decay** — they scrape the same live index.
- **Coverage is opaque and changes silently.** No published methodology, no way to audit.
- If crawl coverage varies over time, the measured variable *is* the provider's scraping
  history rather than public attention — a coverage trend would present as a beautiful,
  entirely spurious signal.

**Error profile:** unmeasurable, **non-linear censoring at the top of the distribution**,
plus inherited deletion bias.

---

## Option D — Published tweet-ID datasets

Zenodo, Harvard Dataverse, GWU TweetSets, HuggingFace, Kaggle, ICWSM data challenges.

**Mechanism.** Researchers publish corpora from past studies. X's terms permit
redistributing **tweet IDs only**, not tweet content.

### Raw tweet count available?

**Effectively no, for two compounding reasons.**

1. **Rehydration required.** Datasets ship as bare tweet IDs. Turning them into countable
   tweets means calling the X API for each ID — which needs API access you don't have,
   and re-introduces deletion decay (deleted tweets return 404). Counting IDs without
   rehydrating counts *tweets that once existed in that collection*, which may be usable
   but is not a count of tweets about your topic.
2. **Universe mismatch.** You inherit whatever query, period, and language filter the
   original authors chose. A dataset built for, say, US election discourse contains no
   usable SK Hynix series regardless of size.

**Positives**
- Free and citable.
- Captured at the time, so the ID list itself predates deletion.

**Drawbacks**
- Unlikely any existing dataset targets SK Hynix specifically.
- Rehydration gate makes the content inaccessible without API access.
- Period and query definition are fixed by someone else.

**Verdict:** worth one search, low expected yield. Not a primary candidate.

---

## Comparison

| | Raw tweet count? | Mechanism | Variance | Bias | Auditable | Cost |
|---|---|---|---|---|---|---|
| **A. Official API** | **Yes — exact integer** | Server-side count over live index | Low | Downward, age-dependent, lumpy | Partly | ~$42k/mo |
| **B. IA Spritzer** | **No — 1% sample, scaled ×~100** | You count raw tweets yourself | **High** (Poisson) | **~None** | **Fully** | Free |
| **C. Resellers** | Nominally, but untrustworthy | Query their scrape | Unknown | **Censors peaks** | No | Low |
| **D. ID datasets** | No — needs rehydration | Someone else's ID list | n/a | n/a | Partly | Free |

**Ranking rationale.** For a research finding, **bias is more dangerous than variance.**
Noise costs statistical power and is visible in advance. Bias produces a confident,
publishable-looking number that is false.

Note the tension this creates: **the only option that gives a true count (A) is also
biased and unaffordable; the only affordable unbiased option (B) cannot give a true
count.** There is no option that is simultaneously free, exact, and unbiased.

**Practical ordering:**
1. **B** — free, unbiased, auditable. Costs statistical power, not validity. The working
   default unless the base-rate probe kills it.
2. **A** — best raw measurement, priced out, and needs a control series to be trusted.
3. **D** — cheap to check, unlikely to yield anything.
4. **C** — not recommended. Cheapness does not compensate for uncorrectable censoring.

---

## The measurement that settles this

Everything hinges on the **SK Hynix base rate**, currently unknown.

Pull a few days of IA Spritzer (not a full month — tens of GB), count matches on
`SK Hynix` / `SK하이닉스` / `000660`, multiply by 100. Sample one quiet day, one earnings
day, one HBM-news day.

- **>2,000/day** → Option B viable, build it.
- **~200/day** → daily resolution is dead on a 1% sample; Phase 1 needs weekly buckets,
  a wider query, or the paid route.

Costs an afternoon and converts the decision from speculation into arithmetic.
**Do this before writing anything else.**

---

## Open decisions

1. Tweet source — A–D above. Blocked on the base-rate probe.
2. Query definition: English vs. Korean vs. cashtag; include or exclude retweets.
3. Sample period, driven by whichever source is chosen.

## Known unverified claims in this document

Flagged so they are not mistaken for established fact:
- SK Hynix tweet base rate (gates Option B viability entirely).
- Post-2023 IA sample-stream collection characteristics vs. the original Stream Grab.
- Whether any published tweet-ID dataset covers SK Hynix.
- Korean-language coverage depth for every option.

## References

- Kergl, Roedler, Seeber (2014), *On the endogenesis of Twitter's Spritzer and Gardenhose
  sample streams*, IEEE/ACM ASONAM
- Pfeffer et al. (2018), *Tampering with Twitter's Sample API*, EPJ Data Science
- [X Full-Archive Search docs](https://docs.x.com/x-api/posts/search/quickstart/full-archive-search)
- [Archive Team Twitter Stream Grab](https://archive.org/details/twitterstream)
