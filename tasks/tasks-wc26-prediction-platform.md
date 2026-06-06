# Tasks: AI-Powered FIFA World Cup 2026 Prediction Platform (MVP)

Derived from [prd-wc26-prediction-platform.md](prd-wc26-prediction-platform.md).
Scope: **MVP only** (PRD Sections 4 & 15 — the Week 1–9 deliverable). Phases 2+ (live, player model, sentiment, tournament sim, accounts) will get their own task lists after the MVP ships.

## Relevant Files

### Repo root
- `README.md` - Project overview, setup, and run instructions.
- `.gitignore` - Ignore `node_modules`, `__pycache__`, `.env`, large `data/` files, build output.
- `docker-compose.yml` - Local Postgres (and optional Redis) for development.
- `.env.example` - Template for environment variables (DB URL, API base URL, app name).

### Backend (FastAPI) — `backend/`
- `backend/app/main.py` - FastAPI app entrypoint, CORS, router registration, health endpoint.
- `backend/app/db.py` - SQLAlchemy engine/session setup.
- `backend/app/config.py` - Settings loaded from env (DB URL, app name "PitchProphet", model version).
- `backend/app/models/__init__.py` - SQLAlchemy ORM models for all MVP tables.
- `backend/app/schemas/__init__.py` - Pydantic response/request schemas.
- `backend/app/api/matches.py` - `/api/matches/upcoming`, `/api/matches/{id}` routes.
- `backend/app/api/predictions.py` - `/api/predictions/{match_id}` route.
- `backend/app/api/teams.py` - `/api/teams`, `/api/teams/{id}` routes.
- `backend/app/api/groups.py` - `/api/groups`, `/api/groups/{id}` routes.
- `backend/app/api/internal.py` - `POST /api/internal/recompute` (token-protected) route.
- `backend/app/cache.py` - Simple cache layer (in-memory dict for MVP; Redis-ready interface).
- `backend/alembic/` - Database migrations.
- `backend/requirements.txt` - Python dependencies.
- `backend/tests/test_api.py` - API endpoint tests.
- `backend/tests/test_models.py` - ORM/schema tests.

### ML engine — `ml/`
- `ml/ratings/elo.py` - Elo computation and update logic.
- `ml/ratings/elo_test.py` - Tests: Elo update math, host bonus, sanity ranking.
- `ml/models/poisson.py` - Poisson goals model → W/D/L + scoreline grid.
- `ml/models/poisson_test.py` - Tests: probabilities sum to 1, symmetric inputs, known matchups.
- `ml/models/baseline_logistic.py` - Logistic regression baseline classifier.
- `ml/models/baseline_logistic_test.py` - Tests: training + predict shape.
- `ml/features/build_features.py` - Feature engineering (elo gap, form, H2H, goals profile, host bonus).
- `ml/features/build_features_test.py` - Tests: feature values, missing-data fallbacks.
- `ml/explain/reasons.py` - Generate plain-English reasons + confidence level from features.
- `ml/explain/reasons_test.py` - Tests: 3+ reasons produced, confidence thresholds.
- `ml/simulate/group_sim.py` - Per-group qualification probability via simulation over remaining fixtures.
- `ml/simulate/group_sim_test.py` - Tests: probabilities sum sensibly, deterministic seed.
- `ml/evaluation/backtest.py` - Backtest harness (train-to-date → predict tournament → log-loss).
- `ml/evaluation/backtest_test.py` - Tests on a tiny fixture dataset.
- `ml/evaluation/calibration.py` - Reliability curve + Platt/isotonic calibration.
- `ml/evaluation/calibration_test.py` - Tests: calibrated output monotonic.
- `ml/evaluation/naive_baseline.py` - Naive "higher-FIFA-rank wins" baseline for the beat-the-baseline gate.

