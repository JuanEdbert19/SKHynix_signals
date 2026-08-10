# Data Sources — Price Data

Options for daily OHLCV on SK Hynix (`000660.KS`) and the KOSPI index.
Status: **implemented in `quant/prices.py`** — pykrx for the stock, yfinance for the
index (see the correction below).

Last reviewed: 2026-08-08.

---

## Options

All free.

| Source | Provides | Notes |
|---|---|---|
| **pykrx** | Official KRX scrape — OHLCV, market cap, investor-type flows (foreign / institutional / retail net buying), short-selling volume | Recommended primary. The flow columns enable a sharper later question: does tweet volume predict *retail* net buying? |
| **FinanceDataReader** | OHLCV, KRX + global exchanges | Fine as a cross-check |
| **yfinance** | `000660.KS` OHLCV, `^KS11` (KOSPI) | Convenient for the index. `Adj Close` dividend adjustment differs from KRX convention — do not mix adjusted and unadjusted series |

## Recommendation — as implemented

**pykrx for the stock, yfinance for the index.** KOSPI is pulled alongside SK Hynix so
the raw-vs-market-excess question stays open rather than being foreclosed by what was
downloaded.

### Correction to the original recommendation

pykrx was recommended for *both* series. That is wrong for the index:
`get_index_ohlcv_by_date` now requires KRX account credentials (`KRX_ID` / `KRX_PW`)
and fails without them — the ticker-name lookup raises `KeyError: '지수명'`, then
`KRX 로그인 실패`. The **stock** OHLCV endpoint still works with no auth.

So `load_index` uses yfinance `^KS11` instead. It covers 1,862 days against SK Hynix's
1,865 over 2019-01-02 → 2026-08-06; the 3 missing days simply yield a NaN excess return,
which the panel drops. Revisit if KRX credentials become available — pykrx would give a
consistent single source and the KRX-official index level.

**Cross-check done.** `tests/test_framework.py::test_pykrx_matches_yfinance` compares 20
random days of pykrx close against yfinance `000660.KS` and passes within 1%. Marked
`slow`; run with `pytest -m slow`.

## Gotchas

- **pykrx returns KST-naive dates.** Timezone-tag everything on entry to the panel. This
  matters because tweet timestamps are UTC and the alignment bug it would cause is
  invisible in the output — see `data-sources.md` for why the tweet-day boundary has to
  be defined against the 15:30 KST close.
- **Adjusted vs. unadjusted close.** yfinance's `Adj Close` and KRX's own adjustment
  convention are not the same. Pick one and use it consistently; state which in the
  analysis.
- KRX regular session is 09:00–15:30 KST. Holidays and halts leave gaps in the trading
  calendar that the tweet series (24h, 365d) does not have.

## Open decisions

1. Raw vs. KOSPI-excess returns. Both are implemented as selectable targets
   (`fwd_ret` / `fwd_exret`) so the decision is not foreclosed. **`fwd_exret` assumes
   β=1**, which is optimistic for a high-beta semiconductor name (realistically
   1.2–1.4) — a rolling-regression beta would be more correct but requires choosing an
   estimation window. Raw is the primary target for now.
2. Sample period — will be driven by whichever tweet source is chosen, not by price
   availability (price history is effectively unlimited for this ticker).
3. Which adjustment convention.

## Note on KOSPI self-inclusion

SK Hynix is roughly 8% of the KOSPI, so the excess return is about
`0.92 × (r_hynix − r_others)`. This is a shrink by a **constant factor**: it changes the
interpretation of coefficient magnitudes but leaves correlations and t-statistics
unaffected, so it does not hurt detectability.

## References

- [pykrx](https://github.com/sharebook-kr/pykrx)
- [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader)
