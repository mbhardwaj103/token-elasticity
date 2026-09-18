"""AI user share (% of working-age population using generative AI), from Microsoft's AI
Diffusion Report, retrieved via Our World in Data's grapher CSV (CC BY 4.0), which carries
the World aggregate and exact period-end dates. Falls back to the Microsoft GitHub CSV
(countries only) and data/manual/global_adoption.csv (world) when OWID is unavailable.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from pipeline.common import MANUAL, http_get, latest_raw, save_raw_bytes

WORLD = "World"
_PERIOD_END = {"H1": (6, 30), "H2": (12, 31), "Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31)}


def _fetch(url: str, raw_name: str, cfg: dict, warnings: list[str], label: str) -> bytes:
    try:
        content = http_get(url, cfg).content
        save_raw_bytes(raw_name, content)
        return content
    except Exception as exc:
        fallback = latest_raw(raw_name)
        if fallback is None:
            raise
        warnings.append(f"{label}: live fetch failed ({exc}); using saved copy from {fallback.parent.name}")
        return fallback.read_bytes()


def _read_csv(content: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):  # Microsoft's CSV is not always UTF-8
        try:
            return pd.read_csv(io.BytesIO(content), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("unreadable CSV encoding")


def _owid(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    df = _read_csv(_fetch(cfg["microsoft"]["owid_csv"], "owid_ai_user_share.csv", cfg, warnings, "OWID AI user share"))
    df = df.rename(columns={"entity": "country", "day": "date", "ai_user_share": "value"})
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "country", "value"]].dropna()


def _period_end(label: str) -> pd.Timestamp | None:
    mt = re.search(r"(H[12]|Q[1-4]) (\d{4})", label)
    if not mt:
        return None
    month, day = _PERIOD_END[mt.group(1)]
    return pd.Timestamp(year=int(mt.group(2)), month=month, day=day)


def _microsoft_github(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    df = _read_csv(_fetch(cfg["microsoft"]["diffusion_csv"], "ms_ai_diffusion.csv", cfg, warnings, "Microsoft diffusion CSV"))
    col = df.columns[0]
    long = df.melt(id_vars=col, var_name="period", value_name="raw").rename(columns={col: "country"})
    long["date"] = long["period"].map(_period_end)
    long["value"] = pd.to_numeric(long["raw"].astype(str).str.rstrip("%"), errors="coerce")
    return long.dropna(subset=["date", "value"])[["date", "country", "value"]]


def adoption(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    """Long frame: date, country (incl. 'World'), value (%)."""
    try:
        df = _owid(cfg, warnings)
        if (df["country"] == WORLD).any():
            return df.sort_values(["country", "date"]).reset_index(drop=True)
        warnings.append("OWID CSV has no World row; using Microsoft CSV + manual world figures")
    except Exception as exc:
        warnings.append(f"OWID AI user share unavailable ({exc}); using Microsoft CSV + manual world figures")
    countries = _microsoft_github(cfg, warnings)
    world = pd.read_csv(MANUAL / "global_adoption.csv", parse_dates=["date"])[["date", "value"]].assign(country=WORLD)
    return pd.concat([countries, world], ignore_index=True).sort_values(["country", "date"]).reset_index(drop=True)
