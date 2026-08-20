# Data Sources — Tweet Count per Topic

Options for obtaining **daily tweet counts mentioning SK Hynix**. Nothing else.

Status: **no tweet source is currently obtainable.** As of 2026-08-20 every option is
blocked, priced out, or disqualified — see the ranking at the end. This is a change from
the previous review, which treated Option B as a free working default.

Sentiment-vendor products (MarketPsych, RavenPack, Bloomberg, Brandwatch, Sometrend) are
deliberately excluded — they are sentiment/media-analytics products, not tweet-count
sources.

Last reviewed: 2026-08-20 (Option B re-verified against the live Internet Archive API;
findings below are reproducible with the commands given in each section).

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

> **BLOCKED as of 2026-08-20.** The collection is no longer anonymously downloadable.
> Everything below the mechanism description is retained because the analysis is still
> correct *if* access is ever restored — but it cannot currently be executed.

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
- You count matches yourself, then scale to estimate the true daily count.
- **The scaling factor is ~105, not 100.** Sequiera & Lin (2017) compared the IA capture
  for Feb–Mar 2013 against a dedicated purpose-built crawler over the identical period:
  246,615,368 tweets vs 259,035,603, i.e. the archive holds **95.2%** of what a dedicated
  spritzer consumer received. Content overlap was ~95%. This is the only published
  measurement of the archive's capture efficiency and it is period-specific — the rate
  drifts, see the volume anomalies below.
- The estimate carries Poisson error — see the table below. It is an *estimate with a
  known error distribution*, not a measurement.

So: raw *tweets* yes (1% of them), true *count* no.

---

### BLOCKER 1 — the collection now requires authentication

Verified 2026-08-20. Every item in `collection:twitterstream` carries
`access-restricted-item: true`, and anonymous requests fail:

| Endpoint | Result |
|---|---|
| `archive.org/download/<item>/<day>.tar` | **401** |
| `ia601501.us.archive.org/2/items/<item>/<day>.tar` (direct node) | **403** |
| `archive.org/download/<item>/<item>_archive.torrent` | **401** |
| `view_archive.php` (tar member listing) | **403** |
| `archive.org/metadata/<item>` | 200 — metadata is still open |

A control fetch against an unrestricted IA item succeeds from the same host, so this is
collection access control, not a network or rate-limit artifact. Reproduce with:

```bash
curl -sIL "https://archive.org/download/archiveteam-twitter-stream-2022-03/twitter-stream-20220301.tar"
curl -s "https://archive.org/metadata/archiveteam-twitter-stream-2022-03" | grep -o 'access-restricted-item[^,]*'
```

The restriction is recent. Item reviews on `archiveteam-twitter-stream-2023-01` record it:
"Why are the files locked? I was able to download them last year" (2025-01-31); "These were
available for download via torrent last year but they're no longer available" (2025-03-06).
The Archive Team wiki now describes the collection as "rather useless now that IA restricted
the access, since it's not WARCs."

**Whether a free archive.org account lifts the 401 is UNVERIFIED.** `access-restricted-item`
is normally a login gate rather than a dark flag (`is_dark` is not set), so a plain account
may suffice — but this was not testable here and should not be assumed. Torrents are not a
workaround: they 401 as well, and reported live swarms exist for only four months
(2022-03, 2022-04, 2022-05, 2023-01).

### BLOCKER 2 — the archive stops at 2023-01-30

The last item is `archiveteam-twitter-stream-2023-01`; `-2023-02` and everything later do
not exist. The final day file is `twitter-stream-20230130.tar` — there is no `20230131`.
The grab therefore ended roughly two weeks **before** Twitter killed free API access
(announced 2023-02-02), not because of it.

A successor collection exists — `collection:twitterarchive`, still producing items daily
through 2026 — but it is **unusable for this purpose**: WARC web-crawl data
(`mediatype: web`), not line-delimited JSON, with every data file marked `private: true`,
`access-restricted-item: true`, and 403 on download. Volume is also ~53 GB per item at
~18 items/day.

