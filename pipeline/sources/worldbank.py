"""World Bank working-age population (15-64), used to turn AI user share into user counts."""
from __future__ import annotations

from pipeline.common import http_get, latest_raw, save_raw_json

URL = "https://api.worldbank.org/v2/country/WLD/indicator/SP.POP.1564.TO?format=json&per_page=20&mrnev=1"


def world_working_age_population(cfg: dict, warnings: list[str]) -> tuple[float, int] | None:
    """(population, year) of the latest available estimate, or None."""
    raw_name = "wb_working_age_pop.json"
    try:
        payload = http_get(URL, cfg).json()
        save_raw_json(raw_name, payload)
    except Exception as exc:
        fallback = latest_raw(raw_name)
        if fallback is None:
            warnings.append(f"World Bank population unavailable ({exc}); tokens-per-user proxy skipped")
            return None
        import json
        payload = json.loads(fallback.read_text(encoding="utf-8"))
    rows = [r for r in (payload[1] or []) if r.get("value")]
    if not rows:
        return None
    return float(rows[0]["value"]), int(rows[0]["date"])
