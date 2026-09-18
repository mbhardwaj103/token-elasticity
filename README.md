# Token Elasticity

A dashboard that tracks whether AI use is growing, whether tokens are getting cheaper,
how volume responds to price (elasticity), and how fast people and businesses are adopting AI.

**Live:** <https://mbhardwaj103.github.io/token-elasticity/> — rebuilt every morning at
07:00 US Central by [`.github/workflows/daily.yml`](.github/workflows/daily.yml).

## Run it

```powershell
# one-time setup (uv is already installed at ~/.local/bin)
uv venv .venv --python 3.14
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

.venv\Scripts\python -m pipeline.build   # fetch data -> dashboard/data/dashboard.json
.venv\Scripts\python serve.py            # open http://127.0.0.1:8765
```

The **Refresh data** button on the page reruns the pipeline through `serve.py` (about 1 minute).
Opening `dashboard/index.html` directly from disk will not work: browsers block `fetch` from `file://`.

**Weekly refresh (local):** `scripts\register_weekly_task.ps1` registers the `TokenElasticityWeekly`
task (Mondays 08:00), which runs `scripts\run_build.cmd` and logs to `data\build.log`.
Remove it with `schtasks /Delete /TN TokenElasticityWeekly /F`. This only keeps the local copy
fresh; the published dashboard is built in CI.

**Tests:** `.venv\Scripts\python -m pytest tests`

## Daily refresh and email digest

`.github/workflows/daily.yml` runs at 12:00 UTC (07:00 CDT / 06:00 CST — cron is always UTC, so
it shifts an hour with daylight saving), and can also be run by hand from the Actions tab. Each run
rebuilds the data, runs the metric tests, emails a digest, and publishes `dashboard/` to GitHub Pages.
Every source is public and keyless, so no API credentials are needed for the build itself.

`scripts/email_digest.py` renders the digest and compares each KPI against the previous run, so the
mail shows what actually moved. Upstream data is weekly, so most mornings read "unchanged" — that is
the expected result, not a failure. If a source fails, the affected chart keeps its last good value
and the failure is listed in the digest.

**No mail credentials are involved.** The workflow posts the digest as a GitHub issue labelled
`digest` using the built-in `GITHUB_TOKEN`, and GitHub emails it out through ordinary notifications.
The body ends with a `cc @owner` line so the mention fires even if the repo is not being watched.
Delivery is therefore governed by GitHub notification settings rather than an SMTP password.

Each run opens one issue. To clear old ones out:

```bash
gh issue list --label digest --state open --limit 200 --json number --jq '.[].number' \
  | xargs -n1 gh issue close
```

Daily source snapshots (`data/raw/`, ~3 MB/day) are **not** committed; CI carries them in the Actions
cache instead, so the repository does not grow without bound. `data/cache/wayback/` *is* tracked,
because those archived price lists cannot be refetched cheaply.

## Data sources

| What | Source | Notes |
|---|---|---|
| Weekly tokens by model / by maker | `openrouter.ai/api/frontend/v1/rankings/*` | Keyless but **undocumented**. Raw responses are saved in `data/raw/<date>/`; if a fetch fails, the last good copy is used. History starts 2025-09-15. |
| Prompt:completion ratio | same, `models?view=week` | Measured each run (~38:1 in Sep 2026) |
| Model prices | `openrouter.ai/api/v1/models` + Internet Archive snapshots | Archive copies are cached in `data/cache/wayback/`; each run adds its own snapshot |
| World and country AI user share | Microsoft AI Diffusion Report via Our World in Data | Fallback: Microsoft GitHub CSV + `data/manual/global_adoption.csv` |
| US business AI use by sector | Census BTOS `National.xlsx` / `Sector.xlsx` | Q7 (use, last 2 weeks), Q24 (expect, next 6 months) |
| Usage frequency | Gallup, Pew | Entered by hand in `data/manual/intensity.csv`; add rows when new surveys come out |

If you get a free OpenRouter API key, the official `GET /api/v1/datasets/rankings-daily` endpoint
(daily data from 2025-01-01, top 50 models) becomes an option. It is listed in `config.yaml`, but the
pipeline does not call it yet.

## Metric definitions

- **Average price:** tokens-weighted blended $/1M tokens across named models,
  blend = (r·prompt + completion)/(r+1). Free and stealth models count as $0. The "Others" bucket
  (~35–50% of tokens) is excluded, and its token share is reported as *price coverage*.
- **Same-model price index:** a weekly chained index with last week's model mix held fixed at this
  week's prices. It moves only with real price changes, not with shifts to cheaper models.
- **Implied spend:** tokens × average price.
- **Elasticity:** the 12-week rolling OLS slope of Δln(tokens) on Δln(price), using 4-week smoothing.
  It describes correlation, not causation.
- **Adoption speed:** a logistic fit on the Census US series (pp per quarter), and the linear pp per quarter for the world.

## Caveats

OpenRouter carries only part of the market. Direct OpenAI, Anthropic and Google API traffic and
enterprise contracts don't show up. Use it for direction and relative change, not absolute market size.
