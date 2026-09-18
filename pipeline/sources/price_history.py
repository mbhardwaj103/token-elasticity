"""Historical OpenRouter prices.

OpenRouter's /api/v1/models only returns today's prices. History comes from:
  1. Wayback Machine snapshots of that endpoint (roughly monthly since mid-2023), cached
     permanently under data/cache/wayback/ because archived snapshots never change.
  2. Our own saved copies under data/raw/<date>/or_models_catalog.json.
Result: one row per (snapshot date, model slug) with prompt/completion USD per 1M tokens.
"""
from __future__ import annotations

import gzip
import json

import pandas as pd

from pipeline.common import DATA, RAW, http_get
from pipeline.sources.openrouter import catalog_to_frame

CDX = "https://web.archive.org/cdx/search/cdx?url=openrouter.ai/api/v1/models&output=json&fl=timestamp&filter=statuscode:200&collapse=timestamp:6"
CACHE = DATA / "cache" / "wayback"


def _decode(raw: bytes) -> dict:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def _wayback_snapshots(cfg: dict, since: str, warnings: list[str]) -> list[tuple[pd.Timestamp, dict]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        rows = http_get(CDX, cfg).json()[1:]
        stamps = [r[0] for r in rows if r[0][:8] >= since.replace("-", "")]
    except Exception as exc:
        warnings.append(f"Wayback index unavailable ({exc}); using cached price snapshots only")
        stamps = [p.stem for p in CACHE.glob("*.json")]
    out = []
    for ts in sorted(set(stamps)):
        path = CACHE / f"{ts}.json"
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
            else:
                url = f"https://web.archive.org/web/{ts}id_/https://openrouter.ai/api/v1/models"
                payload = _decode(http_get(url, cfg).content)
                path.write_text(json.dumps(payload), encoding="utf-8")
            out.append((pd.Timestamp(ts[:8]), payload))
        except Exception as exc:
            warnings.append(f"Wayback price snapshot {ts} skipped ({exc})")
    return out


def _own_snapshots() -> list[tuple[pd.Timestamp, dict]]:
    out = []
    if RAW.exists():
        for p in sorted(RAW.glob("*/or_models_catalog.json")):
            out.append((pd.Timestamp(p.parent.name), json.loads(p.read_text(encoding="utf-8"))))
    return out


def price_history(cfg: dict, since: str, warnings: list[str]) -> pd.DataFrame:
    """Columns: snapshot, slug, prompt_usd_per_m, completion_usd_per_m.

    Each model is indexed under both its id and canonical_slug so it can be joined to the
    rankings permaslugs (which use canonical slugs, sometimes with ':free' suffixes).
    """
    frames = []
    for snap, payload in _wayback_snapshots(cfg, since, warnings) + _own_snapshots():
        cat = catalog_to_frame(payload)
        if cat.empty:
            continue
        by_id = cat.assign(slug=cat["id"])
        by_canon = cat.assign(slug=cat["canonical_slug"])
        both = pd.concat([by_id, by_canon]).drop_duplicates("slug")
        both["snapshot"] = snap
        frames.append(both[["snapshot", "slug", "prompt_usd_per_m", "completion_usd_per_m"]])
    if not frames:
        return pd.DataFrame(columns=["snapshot", "slug", "prompt_usd_per_m", "completion_usd_per_m"])
    return pd.concat(frames, ignore_index=True).sort_values(["slug", "snapshot"]).reset_index(drop=True)
