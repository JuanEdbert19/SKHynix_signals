"""Parquet cache shared by every data loader.

Cache key is entirely the filename, so callers construct paths that encode all
parameters affecting the result.
"""

from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"


def cached(path, fetch):
    if path.exists():
        return pd.read_parquet(path)
    df = fetch()
    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(path)
    return df