**Consequence for this project:** price data runs to 2026-08, so the maximum overlap is
2019-01 → 2023-01. That excludes the entire HBM/AI cycle — the period in which SK Hynix
attention is most likely to carry information.

### BLOCKER 3 — volume

One tar per day, individually addressable (good for incremental fetching), but:

| Year | GB/day | Year total |
|---|---|---|
| 2019 | ~2.0 | 506 GB |
| 2020 | — | 1,284 GB |
| 2021 | ~2.4–2.8 | 787 GB |
| 2022 | ~2.7–3.0 | 940 GB |
| 2023-01 | ~2.5 | 84 GB |

| Candidate sample | Trading days | Download |
|---|---|---|
| 2019-01 → 2023-01 | ~1,000 | **3,600 GB** |
| 2021-01 → 2023-01 | ~500 | 1,811 GB |
| 2022-01 → 2023-01 | ~260 | 1,024 GB |

Reproduce with the `advancedsearch.php` API filtered to `collection:twitterstream`,
summing `item_size`.

Note the 2019 → 2020 jump (506 → 1,284 GB annually). **That shift is far larger than any
plausible attention signal**, so the archive's own daily total is not optional — it is the
capture-rate denominator, and any un-normalised series would carry a collector artifact
that looks exactly like a trend in attention.

⚠️ `archiveteam-twitter-stream-2020-02` reports 478 GB with all 15 day-tars showing the
*identical* size 31,898,490,880 — corrupt size metadata, not real data. Do not include it
in any volume estimate.

### BLOCKER 4 — 125 missing days, in blocks

Enumerated by parsing the embedded date out of every day-file name across all items
(reproducible via `/metadata/<item>` → `files[].name`). Between 2018-11-01 and 2023-01-31,
1,430 day-tars exist and **125 calendar days are absent**:

| Gap | Days |
|---|---|
| 2018-12-09 → 12-23 | 15 |
| 2019-01-04 → 01-08, 01-11 → 01-12 | 7 |
| 2019-03-24 → 03-27 | 4 |
| 2019-09-14 → 09-15 | 2 |
| 2019-10-14 → 10-22 | 8 |
| 2020-02 (scattered) | 14 |
| 2020-07-05 | 1 |
| **2021-01-07 → 01-24** | **18** |
| **2021-04-11 → 04-26** | **16** |
| 2021-07-06 | 1 |
| **2022-11-23 → 12-11** | **19** |
| **2022-12-13 → 12-31** | **19** |
| 2023-01-31 | 1 |

Visible in the item sizes before downloading anything: `2021-01` is 26.3 GB and `2021-04`
is 29.1 GB against ~70–85 GB for their neighbours.

**Why blocks are worse than scattered gaps.** A rolling z-score baseline spanning a
19-day hole is computed from the wrong period, and every overlapping forward-return window
that straddles a hole is malformed. These are not 125 lost observations; they are four
regions where the signal construction is invalid, plus their surrounding windows.

Part of the 2022-11/12 gap may be recoverable: `archiveteam-twitter-stream-2022-12`
contains exactly one file, `twitter-stream-20221212.tar.gz` at 47.5 GB — named for a single
day but ~19× a normal day, so it plausibly holds much of Nov 23 – Dec 31. Unverifiable
without access.

### BLOCKER 5 — five container formats and mislabeled items

The identifier convention (`archiveteam-twitter-stream-YYYY-MM`) is stable. The contents
are not:

| Era | Inner naming | Container |
|---|---|---|
| 2012-01 … 2018-04 | `archiveteam-twitter-stream-2018-01.tar` | one monolithic TAR per month |
| 2018-04 … 2018-10 | `twitter-2018-06-06.tar` | daily TAR |
| 2018-11 … 2020-12 | `twitter_stream_2019_05_01.tar` (**underscores**) | daily TAR |
| 2021-01 … 2021-08-22 | `twitter-stream-2021-08-01.zip` | **daily ZIP** |
| 2021-08-23 … 2023-01 | `twitter-stream-20210823.tar` (compact date) | daily TAR |
| 2022-12 | `twitter-stream-20221212.tar.gz` | one 47.5 GB TAR.GZ for the month |

