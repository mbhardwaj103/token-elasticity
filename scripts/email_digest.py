"""Render dashboard.json as an HTML email digest, with changes since the previous run.

Usage:
  python -m scripts.email_digest --current dashboard/data/dashboard.json \
      [--previous prev.json] --out digest.html [--send]

With --send, reads SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS and MAIL_TO from the
environment. Nothing is sent if SMTP_USER or SMTP_PASS is unset.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
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


def build(cur: dict, prev: dict | None, site_url: str) -> tuple[str, str]:
    k = cur.get("kpis", {})
    warnings = cur.get("warnings") or []
    errors = cur.get("errors") or {}

    week = k.get("week", "unknown")
    if errors:
        subject = f"Token Elasticity: build had {len(errors)} failed source(s)"
    else:
        head = []
        if isinstance(k.get("weekly_tokens"), (int, float)):
            head.append(f"{_tokens(k['weekly_tokens'])} tokens/wk")
        if isinstance(k.get("effective_price"), (int, float)):
            head.append(f"{_price(k['effective_price'])}/1M")
        subject = "Token Elasticity: " + ", ".join(head) if head else "Token Elasticity daily update"

    prev_kpis = (prev or {}).get("kpis", {})
    unchanged = prev is not None and all(
        prev_kpis.get(key) == k.get(key) for key, *_ in ROWS
    )

    rows_html = []
    for key, label, fmt, dfmt in ROWS:
        v = k.get(key)
        value = fmt(v) if isinstance(v, (int, float)) else "n/a"
        chg = _change(key, k, prev_kpis, dfmt)
        colour = "#6b7280"
        if chg.startswith("+"):
            colour = "#15803d"
        elif chg.startswith("-"):
            colour = "#b91c1c"
        rows_html.append(
            f'<tr><td style="padding:8px 14px 8px 0;border-bottom:1px solid #e5e7eb;'
            f'color:#374151;">{html.escape(label)}</td>'
            f'<td style="padding:8px 14px 8px 0;border-bottom:1px solid #e5e7eb;'
            f'font-weight:600;color:#111827;white-space:nowrap;">{html.escape(value)}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:{colour};'
            f'white-space:nowrap;">{html.escape(chg)}</td></tr>'
        )

    notes = []
    if errors:
        items = "".join(
            f"<li><strong>{html.escape(name)}</strong>: {html.escape(str(msg))}</li>"
            for name, msg in errors.items()
        )
        notes.append(
            '<p style="margin:20px 0 6px;font-weight:600;color:#b91c1c;">Failed sources</p>'
            f'<ul style="margin:0;padding-left:20px;color:#374151;">{items}</ul>'
        )
    if warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in warnings[:12])
        notes.append(
            '<p style="margin:20px 0 6px;font-weight:600;color:#92400e;">Warnings</p>'
            f'<ul style="margin:0;padding-left:20px;color:#374151;">{items}</ul>'
        )
    if unchanged:
        notes.append(
            '<p style="margin:20px 0 0;color:#6b7280;">No KPI changed since the previous run '
            "&mdash; the upstream weekly data has not refreshed yet.</p>"
        )

    link = (
        f'<p style="margin:24px 0 0;"><a href="{html.escape(site_url)}" '
        f'style="color:#1d4ed8;">Open the dashboard</a></p>'
        if site_url
        else ""
    )
    generated = cur.get("generated_at", datetime.now(timezone.utc).isoformat())

    body = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
font-size:15px;line-height:1.5;color:#111827;max-width:620px;">
  <h1 style="font-size:20px;margin:0 0 4px;">Token Elasticity</h1>
  <p style="margin:0 0 20px;color:#6b7280;">Data week of {html.escape(str(week))}
     &middot; built {html.escape(str(generated))}</p>
  <table style="border-collapse:collapse;width:100%;font-size:15px;">
    <thead><tr>
      <th align="left" style="padding:0 14px 8px 0;font-weight:500;color:#6b7280;">Metric</th>
      <th align="left" style="padding:0 14px 8px 0;font-weight:500;color:#6b7280;">Now</th>
      <th align="left" style="padding:0 0 8px;font-weight:500;color:#6b7280;">Since last run</th>
    </tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  {''.join(notes)}
  {link}
  <p style="margin:28px 0 0;font-size:12px;color:#9ca3af;">
    OpenRouter covers its own marketplace only &mdash; direct API and enterprise traffic are
    not included, so treat volumes as directional.</p>
</div>"""
    return subject, body


def _plain_text(subject: str, site_url: str) -> str:
    tail = f"\n\n{site_url}\n" if site_url else "\n"
    return f"{subject}\n\nThis message is best viewed as HTML.{tail}"


def send(subject: str, body_html: str, site_url: str) -> bool:
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    if not user or not password:
        print("SMTP_USER/SMTP_PASS not set — skipping send", file=sys.stderr)
        return False

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    to = os.environ.get("MAIL_TO", "").strip() or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(_plain_text(subject, site_url))
    msg.add_alternative(body_html, subtype="html")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=60) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
    print(f"Sent digest to {to}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", default="dashboard/data/dashboard.json")
    ap.add_argument("--previous")
    ap.add_argument("--out", default="digest.html")
    ap.add_argument("--subject-out", default="subject.txt")
    ap.add_argument("--site-url", default="")
    ap.add_argument("--send", action="store_true", help="deliver over SMTP")
    args = ap.parse_args()

    cur = json.loads(Path(args.current).read_text(encoding="utf-8"))
    prev = None
    if args.previous and Path(args.previous).exists():
        try:
            prev = json.loads(Path(args.previous).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = None

    subject, body = build(cur, prev, args.site_url)
    Path(args.out).write_text(body, encoding="utf-8")
    Path(args.subject_out).write_text(subject, encoding="utf-8")
    print(subject)
    if args.send:
        send(subject, body, args.site_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
