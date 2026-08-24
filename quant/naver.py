"""Daily Naver search-trend series as an attention signal.

Chosen over Wikipedia pageviews because of what each measures, not because of
the pageview null. A Wikipedia lookup is encyclopedic curiosity, and
ko:SK하이닉스 averages 75 views/day (median 62) — mostly integer quantization.
Naver is roughly 60% of Korean search, and the keyword groups here include
`주가` and the ticker, so what they capture is Korean retail investors looking
up a stock. That is the audience that trades this name.

NOT A COUNT. Each series is a 0-100 index rescaled to its own maximum within
the requested window, so levels are not comparable between files and `raw` is
meaningless as a transform. Only within-series abnormality is interpretable.
Resolution is nevertheless fine: 5 decimal places, 2,741 distinct values across
2,775 days, no zeros.

Acquired by hand from datalab.naver.com/keyword/trendSearch.naver, because the
REST API is closed to new applications — keys authenticate and the DataLab
scope is refused. The exact keywords and query permalinks are in
data-sources.md, which is what makes these files regenerable; they are not
committed. See that document before changing anything here.

Series are keyed by KST calendar date. Converting them to trading dates is
quant.align's job, not this module's.
"""

import pandas as pd

from quant.cache import CACHE_DIR

FILES = {
    "hynix": "hynix_datalab.xlsx",
    "semi": "semi_datalab.xlsx",
    "hbm": "hbm_datalab.xlsx",
    "memory": "memory_datalab.xlsx",
    "samsung": "samsung_datalab.xlsx",
}

# The export settings every file must share. These are hand-set toggles in a web
# UI, so a weekly export or a device-filtered one is a live failure mode rather
# than a hypothetical: it would load, align and regress without complaint.
REQUIRED = {"범위": "합계", "성별": "전체(여성,남성)", "연령대": "전체"}
SHEET = "개요"


def load_trend(key):
    """One Naver search-trend series, keyed by KST calendar date."""
    if key not in FILES:
        raise KeyError(f"unknown series {key!r}; available: {sorted(FILES)}")
    path = CACHE_DIR / FILES[key]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. These .xlsx files are downloaded by hand and gitignored — "
            "re-download using the query permalinks recorded in data-sources.md."
        )

    import warnings

    import openpyxl

    with warnings.catch_warnings():
        # Naver's export carries no default style block, which openpyxl warns
        # about on every load. Nothing here reads styles.
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        wb = openpyxl.load_workbook(path, data_only=True)
    rows = list(wb[SHEET].iter_rows(values_only=True))
    meta = {r[0]: r[1] for r in rows if r and r[0] and r[0] != "날짜"}

    for field, want in REQUIRED.items():
        if meta.get(field) != want:
            raise ValueError(
                f"{path.name}: {field} is {meta.get(field)!r}, expected {want!r} — "
                "re-export with the settings in data-sources.md"
            )
    if not str(meta.get("기간", "")).startswith("일간"):
        raise ValueError(
            f"{path.name}: 기간 is {meta.get('기간')!r}, expected a 일간 (daily) export"
        )

    head = next(i for i, r in enumerate(rows) if r and r[0] == "날짜")
    out = pd.Series(
        {pd.Timestamp(r[0]): float(r[1]) for r in rows[head + 1:] if r and r[0]},
        dtype="float64",
    ).sort_index()
    out.index.name = "date"
    return out.rename(key)
