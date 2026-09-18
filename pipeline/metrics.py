"""Metric calculations: effective price, like-for-like price index, spend, elasticity,
growth, and logistic adoption fits. Pure functions over pandas frames so they can be
unit-tested with synthetic data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

FREE_MARKERS = (":free", "openrouter/", "stealth/")


def blended_price(prompt: pd.Series | float, completion: pd.Series | float, ratio: float):
    """USD per 1M tokens for a token mix of `ratio` prompt tokens per completion token."""
    return (ratio * prompt + completion) / (ratio + 1)


def measured_prompt_ratio(snapshot: pd.DataFrame) -> float:
    """Prompt:completion ratio from the weekly per-model snapshot."""
    c = snapshot["total_completion_tokens"].sum()
    return float(snapshot["total_prompt_tokens"].sum() / c) if c else float("nan")


def is_free_slug(slug: str) -> bool:
    return any(m in slug for m in FREE_MARKERS)


def price_as_of(prices: pd.DataFrame, slug: str, week: pd.Timestamp) -> pd.Series | None:
    """Most recent known price for `slug` on or before `week`; else earliest after it
    (a model's launch-month price is the best estimate for weeks before its first snapshot)."""
    base = slug.split(":")[0]
    p = prices[prices["slug"] == base]
    if p.empty:
        return None
    before = p[p["snapshot"] <= week]
    return (before.iloc[-1] if not before.empty else p.iloc[0])


def attach_prices(model_tokens: pd.DataFrame, prices: pd.DataFrame, ratio: float) -> pd.DataFrame:
    """Add blended_price (USD/1M) per (week, model). Free/stealth models are priced at 0.
    Rows with no known price get NaN and are excluded from price metrics (reported as coverage)."""
    out = model_tokens[model_tokens["series"] != "Others"].copy()
    vals = []
    for week, slug in zip(out["week"], out["series"]):
        if is_free_slug(slug):
            vals.append(0.0)
            continue
        row = price_as_of(prices, slug, week)
        vals.append(np.nan if row is None else blended_price(row["prompt_usd_per_m"], row["completion_usd_per_m"], ratio))
    out["blended_price"] = vals
    return out


def weekly_price_metrics(priced: pd.DataFrame, total_tokens: pd.Series) -> pd.DataFrame:
    """Per week: effective price over priced named models, like-for-like chained index,
    and price coverage (share of all tokens that had a known price)."""
    rows = []
    prev = None
    chain = 100.0
    for week, g in priced.groupby("week", sort=True):
        known = g.dropna(subset=["blended_price"])
        tok = known["tokens"].sum()
        eff = float((known["tokens"] * known["blended_price"]).sum() / tok) if tok else np.nan
        if prev is not None:
            common = known.merge(prev, on="series", suffixes=("", "_prev"))
            if not common.empty and common["tokens_prev"].sum() > 0:
                w = common["tokens_prev"]
                p0 = (w * common["blended_price_prev"]).sum()
                p1 = (w * common["blended_price"]).sum()
                if p0 > 0:
                    chain *= p1 / p0  # Laspeyres link: last week's mix at this week's prices
        rows.append({
            "week": week,
            "effective_price": eff,
            "like_for_like_index": chain,
            "price_coverage": float(tok / total_tokens.get(week, np.nan)) if tok else 0.0,
        })
        prev = known[["series", "tokens", "blended_price"]]
    return pd.DataFrame(rows)


def volume_metrics(totals: pd.Series, ma_weeks: int) -> pd.DataFrame:
    """totals: weekly total tokens indexed by week."""
    df = pd.DataFrame({"tokens": totals.astype(float)})
    df["tokens_ma"] = df["tokens"].rolling(ma_weeks, min_periods=1).mean()
    df["wow_pct"] = df["tokens"].pct_change() * 100
    df["growth_4w_pct"] = df["tokens_ma"].pct_change(ma_weeks) * 100
    df["yoy_pct"] = df["tokens"].pct_change(52) * 100
    return df


def index_to_100(s: pd.Series) -> pd.Series:
    first = s.dropna()
    return s / first.iloc[0] * 100 if not first.empty and first.iloc[0] else s * np.nan


def rolling_elasticity(volume: pd.Series, price: pd.Series, window: int) -> pd.Series:
    """Rolling OLS slope of Δln(volume) on Δln(price). Negative = volume rises as price falls;
    below -1 = demand is elastic (price cuts grow total spend)."""
    dv = np.log(volume.astype(float)).diff()
    dp = np.log(price.astype(float)).diff()
    out = pd.Series(np.nan, index=volume.index)
    for i in range(window, len(volume)):
        x = dp.iloc[i - window + 1 : i + 1]
        y = dv.iloc[i - window + 1 : i + 1]
        mask = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
        if mask.sum() < max(4, window // 2) or x[mask].var() == 0:
            continue
        out.iloc[i] = np.polyfit(x[mask], y[mask], 1)[0]
    return out


def arc_elasticity(volume: pd.Series, price: pd.Series, lag: int) -> pd.Series:
    """%Δvolume / %Δprice over `lag` periods using log changes (symmetric)."""
    dv = np.log(volume.astype(float)).diff(lag)
    dp = np.log(price.astype(float)).diff(lag)
    return (dv / dp).where(dp.abs() > 1e-3)


def logistic(t, k, r, t0):
    return k / (1 + np.exp(-r * (t - t0)))


def fit_logistic(dates: pd.Series, values: pd.Series, horizon_days: int = 730) -> dict | None:
    """Fit an S-curve to adoption % over time. Returns saturation (k), growth rate,
    inflection date, current speed (pp per quarter) and a projected curve."""
    d = pd.DataFrame({"date": pd.to_datetime(dates), "v": values.astype(float)}).dropna()
    if len(d) < 4:
        return None
    t0 = d["date"].min()
    t = (d["date"] - t0).dt.days.to_numpy(dtype=float)
    y = d["v"].to_numpy()
    try:
        (k, r, mid), _ = curve_fit(
            logistic, t, y,
            p0=[min(100, max(y) * 2), 0.005, t.max()],
            bounds=([max(y), 1e-5, -5000], [100, 0.1, 10000]),
            maxfev=20000,
        )
    except (RuntimeError, ValueError):
        return None
    last = t.max()
    speed = (logistic(last + 91, k, r, mid) - logistic(last, k, r, mid))
    grid = np.linspace(t.min(), last + horizon_days, 60)
    return {
        "saturation": float(k),
        "rate_per_day": float(r),
        "inflection": (t0 + pd.Timedelta(days=float(mid))).date().isoformat(),
        "pp_per_quarter": float(speed),
        "curve": [
            {"date": (t0 + pd.Timedelta(days=float(g))).date().isoformat(), "value": float(logistic(g, k, r, mid))}
            for g in grid
        ],
    }
