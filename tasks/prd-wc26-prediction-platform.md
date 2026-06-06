# PRD: AI-Powered FIFA World Cup 2026 Prediction Platform

**Status:** Draft v1
**Date:** 2026-06-06
**Author:** Project owner (with AI assistance)
**Target reader:** A junior developer who is comfortable building apps but is new to machine learning.

---

## 0. How to read this document

This is a long PRD because the product is large. To keep it buildable, it is organized around a **strict MVP** (what you build first and can actually finish) and **later phases** (what you add once the MVP works). If you only read three sections, read:

1. **Section 4 — Functional Requirements (MVP)**
2. **Section 15 — What to build first**
3. **Section 14 — Development timeline**

Decisions already locked in (from project owner):

- **Primary audience:** Casual football fans first. Analysts later.
- **Data budget:** $0 in MVP. Free and open data sources only. No paid live or odds feeds yet.
- **Live in-game prediction:** Phase 2, not MVP.
- **Builder skill level:** Junior — learning full-stack and ML at the same time. The PRD favors the simplest stack and explains ML gently.

---

## 1. Introduction / Overview

**The feature:** A web dashboard that predicts FIFA World Cup 2026 outcomes — match win/draw/loss probabilities, predicted scorelines, group standings, qualification odds, knockout-round probabilities, and the overall tournament-winner probability — and **explains why** each prediction was made.

**The problem it solves:** Football fans and analysts have lots of raw data (results, rankings, form) but no single place that turns it into clear, trustworthy, explained predictions for WC2026. Existing prediction sites are either black boxes (just a number) or buried in spreadsheets. This product makes predictions **visual, explainable, and updatable**.

**The goal:** Ship an MVP that, using only free data, gives credible pre-match predictions and a live-simulated tournament outlook for WC2026, with a clean dashboard a casual fan can understand in 10 seconds and an analyst can dig into. Then layer in live match updates, player-influence modeling, sentiment, and a full Monte Carlo tournament simulator.

**One-line pitch:** *"FiveThirtyEight-style World Cup predictions, but explainable and built in public."*

---

## 2. Goals

Measurable objectives:

1. **Coverage:** Store all 48 WC2026 teams, all 12 groups, and the full match schedule (104 matches) in the database.
2. **Prediction quality (MVP):** Produce a win/draw/loss probability + predicted scoreline for every upcoming match. Predictions must be **calibrated** — when the model says "60%", that outcome should happen ~60% of the time in backtests.
3. **Backtested benchmark:** The MVP model must beat a naive baseline (always predict the higher-FIFA-ranked team) on log-loss when backtested against WC2018 and WC2022.
4. **Explainability:** Every prediction shows at least 3 plain-English reasons ("Brazil ranked higher", "strong recent form", "won last 2 head-to-heads").
5. **Performance:** Dashboard first meaningful paint < 2.5s on mobile; prediction pages served from cache.
6. **Maintainability:** A single scheduled job refreshes data and re-runs predictions without manual code changes.

Non-measurable but important:

7. Casual fans understand a prediction without reading docs.
8. The data layer is **source-agnostic** so paid feeds can be added later without rewrites.

---

## 3. User Stories

**Casual fan**
- As a fan, I want to see who is predicted to win an upcoming match, so I can talk about it with friends.
- As a fan, I want a predicted scoreline and a confidence level, so I know how sure the model is.
- As a fan, I want to see my team's chance of getting out of the group, so I can follow their journey.
- As a fan, I want simple reasons for a prediction, so I trust it isn't random.
- As a fan, I want the dashboard to work well on my phone.

**Engaged fan / analyst**
- As an analyst, I want to compare the model's probability to bookmaker odds, so I can spot disagreements ("value").
- As an analyst, I want to see which factors mattered most for a prediction.
- As an analyst, I want a team's prediction trend over time.
- As an analyst, I want tournament-winner probabilities from a Monte Carlo simulation (Phase 3).

**Operator (you)**
- As the operator, I want data to refresh on a schedule so the site stays current with no manual work.
- As the operator, I want to backtest the model against past World Cups so I can trust it before launch.

---

## 4. Functional Requirements — MVP

> The MVP is **pre-match only**. No live in-game updates. No paid data. The numbered list below is the contract for the first shippable version.

### 4.1 Data & ingestion
1. The system must store all WC2026 teams, groups, and the full fixture list.
2. The system must import historical international match results (results, dates, venue, neutral-ground flag) from free sources.
3. The system must import or compute FIFA rankings and an **Elo rating** per team over time.
4. The system must run a **scheduled refresh job** (daily) that pulls new results, recomputes ratings, and regenerates predictions.
5. The system must handle missing data gracefully (e.g., a team with few recent matches falls back to FIFA ranking + confederation strength).

