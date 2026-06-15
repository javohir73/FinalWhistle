# Deployment Guide — FinalWhistle

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
| `CORS_ORIGINS` | ✅ | `https://fifa-wc26-prediction.vercel.app` | Comma-separated allowed frontend origins. **Set after the Vercel URL exists.** |
| `MODEL_VERSION` | ➖ | `poisson-elo-v0.1` | Stamped on predictions. |
| `CACHE_TTL_SECONDS` | ➖ | `600` | Read-cache lifetime; lets the cron's DB writes appear in the web process. |
| `FOOTBALL_DATA_API_KEY` | ➖ | (from football-data.org) | Enables **live in-game scores**. Empty = feature off (no-op). Free key at football-data.org/client/register. |
| `FOOTBALL_DATA_COMPETITION` | ➖ | `WC` | Competition code for the live feed (World Cup). |
| `LIVE_MODE_ENABLED` | ➖ | `true` | Master switch for live mode. Live updates run only when this is `true` **and** an API key is set. |

### Live in-game scores (optional, free)

Live scores are pulled from [football-data.org](https://www.football-data.org) (free tier covers the World Cup). To turn it on during the tournament:

1. Create a free key at football-data.org and set `FOOTBALL_DATA_API_KEY` on the Render service.
2. Set `LIVE_MODE_ENABLED=true` on the same service (it restarts automatically).

That's it — **no external cron is required**. The backend refreshes scores
opportunistically (see `backend/app/live_refresh.py`): while a match window is
active (a game in play, or kickoff within the last 3 h / next 5 min), traffic on
the matches board triggers a background refresh at most once per minute. The
board polls every 30 s, so any viewer keeps scores live; idle hours make zero
upstream calls (free tier allows 10 req/min — we use ≤1).

Optionally, `POST /api/internal/refresh-live` (header `X-Recompute-Token:
<RECOMPUTE_TOKEN>`) still works as a belt-and-braces external trigger, e.g. a
[cron-job.org](https://cron-job.org) job during match windows — useful only if
you expect live viewers to be rare. Without an API key both paths are safe
no-ops. The matches board shows a LIVE badge + running score and minute.

### Frontend (Vercel)

| Variable | Required | Example | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | ✅ | `https://pitchprophet-api.onrender.com` | Backend base URL. Must be set for all environments (Production/Preview). |

---

## 2. Database migration / deploy notes (free tier)

Render's **free tier doesn't allow pre-deploy commands or cron jobs**, so migrations
and the daily data refresh run from **GitHub Actions** (`.github/workflows/refresh.yml`),
which connects to the Render Postgres over its external URL. This is free and runs
the full pipeline (migrate → ingest → Elo → stats → predictions).

One-time setup:
1. In Render, open **pitchprophet-db** → **Info** → copy the **External Database URL**.
2. In GitHub: repo → **Settings → Secrets and variables → Actions → New repository secret**
   named `DATABASE_URL` = that external URL.
3. Run the **refresh-data** workflow once (Actions tab → *refresh-data* → **Run workflow**)
   to apply migrations and seed the database. It then runs daily at 06:00 UTC.

The web service stays read-only and serves from cache (10-min TTL), so the
Action's DB writes appear within ~10 minutes without restarting the API.

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
3. Connect the repo. Render detects `render.yaml` and shows: **1 web service + 1 Postgres**.
4. Click **Apply**. Render creates the database and builds the Docker image.
5. When the web service is live, copy its URL (e.g. `https://pitchprophet-api.onrender.com`).
6. **Migrate + seed the DB** (see §2): copy the database's External URL → add it as the
   GitHub `DATABASE_URL` secret → run the **refresh-data** GitHub Action once.
7. Set `CORS_ORIGINS` on the **pitchprophet-api** service → **Environment** to your Vercel
   URL (you'll have it after the Vercel section; placeholder now, update later).
8. Verify: open `https://<api>/api/health` → `{"status":"ok",...}`, then `/api/matches/upcoming`
   (returns data after step 6 completes).

Notes:
- Free Postgres expires after ~90 days; upgrade the plan for anything long-lived.
- Free web services sleep when idle and cold-start on the next request (a few seconds).

## 5. Deploy: Vercel (frontend)

Click-by-click:

1. Go to **vercel.com → Add New → Project** and import the repo.
2. **Root Directory** → set to `frontend` (important — the Next.js app lives there).
3. Framework preset: **Next.js** (auto-detected).
4. **Environment Variables** → add `NEXT_PUBLIC_API_URL` = your Render API URL (e.g. `https://pitchprophet-api.onrender.com`). Add it for **Production** and **Preview**.
5. Click **Deploy**. Copy the resulting URL (e.g. `https://fifa-wc26-prediction.vercel.app`).
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
