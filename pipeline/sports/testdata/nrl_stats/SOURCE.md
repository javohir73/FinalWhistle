<!-- pipeline/sports/testdata/nrl_stats/SOURCE.md -->
# NRL team-stats source decision (Wave 2, Task 1 spike)

- **Date probed:** 2026-07-10 (UTC timestamps below; probe run via `pipeline/sports/nrl_stats_spike.py`)
- **Adopted source:** **NRL.com match-centre JSON** — draw endpoint (`/draw/data?...`) for the round listing, plus each fixture's `{matchCentreUrl}data` document (Variant A — the plain JSON endpoint behind the match-centre page). Variant B (embedded `q-data` on the HTML page) was never needed: Variant A returned `200` with parseable JSON on every probed match, so it is the sole path implemented.

## Decision procedure results

### 1. Works (criterion 1) — PASS

| Request | Result |
|---|---|
| `GET https://www.nrl.com/robots.txt` | `200`, 75 bytes |
| `GET https://www.nrl.com/draw/data?competition=111&season=2025&round=1` | `200`, 31185 bytes, valid JSON, 8 fixtures |
| `GET https://www.nrl.com/draw/nrl-premiership/2025/round-1/raiders-v-warriors/data` | `200`, 86043 bytes, valid JSON, `matchState: "FullTime"` |
| `GET https://www.nrl.com/draw/nrl-premiership/2025/round-1/panthers-v-sharks/data` | `200`, 83550 bytes, valid JSON, `matchState: "FullTime"` |

Round 1, 2025 was the Las Vegas double-header (both probed matches played at Allegiant Stadium, 2025-03-02) — both matches are long finished as of the probe date, giving two genuine finished-match documents.

### 2. Has required fields (criterion 2) — PASS, with derivation (not a flat 1:1 title lookup)

The brief's illustrative parser (`_STAT_TITLES` doing a direct `stats.groups[].stats[].title` lookup for all nine fields, with scalar `home`/`away` values) does **not** match the real document shape. The actual shape, verified against both recorded match fixtures:

- **Team identity:** `homeTeam.nickName` / `awayTeam.nickName` (e.g. `"Raiders"`, `"Warriors"`) — matches `SportTeam.name` / fixturedownload nickname convention used elsewhere in the repo. Team ids for cross-referencing timeline events: `homeTeam.teamId` / `awayTeam.teamId` (ints, e.g. `500013` / `500032`).
- **Stat values are nested, not scalar:** `doc["stats"]["groups"]` is a list of `{"title": <group name>, "stats": [...]}`. Each stat row is `{"title": str, "type": str, "homeValue": {"value": float, "isLeader": bool, ...}, "awayValue": {"value": float, ...}, ...}` — the value is at `stat["homeValue"]["value"]`, **not** `stat["home"]`.
- **`tries` and `conversions` are NOT in `stats.groups` at all.** They live on `homeTeam.scoring.tries.made` / `homeTeam.scoring.conversions.made` (and mirrored on `awayTeam.scoring...`). `scoring.tries.summaries` is a bonus cross-check: a list of `"<Player Name> <minute>'"` strings that independently confirms scorer + minute.
- **`set_restarts` is NOT in `stats.groups` either.** There is no team-level "Set Restarts" stat row. It must be derived by counting `doc["timeline"]` entries with `type == "SetRestart"`, grouped by each entry's `teamId` against `homeTeam.teamId`/`awayTeam.teamId`.
- **The remaining six fields ARE flat `stats.groups` title lookups**, but titles differ from the brief's guessed spellings:

  | Contract field | Real group | Real title (verbatim) | Brief's guess (wrong) |
  |---|---|---|---|
  | `penalties_conceded` | Negative Play | `"Penalties Conceded"` | matched |
  | `errors` | Negative Play | `"Errors"` | matched |
  | `run_metres` | Attack | `"All Run Metres"` | matched |
  | `line_breaks` | Attack | `"Line Breaks"` | matched |
  | `tackles` | Defence | `"Tackles Made"` | matched |
  | `tackle_efficiency` | Defence | `"Effective Tackle %"` | guessed `"Effective Tackle"` (missing `%`) — **would silently fail the lookup** |