### Pipeline — `pipeline/`
- `pipeline/team_mapping.py` - Canonical team-name mapping table + normalization function.
- `pipeline/team_mapping_test.py` - Tests: known aliases resolve (e.g., "Korea Republic" → "South Korea").
- `pipeline/ingest/historical_results.py` - Download + clean Kaggle international results CSV.
- `pipeline/ingest/fifa_rankings.py` - Download + clean FIFA rankings.
- `pipeline/ingest/wc26_structure.py` - Load WC2026 teams, 12 groups, 104 fixtures (seed data).
- `pipeline/ingest/football_data_odds.py` - Download historical odds (calibration use only, not user-facing).
- `pipeline/data/wc26_teams.json` - Seed: 48 teams + confederations + host flags.
- `pipeline/data/wc26_groups.json` - Seed: 12 groups and their team assignments.
- `pipeline/data/wc26_fixtures.json` - Seed: 104 fixtures (stage, kickoff, venue, host_team_id).
- `pipeline/run_pipeline.py` - Orchestrator: fetch → clean → load → rate → predict → store.
- `pipeline/run_pipeline_test.py` - Smoke test of the full pipeline on a small sample.
- `.github/workflows/refresh.yml` - Scheduled GitHub Action that calls the pipeline / recompute endpoint.

### Frontend (Next.js) — `frontend/`
- `frontend/app/layout.tsx` - Root layout, nav, persistent `DisclaimerBanner`.
- `frontend/app/page.tsx` - Home / Prediction Dashboard.
- `frontend/app/match/[id]/page.tsx` - Match detail page.
- `frontend/app/groups/page.tsx` - Groups overview.
- `frontend/app/groups/[id]/page.tsx` - Single group detail.
- `frontend/app/team/[id]/page.tsx` - Team profile page.
- `frontend/app/about/page.tsx` - About / Methodology + full disclaimer.
- `frontend/lib/api.ts` - Typed API client for the FastAPI backend.
- `frontend/lib/format.ts` - Formatters (percentages, scorelines, confidence labels).
- `frontend/components/MatchCard.tsx` - Core match card (flags, winner, W/D/L bar, score, confidence).
- `frontend/components/ProbabilityBar.tsx` - W/D/L stacked horizontal bar.
- `frontend/components/ConfidenceBadge.tsx` - High/Med/Low badge.
- `frontend/components/ScoreDistributionChart.tsx` - Recharts scoreline bar chart.
- `frontend/components/ReasonsList.tsx` - "Why this prediction" bullet list.
- `frontend/components/FeatureImportanceChart.tsx` - Top-factors bar chart.
- `frontend/components/GroupTable.tsx` - Standings table with qualification bars.
- `frontend/components/QualificationBar.tsx` - Per-team qualification probability bar.
- `frontend/components/FormStrip.tsx` - Colored last-5/10 form strip.
- `frontend/components/TrendChart.tsx` - Team prediction trend line chart.
- `frontend/components/OddsCompare.tsx` - Stubbed odds-comparison (degrades gracefully; Phase 4).
- `frontend/components/DisclaimerBanner.tsx` - Persistent disclaimer.
- `frontend/components/__tests__/MatchCard.test.tsx` - Component test for the core card.

### Notes — Testing Policy

**Every parent task (step) ends with a test gate. A step is not "done" until its tests are written AND passing.** Tools are split by language:

- **Frontend (TypeScript) → Jest** + React Testing Library. Test files are `*.test.tsx` / `*.test.ts` co-located with the code. Run with `npx jest [optional/path]`.
- **Backend / ML / pipeline (Python) → pytest.** Test files are `*_test.py` co-located with the code. Run with `pytest` from `backend/`, `ml/`, or `pipeline/`.
- *(Why two runners: Jest cannot execute Python, and the ML must stay in Python for scikit-learn/XGBoost/Poisson. This was the chosen approach — Jest where it's TypeScript, pytest where it's Python.)*
- A handy root script (e.g. `make test` or an npm script `test:all`) should run both suites so "the end of each step" is one command.

### Other Notes

