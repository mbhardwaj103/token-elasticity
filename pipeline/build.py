"""Run every source, compute metrics, write dashboard/data/dashboard.json.

Usage (from the project root):  .venv\\Scripts\\python -m pipeline.build
Each source is isolated: if one fails, the others still build and the failure is listed
in `warnings` so the dashboard can flag the affected chart.
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from pipeline import metrics as m
from pipeline.common import DASHBOARD_DATA, MANUAL, PROCESSED, load_config, utc_now_iso
from pipeline.sources import census_btos, ms_diffusion, openrouter, price_history, worldbank


def _clean(obj):
    """Make frames/numpy values JSON-safe (NaN/inf -> null, timestamps -> ISO dates)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.date().isoformat()
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def _series_points(df: pd.DataFrame, date_col: str, value_col: str) -> list[dict]:
    return [{"date": d, "value": v} for d, v in zip(df[date_col], df[value_col])]


def _run(name: str, fn, warnings: list[str], errors: dict):
    try:
        return fn()
    except Exception as exc:
        errors[name] = f"{type(exc).__name__}: {exc}"
        warnings.append(f"{name} failed: {exc}")
        traceback.print_exc()
        return None


def build_tokens(cfg: dict, warnings: list[str], errors: dict) -> dict:
    out: dict = {}
    model_tokens = _run("openrouter_model_chart", lambda: openrouter.weekly_model_tokens(cfg, warnings), warnings, errors)
    if model_tokens is None or model_tokens.empty:
        return out

    if cfg["metrics"]["drop_incomplete_last_week"]:
        cutoff = pd.Timestamp(datetime.now(timezone.utc).date() - timedelta(days=7))
        model_tokens = model_tokens[model_tokens["week"] <= cutoff]

    snapshot = _run("openrouter_models_week", lambda: openrouter.model_week_snapshot(cfg, warnings), warnings, errors)
    ratio = cfg["metrics"]["prompt_completion_ratio"]
    if ratio is None:
        ratio = m.measured_prompt_ratio(snapshot) if snapshot is not None else float("nan")
        if not np.isfinite(ratio):
            ratio = cfg["metrics"]["fallback_prompt_completion_ratio"]
    out["prompt_completion_ratio"] = ratio

    totals = model_tokens.groupby("week")["tokens"].sum().sort_index()
    vol = m.volume_metrics(totals, cfg["metrics"]["moving_average_weeks"])

    # Save today's price list first so price_history includes it.
    _run("price_catalog_snapshot", lambda: openrouter.price_catalog(cfg, warnings), warnings, errors)
    since = (totals.index.min() - pd.Timedelta(days=120)).date().isoformat()
    prices = _run("price_history", lambda: price_history.price_history(cfg, since, warnings), warnings, errors)

    frame = vol.copy()
    if prices is not None and not prices.empty:
        priced = m.attach_prices(model_tokens, prices, ratio)
        pm = m.weekly_price_metrics(priced, totals).set_index("week")
        frame = frame.join(pm)
        frame["spend_usd"] = frame["tokens"] / 1e6 * frame["effective_price"]
        frame["volume_index"] = m.index_to_100(frame["tokens"])
        frame["price_index"] = m.index_to_100(frame["effective_price"])
        frame["spend_index"] = m.index_to_100(frame["spend_usd"])
        window = cfg["metrics"]["elasticity_window_weeks"]
        frame["elasticity_rolling"] = m.rolling_elasticity(frame["tokens_ma"], frame["effective_price"].rolling(4, min_periods=1).mean(), window)
        frame["elasticity_arc"] = m.arc_elasticity(frame["tokens_ma"], frame["effective_price"].rolling(4, min_periods=1).mean(), window)
        unpriced = priced[priced["blended_price"].isna()]["series"].unique().tolist()
        if unpriced:
            warnings.append(f"No price found for {len(unpriced)} model(s), excluded from price metrics: {', '.join(unpriced[:8])}")
        latest_week = priced["week"].max()
        out["top_models_latest"] = (
            priced[priced["week"] == latest_week]
            .sort_values("tokens", ascending=False)[["series", "tokens", "blended_price"]]
            .to_dict("records")
        )
    frame = frame.reset_index().rename(columns={"index": "week"})
    PROCESSED.mkdir(parents=True, exist_ok=True)
    frame.to_csv(PROCESSED / "token_price_weekly.csv", index=False)
    out["weekly"] = {col: frame[col].tolist() for col in frame.columns}

    authors = _run("openrouter_author_share", lambda: openrouter.weekly_author_tokens(cfg, warnings), warnings, errors)
    if authors is not None and not authors.empty:
        authors = authors[authors["week"].isin(totals.index)]
        wide = authors.pivot_table(index="week", columns="series", values="tokens", aggfunc="sum").fillna(0)
        share = wide.div(wide.sum(axis=1), axis=0) * 100
        order = share.iloc[-1].sort_values(ascending=False).index.tolist()
        if "others" in order:
            order = [c for c in order if c != "others"] + ["others"]
        out["author_share"] = {"weeks": share.index.tolist(), "series": {c: share[c].tolist() for c in order}}

    spend = _run("openrouter_task_spend", lambda: openrouter.task_spend(cfg, warnings), warnings, errors)
    if spend:
        out["task_spend"] = spend
    return out