`archiveteam-twitter-stream-2021-08` contains the switch mid-item: 22 `.zip` files then
9 `.tar` files.

**Item identifiers do not reliably describe their contents:**

- `archiveteam-twitter-stream-2018-10` contains October **2019**
- `-2018-11` contains both Nov 2018 and Nov **2019** (60 day-files)
- `-2018-12` contains both Dec 2018 and Dec **2019** (47 day-files)
- `-2019-08` contains Aug **and** Sep 2019 (59 files, 119.6 GB)
- There are no `-2019-09` … `-2019-12` items; that data is present but filed elsewhere

Any pipeline must index by parsing dates out of `files[].name` across **all** items, never
by trusting the identifier.

**Internal layout** is `MM/DD/HH/MM.json.bz2` — minute-granularity bzip2 NDJSON, ~1,440
members per day-tar. Useful property: the member path carries the timestamp, so bucketing
by time needs no JSON parsing. But inner compression is **not consistent** — `.bz2` is
documented for 2020 while `.gz` was observed for Nov 2022, and third-party parsers report
top-level-vs-nested layout differences across items. A reader must sniff magic bytes rather
than trust extensions.

### Tweet JSON, if this is ever revisited

Line-delimited Twitter v1.1 `statuses/sample` objects. Text resolution:
`obj.get("retweeted_status", obj)` → `extended_tweet.full_text` → `full_text` → `text`
(`text` is 140-truncated when `truncated == true`). Timestamps: prefer `timestamp_ms`
(epoch ms, unambiguous) over `created_at` (`"%a %b %d %H:%M:%S %z %Y"`, always `+0000`).
Retweets are identified by the presence of `retweeted_status`, **not** the `retweeted`
boolean (which reflects the authenticating user and is effectively always false in stream
data). Quote tweets are a distinct case (`quoted_status` / `is_quote_status`).

Non-tweet envelope lines are interleaved and must be skipped: `delete` (very common),
`limit`, `scrub_geo`, `status_withheld`, `user_withheld`, `disconnect`, `warning`, and
blank keep-alive lines. Safe filter: treat a line as a tweet only if the parsed object has
both `id_str` and `user`. Budget for truncated final members — the grabber was killed
mid-write at times.

### Original assessment (retained)

**Positives**
- **Free.** — *no longer true in practice; see Blocker 1.*
- **Immune to deletion decay.** Tweets were captured as posted, so a post deleted in 2023
  is still in the 2021 file. This advantage is real and now quantified: Sequiera & Lin
  tracked the 2013 collection forward and found **18.5% of tweets deleted within four
  years** (259.0M → 211.0M), with deletions still arriving years after posting. Any
  live-index source (Option A, Option C) inherits that bias; this one does not.
- **Sampling error is unbiased** — symmetric noise, not a trend. It cannot manufacture a
  signal. It attenuates regression coefficients toward zero (classical measurement error),
  costing statistical power but not validity.
- **Fully auditable.** You can measure the gaps yourself.
- **You control the matcher** — transparent substring matching on `SK하이닉스` in your own
  code rather than an uninspectable tokenizer.
- Sampling happens upstream of any notion of the query, so it cannot be biased toward or
  against our topic.

**Drawbacks**
- **Poisson noise scales badly at low base rates.** Observed ≈ `Poisson(0.0095 × N)`:

  | True tweets/day | Observed | Std dev | Relative noise |
  |---|---|---|---|
  | 5,000 | 48 | 6.9 | 14% |
  | 2,000 | 19 | 4.4 | 23% |
  | 500 | 5 | 2.2 | 46% |
  | 200 | 2 | 1.4 | 72% |

  Below ~1,000 true tweets/day this stops being a measurement.
- **Automation bias.** Bots and scheduled posts fire at clustered milliseconds rather than
  arbitrary ones, so automated content is over- or under-represented. Roughly constant
  *level* distortion — shifts the baseline, does not create day-to-day signal.
- Deterministic public rule means the sample is manipulable in principle (Pfeffer et al.).
- **Storage/compute.** See Blocker 3.