### 4.2 Prediction engine (MVP model)
6. The system must compute, for every upcoming match, a probability of **home/team-A win, draw, team-B win**. (At a neutral World Cup, "home" = no home advantage unless host nation.)
7. The system must produce a **most-likely scoreline** and the probability of that scoreline.
8. The system must produce a **confidence level** (High / Medium / Low) derived from how far apart the probabilities are and how much data backs the teams.
9. The system must produce **3+ plain-English reasons** per prediction, generated from the features that moved the prediction most.
10. The system must compute, per group, each team's **qualification probability** (advance from group) using simple simulation over remaining fixtures.
11. The system must produce a **predicted final group table** (points, GD, GF).

### 4.3 Dashboard (web UI)
12. **Home / Prediction Dashboard:** list of upcoming matches with predicted winner, W/D/L bar, predicted score, confidence badge.
13. **Match detail page:** full probabilities, predicted score distribution, reasons, head-to-head summary, and odds comparison (if free odds available; otherwise hidden).
14. **Group page:** the 12 groups with live-ish standings and qualification probabilities.
15. **Team profile page:** squad placeholder, recent form (last 5–10 results), historical WC performance, strengths/weaknesses summary, and a prediction-trend chart.
16. ~~**Odds comparison (basic):** where free odds exist, show model probability vs implied bookmaker probability and flag the difference.~~ **DEFERRED to Phase 4** (see Resolved Decision #1). MVP shows no user-facing odds; historical odds are used internally for calibration only. The `OddsCompare` component is stubbed to degrade gracefully.
17. The dashboard must be **mobile-first and responsive**.
18. Every page must show a clear **disclaimer**: "For analytics and entertainment. Not betting advice."

### 4.4 Operability
19. Predictions must be **cached** and served fast; recomputation happens in the background job, not on user request.
20. The system must log each prediction with a timestamp and the model version, so accuracy can be evaluated later.

---

## 5. Non-Goals (Out of Scope for MVP)

To keep the MVP finishable, the MVP will **NOT** include:

- ❌ Live in-game probability updates (Phase 2).
- ❌ Real-time WebSocket/SSE infrastructure (Phase 2).
- ❌ Paid data APIs of any kind (Sportmonks, API-Football paid tiers, paid odds, social APIs).
- ❌ Player-level influence modeling and injury impact (Phase 3) — MVP is team-level only.
- ❌ Social media sentiment ingestion (Phase 4).
- ❌ Full Monte Carlo bracket simulator with knockout visualization (Phase 3) — MVP does simple per-group qualification sim only.
- ❌ User accounts, login, favorites, alerts/notifications (Phase 5).
- ❌ Neural networks / deep learning (Phase 3+ if ever; gradient boosting first).
- ❌ Native mobile apps (responsive web only).

These are listed not as "never" but as "not now". The architecture must leave room for them.

---

## 6. Recommended Tech Stack

Chosen for a junior builder: popular, well-documented, free tiers, minimal moving parts.

| Layer | Choice | Why |
|---|---|---|
| **Frontend** | Next.js (React) + TypeScript, Tailwind CSS, shadcn/ui, Recharts | One framework for pages + API routes; huge community; charts are easy with Recharts. |
| **Backend / ML API** | Python + FastAPI | Python is where the ML lives (pandas, scikit-learn, XGBoost). FastAPI is simple and fast. |
| **ML libraries** | pandas, numpy, scikit-learn, **XGBoost/LightGBM**, plus a small Poisson/Elo module you write yourself | Gradient boosting is the workhorse; Elo + Poisson are simple and interpretable. No deep learning needed. |
| **Database** | PostgreSQL | Relational data fits perfectly (teams, matches, predictions). |
| **ORM / migrations** | SQLAlchemy + Alembic (Python) | Clean schema management. |
| **Cache** | Redis (optional in MVP) | Cache predictions and group tables. Can start without it and add later. |
| **Scheduling** | Start with **cron** (or GitHub Actions scheduled workflow). Move to **Prefect** in Phase 2. | Don't install Airflow as a junior. A daily cron job is enough for pre-match. |
| **Deployment** | Frontend on **Vercel** (free). Backend + DB on **Railway** or **Render** (free/cheap tiers). | Cheapest path to live. |
| **Data fetching/scraping** | Python `requests` + `pandas.read_csv`/`read_html`; `BeautifulSoup` for light scraping | Free data is mostly CSV/HTML. |

**Architecture note:** Keep the ML in Python (FastAPI), keep the UI in Next.js, talk over a small REST API. Don't try to do ML in JavaScript.

---

## 7. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USERS (browser / mobile web)          │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS
                  ┌─────────▼──────────┐
                  │  Next.js frontend  │  (Vercel)
                  │  pages + Recharts  │
                  └─────────┬──────────┘
                            │ REST (JSON)
                  ┌─────────▼──────────┐
                  │   FastAPI backend  │  (Railway/Render)
                  │  /matches /predict │
                  │  /teams /groups    │
                  └───┬───────────┬────┘
                      │           │
              reads   │           │ reads/writes
              cache   │           │
              ┌───────▼───┐   ┌───▼────────────┐
              │   Redis   │   │   PostgreSQL   │
              │ (optional)│   │  source of     │
              └───────────┘   │  truth         │
                              └───▲────────────┘
                                  │ writes
              ┌───────────────────┴───────────────────┐
              │      Scheduled pipeline (cron)         │
              │  1. fetch results / rankings (free)    │
              │  2. clean + load into Postgres         │
              │  3. recompute Elo + features           │
              │  4. run model → write predictions      │
              │  5. run group qualification sim        │
              └─────────────────┬──────────────────────┘
                                │ pulls from
        ┌───────────────────────▼───────────────────────────┐
        │  FREE DATA SOURCES (Kaggle CSVs, football-data,     │
        │  StatsBomb open data, FIFA ranking pages, fixtures) │
        └─────────────────────────────────────────────────────┘
```

**Data flow in one sentence:** A daily job pulls free data → cleans and stores it in Postgres → recomputes ratings and features → runs the model → saves predictions → the frontend just reads cached predictions through FastAPI.

**Key principle:** The frontend never triggers a model run. Predictions are pre-computed by the pipeline and read instantly.

**Phase 2 addition (live):** add a `live-ingest` worker that polls a live-score source, writes to a `live_events` table, and pushes updates to the browser via SSE. The in-game model reads current match state and overwrites the live probability.

---

## 8. Data Source Recommendations

> MVP rule: **free and open only.** Paid sources are documented for later phases so the architecture can plan for them.

### 8.1 Free / open (use in MVP)

| Source | What it provides | Cost | Reliability | Update freq | How used in model |
|---|---|---|---|---|---|
| **Kaggle: "International football results 1872–present"** | Every international match result, venue, neutral flag | Free | High (community-maintained) | Periodic dumps | Core training data for Elo, Poisson, form, H2H |
| **football-data.co.uk** | Club + some intl results, plus historical **odds** | Free | High | Weekly | Historical odds for calibration + odds-comparison practice |
| **StatsBomb Open Data (GitHub)** | Detailed event data (xG, passes, shots) for select competitions incl. some World Cups/Euros | Free | Very high | Static repo | Feature engineering: xG, shot quality, set-pieces (where covered) |
| **FIFA rankings** (official site / Kaggle mirror) | Monthly FIFA ranking + points per team | Free | High | Monthly | Strength feature + cold-start fallback |
| **Elo ratings** (eloratings.net data / compute yourself) | Continuously updated team Elo | Free (compute) | High | Per match | Primary strength feature |
| **Wikipedia / official FIFA fixtures** | WC2026 schedule, groups, venues | Free | High | As scheduled | Fixtures + group structure |
| **Confederation info** (static) | UEFA/CONMEBOL/etc. membership + rough strength | Free | High | Static | Confederation-strength feature, cold start |

### 8.2 Paid / later phases (document now, buy later)

| Source | What it provides | Cost (approx) | Phase |
|---|---|---|---|
| **API-Football** | Fixtures, live scores, lineups, stats, some odds | Free tier (limited) → ~$15–40/mo | Phase 2 (live), some free-tier use possible earlier |
| **Sportmonks** | Rich football data, live, xG, lineups | Paid (€/mo tiers) | Phase 2/3 |
| **The Odds API / OddsAPI** | Pre-match + live odds across bookmakers | Free tier (limited calls) → paid | Phase 2 (odds), basic free-tier in MVP if time allows |
| **News API (newsapi.org / GDELT)** | Headlines, articles | Free tier / GDELT free | Phase 4 (sentiment) |
| **X/Twitter, Reddit, TikTok APIs** | Social posts | Paid / restricted | Phase 4 (sentiment) |
| **Official squad sources / FBref, Transfermarkt (scrape carefully, respect ToS)** | Squads, minutes, injuries, market values | Free-ish (scraping risk) | Phase 3 (player model) |

**Cold-start strategy (important for a tournament):** WC2026 has new qualifiers with thin data. When a team has few recent matches, fall back in this order: Elo → FIFA ranking → confederation average. Always have a default so no match is un-predictable.

---

## 9. Machine Learning Strategy

This section is written for someone new to ML. Build models in this order; each one is useful on its own.

### 9.1 The mental model
A football prediction model answers: *given two teams and the match context, what's the probability of each outcome and the likely score?* We get there with **strength ratings** (how good is each team) + **a goals model** (turn strength difference into goals) + **a learner** (gradient boosting) that blends many features.

### 9.2 Model roadmap (simplest → most advanced)

**Step 1 — Elo rating model (MVP, build first).**
- A single number per team, updated after each match. Higher Elo = stronger.
- Gives a quick win/draw/loss estimate from the Elo gap.
- *Why first:* trivial to implement, interpretable, no training needed, strong baseline.

**Step 2 — Poisson goals model (MVP).**
- Model goals scored as a Poisson distribution. Each team has an attack strength and defense strength; combine them to get expected goals for each side, then compute the probability of every scoreline (0-0, 1-0, 2-1, …).
- From the scoreline grid you get W/D/L probabilities **and** a predicted score. This is the MVP's main engine.
- *Why:* gives scorelines and draw probabilities naturally — Elo alone struggles with draws.

**Step 3 — Logistic regression baseline (MVP, for evaluation).**
- A simple classifier predicting W/D/L from a handful of features (Elo gap, FIFA rank gap, recent form, H2H).
- *Why:* a transparent baseline to compare the fancier model against. If gradient boosting can't beat this, something's wrong.

**Step 4 — Gradient boosting (XGBoost/LightGBM) (MVP if time, else Phase 2).**
- The workhorse. Feed it engineered features; it learns interactions automatically.
- Output W/D/L probabilities; keep Poisson for scorelines, or train a second model for goals.
- *Why:* best accuracy-per-effort for tabular data; gives feature importances → powers explanations.

**Step 5 — Monte Carlo tournament simulator (Phase 3).**
- Use the match model to simulate the whole tournament thousands of times (group → knockout). Count how often each team wins to get tournament-winner %, reach-final %, etc.
- *Why:* the only honest way to get tournament-level probabilities.

**Step 6 — Live in-game win-probability model (Phase 2).**
- A separate model that takes current score, minute, red cards, and pre-match strength → updates W/D/L live.
- Start simple: adjust the pre-match Poisson by remaining minutes and current scoreline; upgrade to a trained in-game model later.

**Step 7 — Bayesian / neural approaches (optional, much later).**
- Bayesian models (e.g., hierarchical Poisson) handle uncertainty elegantly; neural nets only if data volume justifies it. **Not needed for a strong product.**

### 9.3 Feature engineering (what goes into the model)
- **Strength:** Elo, FIFA ranking, confederation strength.
- **Form:** points/goals over last 5–10 matches; weighted so recent matters more.
- **Head-to-head:** recent H2H record and goal margins.
- **Context:** neutral venue (almost always true at a WC); **host bonus of +60 Elo applied only when a host nation plays in its own country** (see Resolved Decision #2); rest days, travel distance (Phase 2+); competition importance (qualifier vs friendly weighting).
- **Goals profile:** average goals scored/conceded, clean-sheet rate.
- **(Phase 3) Player:** squad strength index, key-player availability, GK quality.

### 9.4 Data cleaning & missing data
- Normalize team names (Germany vs "West Germany", "Korea Republic" vs "South Korea") with a mapping table — **this is the #1 silent bug source.**
- Deduplicate matches present in multiple datasets.
- Missing stats → fall back per the cold-start order (Section 8.2). Never drop a fixture; always produce a prediction with lower confidence.

### 9.5 Evaluation, backtesting, calibration
- **Metrics:** log-loss (primary), Brier score, accuracy. Log-loss punishes confident wrong predictions — exactly what we want.
- **Backtest:** train on data up to WC2018, predict WC2018; train up to WC2022, predict WC2022. Compare to the naive baseline (Goal #3).
- **Calibration:** plot a reliability curve (predicted % vs actual %). If miscalibrated, apply Platt scaling or isotonic regression. **A calibrated 60% must mean 60%.**
- **Avoid overfitting:** time-based splits (never train on the future), keep feature count modest, use cross-validation, prefer simpler models when scores tie.

### 9.6 Combining different data types (the blending question)
- **Statistical features** → the core model input.
- **Odds data** → treat as a strong external signal; can be a feature or used only for comparison. In MVP, use only for the comparison view (don't let bookies train your model yet).
- **Player data** (Phase 3) → adjust team strength up/down based on availability.
- **Sentiment data** (Phase 4) → a **weak, capped signal only** (see Section 11). Never let hype dominate.
- **Method:** start by keeping signals separate and interpretable. Later, blend with a stacked/ensemble model where each signal is a feature with a learned (and bounded) weight.

---

## 10. Database Schema

PostgreSQL. Primary keys are `id` (serial/UUID) unless noted. Below: main fields + relationships. Build the **bold** tables in MVP; others in later phases.

**`tournaments`**
- id, name ("FIFA World Cup 2026"), year, host_countries, start_date, end_date
- 1 tournament → many groups, many matches

**`teams`** (MVP)
- id, name, country_code (ISO), confederation, fifa_rank, elo_rating, flag_url, is_host (bool)
- 1 team → many players, many team_stats, appears in many matches

**`groups`** (MVP)
- id, tournament_id (FK), name ("Group A")
- 1 group → many teams (via standings), many matches

**`group_teams`** (MVP, join table)
- id, group_id (FK), team_id (FK)

**`matches`** (MVP)
- id, tournament_id (FK), group_id (FK nullable for knockouts), stage (group/R32/QF…), team_home_id (FK), team_away_id (FK), kickoff_utc, venue, venue_country, is_neutral (bool), host_team_id (FK nullable — set when a host nation plays in its own country, drives the +60 Elo bonus per Decision #2), status (scheduled/live/finished), score_home, score_away
- 1 match → many predictions, many odds rows, many live_events

**`historical_matches`** (MVP) — separate from tournament `matches`
- id, date, team_a_id, team_b_id, score_a, score_b, competition, is_neutral, venue
- Used for training; not shown directly in UI

**`team_stats`** (MVP, can start minimal)
- id, team_id (FK), as_of_date, matches_played, goals_for, goals_against, clean_sheets, form_points_last10, xg_for (nullable), xg_against (nullable)

**`predictions`** (MVP)
- id, match_id (FK), model_version, created_at, prob_home_win, prob_draw, prob_away_win, predicted_score_home, predicted_score_away, predicted_score_prob, confidence (enum), reasons (JSON array of strings), top_features (JSON)
- 1 match → many predictions over time (keep history for the trend chart & accuracy tracking)

**`standings`** (MVP)
- id, group_id (FK), team_id (FK), played, won, drawn, lost, goals_for, goals_against, goal_diff, points, qualification_prob, as_of (timestamp)

**`odds`** (Phase 2; MVP only if a free source is wired)
- id, match_id (FK), bookmaker, odds_home, odds_draw, odds_away, implied_prob_home/draw/away, captured_at

**`players`** (Phase 3)
- id, team_id (FK), name, position, club, age, rating, minutes, goals, assists, xg, xa, is_captain, is_gk

**`player_stats`** (Phase 3)
- id, player_id (FK), as_of_date, minutes, goals, assists, xg, xa, fatigue_index

**`injuries`** (Phase 3)
- id, player_id (FK), type, status (out/doubtful/available), expected_return, severity

**`live_events`** (Phase 2)
- id, match_id (FK), minute, event_type (goal/red_card/sub/penalty/var), team_id, player_id (nullable), payload (JSON), created_at

**`social_sentiment`** (Phase 4)
- id, team_id (FK), source (news/x/reddit), as_of_date, sentiment_score (-1..1), credibility_weight (0..1), volume, summary

**`simulations`** (Phase 3)
- id, tournament_id (FK), run_at, n_simulations, results (JSON: per-team advance/QF/SF/final/winner probabilities), model_version

**Relationship summary:** `tournaments` → `groups` → `group_teams` → `teams`; `teams` ↔ `matches` (home/away) → `predictions`/`odds`/`live_events`; `teams` → `players` → `player_stats`/`injuries`; `groups` → `standings`.

---

## 11. API Endpoint Design

REST, JSON, served by FastAPI. `GET` unless noted. (MVP) / (Phase) tags included.

| Method | Endpoint | Purpose | Phase |
|---|---|---|---|
| GET | `/api/matches/upcoming` | List upcoming matches with predicted winner + W/D/L + score + confidence | MVP |
| GET | `/api/matches/{id}` | Full match detail incl. prediction, reasons, H2H, odds (if any) | MVP |
| GET | `/api/predictions/{match_id}` | Prediction object for a match (current + history) | MVP |
| GET | `/api/teams` | List all 48 teams | MVP |
| GET | `/api/teams/{id}` | Team profile: form, history, strengths, prediction trend | MVP |
| GET | `/api/groups` | All groups with standings + qualification probs | MVP |
| GET | `/api/groups/{id}` | Single group detail | MVP |
| GET | `/api/odds/{match_id}` | Model prob vs bookmaker implied prob + value flag | Phase 2 (MVP if free odds wired) |
| GET | `/api/simulations/tournament` | Monte Carlo tournament-winner & round probabilities | Phase 3 |
| GET | `/api/matches/{id}/live` | Current live match state + live probabilities | Phase 2 |
| GET (SSE) | `/api/matches/{id}/stream` | Server-Sent Events stream of live updates | Phase 2 |
| POST | `/api/internal/recompute` | (Protected) trigger pipeline run — used by the cron job | MVP |
| GET | `/api/players/{id}` | Player profile + influence score | Phase 3 |
| GET | `/api/teams/{id}/influence` | Player-influence ranking + injury impact | Phase 3 |

**Conventions:** versioned under `/api/`; consistent error shape `{ "error": { "code", "message" } }`; all responses include `model_version` and `generated_at` where relevant.

---

## 12. Dashboard / Page Design

Design principles: **mobile-first, visual, fast, simple by default with depth on demand.** Casual fans see the answer immediately; analysts can expand for detail.

### 12.1 Pages

1. **Home / Prediction Dashboard**
   - Header: tournament countdown, disclaimer banner.
   - Filter bar: by group, by date, by team (search).
   - **Match cards** (the core component): two flags, predicted winner highlighted, a horizontal **W/D/L probability bar** (3 colored segments), predicted score, confidence badge (🟢High/🟡Med/🔴Low). Tap → match detail.

2. **Match Detail**
   - Big W/D/L bar + exact percentages.
   - **Scoreline distribution** (small bar chart of most likely scores).
   - **"Why this prediction"** — 3+ bullet reasons + a "top factors" mini bar chart (feature importance).
   - Head-to-head summary (last 5 meetings).
   - Odds comparison block (if available): model % vs implied %, value flag.

3. **Groups**
   - 12 group cards, each a mini standings table with a **qualification-probability bar** per team.
   - Tap a group → full table + remaining fixtures + scenario notes.

4. **Team Profile**
   - Hero: flag, FIFA rank, Elo, confederation.
   - Recent form strip (W/D/L of last 5–10, colored).
   - Historical WC performance (best finish, appearances).
   - Strengths & weaknesses (auto-generated bullets).
   - **Prediction-trend line chart** (their tournament-winner % over time).

5. **Tournament Outlook** (Phase 3)
   - Bracket visualization + tournament-winner leaderboard from Monte Carlo.

6. **About / Methodology** — how predictions work, data sources, **the disclaimer in full**. Builds trust; important for a transparent product.

### 12.2 Key components
- `MatchCard`, `ProbabilityBar` (W/D/L), `ConfidenceBadge`, `ScoreDistributionChart` (Recharts), `ReasonsList`, `FeatureImportanceChart`, `GroupTable`, `QualificationBar`, `FormStrip`, `TrendChart`, `OddsCompare`, `DisclaimerBanner`.

### 12.3 Charts (Recharts)
- W/D/L stacked horizontal bar; scoreline bar chart; feature-importance bar; qualification-probability bars; team trend line. (D3 only if a custom bracket needs it in Phase 3.)

### 12.4 User flows
- **Casual:** Home → tap a match → see winner + score + 3 reasons → done. (Under 10 seconds.)
- **Analyst:** Home → filter by group → match detail → expand factors → odds compare → team profile → trend.

---

## 13. Risks & Challenges

| Risk | Impact | Mitigation |
|---|---|---|
| **Thin data for new WC qualifiers** | Bad predictions for some teams | Cold-start fallback chain (Elo→FIFA→confederation); show Low confidence honestly |
| **Team-name mismatches across datasets** | Silent data corruption | A canonical team mapping table; tested ingestion |
| **Overfitting to past tournaments** | Looks great in backtest, fails live | Time-based splits, simple models, calibration, beat-the-baseline gate |
| **Free data goes stale / source disappears** | Pipeline breaks | Source-agnostic ingestion layer; cache last good data; alerting on job failure |
| **Scope creep (trying to build everything)** | Never ships | Strict MVP (Section 4); Non-Goals (Section 5) enforced |
| **Live infra complexity (Phase 2)** | Hard for a junior | Start with polling + SSE, not custom WebSockets; simulate live first |
| **Calibration neglected** | Probabilities mislead users | Reliability curve + Platt/isotonic before launch; Goal #2 |
| **Legal exposure from odds/betting framing** | Real liability | Strong disclaimer everywhere; analytics framing; see Section 16 |
| **Burnout (solo junior, huge scope)** | Project dies | Ship the smallest useful thing (Section 15) and iterate publicly |

---

## 14. Development Timeline

Assumes solo, part-time, junior pace. Adjust to your hours.

| Phase | Duration | Deliverable |
|---|---|---|
| **Phase 0 — Setup** | Week 1 | Repo, Next.js + FastAPI + Postgres scaffold, deploy a "hello world" to Vercel + Railway |
| **Phase 1 — Data + ratings** | Weeks 2–3 | Ingest free historical data; team-name mapping; compute Elo; load WC2026 teams/groups/fixtures |
| **Phase 2 — MVP model** | Weeks 4–6 | Elo + Poisson engine; logistic baseline; backtest vs WC2018/2022; calibration; write predictions to DB |
| **Phase 3 — MVP dashboard** | Weeks 7–9 | Home, match detail, groups, team pages; charts; reasons; disclaimer; cron refresh; **deploy MVP** |
| **Phase 4 — Polish + XGBoost + odds + accuracy** | Weeks 10–11 | Add gradient boosting + feature importances; wire The Odds API free tier for the user-facing odds-comparison view (Decision #1); publish running accuracy + calibration curve on the methodology page (Decision #6) |
| **Phase 5 — Tournament sim** | Weeks 12–14 | Monte Carlo simulator + tournament outlook page + bracket |
| **Phase 6 — Live (real or simulated)** | Weeks 15–18 | Live ingest worker, SSE, in-game win-prob model, live dashboard |
| **Phase 7 — Player model** | Weeks 19–22 | Squads, player influence, injury impact |
| **Phase 8 — Sentiment** | Weeks 23–26 | News/social ingestion, credibility filtering, capped weak signal |
| **Phase 9 — Accounts/alerts** | Later | Auth, favorites, notifications |

**Milestone that matters: end of Week 9 = a real, deployed, predicting MVP.**

---

## 15. What to Build First (Concrete First Steps)

Do these in order. Don't skip ahead.

1. **Scaffold + deploy nothing-yet.** Next.js frontend on Vercel, FastAPI + Postgres on Railway, prove they talk to each other with one dummy endpoint. (Confidence that deploy works early saves pain later.)
2. **Load the WC2026 structure.** Teams, 12 groups, 104 fixtures into Postgres. Build the team-name mapping table now.
3. **Ingest historical results** (Kaggle international results CSV) and **compute Elo**. Verify Elo looks sane (Brazil/France/Argentina near the top).
4. **Build the Poisson match model.** For any two teams, output W/D/L + scoreline. Test on a few known matches.
5. **Backtest** against WC2018 & WC2022; compute log-loss; **beat the naive baseline** before going further.
6. **Calibrate** and store predictions for all WC2026 fixtures in the `predictions` table.
7. **Build the dashboard MVP** reading those predictions: Home → Match detail → Groups → Team pages.
8. **Add the cron refresh** so it stays current. **Deploy. Share it.**

Everything after step 8 is Phase 2+. Ship step 8 first.

---

## 16. Legal & Ethical Considerations

**Betting / odds:**
- Display a clear, persistent disclaimer: *"This platform is for analytics, research, and entertainment only. It is not betting advice and does not guarantee outcomes. Gamble responsibly; 18+/21+ per your jurisdiction."*
- Do not present "value bets" as instructions to wager. Frame as model-vs-market *disagreement*.
- Some jurisdictions regulate gambling-adjacent content and advertising. Keep the product analytics-framed, avoid affiliate betting links in MVP, and check local law before any monetization that touches betting.
- Respect each odds provider's Terms of Service and licensing for displaying odds.

**Social / political / external context (Section 6 of the brief) — use responsibly:**
- Treat sentiment as a **weak, capped signal** with a credibility weight. Filter for source credibility; down-weight anonymous/viral/unverified content; never let hype override on-pitch data.
- Use political/social context only where it has a **defensible, measurable** effect on performance (e.g., host-nation advantage, documented travel/rest disruption). **Do not** encode assumptions based on nationality, ethnicity, religion, or politics as proxies for skill — that is both unfair and inaccurate.
- Be transparent in the methodology page about which contextual factors are used and why.

**Data & privacy:**
- Respect dataset licenses and API Terms of Service. Scrape only what ToS allows; cache responsibly.
- Player data: use publicly available professional performance data only; avoid sensitive personal data.

**Honesty of predictions:**
- Always show confidence and never imply certainty. Calibration (Section 9.5) is an ethical requirement, not just a technical one — overconfident predictions mislead users.

---

## 17. Example Prediction Output Format

The `predictions` API returns JSON like this (this is the contract the frontend consumes):

```json
{
  "match_id": 1042,
  "model_version": "poisson-elo-v1.2",
  "generated_at": "2026-06-06T12:00:00Z",
  "teams": { "home": "Brazil", "away": "Serbia" },
  "is_neutral": true,
  "probabilities": {
    "home_win": 0.62,
    "draw": 0.24,
    "away_win": 0.14
  },
  "predicted_score": { "home": 2, "away": 0, "probability": 0.17 },
  "confidence": "High",
  "reasons": [
    "Brazil has a much higher Elo rating (2105 vs 1788).",
    "Brazil scored in each of its last 8 competitive matches.",
    "Brazil won the only previous meeting at a World Cup."
  ],
  "top_features": [
    { "name": "elo_gap", "weight": 0.41 },
    { "name": "form_last10", "weight": 0.22 },
    { "name": "goals_for_avg", "weight": 0.15 }
  ],
  "head_to_head": { "matches": 1, "home_wins": 1, "draws": 0, "away_wins": 0 },
  "odds_comparison": {
    "available": false
  },
  "disclaimer": "For analytics and entertainment only. Not betting advice."
}
```

A human-readable summary the UI can show: *"Brazil are strong favourites (62%) and predicted to win 2–0, mainly because of a large Elo advantage and excellent recent scoring form."*

---

## 18. Suggested Folder Structure

```
fifa-wc26-prediction/
├─ README.md
├─ docs/
│  └─ methodology.md
├─ frontend/                  # Next.js + TypeScript
│  ├─ app/                    # pages: /, /match/[id], /groups, /team/[id], /about
│  ├─ components/             # MatchCard, ProbabilityBar, charts, etc.
│  ├─ lib/                    # api client, formatters
│  └─ styles/
├─ backend/                   # FastAPI
│  ├─ app/
│  │  ├─ main.py              # FastAPI app + routes
│  │  ├─ api/                 # routers: matches, teams, groups, predictions
│  │  ├─ models/              # SQLAlchemy models (schema)
│  │  ├─ schemas/             # Pydantic response schemas
│  │  ├─ db.py                # DB session
│  │  └─ cache.py             # Redis (optional)
│  └─ alembic/                # migrations
├─ ml/                        # the prediction brain
│  ├─ ratings/elo.py
│  ├─ models/poisson.py
│  ├─ models/baseline_logistic.py
│  ├─ models/gradient_boost.py     # later
│  ├─ features/build_features.py
│  ├─ evaluation/backtest.py
│  ├─ evaluation/calibration.py
│  └─ simulate/monte_carlo.py      # Phase 3
├─ pipeline/                  # the scheduled job
│  ├─ ingest/                 # fetch + clean free data
│  ├─ team_mapping.py         # canonical name table
│  ├─ run_pipeline.py         # fetch → load → rate → predict → store
│  └─ schedule (cron / GH Action)
├─ data/                      # raw + processed (gitignored where large)
└─ tests/
```

---

## 19. Resolved Decisions

These were open questions; each is now resolved with a default chosen to fit the locked-in constraints (casual fans, $0 budget, junior builder, ship fast). Change any of them later if your priorities shift.

1. **Free odds in MVP? → DEFER to Phase 2.**
   The MVP ships with **no live odds**. Rationale: the brief asked for "basic odds comparison," but the $0 constraint and junior-builder constraint make a live odds integration (rate limits, ToS, key management, another point of failure) a poor first bet. Instead, the MVP uses **historical odds from football-data.co.uk** (already a free MVP source) for *one* purpose only: to **calibrate and sanity-check the model during backtesting** (Section 9.5) — not shown to users. The user-facing odds-comparison view becomes the first Phase 4 task, wired to The Odds API free tier. Functional Requirement #16 is therefore **out of MVP scope**; the `OddsCompare` component and `/api/odds` endpoint are stubbed (return `{ "available": false }`) so the UI degrades gracefully.

2. **Host advantage → small fixed bonus, applied only to the team playing in its own country.**
   Concrete rule for the model: matches are treated as neutral (`is_neutral = true`) **except** when USA, Canada, or Mexico plays a match hosted in *its own* country — then that team gets a **host bonus of +60 Elo points** (≈ the conventional home-advantage value, applied once, not stacked). All three hosts use the same +60; we do **not** hand-tune per-country boosts (that would be guessing). Mexico's Estadio Azteca altitude is **not** separately modeled in MVP (Phase 7 candidate). This is stored as a per-match `host_team_id` field rather than a team-level flag, so a host only benefits at its own venues.

3. **Knockout draw uncertainty → YES, model the bracket probabilistically (confirmed for Phase 3).**
   The Monte Carlo simulator advances simulated group winners/runners-up into the official bracket structure and resolves each knockout tie by sampling from the match model. Until real group results exist, every simulation re-draws the groups from current probabilities, so bracket paths are themselves probabilistic. This is the standard and correct approach.

4. **Monetization → portfolio-first, conservative legal posture.**
   Treat this as a **portfolio / build-in-public project first**, with a clean path to ads or a premium analyst tier later. Practical consequences: **no affiliate betting links, no "place this bet" framing, ever** in the current scope; keep the analytics framing and full disclaimer (Section 16) regardless. This keeps legal exposure minimal now and leaves monetization open without rework.

5. **Branding/name → working name "PitchProphet" (placeholder, not final).**
   Used for the About page, repo, and copy until you pick a final name. Alternatives to consider: *GoalOracle*, *KnockoutIQ*, *XI Predictions*. Final naming + domain is a pre-launch marketing task, not a blocker for any engineering work — keep the name in one config constant so it's a one-line change.

6. **Accuracy display → YES, show running accuracy/calibration publicly.**
   Once matches are played, the About/Methodology page shows the model's running **log-loss, accuracy, and a reliability (calibration) curve**, plus a simple "last 20 predictions: X correct" strip. Rationale: transparency is the product's core value proposition; honestly showing misses builds more trust than hiding them. This is a small Phase 4 addition that reuses the prediction-history already logged in MVP (Functional Requirement #20).

---

## 20. Remaining Open Questions

None blocking. Two genuinely external items to revisit before public launch (not before building):

- **Final product name + domain** (decision #5) — a marketing choice, deferred by design.
- **Real odds provider choice** (decision #1) — pick the specific free tier when you reach Phase 4.