- **Full verified field map (transcribed from `match_2025_r01_a.json`, Raiders 30 v Warriors 8):**

  | Field | Home (Raiders) | Away (Warriors) |
  |---|---|---|
  | tries | 5 | 2 |
  | conversions | 4 | 0 |
  | penalties_conceded | 7 | 5 |
  | errors | 13 | 13 |
  | set_restarts | 1 | 3 |
  | run_metres | 1822 | 1565 |
  | line_breaks | 6 | 2 |
  | tackles | 378 | 356 |
  | tackle_efficiency | 91.3 | 83.18 |

  Score reconstruction check (tries×4 + conversions×2 + penalty_goals×2): home = 5×4+4×2+1×2 = 30 = actual; away = 2×4+0×2+0×2 = 8 = actual. Self-consistent.

  Second fixture (`match_2025_r01_b.json`, Panthers 28 v Sharks 22): tries home=5/away=4, conversions home=4/away=3, penalties_conceded 7/4, errors 13/12, set_restarts 4/2, run_metres 1837/1631, line_breaks 7/5, tackles 391/375, tackle_efficiency 89.07/91.46. Score check: home 5×4+4×2+0×2=28 = actual; away 4×4+3×2+0×2=22 = actual.

- **Try events** live in `doc["timeline"]`, a flat list of ~100 entries per match (mixed event types: `Try`, `Goal`/`GoalMissed`, `Penalty`, `Error`, `SetRestart`, `Interchange`, `LineBreak`, game-clock markers, etc. — each entry also carries a large `content` blob of video/highlight metadata unrelated to the stat contract). Try-entry shape (verified, `content` stripped):
  ```json
  {"title": "Try", "type": "Try", "gameSeconds": 316, "playerId": 504148, "teamId": 500013, "homeScore": 4}
  ```
  - **No `minutes`/`minute` field** — must derive `minute = gameSeconds // 60` (verified to match NRL's own displayed `"Sebastian Kris 5'"` — `gameSeconds=316 -> 316//60=5`, cross-checked against all 16 try events across both fixtures with zero mismatches).
  - **No `playerName` string** — must resolve `playerId` against `homeTeam.players[]` / `awayTeam.players[]` (list of `{"playerId": int, "firstName": str, "lastName": str, "position": str, "number": int, ...}`), joined as `f"{firstName} {lastName}"`.
  - **No `teamNickName` string** — must resolve `teamId` against `homeTeam.teamId`/`awayTeam.teamId` to get the nickName.
  - **Running score fields (`homeScore`/`awayScore`) are omitted (not zero) until that side's first score.** They are cumulative-at-that-instant and appear on every `Try`/`Goal`(made) event, but are absent (not `0`) while a side hasn't scored yet, and absent on non-scoring events (`GoalMissed`, `Error`, `SetRestart`, etc.). Reconstructing the running score requires forward-filling across `Try`+`Goal` events sorted by `gameSeconds`, defaulting both sides to `0` before their first appearance — **not** a raw per-event read.
  - **The try's own `homeScore`/`awayScore` reflects the score immediately after the try (pre-conversion)**, e.g. an unconverted-at-that-instant 4-point try. The conversion (if any) is a separate later `Goal` timeline entry ~1 minute afterward. The dataclass docstring's "(running score after this try (+conversion))" is therefore only exactly true if the try event's own carried score is combined with the immediately-following made-conversion, which Task 2's parser must decide how to handle (either take the try's raw post-try score, or look ahead to the next same-team `Goal` event within the same passage of play). This spike does not resolve that judgement call — it is Task 2's parsing decision; recorded here so it isn't rediscovered from scratch.
  - Verified full ordered try list, `match_2025_r01_a.json` (Raiders v Warriors, 30-8), `minute`/`team`/`player`/running `(home,away)` after the raw try event:
    1. 5, Raiders, Sebastian Kris, (4, 0)
    2. 26, Raiders, Xavier Savage, (10, 0)
    3. 31, Raiders, Xavier Savage, (14, 0)
    4. 36, Warriors, Kurt Capewell, (16, 4)
    5. 44, Raiders, Sebastian Kris, (20, 4)
    6. 55, Raiders, Matthew Timoko, (26, 4)
    7. 71, Warriors, Roger Tuivasa-Sheck, (28, 8)
  - Verified full ordered try list, `match_2025_r01_b.json` (Panthers v Sharks, 28-22):
    1. 3, Sharks, Jesse Ramien, (0, 4)
    2. 26, Panthers, Isaah Yeo, (4, 4)
    3. 28, Panthers, Izack Tago, (10, 4)
    4. 35, Sharks, Briton Nikora, (12, 8)
    5. 48, Panthers, Daine Laurie, (16, 10)
    6. 52, Panthers, Paul Alamoti, (22, 10)
    7. 58, Sharks, Kayal Iro, (24, 14)
    8. 68, Sharks, Addin Fonua-Blake, (24, 20)
    9. 75, Panthers, Daine Laurie, (28, 22)

- **Draw/fixture-listing shape** (`draw_2025_r01.json`): top-level `fixtures` is a list of 8 dicts (one 2025 Round 1 bye-free round). Each fixture has `homeTeam.nickName` / `awayTeam.nickName` and `matchCentreUrl` (e.g. `"/draw/nrl-premiership/2025/round-1/raiders-v-warriors/"`) — this matches the brief's `parse_draw_fixtures` assumption exactly (no deviation here).

### 3. Tolerable ToS (criterion 3) — PASS, with one caveat to weigh

- **robots.txt** (`https://www.nrl.com/robots.txt`, fetched 2026-07-10): full contents are
  ```
  User-agent: *

  #Sitemap
  Sitemap: https://www.nrl.com/sitemap/sitemap.xml
  ```
  **Zero `Disallow` directives** — every probed path (`/draw/data`, `/draw/nrl-premiership/.../data`) is unrestricted.
- **Terms of Use** (`https://www.nrl.com/terms-of-use/`, fetched 2026-07-10, `200`): no mention of `scrap(e/ing)`, `robot`, `automat(ed/ion)`, `crawl`, `data mining`, or `spider` anywhere in the page text. No blanket anti-automation clause.
- **Caveat (flagging honestly, not burying it):** the ToS does contain "you will only use the NRL Network for personal, non-commercial use" (section on Information/Use). It is written in a login/account-registration context and is common sports-site boilerplate, and match-centre statistics are the same public data NRL.com itself renders to every visitor without a login. Our actual access pattern (an unauthenticated GET, `>=1s` apart, browser-identifying UA, weekly refresh + one-off backfill, feeding a non-betting analytics/entertainment product per this program's global constraints — no bookmaker links/odds CTAs anywhere) is much closer to "personal use of public information" than to commercial redistribution or resale of NRL's data product. Still, this is a real clause a reviewer/legal owner should see rather than have hidden — recording it here rather than silently treating criterion 3 as a clean pass.
- **Access pattern used during this spike:** identified with a descriptive contact User-Agent (`Mozilla/5.0 (compatible; NRL-Match-Intel-Spike/1.0; contact: pete@degail.com; one-off research probe)`), `>=1s` between every request (rate-limited in `_get()`), total of **11 live requests** for the entire spike (robots.txt ×1, draw ×2 — one dry-run + one `--record` run, 2 match documents ×2 runs = 4, rlp robots.txt ×1, rlp results page ×1, terms-of-use probing ×2 additional exploratory requests) — well under the 30-request budget.

## Rejected candidates & why

- **rugbyleagueproject.org** — `robots.txt` fetched (`200`): `Disallow: /matches/Custom` and `Disallow: /*?` (neither disallows the probed `/seasons/nrl-2025/results.html` path, so criterion 3 would have passed). **Rejected on criterion 2**: `GET https://www.rugbyleagueproject.org/seasons/nrl-2025/results.html` returned `200` (237124 bytes) but contains no `run metres` / `tackle` text anywhere on the page — confirms the brief's expectation that this source has scorelines/scorers only, no team-level run-metres/tackle-efficiency stats. As documented in the brief, this makes it "only a fallback for try events, which is insufficient alone" — never reached, since candidate 1 already passed all three criteria.
- **Public GitHub NRL datasets** — not evaluated in depth: candidate 1 passed the full decision procedure first, and the procedure says "adopt the first candidate that passes all three." Per the decision procedure's ordering, candidate 3 is documented but unexplored beyond confirming candidate 1's success made it unnecessary.

## Fixtures recorded (never edit by hand except documented pruning)

No pruning was needed — all three files are well under the 1 MB threshold (47 KB, 138 KB, 133 KB).

- **`draw_2025_r01.json`** — `GET https://www.nrl.com/draw/data?competition=111&season=2025&round=1`, fetched 2026-07-10T14:57:46Z. 2025 NRL Premiership (competition 111) Round 1 draw, 8 fixtures (the Las Vegas double-header round).
- **`match_2025_r01_a.json`** — `GET https://www.nrl.com/draw/nrl-premiership/2025/round-1/raiders-v-warriors/data`, fetched 2026-07-10T14:57:47Z. **Raiders 30 v Warriors 8** (Allegiant Stadium, Las Vegas, kickoff 2025-03-02T00:00:00Z), `matchState: "FullTime"`.
- **`match_2025_r01_b.json`** — `GET https://www.nrl.com/draw/nrl-premiership/2025/round-1/panthers-v-sharks/data`, fetched 2026-07-10T14:57:48Z. **Panthers 28 v Sharks 22** (Allegiant Stadium, Las Vegas, kickoff 2025-03-02T04:30:00Z), `matchState: "FullTime"`.

Both matches are 2025-season Round 1 NRL Premiership fixtures; team nicknames (`Raiders`, `Warriors`, `Panthers`, `Sharks`) match the fixturedownload-nickname convention `pipeline/sports/nrl_ingest.py` already ingests into `sport_matches`/`sport_teams` for `sport="nrl"`.

## Access policy

`>= 1s` between requests, browser-identifying UA, weekly `nrl-refresh` + one-off backfill only. Production provider (Task 3) should keep the plain `"Mozilla/5.0"` UA used by the rest of the repo's ingest code (`nrl_ingest.py` convention) for consistency, rather than this spike's more verbose descriptive UA (which was used here specifically to self-identify during manual research probing, per the live-HTTP rules given for this spike task).

## Guidance for Task 2 (parser implementation)

The brief's illustrative `_STAT_TITLES` / `_stat_lookup` / `_team_names` / `_parse_try_events` code needs real rework against this source, not just spelling fixes:

1. `_team_names(doc)` — unchanged, `doc["homeTeam"]["nickName"]` / `doc["awayTeam"]["nickName"]` works as written.
2. `_stat_lookup(doc)` must read `stat["homeValue"]["value"]` / `stat["awayValue"]["value"]`, not `stat["home"]`/`stat["away"]`.
3. `tries` and `conversions` must come from `doc["homeTeam"]["scoring"]["tries"]["made"]` / `["conversions"]["made"]` (and the `away` mirror) — they are **not** in `_stat_lookup`'s title map at all.
4. `set_restarts` must come from counting `doc["timeline"]` entries where `type == "SetRestart"`, split by `teamId == doc["homeTeam"]["teamId"]` vs `awayTeam`'s — also not in the title map.
5. `tackle_efficiency`'s real title is `"Effective Tackle %"` (not `"Effective Tackle"`).
6. `_parse_try_events` must: filter `timeline` entries to `type == "Try"`; compute `minute = entry["gameSeconds"] // 60`; resolve `player` via `playerId` lookup against `homeTeam["players"] + awayTeam["players"]` (`f"{firstName} {lastName}"`); resolve `team` via `teamId` against `homeTeam["teamId"]`/`awayTeam["teamId"]`; and forward-fill `score_home`/`score_away` across `Try`+`Goal`-type events sorted by `gameSeconds` (both default to `0`, each updated only when its key is present on an event) rather than reading `homeScore`/`awayScore` off the try event in isolation.