**Error profile:** high variance, **near-zero bias**, hard gaps — and currently inaccessible.

### Short-window feasibility (added 2026-08-20)

The volume blocker above assumes a multi-year sample. For a **2–3 month** window the
arithmetic changes completely — but the access blocker does not, since the 401 is
per-request, not per-byte. Shrinking the ask makes Option B *affordable*, not *accessible*.

Gap-free candidate windows, chosen against the gap table above:

| Window | GB/day | Total | Notes |
|---|---|---|---|
| **2019-06-01 → 08-31** | ~2.0 | **~184 GB** | cheapest; contains the July 2019 Japanese export controls on photoresist and hydrogen fluoride, aimed squarely at Korean chipmakers — large, genuinely semiconductor-specific attention variation |
| 2021-09-01 → 11-30 | ~2.6 | ~239 GB | quiet period |
| 2022-08-01 → 10-31 | ~2.8 | ~258 GB | memory downturn; SK Hynix Q3 capex cut announced late Oct |

All three avoid every gap listed above. Note that `-2019-08` is one of the mislabeled items
(it contains August *and* September 2019), so a fetcher must still index by filename.

**Statistical caveat, which is not optional.** 2–3 months is ~40–60 trading days. Against
the power table at the top of this document (`n ≈ 7.85 / ρ²`), 60 days detects only
**ρ ≈ 0.36 or larger**, while realistic attention effects run 0.05–0.15. Such a sample will
return "no significant relationship" whether or not an effect exists, and that null is
uninformative — the test never had power to find anything.

This does not make a short window pointless: it is sufficient to demonstrate the pipeline
end to end (alignment correct, signal flowing through the harness, numbers reproducible).
It is not sufficient to answer the research question, and any writeup must say so
explicitly rather than presenting an underpowered null as a finding.

**Mandatory diagnostic if access is ever restored**
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

| | Raw tweet count? | Mechanism | Variance | Bias | Auditable | Cost | Obtainable now? |
|---|---|---|---|---|---|---|---|
| **A. Official API** | **Yes — exact integer** | Server-side count over live index | Low | Downward, age-dependent, lumpy | Partly | ~$42k/mo | Priced out |
| **B. IA Spritzer** | No — 1% sample, scaled ×~105 | You count raw tweets yourself | **High** (Poisson) | **~None** | **Fully** | Free* | **No — 401** |
| **C. Resellers** | Nominally, but untrustworthy | Query their scrape | Unknown | **Censors peaks** | No | Low | Yes, but disqualified |
| **D. ID datasets** | No — needs rehydration | Someone else's ID list | n/a | n/a | Partly | Free | Gated behind A |

\* free only if an archive.org account clears `access-restricted-item`, which is unverified.

**Ranking rationale.** For a research finding, **bias is more dangerous than variance.**
Noise costs statistical power and is visible in advance. Bias produces a confident,
publishable-looking number that is false.

The tension previously recorded here — that the only exact source (A) is biased and
unaffordable while the only unbiased source (B) cannot give a true count — has since
resolved in the worst direction: **B is no longer obtainable either.**

**Practical ordering as of 2026-08-20:**

1. **B** — still the best design if access is restored. Blocked on an account test that
   costs minutes. Even if unblocked, it carries ~3.6 TB, 125 missing days across four
   multi-week blocks, five container formats, and a hard 2023-01 cutoff.
2. **A** — best raw measurement, priced out, and needs a control series to be trusted.
   The deletion bias is now quantified at ~18.5% over four years (Sequiera & Lin 2017).
3. **D** — cheap to check, unlikely to yield anything, and rehydration needs A.
4. **C** — not recommended. Cheapness does not compensate for uncorrectable censoring.

**Conclusion: there is currently no free route to historical tweet counts.** This is a
change of status, not a change of preference.

---

## The measurement that was supposed to settle this

The previous review specified a base-rate probe: pull a few days of IA Spritzer, count
matches on `SK Hynix` / `SK하이닉스` / `000660`, scale up, and compare against a 2,000/day
threshold. **That probe is not currently executable** — it requires the access described
in Blocker 1.