- The MVP cache (`backend/app/cache.py`) can be a simple in-memory dict behind an interface; swap to Redis later with no caller changes.
- Scheduling starts as a **GitHub Actions cron** hitting `POST /api/internal/recompute` — no Airflow/Prefect for MVP.
- Keep `OddsCompare` and `/api/odds` stubbed returning `{ "available": false }` per PRD Resolved Decision #1.
- The app name lives in one config constant (`PitchProphet`, placeholder) per PRD Resolved Decision #5.

## Instructions for Completing Tasks

**IMPORTANT:** As you complete each task, check it off by changing `- [ ]` to `- [x]`. Update the file after each sub-task, not just after a whole parent task.

## Tasks

- [x] 0.0 Initialize repository and feature branch
  - [x] 0.1 Run `git init` (this folder is not yet a git repo), then make an initial commit of the PRD + task files
  - [x] 0.2 Add a root `.gitignore` (node_modules, `__pycache__`, `.env`, build output, large `data/` files)
  - [x] 0.3 Create and checkout the feature branch: `git checkout -b feature/wc26-mvp`
  - [x] 0.4 **Test gate:** Add the testing toolchains — `pytest` to `backend/requirements.txt` and a `frontend/` Jest + React Testing Library config; add a root `test:all` script that runs both. Verify each runner executes (even with zero tests) and commit.

- [ ] 1.0 Scaffold the monorepo and prove end-to-end deploy
  - [x] 1.1 Create the folder structure from PRD §18 (`frontend/`, `backend/`, `ml/`, `pipeline/`, `data/`, `docs/`)
  - [x] 1.2 Initialize the FastAPI app (`backend/app/main.py`) with a `/api/health` endpoint returning `{status:"ok", app:"PitchProphet"}`
  - [x] 1.3 Add `backend/requirements.txt` (fastapi, uvicorn, sqlalchemy, alembic, psycopg2-binary, pydantic-settings, pandas, numpy, scikit-learn, pytest)
  - [x] 1.4 Add `docker-compose.yml` with a local Postgres service and wire `backend/app/db.py` + `backend/app/config.py` to it
  - [x] 1.5 Initialize the Next.js app (TypeScript) in `frontend/`, add Tailwind, shadcn/ui, and Recharts
  - [x] 1.6 Create `frontend/lib/api.ts` and a homepage that calls `/api/health` and renders the status (proves frontend↔backend)
  - [x] 1.7 Add `.env.example` and document local setup in `README.md`
  - [ ] 1.8 Deploy: frontend to Vercel, backend + Postgres to Railway/Render; confirm the deployed homepage reads the deployed health endpoint *(DEFERRED by user — revisit after the model is proven; build locally for now)*
  - [ ] 1.9 Commit and verify the deployed URLs work end-to-end *(DEFERRED with 1.8)*
  - [x] 1.10 **Test gate:** pytest test for `/api/health` (returns 200 + correct payload); Jest test that `frontend/lib/api.ts` calls the health endpoint and the homepage renders the status. Run `test:all`; all green before moving on.

- [ ] 2.0 Build the database schema and data-ingestion pipeline
  - [x] 2.1 Define SQLAlchemy models for MVP tables (`tournaments`, `teams`, `groups`, `group_teams`, `matches` incl. `venue_country`/`host_team_id`, `historical_matches`, `team_stats`, `predictions`, `standings`) per PRD §10
  - [x] 2.2 Configure Alembic and generate the initial migration; apply it to local Postgres *(migration generated + applied/verified on SQLite; Postgres apply just needs `docker compose up` later)*
  - [x] 2.3 Build `pipeline/team_mapping.py` canonical name map + `normalize_team_name()`; write tests for known aliases (West Germany→Germany, Korea Republic→South Korea, etc.)
  - [ ] 2.4 Create WC2026 seed data files (`wc26_teams.json`, `wc26_groups.json`, `wc26_fixtures.json`) — all 48 teams, 12 groups, 104 fixtures, with `host_team_id` set where a host plays at home
  - [ ] 2.5 Build `pipeline/ingest/wc26_structure.py` to load the seed data into the DB (idempotent upserts)
  - [ ] 2.6 Build `pipeline/ingest/historical_results.py` — download Kaggle international results CSV, normalize names, dedupe, load into `historical_matches`
  - [ ] 2.7 Build `pipeline/ingest/fifa_rankings.py` — load FIFA rankings; populate `teams.fifa_rank`
  - [ ] 2.8 Build `pipeline/ingest/football_data_odds.py` — download historical odds for calibration use only (store separately; not user-facing)
  - [ ] 2.9 Compute and store basic `team_stats` (goals for/against, clean sheets, form_points_last10) from historical matches
  - [ ] 2.10 **Test gate (pytest):** team-mapping alias tests; ingestion smoke test on a small sample (verify row counts, no null team references, no duplicate matches); a model-creation/migration test that the schema builds. All green before moving on.

