"""Daily OHLCV for SK Hynix and the KOSPI index.

The index of every frame returned here is a timezone-naive DatetimeIndex of KRX
trading dates (KST). That is the join key for the whole project — signals are
mapped onto it by quant.align, which is the only module that touches timezones.
"""

from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"

HYNIX = "000660"   # KRX ticker, for pykrx
KOSPI = "^KS11"    # yfinance symbol for the KOSPI index level

_COLS = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
}


def _cached(path, fetch):
    if path.exists():
        return pd.read_parquet(path)
    df = fetch()
    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(path)
    return df


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

    return _cached(path, fetch)


def load_index(symbol=KOSPI, start="2019-01-01", end="2026-08-06"):
    """Daily OHLCV for the KOSPI index, via yfinance.

    Not pykrx: its index endpoint now requires KRX account credentials
    (KRX_ID / KRX_PW) and fails without them. yfinance's ^KS11 needs no auth and
    matches the KRX calendar to within a couple of days over 2019-2026 — days it
    lacks simply produce a NaN excess return, which the panel drops.

    This is the index *level*, deliberately, not a futures or ETF price — those
    carry their own basis and trading hours.
    """
    path = CACHE_DIR / f"index_{symbol}_{start}_{end}.parquet"

    def fetch():
        import yfinance as yf

        raw = yf.download(symbol, start=start, end=end, progress=False,
                          auto_adjust=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(-1)
        raw = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        raw.index = pd.DatetimeIndex(raw.index).tz_localize(None).normalize()
        raw.index.name = "date"
        return raw[raw["close"] > 0].sort_index()

    return _cached(path, fetch)


def trading_days(px):
    """The KRX trading calendar, taken from the price data itself."""
    return px.index