It is retained as the correct first step if Option B reopens. Note one refinement: the scan
cost is in decompressing tweets, not in matching them, so a single pass should count every
candidate term at once (English/Korean/Japanese/Chinese variants, SK Hynix terms, a matched
control such as Samsung, and the mandatory total-lines denominator). That converts the
base-rate question from an assumption into a measurement without a second download.

---

## Out of this document's original scope: free attention sources

This document is deliberately about tweet counts. This section is recorded here anyway
because it is the direct consequence of every tweet option closing — these were measured on
2026-08-20 while establishing that tweets are unobtainable, and the comparison is only
meaningful next to the options above.

**Status: Wikimedia pageviews were ADOPTED on 2026-08-20** and are implemented in
`quant/wiki.py` as the signals `wiki_hynix` / `wiki_semi` / `wiki_hbm`. All three read null
against 3-day forward returns; see CLAUDE.md Status. Every other entry below remains
analysis only. Each is a measured fact plus the command that produced it. Adopting any of these would change the project's research question from *Twitter
activity* to *attention* more broadly, which must be stated explicitly rather than
substituted quietly.

### What each source is

**GDELT** (Global Database of Events, Language, and Tone). A project that has machine-read
world news since 2015 in 100+ languages, republishing every 15 minutes. Free, no key.
`mode=timelinevol` returns, per day, **the fraction of all monitored articles mentioning a
query**. This is *news* attention — journalists writing — not social attention. Being a
share rather than a count makes it self-normalising against archive growth, which is a real
advantage over the raw-count sources above.

**Wikimedia pageviews.** The official Wikipedia analytics API: how many people opened a
given article on a given day, with `agent=user` excluding known spiders. A **census** —
every view counted, none sampled — so unlike Option B there is no sampling error and no
scaling factor at all.

**Google Trends.** Google's public window onto its own search volume. It will not return a
raw search count under any circumstances; it returns a **0–100 index rescaled within the
requested window**, so the peak of each request is always exactly 100 and two requests are
not on a common scale. No official API exists — `pytrends` is an unofficial wrapper around
the internal endpoint.

**Naver DataLab.** The same concept for Naver, South Korea's dominant search engine at
roughly 60% share. For a KRX-listed stock traded largely by Korean retail investors this is
closer to the relevant audience than Google is. Free, but requires a key.

**Reddit / Pushshift.** Reddit is the forum; Pushshift was the independent archive
researchers relied on for years. Reddit cut Pushshift off in 2023 and restricted it to
moderators.

**StockTwits.** A Twitter-like network built specifically for traders, with ticker-tagged
posts — conceptually the best fit for this project's question of anything on this page.

**Bluesky.** The Twitter alternative, with a genuinely open API and no scraping
restrictions. Launched 2023 and only grew large in 2024, so it has no history covering most
of the price sample.

