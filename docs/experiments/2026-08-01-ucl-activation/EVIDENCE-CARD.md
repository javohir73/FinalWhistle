# UEFA Champions League activation — 2026-08-01

## Decision

Add `ucl` as a fourth active football competition beside the Premier League,
La Liga, and Bundesliga. The platform serves competition-scoped home, fixture,
match, team, league-phase standings, and score-prediction surfaces. It does not
advertise a knockout bracket until a real competition-scoped bracket tree is
available.

## Provider identity and current state

The configured API-Football account was queried directly on 2026-08-01. No
provider ids, team ids, season keys, or fixtures were inferred.

| Field | Verified value |
|---|---|
| Competition | UEFA Champions League |
| API-Football league id | `2` |
| API-Football season | `2026` (the 2026-27 edition) |
| Current provider fixtures | 76 |
| Current provider teams | 48 qualifying participants |
| Current rounds | First, second, and third qualifying rounds |
| Current standings flag | `false` |
| Current feed end | 2026-08-11 |

UEFA's 2026-27 calendar confirms that the play-offs follow on 18/19 and 25/26
August, the 36-team league-phase draw is 27 August, and Matchday 1 is 8-10
September. Consequently, qualifying fixtures are ingested and predicted but
are excluded from the shared league-phase table and matchweek tips. Before the
draw, an empty league-phase table is the correct state, and UCL score tips stay
gated until real league-stage matchweeks load.

## Prediction history and model lineage

Domestic division CSVs cannot represent a cross-border competition. The UCL
activation therefore uses finished API-Football fixtures from the explicit
2022, 2023, 2024, and 2025 editions as its bounded, one-time historical Elo
backfill. Regulation-time scores are used for AET/PEN fixtures and finals are
marked neutral. Subsequent finished 2026-27 fixtures enter the same
competition-scoped history through the existing daily sync.

UCL predictions use their own `poisson-elo-ucl-v0.1` ledger. No
competition-specific parameter fit has cleared a promotion gate, so the engine
keeps the existing club defaults without claiming the domestic v0.2 lineage.
New qualifying entrants with no prior UCL history use the model's documented
1500 cold start rather than blocking the changing summer field.

## Badges and branding

- The competition image is the self-hosted API-Football league-2 asset.
- All 48 clubs in the live qualifying feed have self-hosted provider-id-keyed
  crest assets.
- Fourteen of UEFA's 29 automatic league-phase qualifiers reuse existing
  Premier League, La Liga, or Bundesliga crest assets.
- The remaining 15 automatic qualifiers were resolved by exact senior-club
  name and country against API-Football; ambiguous and unresolved counts were
  both zero, and their crests are self-hosted.
- Unknown future entrants still fail safely to the existing monogram until the
  provider adds them to the verified feed.

## Operational scope

The repository variable already selects `PIPELINE_TARGET=league`; no workflow,
secret, paid-service, or production-database setting is changed by this PR.
After merge, the normal refresh performs the bounded UCL history preparation
once and then one current-season fixture request per run.

## Verification

- Live provider history probe: 988 finished regulation-time rows across the
  explicit 2022-2025 editions (214, 214, 279, and 281 fixtures respectively).
- Disposable SQLite production-path run: 988 historical rows backfilled, 76
  current fixtures ingested, 56 finished qualifiers synced, 1,044 UCL matches
  replayed for Elo, and 20 scheduled qualifiers predicted under
  `poisson-elo-ucl-v0.1`.
- The same run produced zero league-phase members and zero standings rows,
  matching the pre-draw provider state; all 76 current fixtures were classified
  as qualifying.
- Focused Python regression suites passed, including regulation-time AET/PEN
  sync, competition team scoping, model lineage, and qualifier isolation.
- Full Python suite passed with a single Alembic head (`e2f3a4b5c6d7`).
- Full frontend suite: 133 suites and 818 tests passed.
- Frontend type-check, lint, and production build passed.
- Badge regression suite checks that every verified UCL crest path exists.

## Primary sources

- [API-Football documentation](https://www.api-football.com/documentation-v3)
- [UEFA 2026-27 Champions League teams and dates](https://www.uefa.com/uefachampionsleague/news/02a6-20d57cfcd03e-407c22a7f465-1000--2026-27-champions-league-teams-dates-draws-format-final/)
- [UEFA 2026-27 Champions League teams](https://www.uefa.com/uefachampionsleague/clubs/)
