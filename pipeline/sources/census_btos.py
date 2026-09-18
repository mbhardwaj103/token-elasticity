"""US Census Business Trends and Outlook Survey (BTOS): share of businesses using AI.

Q7  "In the last two weeks, did this business use AI in any of its business functions?"
Q24 "During the next six months, do you think this business will be using AI ...?"
Released every two weeks; columns are period codes like 202618, mapped to reference
dates via the 'Collection and Reference Dates' sheet.
"""
from __future__ import annotations

import io

import pandas as pd

from pipeline.common import http_get, latest_raw, save_raw_bytes

ALL_US = "US"


def _download(cfg: dict, key: str, raw_name: str, warnings: list[str]) -> bytes:
    try:
        content = http_get(cfg["btos"][key], cfg).content
        save_raw_bytes(raw_name, content)
        return content
    except Exception as exc:
        fallback = latest_raw(raw_name)
        if fallback is None:
            raise
        warnings.append(f"Census BTOS {key}: live fetch failed ({exc}); using saved copy from {fallback.parent.name}")
        return fallback.read_bytes()


def _pct(v) -> float | None:
    s = str(v).strip()
    if not s.endswith("%"):
        return None  # "S" = suppressed, "." = not asked
    return float(s.rstrip("%"))


def _period_dates(xlsx: bytes) -> dict[str, pd.Timestamp]:
    d = pd.read_excel(io.BytesIO(xlsx), sheet_name="Collection and Reference Dates")
    d = d.dropna(subset=["Smpdt", "Ref End"])
    return {str(int(s)): pd.Timestamp(e) for s, e in zip(d["Smpdt"], d["Ref End"])}


def _extract(df: pd.DataFrame, question: int, dates: dict, group_col: str | None) -> pd.DataFrame:
    periods = [c for c in df.columns if str(c).isdigit()]
    sel = df[(pd.to_numeric(df["Question ID"], errors="coerce") == question) & (df["Answer"] == "Yes")]
    rows = []
    for _, r in sel.iterrows():
        group = ALL_US if group_col is None else str(r[group_col]).split(".")[0]
        for p in periods:
            val = _pct(r[p])
            if val is not None and str(p) in dates:
                rows.append({"date": dates[str(p)], "group": group, "value": val})
    return pd.DataFrame(rows)


def ai_use(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    """Long frame: date, group ('US' or NAICS code), metric ('use'|'expect'), value (%)."""
    nat = _download(cfg, "national_url", "btos_National.xlsx", warnings)
    sec = _download(cfg, "sector_url", "btos_Sector.xlsx", warnings)
    dates = _period_dates(nat)
    nat_df = pd.read_excel(io.BytesIO(nat), sheet_name="Response Estimates")
    sec_df = pd.read_excel(io.BytesIO(sec), sheet_name="Response Estimates")
    frames = []
    for metric, q in [("use", cfg["btos"]["question_use"]), ("expect", cfg["btos"]["question_expect"])]:
        for df, col in [(nat_df, None), (sec_df, "Sector")]:
            part = _extract(df, q, dates, col)
            part["metric"] = metric
            frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    wanted = {ALL_US, *map(str, cfg["btos"]["sectors"].keys())}
    return out[out["group"].isin(wanted)].sort_values("date").reset_index(drop=True)
