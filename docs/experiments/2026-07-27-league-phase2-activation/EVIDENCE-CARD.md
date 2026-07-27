# La Liga and Bundesliga activation — 2026-07-27

## Decision

Activate `laliga` and `bundesliga` beside `epl` in the local pipeline and
football tips UI. This change is code/config only: production remains on
`PIPELINE_TARGET=wc26` until the normal merge, pipeline-target, and deployment
stop gates are separately approved.

## Provider and quota verification

The configured API-Football account reported an active Pro subscription with a
7,500-request daily limit. At the time of the probe, six requests had been used.
A complete fixture refresh is one `/fixtures` request per league, so the three
active leagues consume three fixture-list requests per league-pipeline run.

| League | API-Football ID | 2026-27 fixtures | Teams | First kickoff UTC | Last kickoff UTC |
|---|---:|---:|---:|---|---|
| La Liga | 140 | 380 | 20 | 2026-08-15 17:30 | 2027-05-30 15:00 |
| Bundesliga | 78 | 306 | 18 | 2026-08-28 18:30 | 2027-05-22 13:30 |

## Historical model preparation

The public football-data.co.uk SP1 and D1 files were downloaded for ten seasons
(2016-17 through 2025-26). The final season was held out for choosing among the
precommitted 40/60/80 Elo home-advantage candidates.

| League | Historical matches | 2025-26 holdout | LL @ 40 | LL @ 60 | LL @ 80 | Selected |
|---|---:|---:|---:|---:|---:|---:|
| La Liga | 3,800 | 380 | 0.999138 | 0.990590 | **0.985294** | 80 |
| Bundesliga | 3,060 | 306 | 0.974315 | **0.973283** | 0.975482 | 60 |

The activation path now idempotently backfills a fresh/partial database and
fails before fixture predictions if the league remains below its minimum
historical-row threshold.

## Roster reconciliation

The live 2026-27 provider rosters were compared with normalized SP1/D1 team
names. Confirmed aliases were added for five Spanish and eleven German provider
name differences. A disposable in-memory database then ran the production
backfill, fixture ingest, and Elo replay:

| League | Fixtures inserted | Roster clubs | Elo-rated historical clubs | Unrated current roster | Unexpected unrated |
|---|---:|---:|---:|---|---|
| La Liga | 380 | 20 | 31 | Racing Santander | none |
| Bundesliga | 306 | 18 | 30 | SV Elversberg | none |

Racing Santander and SV Elversberg have no top-flight record in the ten-season
source window. They are explicit cold starts, matching the approved design's
promoted-club rule. Any other unrated current club causes that league's
prediction pass to be skipped and reported by the roster audit.

## Product activation

- Pipeline order: Premier League, La Liga, Bundesliga.
- `/tips` exposes all three through the league switcher.
- `/play` renders an isolated score-prediction section and matchweek state for
  each league.
- The unified leaderboard uses the selected league's own resolved matchweek.
- Bundesliga standings use 18-team relegation bands: playoff at 16, direct
  relegation at 17-18.
- Existing competition-scoped home, fixture, standings, match, and team routes
  remain the canonical platform URLs.

## Verification

- Full Python suite: 1,924 passed.
- Full frontend suite: 134 suites and 691 tests passed.
- Frontend type-check, lint, and production build passed.
- Desktop and 390-pixel mobile browser checks passed for `/tips` and `/play`:
  all three leagues were selectable, rendered their own fixture data, and had
  no horizontal overflow.
- `git diff --check` passed.

## Primary sources

- [API-Football documentation](https://www.api-football.com/documentation-v3)
- [football-data.co.uk data files](https://www.football-data.co.uk/data.php)
