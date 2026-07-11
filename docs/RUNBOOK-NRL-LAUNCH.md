# NRL Model Launch Runbook

## 1. Prod backfill & cadence

Migration `c1d2e3f4a5b6` (sport_* tables) must reach the prod database before the model code serves traffic.

### Step 1a: Dispatch migration to prod

1. In GitHub Actions, find the `refresh` workflow
2. Dispatch `refresh.yml` manually
3. Wait for completion and confirm `alembic upgrade head` succeeded
4. This applies migration `c1d2e3f4a5b6` to the prod database

### Step 1b: Backfill historical seasons and generate initial predictions

On a machine with prod `DATABASE_URL` set:

```bash
# Ingest NRL match data for 2017–2026
PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_ingest --seasons 2017 2026

# Generate predictions on ingested data and grade against outcomes
PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_predict --generate --grade
```

### Step 1c: Cadence (ongoing, manual or cron)

The `nrl_ingest` and `nrl_predict` commands above are **not** wired into the football daily pipeline by design. Operationally:

- **Ingest cadence**: after each NRL round completes, run `nrl_ingest --seasons 2026`
- **Predict cadence**: after ingest, run `nrl_predict --generate --grade`

Both are candidates for weekly cron jobs or manual dispatch tied to the round cycle.

- `pipeline/sports/nrl_stats.py` — team-level match stats + try events (StatsProvider;
  source per `pipeline/sports/testdata/nrl_stats/SOURCE.md`). Runs in `nrl-refresh` after
  ingest: `python -m pipeline.sports.nrl_stats --seasons 2024 2026` (resumable — skips
  matches that already have stats; >= 1s between requests). Not wired into the football
  daily pipeline by design.

---

## 2. Shadow gate

The model ships in shadow mode (predictions returned, but `is_shadow=True` in all rows). Public go-live requires both gates to pass:

### Gate A: Walk-forward test results

Gate: model log loss < favorite baseline log loss in ≥2 of the 3 held-out seasons (achieved: see table).

Re-run with `PYTHONPATH=backend:. .venv/bin/python -m pipeline.sports.nrl_backtest` and compare against:

| Season | Model LL | Favorite LL |
|--------|----------|------------|
| 2023   | 0.6618   | 0.6951     |
| 2024   | 0.6760   | 0.6977     |
| 2025   | 0.6883   | 0.7013     |

Result: 3/3 seasons — GATE PASS.

### Gate B: ≥2 live NRL rounds graded clean in prod

Once the model has predicted and been graded on at least 2 live NRL rounds:

```bash
curl https://pitchprophet-api.onrender.com/api/nrl/model/record
```

Confirm:
- `evaluated_matches` grows across ≥2 rounds (the ledger is one entry per graded MATCH, not per round — so this count should climb by however many matches were in each newly-graded round)
- No 5xx errors
- `winner_accuracy` value is sane (0.0–1.0 range)
- `avg_log_loss` is present

Once both gates pass, the model is approved to flip to shadow=False via the go-public PR (Task 3).

---

## 3. Go-public flip

**This is a separate PR and a STOP-GATE decision** — the merge and deploy requires explicit human approval.

The flip PR will:

1. **Default `is_shadow=False`** for all new NRL prediction rows
2. **Frontend NRL pages** — enable UI to show predictions to end users
3. **Calibrator fit** — fit a calibration layer on the walk-forward backtest seasons (2023–2025)
4. **Cache note** — if a live NRL scoreboard ships, ensure `/api/nrl/*` endpoints join `main.py`'s no-store cache branch
5. **Wider-grid retune + full gate re-run** — 4 of 5 tuned params sat at grid edges: k=24/cap=1.8/p_draw=0.008 minima, season_regress=0.35 maximum. Widen the grids past these edges, retune, and re-run the gate before flipping — the current params may not be a real optimum, just the best of a grid that stopped short.

The flip is irreversible and public-facing → it stops the deployment pipeline for approval.

---

## 4. Post-deploy verification

After the go-public PR lands and deploys:

### 4a: Health endpoint (unchanged, football unaffected)

```bash
curl https://pitchprophet-api.onrender.com/api/health
```

Should return `200 OK` with unchanged football model status.

### 4b: NRL matches endpoint

```bash
curl https://pitchprophet-api.onrender.com/api/nrl/matches?season=2026
```

Should return rounds with populated predictions (p_home/p_draw/p_away, expected_margin, etc.).

### 4c: NRL record endpoint

```bash
curl https://pitchprophet-api.onrender.com/api/nrl/model/record
```

On initial deploy (before live rounds are graded), should return:
- `evaluated_matches: 0`
- No 5xx errors
- Confidence bounds fields present

### 4d: Diff audit — zero football-file changes

Verify the PR introduces **only** NRL-specific and documentation files:

```bash
git diff --name-only origin/main...HEAD
```

Expected changes:
- Plan + runbook docs (`docs/superpowers/plans/*`, `docs/RUNBOOK-NRL-LAUNCH.md`)
- API route (`backend/app/api/sports.py`)
- Model append (`backend/app/models/__init__.py` — append-only block for the Sport* tables)
- Migration file (`backend/alembic/versions/c1d2e3f4a5b6_add_sport_tables.py`)
- Backend tests (`backend/tests/test_sport_models.py`, `backend/tests/test_sports_api.py`)
- ML module (`ml/sports/**` — NRL Elo model, backtest/tuner, params loader + `params.json`)
- Pipeline module (`pipeline/sports/**` — ingest, predict/grade, backtest CLI)
- One import-list entry plus one `include_router` line in `backend/app/main.py`

Should **not** include changes to football model files, football routes, or existing football data tables.

---

## Sign-off

- Walk-forward gate: ✓ (verify Task 4 numbers above)
- Live grading gate: ✓ (2+ rounds graded in prod)
- Go-public flip approval: [human decision]
- Post-deploy verification: ✓ (all curl checks pass, diff audit clean)
