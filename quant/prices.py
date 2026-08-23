"""Daily OHLCV for SK Hynix and the KOSPI index.

The index of every frame returned here is a timezone-naive DatetimeIndex of KRX
trading dates (KST). That is the join key for the whole project — signals are
mapped onto it by quant.align, which is the only module that touches timezones.
"""

import re

import numpy as np
import pandas as pd

from quant.cache import CACHE_DIR, cached

HYNIX = "000660"   # KRX ticker, for pykrx
KOSPI = "^KS11"    # yfinance symbol for the KOSPI index level

# Symbols reach load_quote from a free-text box in the dashboard and are
# interpolated into a cache filename, so they are checked before use.
_SYMBOL = re.compile(r"^[A-Za-z0-9.^=-]{1,15}$")

_COLS = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
}


def _clean(df):
    df = df.rename(columns=_COLS)
    df = df[[c for c in ("open", "high", "low", "close", "volume") if c in df.columns]]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    # KRX reports suspended/halted sessions as zero rows; they are not prices.
    return df[df["close"] > 0].sort_index()


def load_prices(ticker=HYNIX, start="2019-01-01", end="2026-08-06"):
    """Daily OHLCV for a KRX-listed stock."""
    path = CACHE_DIR / f"prices_{ticker}_{start}_{end}.parquet"

    def fetch():
        from pykrx import stock

        raw = stock.get_market_ohlcv_by_date(
            start.replace("-", ""), end.replace("-", ""), ticker
        )
        return _clean(raw)

    return cached(path, fetch)


def _load_yf(symbol, start, end, prefix):
    """Daily OHLCV for any yfinance symbol, cached under `prefix`."""
    if not _SYMBOL.match(symbol):
        raise ValueError(f"invalid symbol {symbol!r}")
    path = CACHE_DIR / f"{prefix}_{symbol}_{start}_{end}.parquet"

    def fetch():
        import yfinance as yf

        raw = yf.download(symbol, start=start, end=end, progress=False,
                          auto_adjust=False)
        # yfinance answers an unknown symbol with an empty frame rather than an
        # error, and cached() would write that emptiness to parquet and serve it
        # forever. Raising keeps a typo out of the cache.
        if raw.empty:
            raise ValueError(f"no data for {symbol!r} over {start}..{end}")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(-1)
        raw = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        raw.index = pd.DatetimeIndex(raw.index).tz_localize(None).normalize()
        raw.index.name = "date"
        return raw[raw["close"] > 0].sort_index()

    return cached(path, fetch)


def load_index(symbol=KOSPI, start="2019-01-01", end="2026-08-06"):
    """Daily OHLCV for the KOSPI index, via yfinance.

    Not pykrx: its index endpoint now requires KRX account credentials
    (KRX_ID / KRX_PW) and fails without them. yfinance's ^KS11 needs no auth and
    matches the KRX calendar to within a couple of days over 2019-2026 — days it
    lacks simply produce a NaN excess return, which the panel drops.

    This is the index *level*, deliberately, not a futures or ETF price — those
    carry their own basis and trading hours.
    """
    return _load_yf(symbol, start, end, "index")


def load_quote(symbol, start="2019-01-01", end="2026-08-06"):
    """Daily OHLCV for a comparison ticker — KRX (`005930.KS`) or US (`NVDA`).

    Dashboard charting only. These series are not aligned to KRX sessions by
    quant.align, so they must not be used as a signal or a target without going
    through it first.
    """
    return _load_yf(symbol, start, end, "quote")


def rebase(s, base=100.0):
    """Index a price series to `base` at its first observed value.

    Anchored on the first non-NaN value, not iloc[0]: a US ticker reindexed onto
    the KRX calendar can start on a US holiday, which would otherwise make the
    whole line NaN.
    """
    seen = s.dropna()
    if seen.empty or seen.iloc[0] == 0:
        return pd.Series(np.nan, index=s.index, name=s.name)
    return s / seen.iloc[0] * base


def trading_days(px):
    """The KRX trading calendar, taken from the price data itself."""
    return px.index
