# PitchProphet — FIFA World Cup 2026 Prediction Platform

> ⚠️ For analytics, research, and entertainment only. **Not betting advice.** Predictions are probabilistic and never guaranteed.

An explainable AI dashboard that predicts FIFA World Cup 2026 outcomes — match win/draw/loss probabilities, scorelines, group standings, qualification odds, and tournament-winner probabilities — and explains *why* for each prediction.

- **Product spec:** [tasks/prd-wc26-prediction-platform.md](tasks/prd-wc26-prediction-platform.md)
- **Build plan / task list:** [tasks/tasks-wc26-prediction-platform.md](tasks/tasks-wc26-prediction-platform.md)

## Architecture (MVP)

```
Next.js frontend  ──REST──►  FastAPI backend  ──►  PostgreSQL
   (Vercel)                  (Railway/Render)        (source of truth)
                                   ▲
                          scheduled pipeline (cron)
                       fetch free data → rate → predict → store
```

The frontend never triggers a model run — predictions are precomputed by the pipeline and read from cache.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | Next.js (TypeScript), Tailwind CSS, shadcn/ui foundation, Recharts |
| Backend | Python, FastAPI, SQLAlchemy, Alembic |
| ML | pandas, numpy, scikit-learn (Elo + Poisson + logistic; XGBoost later) |
| Database | PostgreSQL |
| Tests | **Jest** (frontend) + **pytest** (Python) |

## Repository layout

```
backend/    FastAPI app, ORM models, API routers
ml/         prediction engine (Elo, Poisson, features, evaluation, simulation)
pipeline/   data ingestion + scheduled orchestration + team-name mapping
frontend/   Next.js dashboard
data/        raw/processed data (gitignored)
docs/        methodology and notes
tasks/       PRD + task list
```

## Local setup

Prerequisites: **Python 3.12+**, **Node 20+**, and **Docker** (for Postgres).

```bash
# 1. Clone, then create the environment files
cp .env.example .env                      # backend reads this
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local

# 2. Install everything (Python venv + frontend node_modules)
make install

# 3. Start Postgres
docker compose up -d

# 4. Apply migrations
cd backend && PYTHONPATH=. ../.venv/bin/alembic upgrade head && cd ..

# 5. Populate data + predictions (downloads free historical results, ~50k rows)
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_pipeline

# 6. Run the backend (http://localhost:8000). PYTHONPATH includes the repo root
#    so the recompute endpoint can import the ml/ and pipeline/ packages.
PYTHONPATH=backend:. .venv/bin/uvicorn app.main:app --reload

# 7. Run the frontend (http://localhost:3000)
cd frontend && npm run dev
```

Open http://localhost:3000 to see match predictions, group tables, and team pages.

## Data pipeline

```bash
# Full daily refresh: load structure -> ingest results -> Elo -> stats -> predict
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_pipeline

# Backtest the model against WC2018 & WC2022 (prints log-loss/Brier/accuracy)
PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_backtest
```

In production the daily refresh runs via `.github/workflows/refresh.yml`, which
POSTs to `/api/internal/recompute` on the deployed backend (set the `API_URL` and
`RECOMPUTE_TOKEN` repo secrets). See [docs/methodology.md](docs/methodology.md)
for how predictions are made and how accurate they are.

## Running tests

A step is never "done" until tests pass. Run **both** suites:

```bash
make test        # runs pytest (Python) + Jest (frontend)
make test-py     # Python only
make test-js     # frontend only
```

## Deployment

Full click-by-click instructions, env-var reference, and a local production-style
test are in **[DEPLOYMENT.md](DEPLOYMENT.md)**. Summary:

- **Frontend → Vercel** (root directory `frontend`, env `NEXT_PUBLIC_API_URL`).
- **Backend + Postgres + daily cron → Render** via the `render.yaml` blueprint
  (Docker image from `backend/Dockerfile`).

Required environment variables:

| Where | Variable | Purpose |
|---|---|---|
| Backend | `DATABASE_URL` | Postgres connection (auto-wired by Render) |
| Backend | `RECOMPUTE_TOKEN` | Secret for `POST /api/internal/recompute` |
| Backend | `CORS_ORIGINS` | Allowed frontend origin(s), e.g. the Vercel URL |
| Backend | `MODEL_VERSION`, `CACHE_TTL_SECONDS` | Optional tuning |
| Frontend | `NEXT_PUBLIC_API_URL` | Backend base URL |

Migrations run automatically on deploy (`alembic upgrade head`); seed data once
after the first deploy by running the refresh cron. See DEPLOYMENT.md for details.

## Status

MVP in progress — see the task list for current state. Phases after MVP: live in-game updates, player-influence model, sentiment, Monte Carlo tournament simulator, user accounts.
