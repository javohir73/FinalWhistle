# Deployment Guide — PitchProphet

Architecture: **frontend on Vercel**, **backend + Postgres + daily cron on Render**.

```
Vercel (Next.js)  ──HTTPS──►  Render Web Service (FastAPI, Docker)  ──►  Render Postgres
                                        ▲
                              Render Cron (daily) → run_pipeline → writes predictions
```

---

## 1. Environment variables

### Backend (Render web service + cron)

| Variable | Required | Example | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://user:pass@host/db` | Auto-wired from the Render database. `postgres://`/`postgresql://` are normalized to the psycopg2 driver automatically. |
| `RECOMPUTE_TOKEN` | ✅ | (generated) | Secret guarding `POST /api/internal/recompute`. Render generates it. |
| `CORS_ORIGINS` | ✅ | `https://pitchprophet.vercel.app` | Comma-separated allowed frontend origins. **Set after the Vercel URL exists.** |
| `MODEL_VERSION` | ➖ | `poisson-elo-v0.1` | Stamped on predictions. |
| `CACHE_TTL_SECONDS` | ➖ | `600` | Read-cache lifetime; lets the cron's DB writes appear in the web process. |

### Frontend (Vercel)

| Variable | Required | Example | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | ✅ | `https://pitchprophet-api.onrender.com` | Backend base URL. Must be set for all environments (Production/Preview). |

---

## 2. Database migration / deploy notes

- The schema is owned by **Alembic**. The Render web service runs `alembic upgrade head` automatically before every deploy (`preDeployCommand` in `render.yaml`).
- After the **first** successful deploy the database is empty. Seed it once (either is fine):
  - Trigger the cron manually: Render dashboard → `pitchprophet-refresh` → **Run now**, or
  - Open a shell on the web service and run `python -m pipeline.run_pipeline`.
- The daily cron re-runs the full pipeline (idempotent) at 06:00 UTC.

---

## 3. Local production-style test (do this before deploying)

Build and run the backend exactly as Render will (Docker), pointed at local Postgres.

```bash
# 1. Local Postgres
docker compose up -d

# 2. Build the backend image (context = repo root)
docker build -f backend/Dockerfile -t pitchprophet-api .

# 3. Migrate + seed against local Postgres (host networking via host.docker.internal)
docker run --rm -e DATABASE_URL="postgresql://wc26:wc26@host.docker.internal:5432/wc26" \
  pitchprophet-api sh -c "cd /app/backend && alembic upgrade head"
docker run --rm -e DATABASE_URL="postgresql://wc26:wc26@host.docker.internal:5432/wc26" \
  pitchprophet-api python -m pipeline.run_pipeline

# 4. Run the API container
docker run --rm -p 8000:8000 \
  -e DATABASE_URL="postgresql://wc26:wc26@host.docker.internal:5432/wc26" \
  -e CORS_ORIGINS="http://localhost:3000" \
  pitchprophet-api
# → curl http://localhost:8000/api/health  and  /api/matches/upcoming

# 5. Frontend production build, pointed at the local API
cd frontend
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run start   # http://localhost:3000
```

> No Docker? You can do the same with the venv: `alembic upgrade head`, `python -m pipeline.run_pipeline`, then `uvicorn` — see the README "Local setup".

---

## 4. Deploy: Render (backend + DB + cron)

Click-by-click:

1. Push this repo to GitHub.
2. Go to **dashboard.render.com → New → Blueprint**.
3. Connect the repo. Render detects `render.yaml` and shows: 1 web service, 1 cron, 1 Postgres.
4. Click **Apply**. Render creates the database, builds the Docker image, and runs `alembic upgrade head` before the web service goes live.
5. When the web service is live, copy its URL (e.g. `https://pitchprophet-api.onrender.com`).
6. Open the **pitchprophet-api** service → **Environment** → set `CORS_ORIGINS` to your Vercel URL (you'll have it after step 5 of the Vercel section; you can set a placeholder now and update later).
7. Seed data: **pitchprophet-refresh** cron → **Run now** (or run `python -m pipeline.run_pipeline` from the web service Shell).
8. Verify: open `https://<api>/api/health` (should be `{"status":"ok",...}`) and `https://<api>/api/matches/upcoming`.

Notes:
- Free Postgres expires after ~90 days; upgrade the plan for anything long-lived.
- Free web services sleep when idle and cold-start on the next request (a few seconds).

## 5. Deploy: Vercel (frontend)

Click-by-click:

1. Go to **vercel.com → Add New → Project** and import the repo.
2. **Root Directory** → set to `frontend` (important — the Next.js app lives there).
3. Framework preset: **Next.js** (auto-detected).
4. **Environment Variables** → add `NEXT_PUBLIC_API_URL` = your Render API URL (e.g. `https://pitchprophet-api.onrender.com`). Add it for **Production** and **Preview**.
5. Click **Deploy**. Copy the resulting URL (e.g. `https://pitchprophet.vercel.app`).
6. Go back to Render → **pitchprophet-api** → Environment → set `CORS_ORIGINS` to that Vercel URL → save (the service redeploys).
7. Open the Vercel URL — the dashboard should load real predictions.

---

## 6. Post-deploy smoke checklist

- [ ] `GET https://<api>/api/health` returns `{"status":"ok"}`
- [ ] `GET https://<api>/api/matches/upcoming` returns 72 matches
- [ ] Vercel site loads and shows match cards (not an error state)
- [ ] A match detail page loads with reasons + probabilities
- [ ] Groups page shows 12 groups with qualification %
- [ ] No CORS errors in the browser console (fix = correct `CORS_ORIGINS`)
- [ ] Trigger the cron once; confirm predictions exist
