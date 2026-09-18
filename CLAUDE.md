# Token Elasticity

A local dashboard tracking global AI token usage, price, spend/elasticity, and adoption
(world + US sectors). See [README.md](README.md) for full source/metric documentation —
this file is Claude-specific working notes.

## Environment

- Windows, no system Python. Interpreter is `uv`-managed: `~/.local/bin/python3.14.exe`
  (also `~/.local/bin/uv.exe`). Project venv lives at `.venv` (created with
  `uv venv .venv --python 3.14`).
- Run everything through `.venv\Scripts\python.exe` (PowerShell) — don't assume a bare
  `python` on PATH works.
- Install/sync deps: `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`

## Common commands

```powershell
.venv\Scripts\python -m pipeline.build   # fetch all sources -> dashboard/data/dashboard.json
.venv\Scripts\python serve.py            # serve dashboard + /api/refresh at :8765
.venv\Scripts\python -m pytest tests -q  # unit tests for pipeline/metrics.py
```

Opening `dashboard/index.html` directly via `file://` will NOT work (fetch is blocked) —
always go through `serve.py`.

## Architecture

- `pipeline/sources/*.py` — one module per data source (OpenRouter rankings/prices,
  Census BTOS, Microsoft/OWID adoption, World Bank population). Each source function
  takes `(cfg, warnings)`, fetches, saves a raw snapshot under `data/raw/<date>/`, and
  falls back to the last saved snapshot on failure (never hard-fails the whole build).
- `pipeline/metrics.py` — pure functions (blended price, like-for-like index, rolling/arc
  elasticity, logistic S-curve fit). Unit-tested in `tests/test_metrics.py` against
  synthetic data with known answers — extend tests here when changing formulas.
- `pipeline/build.py` — orchestrates sources -> metrics -> writes
  `dashboard/data/dashboard.json` (single JSON blob the frontend reads). Wraps every
  source call in `_run()` so partial failures still produce a dashboard with a
  `warnings`/`errors` list.
- `dashboard/index.html` + `dashboard/app.js` — static frontend, ECharts (vendored at
  `dashboard/vendor/echarts.min.js`, not CDN — cdnjs 5.5.1 path 404s, jsdelivr works).
  No build step.
- `serve.py` — stdlib `http.server` serving `dashboard/`, plus `POST /api/refresh`
  (runs `pipeline.build` in a background thread) and `GET /api/status`.
- `data/manual/intensity.csv` and `global_adoption.csv` — hand-entered survey figures
  (Gallup, Pew, Microsoft AI Diffusion world total) with `source_url` columns. Update
  these by hand when new survey waves are published; there's no API for them.
- `scripts/register_weekly_task.ps1` registers a Windows Task Scheduler job
  (`TokenElasticityWeekly`, Mondays 08:00) running `scripts/run_build.cmd`, which logs to
  `data/build.log`. Already registered on this machine as of 2026-09-13.

## Key facts worth remembering

- OpenRouter volume/price come from **undocumented** endpoints behind the public
  `/rankings` page (`/api/frontend/v1/rankings/*`), not the official keyed
  `/api/v1/datasets/rankings-daily` API — no API key was available. These could change
  shape without notice; `pipeline/sources/openrouter.py` and `price_history.py` are the
  fragile parts if a refresh starts erroring.
- Historical OpenRouter prices come from Wayback Machine snapshots of `/api/v1/models`
  (cached in `data/cache/wayback/`, permanent cache since archived pages don't change)
  plus every `or_models_catalog.json` ever saved under `data/raw/`.
- OpenRouter only covers its own marketplace traffic — direct OpenAI/Anthropic/Google API
  and enterprise contracts are invisible. Treat all volume figures as directional.
- "Others" bucket in the weekly model chart is ~35-50% of tokens and has no per-model
  price, so it's excluded from price/elasticity math; `price_coverage` in the output
  reports what share of tokens *did* have a price.
- Prompt:completion blending ratio is measured live from the weekly snapshot each run
  (~38:1 as of Sep 2026 — much higher than a naive chat assumption, driven by
  agentic/coding traffic re-sending large contexts).

## Conventions

- Every source function must accept a `warnings: list[str]` and append human-readable
  strings on degraded/fallback data rather than raising, unless the failure is fatal to
  the whole build.
- JSON output must stay finite: `pipeline/build.py:_clean()` converts NaN/inf to `null`
  and timestamps to ISO date strings — route new fields through it.
- Frontend follows the `dataviz` skill (see `.claude` skill docs): fixed categorical
  color order (never cycled), one axis per chart (index to 100 rather than dual-axis),
  legend for 2+ series, every chart has a "Show data table" fallback, dark/light theme
  via CSS custom properties.
