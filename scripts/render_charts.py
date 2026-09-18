"""Render the first dashboard section as PNGs for the daily email digest.

Email clients cannot run ECharts, so these are static twins of the five charts in
"Token usage, price and spend", drawn from the same dashboard.json with the same
categorical palette (--s1..--s8 in index.html, validated with the dataviz skill's
palette checker). Light surface only: a PNG cannot adapt to the reader's theme.

Usage:  python -m scripts.render_charts --data dashboard/data/dashboard.json --out dashboard/email
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

# Light-mode tokens, copied from dashboard/index.html.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#5a5850"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
# Fixed categorical order — never cycled past 8; an extra series folds into "Other".
S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

FIGSIZE = (9.0, 4.0)
DPI = 110


def _dates(weeks: list[str]) -> list[datetime]:
    return [datetime.fromisoformat(w) for w in weeks]


def _arr(values: list) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


def _fig(title: str, note: str):
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=13, fontweight="bold", loc="left", pad=22)
    if note:
        ax.text(0, 1.035, note, transform=ax.transAxes, color=MUTED, fontsize=9.5, va="bottom")
    ax.grid(True, axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9.5, length=0)
    return fig, ax


def _time_axis(ax, dates):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.set_xlim(dates[0], dates[-1])


def _end_label(ax, dates, values, text, color):
    """Direct label at the series end: required relief for the palette's contrast WARN."""
    finite = np.where(np.isfinite(values))[0]
    if len(finite) == 0:
        return
    i = finite[-1]
    ax.annotate(text, (dates[i], values[i]), textcoords="offset points", xytext=(6, 0),
                va="center", ha="left", fontsize=9.5, color=color, fontweight="bold",
                annotation_clip=False)


def _save(fig, out: Path, name: str) -> Path:
    path = out / name
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    return path


def chart_index(w, out: Path) -> Path:
    dates = _dates(w["week"])
    fig, ax = _fig("Volume, price and spend",
                   "Index, first week = 100 · log scale · weekly tokens, avg price per 1M, implied spend")
    series = [("Token volume", _arr(w["volume_index"]), S[0]),
              ("Average price", _arr(w["price_index"]), S[1]),
              ("Implied spend", _arr(w["spend_index"]), S[2])]
    for label, values, color in series:
        ax.plot(dates, values, color=color, linewidth=2, label=label, solid_capstyle="round")
        _end_label(ax, dates, values, f"{values[np.isfinite(values)][-1]:,.0f}", color)
    ax.set_yscale("log")
    ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.tick_params(which="minor", length=0)
    ax.axhline(100, color=AXIS, linewidth=1, linestyle=(0, (2, 3)), zorder=1)
    _time_axis(ax, dates)
    ax.legend(loc="upper left", frameon=False, fontsize=9.5, labelcolor=INK2, ncol=3,
              handlelength=1.6, columnspacing=1.6, bbox_to_anchor=(0, 1.0))
    return _save(fig, out, "index.png")


def chart_elasticity(w, out: Path) -> Path:
    dates = _dates(w["week"])
    values = _arr(w["elasticity_rolling"])
    fig, ax = _fig("Price elasticity of token demand",
                   "12-week rolling slope of Δln(tokens) on Δln(price) · correlation, not cause")
    # One series: the title names it, so no legend box.
    ax.plot(dates, values, color=S[0], linewidth=2, solid_capstyle="round")
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.axhline(-1, color=MUTED, linewidth=1, linestyle=(0, (2, 3)))
    ax.annotate("−1: price cuts grow total spend", (dates[0], -1), textcoords="offset points",
                xytext=(2, 5), fontsize=9, color=MUTED, annotation_clip=False)
    _end_label(ax, dates, values, f"{values[np.isfinite(values)][-1]:.2f}", S[0])
    _time_axis(ax, dates)
    return _save(fig, out, "elasticity.png")


