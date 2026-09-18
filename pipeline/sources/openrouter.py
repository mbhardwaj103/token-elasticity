"""OpenRouter token volume and price sources (keyless).

Volume comes from the JSON endpoints behind openrouter.ai/rankings. They are undocumented,
so every response is saved under data/raw/<date>/ and the last good copy is reused if a
fetch fails.
"""
from __future__ import annotations

import json

import pandas as pd

from pipeline.common import http_get, latest_raw, save_raw_json


def _fetch_json(cfg: dict, path_key: str, raw_name: str, warnings: list[str]):
    url = cfg["openrouter"]["base_url"] + cfg["openrouter"][path_key]
    try:
        payload = http_get(url, cfg).json()
        save_raw_json(raw_name, payload)
        return payload
    except Exception as exc:  # network, JSON, or HTTP error
        fallback = latest_raw(raw_name)
        if fallback is None:
            raise
        warnings.append(f"OpenRouter {path_key}: live fetch failed ({exc}); using saved copy from {fallback.parent.name}")
        return json.loads(fallback.read_text(encoding="utf-8"))


def _chart_to_long(points: list[dict]) -> pd.DataFrame:
    rows = [
        {"week": p["x"], "series": k, "tokens": float(v)}
        for p in points
        for k, v in p["ys"].items()
    ]
    df = pd.DataFrame(rows)
    df["week"] = pd.to_datetime(df["week"])
    return df


def weekly_model_tokens(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    """Weekly tokens for the top models plus an 'Others' bucket. Columns: week, series, tokens."""
    payload = _fetch_json(cfg, "model_chart", "or_model_chart.json", warnings)
    points = payload["data"]["data"] if isinstance(payload["data"], dict) else payload["data"]
    return _chart_to_long(points)


def weekly_author_tokens(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    """Weekly tokens by model author (x-ai, google, anthropic...). Columns: week, series, tokens."""
    payload = _fetch_json(cfg, "author_share", "or_author_share.json", warnings)
    return _chart_to_long(payload["data"])


def model_week_snapshot(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    """Last-7-days per-model usage with the prompt/completion split (~500 models)."""
    payload = _fetch_json(cfg, "model_week", "or_models_week.json", warnings)
    df = pd.DataFrame(payload["data"])
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "model_permaslug", "variant", "total_prompt_tokens", "total_completion_tokens", "count"]]


def task_spend(cfg: dict, warnings: list[str]) -> dict:
    """30-day spend share and token share by macro task category."""
    payload = _fetch_json(cfg, "task_spend", "or_task_spend.json", warnings)["data"]
    return {
        "spend": payload["spend"]["macroCategories"],
        "tokens": payload["tokens"]["macroCategories"],
        "window_days": payload["spend"]["windowDays"],
    }


def price_catalog(cfg: dict, warnings: list[str]) -> pd.DataFrame:
    """Current public price list, USD per 1M tokens. Saved daily to build price history."""
    payload = _fetch_json(cfg, "models_catalog", "or_models_catalog.json", warnings)
    return catalog_to_frame(payload)


def catalog_to_frame(payload: dict) -> pd.DataFrame:
    rows = []
    for m in payload["data"]:
        p = m.get("pricing") or {}
        try:
            prompt = float(p.get("prompt") or 0) * 1e6
            completion = float(p.get("completion") or 0) * 1e6
        except (TypeError, ValueError):
            continue
        if prompt < 0 or completion < 0:  # "-1" marks router/variable-price entries
            continue
        rows.append({
            "id": m["id"],
            "canonical_slug": m.get("canonical_slug") or m["id"],
            "prompt_usd_per_m": prompt,
            "completion_usd_per_m": completion,
            "created": pd.to_datetime(m.get("created"), unit="s", errors="coerce"),
        })
    return pd.DataFrame(rows)