**Hacker News** (via Algolia's free search API). Tech-news aggregator.

**DART** (`opendart.fss.or.kr`). South Korea's official corporate filing system, the
Korean counterpart to SEC EDGAR. Not attention data — useful for exact event timestamps, to
separate news-driven attention from spontaneous attention.

### Confirmed working — free, no authentication

**Wikimedia pageviews** — whole series retrieved in seconds:

| Article | Days | Coverage | Mean/day | Median | Max |
|---|---|---|---|---|---|
| `en:SK_Hynix` | 2,775 | 2019-01-01 → 2026-08-06 | 383 | 304 | 10,879 |
| `en:Semiconductor` | 2,775 | same | 1,755 | 1,747 | 7,081 |
| `en:High_Bandwidth_Memory` | 2,775 | same | 343 | 303 | 1,830 |
| `ko:SK하이닉스` | 2,775 | same | 75 | 62 | 1,299 |
| `ko:반도체` | 2,775 | same | 124 | 114 | 568 |
| `ko:삼성전자` | 2,775 | same | 229 | 212 | 1,867 |

**Zero missing days; 100% calendar coverage of the price sample.** Daily granularity only —
the per-article *hourly* endpoint returns HTTP 400. A UTC day is complete before the
06:30 UTC KRX close, so labelling each day's count at its closing edge and letting
`quant.align` attribute it to the next session is correct and carries no look-ahead; it
discards the 00:00–06:30 UTC window of the current day. Monthly aggregates and an
edits-per-page series (161 rows for `en:SK_Hynix`) are also available; edits are far too
sparse for a daily signal but work as a free event detector.

Signals are distinct, not redundant — correlation of daily log-changes: `ko:SK하이닉스` vs
`ko:반도체` = **0.30**, vs `ko:삼성전자` = **0.42**.

**GDELT DOC 2.0** — daily granularity confirmed at *both* ends of the price sample:
91 daily points for 2019-01-01→2019-04-01, 89 for 2026-05-01→2026-08-01. Mean intensity for
`"SK Hynix"` was **0.0101 in Q1 2019 vs 0.1042 in mid-2026**, a ~10× rise that is either the
HBM/AI cycle or an expansion of GDELT's source list — **indistinguishable without a control
series**, the same normalisation discipline Option B requires. Rate limit is **1 request per
5 seconds**, aggressively enforced: sustained querying earned an extended block that
persisted well beyond 30-second spacing.

### Confirmed working — with a disqualifying catch

**Google Trends** (`pytrends`). Granularity is chosen by Google from the window length, and
cannot be requested:

| Window | Rows returned | Granularity |
|---|---|---|
| 7.5 years | 92 | **monthly** |
| 7 months | 218 | daily |
| 90 days | 91 | daily |

So daily data over 2019–2026 is impossible in one call — it requires stitching ~30
overlapping windows and renormalising on the overlaps, since each window is independently
rescaled to 0–100.

Worldwide `"SK Hynix"` over 7.5 years returned **6 zero months, mean 4.3** — too small
globally to survive quantisation. Korean geo rescues it: `KR / SK하이닉스` at 90 days gives
mean 48.3 with no zeros; `KR / 반도체` gives 43.5. Also: **429 on the second call** of a
sequence, and `pytrends` is unmaintained — it fails immediately against urllib3 2.x
(`Retry.__init__() got an unexpected keyword argument 'method_whitelist'`) and needs its
retry config stripped to run at all.

### Tested and rejected

| Source | Result |
|---|---|
| **Reddit** `search.json` | **403** anonymous, browser UA included. Pushshift moderator-only since 2023 |
| **StockTwits** API | **403**, Cloudflare interstitial |
| **Bluesky** public AppView | **403** from this host; and no history before 2023 regardless |
| **Hacker News** (Algolia) | **200 — works**, but `"SK Hynix"` returns **137 stories total since 2019** (~1.6/month). Free and reliable, useless at daily resolution |

### Free but require registration

| Source | Probe result | Note |
|---|---|---|
| **Naver DataLab** | `401 Not Exist Client ID` — endpoint live | Highest-value untested source here: Naver is ~60% of Korean search, so it matches the audience that actually trades this stock. Same 0–100 index limitation as Google Trends |
| **DART** | `status 010, unregistered key` — endpoint live | Event timestamps, not attention |

### The axis that matters

The property that disqualified Option B for a company-specific query was **sample vs
census**:

| Source | Measurement type | Daily, 2019–2026? | Auth |
|---|---|---|---|
| Wikimedia pageviews | **true count** | yes, zero gaps | none |
| GDELT | share of news coverage | yes | none |
| Google Trends | 0–100 index, per-window rescaled | only via ~30 stitched windows | none |
| Naver DataLab | 0–100 index | untested | free key |
| HN / Reddit / StockTwits / Bluesky | — | no | blocked or too sparse |

Only Wikipedia returns an actual number. Everything else is a normalised index whose scale
changes between requests — which the `zscore` transform tolerates, but the `raw` transform
and any coefficient interpretation do not.

### Reproduce

```bash
# Wikimedia pageviews (no auth)
curl -s -H "User-Agent: <contact>" \
  "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/SK_Hynix/daily/20190101/20260806"

# GDELT daily news volume (no auth; wait 5s+ between calls)
curl -s "https://api.gdeltproject.org/api/v2/doc/doc?query=%22SK%20Hynix%22&mode=timelinevol&startdatetime=20190101000000&enddatetime=20190401000000&format=json"

# Hacker News (no auth)
curl -s "https://hn.algolia.com/api/v1/search_by_date?query=%22SK%20Hynix%22&tags=story&numericFilters=created_at_i%3E1546300800"
```

Google Trends requires `pytrends` with its retry config removed; see the note above.

### Unverified in this section

- **GDELT earliest coverage date.** A 2015 window returned `Invalid query start date`, so
  the range starts later than 2015, but the exact start was not established — the extended
  rate-limit block prevented it. GDELT DOC 2.0 is documented as beginning 2017-01-01; not
  confirmed here.
- **GDELT Korean-language coverage.** The `SK하이닉스` query was not successfully run. This
  matters: if GDELT under-covers Korean media, the series measures Anglophone coverage of a
  Korean company, which is a materially weaker proxy.
- **Naver DataLab** beyond endpoint liveness — no key was obtained.
- Whether the Bluesky and StockTwits 403s are permanent policy or host-specific blocking.

---

## Open decisions

1. Tweet source — A–D above. **Now blocked on access, not on the base rate.** The cheapest
   next step is testing whether a free archive.org account lifts the 401 on Option B.
2. Whether to substitute an attention proxy for tweets at all, given no free tweet source
   exists. This is a change to the project's research question, not a data-source choice.
3. Query definition, if tweets ever become available: English vs. Korean vs. cashtag;
   include or exclude retweets.
4. Sample period, driven by whichever source is chosen.

## Known unverified claims in this document

Flagged so they are not mistaken for established fact:
- **Whether a free archive.org account lifts `access-restricted-item` on Option B.** Only
  anonymous failure was verified. This is the single highest-value open question here.
- SK Hynix tweet base rate — still unmeasured, and now unmeasurable without access.
- Contents of `twitter-stream-20221212.tar.gz` (47.5 GB) and the oversized
  `twitter-stream-20230130.tar` (11.7 GB); both are inferred from size anomalies.
- Which inner compression (`.bz2` vs `.gz`) applies to which era — third-party evidence
  conflicts, and no listing endpoint is reachable to check.
- Whether the pre-2018-04 monolithic monthly tars have internal day gaps.
- Whether any published tweet-ID dataset covers SK Hynix.
- Korean-language coverage depth for every option.

### Provenance note

Findings marked as verified on 2026-08-20 were obtained directly from
`archive.org/metadata/`, `archive.org/advancedsearch.php`, and HTTP status codes on
`archive.org/download/`, plus live calls to the Wikimedia pageviews API. The 125-day gap
enumeration and the container-format table were derived by parsing `files[].name` across
all `collection:twitterstream` items — reproducible through the metadata API, which remains
open even though downloads are not. Deletion and capture-rate figures are from the
published paper cited below, not measured here.

## References

- Kergl, Roedler, Seeber (2014), *On the endogenesis of Twitter's Spritzer and Gardenhose
  sample streams*, IEEE/ACM ASONAM
- Pfeffer et al. (2018), *Tampering with Twitter's Sample API*, EPJ Data Science
- Sequiera & Lin (2017), *Finally, a Downloadable Test Collection of Tweets*, SIGIR —
  source of the 95.2% capture rate and the 18.5%/4yr deletion figure.
  https://cs.uwaterloo.ca/~jimmylin/publications/Sequiera_Lin_SIGIR2017.pdf
- [X Full-Archive Search docs](https://docs.x.com/x-api/posts/search/quickstart/full-archive-search)
- [Archive Team Twitter Stream Grab](https://archive.org/details/twitterstream)
- [Archive Team wiki: Twitter](https://wiki.archiveteam.org/index.php/Twitter)
- [Twitter streaming message types](https://developer.twitter.com/en/docs/twitter-api/v1/tweets/filter-realtime/guides/streaming-message-types)
- [Wikimedia Pageviews API](https://wikimedia.org/api/rest_v1/#/Pageviews%20data)
