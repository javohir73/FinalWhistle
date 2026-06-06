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

# 4. Run the backend (http://localhost:8000)
.venv/bin/uvicorn app.main:app --reload --app-dir backend

# 5. Run the frontend (http://localhost:3000)
cd frontend && npm run dev
```

Open http://localhost:3000 — the homepage shows a green "Connected" status if it can reach the backend's `/api/health`.

## Running tests

A step is never "done" until tests pass. Run **both** suites:

```bash
make test        # runs pytest (Python) + Jest (frontend)
make test-py     # Python only
make test-js     # frontend only
```

## Status

MVP in progress — see the task list for current state. Phases after MVP: live in-game updates, player-influence model, sentiment, Monte Carlo tournament simulator, user accounts.
