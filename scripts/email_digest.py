"""Render dashboard.json as a Markdown digest, with changes since the previous run.

The daily workflow posts the result as a GitHub issue; GitHub then emails it to the repo
owner through normal notifications, so no mail credentials are involved.

Usage:
  python -m scripts.email_digest --current dashboard/data/dashboard.json \
      [--previous prev.json] --out digest.md --subject-out subject.txt
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _tokens(v: float) -> str:
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= cutoff:
            return f"{v / cutoff:.1f}{suffix}"
    return f"{v:.0f}"


def _usd(v: float) -> str:
    for cutoff, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= cutoff:
            return f"${v / cutoff:.1f}{suffix}"
    return f"${v:,.0f}"


def _price(v: float) -> str:
    return f"${v:.3f}"


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def _pct_of_one(v: float) -> str:
    return f"{v * 100:.0f}%"


def _ratio(v: float) -> str:
    return f"{v:.2f}x"


def _num(v: float) -> str:
    return f"{v:.3f}"


def _d_pp(v: float) -> str:
    return f"{v:.1f} pp"


def _d_frac_pp(v: float) -> str:
    return f"{v * 100:.1f} pp"


def _d_plain(v: float) -> str:
    return f"{v:.3f}"


def _d_ratio(v: float) -> str:
    return f"{v:.2f}x"


# (kpi key, label, value formatter, delta formatter)
ROWS = [
    ("weekly_tokens", "Weekly tokens (OpenRouter)", _tokens, _tokens),
    ("tokens_growth_4w_pct", "Token growth vs 4 weeks earlier", _pct, _d_pp),
    ("effective_price", "Average price per 1M tokens", _price, _price),
    ("price_change_since_start_pct", "Price change since first week", _pct, _d_pp),
    ("spend_usd_week", "Implied weekly spend", _usd, _usd),
    ("elasticity", "Elasticity (rolling)", _num, _d_plain),
    ("price_coverage", "Price coverage of tokens", _pct_of_one, _d_frac_pp),
    ("tokens_change_since_start_x", "Token growth since first week", _ratio, _d_ratio),
    ("global_adoption", "World adults using AI", _pct, _d_pp),
    ("us_business_adoption", "US businesses using AI", _pct, _d_pp),
]


def _change(key: str, cur: dict, prev: dict, dfmt) -> str:
    a, b = cur.get(key), (prev or {}).get(key)
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return ""
    delta = a - b
    if abs(delta) < 1e-9:
        return "unchanged"
    return ("+" if delta > 0 else "-") + dfmt(abs(delta))


# Rendered by scripts/render_charts.py and published with the site.
CHARTS = [
    ("index.png", "Volume, price and spend"),
    ("elasticity.png", "Price elasticity of token demand"),
    ("growth.png", "Growth momentum"),
    ("price.png", "Average price vs same-model price"),
    ("mix.png", "Token share by model maker"),
]


def build(cur: dict, prev: dict | None, site_url: str,
          image_base: str = "", image_version: str = "") -> tuple[str, str]:
    k = cur.get("kpis", {})
    errors = cur.get("errors") or {}
    warnings = cur.get("warnings") or []

    if errors:
        title = f"Token Elasticity: build had {len(errors)} failed source(s)"
    else:
        head = []
        if isinstance(k.get("weekly_tokens"), (int, float)):
            head.append(f"{_tokens(k['weekly_tokens'])} tokens/wk")
        if isinstance(k.get("effective_price"), (int, float)):
            head.append(f"{_price(k['effective_price'])}/1M")
        title = "Token Elasticity: " + ", ".join(head) if head else "Token Elasticity daily update"

    prev_kpis = (prev or {}).get("kpis", {})
    generated = cur.get("generated_at", datetime.now(timezone.utc).isoformat())

    lines = []
    if site_url:
        lines += [f"### [Open the dashboard]({site_url})", ""]
    lines += [
        f"**Data week of {k.get('week', 'unknown')}** · built {generated}",
        "",
        "| Metric | Now | Since last run |",
        "| --- | --- | --- |",
    ]
    for key, label, fmt, dfmt in ROWS:
        v = k.get(key)
        value = fmt(v) if isinstance(v, (int, float)) else "n/a"
        lines.append(f"| {label} | **{value}** | {_change(key, k, prev_kpis, dfmt)} |")

    if prev is not None and all(prev_kpis.get(key) == k.get(key) for key, *_ in ROWS):
        lines += ["", "_No KPI changed since the previous run — the upstream weekly data has "
                  "not refreshed yet._"]

    if image_base:
        # The version query busts GitHub's image proxy cache, which would otherwise
        # keep serving the first day's PNG at an unchanging URL.
        suffix = f"?v={image_version}" if image_version else ""
        lines += ["", "## Token usage, price and spend", ""]
        for filename, alt in CHARTS:
            lines += [f"![{alt}]({image_base.rstrip('/')}/{filename}{suffix})", ""]

    if errors:
        lines += ["", "### Failed sources", ""]
        lines += [f"- **{name}**: {msg}" for name, msg in errors.items()]
    if warnings:
        lines += ["", "### Warnings", ""]
        lines += [f"- {w}" for w in warnings[:12]]

    lines += ["", "---", "", "OpenRouter covers its own marketplace only — direct API and "
              "enterprise traffic are not included, so treat volumes as directional."]
    return title, "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", default="dashboard/data/dashboard.json")
    ap.add_argument("--previous")
    ap.add_argument("--out", default="digest.md")
    ap.add_argument("--subject-out", default="subject.txt")
    ap.add_argument("--site-url", default="")
    ap.add_argument("--image-base", default="", help="published URL of the chart PNGs")
    ap.add_argument("--image-version", default="", help="cache-busting token for image URLs")
    args = ap.parse_args()

    cur = json.loads(Path(args.current).read_text(encoding="utf-8"))
    prev = None
    if args.previous and Path(args.previous).exists():
        try:
            prev = json.loads(Path(args.previous).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = None

    title, body = build(cur, prev, args.site_url, args.image_base, args.image_version)
    Path(args.out).write_text(body, encoding="utf-8")
    Path(args.subject_out).write_text(title, encoding="utf-8")
    print(title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