- [ ] 3.0 Build the prediction engine
  - [ ] 3.1 Implement `ml/ratings/elo.py` — Elo init, K-factor, margin-of-victory weighting, competition weighting, and the +60 host bonus (per Decision #2); write tests
  - [ ] 3.2 Run Elo over all historical matches and store current `teams.elo_rating`; sanity-check top teams (Brazil/France/Argentina near the top)
  - [ ] 3.3 Implement `ml/models/poisson.py` — attack/defense strengths → expected goals → full scoreline grid → W/D/L + most-likely score + score probability; write tests
  - [ ] 3.4 Implement `ml/features/build_features.py` — elo gap, form, H2H, goals profile, host flag; with cold-start fallbacks (Elo→FIFA→confederation); write tests for missing data
  - [ ] 3.5 Implement `ml/models/baseline_logistic.py` — logistic W/D/L classifier on the engineered features; write tests
  - [ ] 3.6 Implement `ml/explain/reasons.py` — derive confidence (High/Med/Low) from probability spread + data availability, and generate 3+ plain-English reasons from top features; write tests
  - [ ] 3.7 Implement `ml/simulate/group_sim.py` — simulate remaining group fixtures to produce per-team qualification probability and a predicted final table; write tests with a fixed seed
  - [ ] 3.8 Wire a `generate_predictions()` function that, for every upcoming match, produces the full prediction object matching PRD §17
  - [ ] 3.9 **Test gate (pytest):** Elo update math + host bonus + sanity ranking; Poisson probabilities sum to 1 and known matchups behave; feature fallbacks on missing data; reasons returns 3+ items and correct confidence buckets; group-sim is deterministic with a fixed seed; `generate_predictions()` output matches the PRD §17 shape. All green before moving on.

- [ ] 4.0 Backtest, calibrate, and validate the model
  - [ ] 4.1 Implement `ml/evaluation/naive_baseline.py` — predict the higher-FIFA-ranked team; produce probabilities for log-loss comparison
  - [ ] 4.2 Implement `ml/evaluation/backtest.py` — train on data up to each tournament, predict WC2018 and WC2022, compute log-loss, Brier, accuracy
  - [ ] 4.3 Run the backtest; confirm the model **beats the naive baseline on log-loss** (PRD Goal #3) — gate further work on this
  - [ ] 4.4 Implement `ml/evaluation/calibration.py` — reliability curve + Platt/isotonic; apply and re-measure
  - [ ] 4.5 Verify calibration: a "60%" bucket resolves ≈60% in backtests (PRD Goal #2); document results in `docs/methodology.md`
  - [ ] 4.6 Tune the few model knobs (Elo K-factor, form window, Poisson dampening) using time-based splits only; avoid overfitting
  - [ ] 4.7 **Test gate (pytest):** backtest runs on a tiny fixture dataset and returns sane metrics; naive-baseline produces valid probabilities; an assertion test that the model's log-loss < baseline's (the PRD Goal #3 gate, encoded as a test); calibration output is monotonic. All green before moving on.

- [ ] 5.0 Build the FastAPI backend
  - [ ] 5.1 Define Pydantic response schemas matching the PRD §17 prediction contract (incl. `model_version`, `generated_at`, stubbed `odds_comparison.available=false`)
  - [ ] 5.2 Implement `/api/matches/upcoming` and `/api/matches/{id}` (joins team + prediction data)
  - [ ] 5.3 Implement `/api/predictions/{match_id}` returning current + historical predictions (for the trend chart)
  - [ ] 5.4 Implement `/api/teams` and `/api/teams/{id}` (form, history, strengths/weaknesses, prediction trend)
  - [ ] 5.5 Implement `/api/groups` and `/api/groups/{id}` (standings + qualification probabilities)
  - [ ] 5.6 Implement `POST /api/internal/recompute` protected by a shared secret token; it runs the pipeline + prediction generation
  - [ ] 5.7 Implement `backend/app/cache.py` (in-memory interface, Redis-ready) and cache the read endpoints; ensure reads never trigger a model run (PRD §7 key principle)
  - [ ] 5.8 Ensure every prediction write logs a timestamped row with `model_version` (PRD Req #20) for later accuracy tracking
  - [ ] 5.9 **Test gate (pytest):** every endpoint covered for happy path + a 404/not-found case; schema-conformance test that prediction responses match the PRD §17 contract (incl. stubbed `odds_comparison.available=false`); a test that read endpoints serve from cache and do NOT trigger a model run; a test that prediction writes log `model_version` + timestamp. All green before moving on.

- [ ] 6.0 Build the Next.js dashboard
  - [ ] 6.1 Set up the root layout with nav and the persistent `DisclaimerBanner` (PRD Req #18); make it mobile-first
  - [ ] 6.2 Build shared components: `ProbabilityBar`, `ConfidenceBadge`, `FormStrip`, `OddsCompare` (stub)
  - [ ] 6.3 Build `MatchCard` and the Home / Prediction Dashboard with filters (by group, date, team search)
  - [ ] 6.4 Build the Match detail page: full W/D/L, `ScoreDistributionChart`, `ReasonsList`, `FeatureImportanceChart`, H2H summary
  - [ ] 6.5 Build the Groups overview + single group page with `GroupTable` and `QualificationBar`
  - [ ] 6.6 Build the Team profile page: hero, form strip, historical WC performance, strengths/weaknesses, `TrendChart`
  - [ ] 6.7 Build the About / Methodology page with the full disclaimer and data-source credits
  - [ ] 6.8 Verify responsiveness on mobile and target first-paint < 2.5s (PRD Goal #5); add loading/empty/error states
  - [ ] 6.9 **Test gate (Jest + React Testing Library):** unit tests for `ProbabilityBar` (segments sum to 100%), `ConfidenceBadge` (correct label/color per level), `MatchCard` (renders winner, score, confidence), and `OddsCompare` (degrades gracefully when unavailable); render tests for each page with mocked API data, including loading/empty/error states; a test asserting the `DisclaimerBanner` is present in the layout. All green before moving on.

- [ ] 7.0 Wire the scheduled refresh and deploy the MVP
  - [ ] 7.1 Build `pipeline/run_pipeline.py` orchestrating fetch → clean → load → rate → predict → store; make each step idempotent and logged
  - [ ] 7.2 Add `.github/workflows/refresh.yml` — daily cron that calls `POST /api/internal/recompute` (or runs the pipeline) with the secret token
  - [ ] 7.3 Add failure alerting (job failure notification) so stale-data/pipeline breaks are visible (PRD risk table)
  - [ ] 7.4 Run a full end-to-end refresh against production; confirm predictions populate for all 104 fixtures
  - [ ] 7.5 Final QA pass: every match has a prediction + 3 reasons + confidence; groups show qualification probs; disclaimer present on all pages
  - [ ] 7.6 **Test gate:** pytest pipeline smoke test (full fetch→store run on a small sample is idempotent — re-running doesn't duplicate rows); a CI step in `.github/workflows/refresh.yml` (or a separate CI workflow) that runs `test:all` so both suites must pass before deploy.
  - [ ] 7.7 Update `README.md` with architecture, setup, and the live URL; run the full `test:all` suite one final time (all green); merge `feature/wc26-mvp`; **deploy and share the MVP**
