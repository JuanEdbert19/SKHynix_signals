# Data Sources — Price Data

Options for daily OHLCV on SK Hynix (`000660.KS`) and the KOSPI index.
Status: **pykrx recommended, not yet implemented.**

Last reviewed: 2026-08-02.

---

## Options

All free.

| Source | Provides | Notes |
|---|---|---|
| **pykrx** | Official KRX scrape — OHLCV, market cap, investor-type flows (foreign / institutional / retail net buying), short-selling volume | Recommended primary. The flow columns enable a sharper later question: does tweet volume predict *retail* net buying? |
| **FinanceDataReader** | OHLCV, KRX + global exchanges | Fine as a cross-check |
| **yfinance** | `000660.KS` OHLCV, `^KS11` (KOSPI) | Convenient for the index. `Adj Close` dividend adjustment differs from KRX convention — do not mix adjusted and unadjusted series |

## Recommendation

**pykrx as primary.** Pull KOSPI at the same time so the raw-vs-market-excess return
question stays open rather than being foreclosed by what was downloaded.

Cross-check ~20 random days against yfinance once, then stop thinking about it.

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

1. Raw vs. KOSPI-excess returns.
2. Sample period — will be driven by whichever tweet source is chosen, not by price
   availability (price history is effectively unlimited for this ticker).
3. Which adjustment convention.

## References

- [pykrx](https://github.com/sharebook-kr/pykrx)
- [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader)
