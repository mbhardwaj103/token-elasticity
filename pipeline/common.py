"""Shared helpers: config, paths, HTTP with retries, raw snapshot storage."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
MANUAL = DATA / "manual"
DASHBOARD_DATA = ROOT / "dashboard" / "data"


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def today_dir() -> Path:
    d = RAW / date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def http_get(url: str, cfg: dict, headers: dict | None = None) -> requests.Response:
    """GET with simple exponential backoff. Raises on final failure."""
    h = {"User-Agent": cfg["http"]["user_agent"], **(headers or {})}
    last_exc: Exception | None = None
    for attempt in range(cfg["http"]["retries"]):
        try:
            r = requests.get(url, headers=h, timeout=cfg["http"]["timeout_seconds"])
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after retries: {last_exc}")


def save_raw_json(name: str, payload) -> Path:
    path = today_dir() / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def save_raw_bytes(name: str, content: bytes) -> Path:
    path = today_dir() / name
    path.write_bytes(content)
    return path


def latest_raw(name: str) -> Path | None:
    """Most recent saved copy of a raw file, used as fallback when a fetch fails."""
    if not RAW.exists():
        return None
    for d in sorted((p for p in RAW.iterdir() if p.is_dir()), reverse=True):
        if (d / name).exists():
            return d / name
    return None