def build_adoption(cfg: dict, warnings: list[str], errors: dict, weekly_tokens: dict) -> dict:
    out: dict = {}
    btos = _run("census_btos", lambda: census_btos.ai_use(cfg, warnings), warnings, errors)
    if btos is not None and not btos.empty:
        names = {**{str(k): v for k, v in cfg["btos"]["sectors"].items()}, census_btos.ALL_US: "All US businesses"}
        use = btos[btos["metric"] == "use"]
        exp = btos[btos["metric"] == "expect"]
        out["us_business"] = {
            names[g]: _series_points(d, "date", "value") for g, d in use.groupby("group")
        }
        out["us_business_expect"] = {
            names[g]: _series_points(d, "date", "value") for g, d in exp.groupby("group")
        }
        us = use[use["group"] == census_btos.ALL_US]
        fit = m.fit_logistic(us["date"], us["value"])
        if fit:
            out["us_business_fit"] = fit
        latest = use[use["date"] == use["date"].max()]
        out["sector_latest"] = sorted(
            [{"sector": names[g], "use": v} for g, v in zip(latest["group"], latest["value"])],
            key=lambda r: -r["use"],
        )

    world_df = _run("ai_user_share", lambda: ms_diffusion.adoption(cfg, warnings), warnings, errors)
    glob = None
    if world_df is not None and not world_df.empty:
        sel = world_df[world_df["country"].isin(cfg["microsoft"]["countries"])]
        out["countries"] = {c: _series_points(d, "date", "value") for c, d in sel.groupby("country")}
        glob = world_df[world_df["country"] == ms_diffusion.WORLD]
        if not glob.empty:
            out["global"] = _series_points(glob, "date", "value")
            # Three points cannot pin down an S-curve; report linear speed instead.
            if len(glob) >= 2:
                days = (glob["date"].iloc[-1] - glob["date"].iloc[0]).days or 1
                out["global_pp_per_quarter"] = float((glob["value"].iloc[-1] - glob["value"].iloc[0]) / days * 91)

    intensity = _run("intensity_manual", lambda: pd.read_csv(MANUAL / "intensity.csv", parse_dates=["date"]), warnings, errors)
    if intensity is not None and not intensity.empty:
        out["intensity"] = intensity.to_dict("records")

    pop = _run("worldbank_population", lambda: worldbank.world_working_age_population(cfg, warnings), warnings, errors)
    weekly = weekly_tokens.get("weekly")
    if pop and glob is not None and not glob.empty and weekly:
        population, year = pop
        users = glob["value"].iloc[-1] / 100 * population
        out["tokens_per_user"] = {
            "population": population,
            "population_year": year,
            "global_share": float(glob["value"].iloc[-1]),
            "ai_users": users,
            "weekly_tokens": weekly["tokens"][-1],
            "tokens_per_user_week": weekly["tokens"][-1] / users,
        }
    return out


def kpis(tokens: dict, adoption: dict) -> dict:
    k: dict = {}
    w = tokens.get("weekly")
    if w and w.get("tokens"):
        k["week"] = w["week"][-1]
        k["weekly_tokens"] = w["tokens"][-1]
        k["tokens_growth_4w_pct"] = w["growth_4w_pct"][-1]
        k["tokens_change_since_start_x"] = w["tokens"][-1] / w["tokens"][0] if w["tokens"][0] else None
        if "effective_price" in w:
            k["effective_price"] = w["effective_price"][-1]
            ep = [p for p in w["effective_price"] if p is not None and not (isinstance(p, float) and math.isnan(p))]
            k["price_change_since_start_pct"] = (ep[-1] / ep[0] - 1) * 100 if ep and ep[0] else None
            k["price_coverage"] = w["price_coverage"][-1]
            er = [e for e in w["elasticity_rolling"] if e is not None and not (isinstance(e, float) and math.isnan(e))]
            k["elasticity"] = er[-1] if er else None
            k["spend_usd_week"] = w["spend_usd"][-1]
    if adoption.get("global"):
        k["global_adoption"] = adoption["global"][-1]["value"]
        if len(adoption["global"]) > 1:
            k["global_adoption_change_pp"] = adoption["global"][-1]["value"] - adoption["global"][-2]["value"]
    us = adoption.get("us_business", {}).get("All US businesses")
    if us:
        k["us_business_adoption"] = us[-1]["value"]
        k["us_business_adoption_date"] = us[-1]["date"]
        prior = [p for p in us if pd.Timestamp(p["date"]) <= pd.Timestamp(us[-1]["date"]) - pd.Timedelta(days=180)]
        if prior:
            k["us_business_change_6m_pp"] = us[-1]["value"] - prior[-1]["value"]
    return k


def main() -> int:
    cfg = load_config()
    warnings: list[str] = []
    errors: dict = {}
    tokens = build_tokens(cfg, warnings, errors)
    adoption = build_adoption(cfg, warnings, errors, tokens)
    result = {
        "generated_at": utc_now_iso(),
        "kpis": kpis(tokens, adoption),
        "tokens": tokens,
        "adoption": adoption,
        "warnings": warnings,
        "errors": errors,
    }
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)
    target = DASHBOARD_DATA / "dashboard.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(result), indent=1), encoding="utf-8")
    tmp.replace(target)
    print(f"Wrote {target} ({len(warnings)} warning(s), {len(errors)} failed source(s))")
    for w in warnings:
        print("  -", w)
    return 1 if "openrouter_model_chart" in errors else 0


if __name__ == "__main__":
    sys.exit(main())