def chart_growth(w, out: Path) -> Path:
    dates = _dates(w["week"])
    wow, ma4 = _arr(w["wow_pct"]), _arr(w["growth_4w_pct"])
    fig, ax = _fig("Growth momentum",
                   "Week-over-week token growth (bars) and 4-week growth of the moving average (line), %")
    bars = ax.bar(dates, wow, width=4.6, color=S[0], label="Week-over-week", zorder=2)
    line, = ax.plot(dates, ma4, color=S[1], linewidth=2, label="4-week growth",
                    solid_capstyle="round", zorder=3)
    _end_label(ax, dates, ma4, f"{ma4[np.isfinite(ma4)][-1]:.0f}%", S[1])
    ax.axhline(0, color=AXIS, linewidth=1, zorder=1)
    _time_axis(ax, dates)
    ax.legend([bars, line], ["Week-over-week", "4-week growth"], loc="upper left",
              frameon=False, fontsize=9.5, labelcolor=INK2, ncol=2,
              handlelength=1.6, columnspacing=1.6, bbox_to_anchor=(0, 1.0))
    return _save(fig, out, "growth.png")


def chart_price(w, out: Path) -> Path:
    dates = _dates(w["week"])
    fig, ax = _fig("Average price vs same-model price",
                   "Index, first week = 100 · the same-model line holds the model mix fixed")
    # s7 rather than the neighbouring s4: orange/amber measures ΔE 13.7 for normal
    # vision, under the 15 floor, and direct labels do not excuse that one.
    series = [("Average price", _arr(w["price_index"]), S[1]),
              ("Same-model price", _arr(w["like_for_like_index"]), S[6])]
    for label, values, color in series:
        ax.plot(dates, values, color=color, linewidth=2, label=label, solid_capstyle="round")
        _end_label(ax, dates, values, f"{values[np.isfinite(values)][-1]:,.0f}", color)
    ax.axhline(100, color=AXIS, linewidth=1, linestyle=(0, (2, 3)), zorder=1)
    _time_axis(ax, dates)
    ax.legend(loc="upper left", frameon=False, fontsize=9.5, labelcolor=INK2, ncol=2,
              handlelength=1.6, columnspacing=1.6, bbox_to_anchor=(0, 1.0))
    return _save(fig, out, "price.png")


def chart_mix(a, out: Path) -> Path:
    dates = _dates(a["weeks"])
    names = [n for n in a["series"] if n != "others"][:7]
    stacks = [(n, _arr(a["series"][n])) for n in names]
    covered = set(names)
    other = np.zeros(len(dates))
    for n, v in a["series"].items():
        if n not in covered:
            other += np.nan_to_num(_arr(v))

    fig, ax = _fig("Token share by model maker",
                   "Share of weekly tokens, % — shifts here explain moves in the average price")
    bottom = np.zeros(len(dates))
    for i, (label, values) in enumerate([*stacks, ("Other", other)]):
        values = np.nan_to_num(values)
        color = S[i] if i < len(names) else AXIS
        ax.fill_between(dates, bottom, bottom + values, facecolor=color, alpha=0.85,
                        linewidth=0, zorder=2, label=label)
        # 2px surface gap between stacked segments.
        ax.plot(dates, bottom + values, color=SURFACE, linewidth=2, zorder=3)
        bottom = bottom + values
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    _time_axis(ax, dates)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False,
              fontsize=9.5, labelcolor=INK2, ncol=4, handlelength=1.4, columnspacing=1.6)
    return _save(fig, out, "mix.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dashboard/data/dashboard.json")
    ap.add_argument("--out", default="dashboard/email")
    args = ap.parse_args()

    d = json.loads(Path(args.data).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    w = d.get("tokens", {}).get("weekly")
    a = d.get("tokens", {}).get("author_share")
    written = []
    if w and w.get("week"):
        written += [chart_index(w, out), chart_elasticity(w, out),
                    chart_growth(w, out), chart_price(w, out)]
    if a and a.get("weeks"):
        written.append(chart_mix(a, out))
    for p in written:
        print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
