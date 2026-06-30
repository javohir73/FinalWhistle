# FinalWhistle — Post-World-Cup Roadmap

Status: DRAFT (for later)
Author: pete@degail.com
Date: 2026-06-25
Frameworks used: office-hours (demand / wedge), CEO review (scope / strategy), make-plan (phased execution)

> One-line thesis: **The 2026 World Cup is the launch wedge, not the product.** The prediction engine is football-agnostic. This plan converts the World Cup traffic spike into a retained base by re-pointing the same engine at continuous football (domestic leagues, then cups), with multi-sport as a later option.

---

## 1. The problem this roadmap solves

An investor read of the product raised two fair objections:

1. **"Why this vs. the dozens of other prediction platforms?"** Low moat, easy to copy, AI-coding made all of it cheap.
2. **"It's event-driven. Traffic collapses after the World Cup."** No path to recurring usage or revenue.

Both are correct as stated. This roadmap is the answer to both, written so it can be defended with evidence rather than optimism.

The answer in two sentences:
- **Differentiation:** an explainable AI opponent with a public, auditable track record. Not "make picks, get points" — "predict against an AI that shows its work, and try to beat it."
- **Durability:** the World Cup is the cheapest user-acquisition moment in football. The same engine carries those users into the domestic season and every cup that follows, so the spike becomes a seasonal handoff instead of a collapse.

---

## 2. What we actually have (codebase reality)

A full coupling audit (frontend + backend + ml + pipeline) sorted the system into three buckets. This is the spine of the whole roadmap: it tells us the league pivot is mostly config + data, not a rebuild.

### Bucket A — Generic / competition-agnostic (works today for any football)
- Prediction engine: `ml/models/poisson.py`, `ml/models/params.py`, `ml/ratings/elo.py`, `ml/features/build_features.py`
- In-play win probability: `backend/app/live_winprob.py`
- ORM models (Tournament, Team, Match, Group): `backend/app/models/__init__.py`
- Fixtures / live scores / teams APIs: `backend/app/api/matches.py`, `backend/app/api/teams.py`
- Live polling providers: `pipeline/ingest/live_scores.py`, `pipeline/ingest/api_football.py`
- Group-stage round-robin sim: `ml/simulate/group_sim.py`
- Frontend match list, group standings, team pages

### Bucket B — Config-coupled (swap a value or a data file, no code change)
- `backend/app/config.py`: `football_data_competition="WC"`, `api_football_league=1`, `api_football_season=2026`, `live_provider`, `public_base_url`
- `frontend/lib/constants.ts`: `SITE_URL`
- Tournament data files: `pipeline/data/wc26_teams.json`, `wc26_groups.json`, `wc26_schedule.json`, `wc26_ko_schedule.json`
- Tournament seed strings: `pipeline/ingest/wc26_structure.py` (`TOURNAMENT_NAME`, `TOURNAMENT_YEAR`)

### Bucket C — Hardcoded to the World Cup (needs code changes to generalize)
| # | What | Where | To generalize |
|---|------|-------|---------------|
| 1 | Knockout stage list (R32→R16→QF→SF→3rd→Final) | `pipeline/ingest/wc26_structure.py` (KNOCKOUT_STAGES) | Read bracket shape from tournament config |
| 2 | R32 pairings, THIRD_SLOTS, KO tree, advancement (top-2 + best-8-thirds) | `ml/simulate/bracket.py` | Data-drive bracket tree + advancement rules |
| 3 | Bracket tree topology, `FINAL_MATCH=104`, `THIRD_PLACE=103` | `frontend/lib/bracketStructure.ts` | Generate from backend API / data file |
| 4 | Scoring match-number ranges (`R32_NOS=range(73,89)`, `FINAL_NO=104`) + point scheme | `backend/app/scoring.py` | Query match numbers by (stage, tournament_id); store point scheme in config |
| 5 | Group-count fallback `72` | `backend/app/api/brackets.py:47` | Compute from Tournament / Group rows |
| 6 | "72 group picks" copy + group-stage assumption | `frontend/app/my-bracket/MyBracketClient.tsx` | Hide group stage when tournament has none |
| 7 | Host bonus conflated with home advantage (`HOME_ADVANTAGE=60`) | `ml/ratings/elo.py:20`, `pipeline/generate_predictions.py` (`_host_adv`) | Separate home_advantage from host_bonus; load per tournament |
| 8 | "World Cup 2026" copy / SEO / OG images | `frontend/app/layout.tsx`, `opengraph-image.tsx`, `manifest.ts`, `match/[id]/opengraph-image.tsx`, `groups/[id]/page.tsx`, `team/[id]/page.tsx`, `about/methodology/terms` | Template off `TOURNAMENT_NAME` |
| 9 | Brackets/picks not scoped by tournament_id in composite keys | `backend/alembic/versions/cc991b98094e_*` | Migration to add tournament_id for multi-tournament |

**Bottom line from the audit:** a full, production-ready, multi-competition pivot is roughly **25-40 human-days** (with Claude Code compression, far less in calendar time). But the cheapest useful pivot, pointing at a competition that already fits the existing shape, is a **3-5 human-day** config + data + copy job. The expensive part is only the bracket/scoring generalization, and only some competitions need it.

---

## 3. The differentiation we are betting on

Features get copied. These three compound and are the actual moat, in priority order:

1. **Public, auditable model track record.** If the model is genuinely good and we show the receipts honestly, that trust compounds and cannot be faked overnight. This is the real defensibility. Protect it: never overclaim, log the real hit rate. (Already have a model-record surface to build on.)
2. **Social loops.** Friends-leagues, shareable "I beat the AI / I beat my mates" cards. Network effects are the only durable moat in consumer prediction. Today this is underbuilt and is the cheapest high-leverage thing to strengthen before launch.
3. **Explainable AI opponent.** "Beat the AI" + "see why it thinks what it thinks" (the existing "Why {team}?", reasons, feature-importance work). This is the hook that earns the first open even before a user has friends in a pool.

---

## 4. Phased plan

Each phase has a goal, what to build (grounded in real files), what it reuses, effort (human / CC-compressed), a success metric, and risks.

### Phase 0 — Retention bridge readiness (NOW → World Cup final, mid-July 2026)
**Goal:** be ready to convert the World Cup audience the moment the final ends. This is the single most important phase and it ships before the Cup is over.

- Build the in-app handoff prompt: "World Cup's over. Keep beating the AI. Your league starts in 3 weeks." Fires after the final, points users at the next competition.
- Decide and register a real domain (also unblocks transactional email; see Risks). `*.vercel.app` cannot send email or anchor a brand.
- Make sharing genuinely frictionless (share card for picks / AI-beat result). Strengthen the social loop while attention is highest.
- Reuse: existing engagement/install-prompt timing (`frontend/lib/useInstallPrompt.ts`), share button (`frontend/components/ShareButton.tsx`), notifications surface.
- Effort: ~3-5 human-days / ~half a day CC for the prompt + share polish; domain decision is a purchase, not eng.
- Success metric: prompt + share flow live and tested before the quarter-finals.
- Risk: if this slips past the final, the audience churns before the handoff exists. Ship it early.

### Phase 1 — Domestic league pivot (World Cup final → mid-August season kickoff)
**Goal:** prove the seasonal handoff. Re-point the engine at a domestic league (or several) so World Cup users have continuous football to predict against the AI.

- Use the config-coupled path first: new `live_provider` settings + new data files, no bracket needed (leagues have no knockout). This is the cheapest possible second competition.
- Generalize the copy (item C8) so "World Cup 2026" becomes the tournament name. Hide the group-stage / bracket UI when a tournament has none (items C5, C6).
- Recalibrate Elo for club football (club Elo is not international Elo; needs league history). Separate host bonus from home advantage (item C7).
- Multi-tournament data scoping if running league + leftover WC data together (item C9 migration).
- Reuse: Buckets A and B almost entirely. Match prediction, live scores, team pages, group/standings tables all work.
- Effort: ~5-8 human-days / ~1-2 days CC for the first league (config + data + copy + Elo recalibration + the "no knockout" UI branch).
- Success metric: a measurable share of World Cup users active on league predictions 30 days after the final.
- Risk: data provider coverage and cost across leagues (API-Football plan limits); model calibration quality on club football.

### Phase 2 — Cup brackets (Champions League, Euro 2028, etc.)
**Goal:** reuse the bracket feature, the most distinctive piece, on the cups that run alongside the league season.

- Generalize the bracket: bracket shape, match numbering, advancement, and scoring move from hardcoded to config/data (items C1-C4). This is the expensive work, deferred to here because leagues do not need it.
- Champions League / Euros have different knockout shapes (no R32 group path, different seeding), so this is where the parameterization pays off.
- Reuse: the entire two-sided bracket UI and live-score wiring built for WC26.
- Effort: ~8-12 human-days / ~2-4 days CC for the bracket + scoring generalization.
- Success metric: a second knockout competition renders and scores correctly from config alone, with WC26 still passing as a regression.
- Risk: bracket/scoring generalization is the highest-complexity change in the codebase; needs strong regression tests against the WC26 baseline.

### Phase 3 — Multi-sport (LATER, only after football retention is proven)
**Goal:** expand TAM once the football retention thesis holds.

- Elo + "predict vs AI" generalizes to NBA, NFL, cricket, tennis. The reusable parts: auth, brackets, leaderboards, the AI-opponent framing, the explainability UI.
- The real work: a new outcome model (Poisson models football goals specifically; basketball/NFL need a points/spread model) and a new data source per sport.
- Effort: large, treat as a separate initiative, not a sprint.
- Success metric: do not start until Phase 1 retention is proven. This is the expansion story for investors, not a launch-week move.
- Risk: easy to over-promise; biggest lift; dilutes focus if started early.

---

## 5. Investor-facing positioning

Do not pitch "World Cup app." Pitch:

> "FinalWhistle is an explainable-AI prediction companion for football. The World Cup is our launch wedge, the cheapest possible user acquisition, and the same engine carries those users into the domestic season and every cup that follows. The model and product are competition-agnostic by design, and the model's public, honest track record is the moat."

"Beyond the World Cup" answer, one line: the engine is football-agnostic (proven by the league pivot), so the day after the final we hand users to continuous football; multi-sport is the later expansion.

---

## 6. Risks and open questions

- **Domain ownership (blocks two things at once).** Need a real domain for brand and for transactional email. Today `EMAIL_FROM=onboarding@resend.dev` only delivers to the Resend account owner. A verified domain fixes email AND anchors the post-WC brand. Decide this in Phase 0.
- **Data provider coverage and cost.** API-Football covers ~1,000 competitions, but plan limits and polling cost scale with how many leagues run concurrently. Cost-model before Phase 1.
- **Model calibration per competition.** Club Elo needs club match history; international Elo will not transfer. Each new competition needs a calibration pass.
- **Retention assumption is unproven.** "World Cup users will follow a league" is the core bet and has no evidence yet. Phase 1 exists to prove or kill it.
- **The moat only holds if the model is actually good.** The track-record advantage evaporates if we overclaim. Keep the hit-rate honest.

---

## 7. Success metrics (the scoreboard)

- Bridge conversion: % of World Cup users who make a first league prediction after the final.
- D30 retention post-final.
- Weekly active users through the league season (the recurring-usage proof).
- AI-beat engagement: how often users open to check their pick vs the AI.
- Virality / K-factor from friends-league shares.

---

## 8. NOT in scope (explicitly deferred)

- Multi-sport now (Phase 3, after football retention is proven).
- Monetization mechanics (decide after retention is real).
- Native push-notification infrastructure beyond the existing PWA/Capacitor shell.
- Full multi-tournament dashboard / tournament switcher UI (only the data scoping in Phase 1 if needed).

---

## 9. The assignment (one concrete next action)

Before the World Cup final:
1. Ship the Phase 0 retention-bridge prompt + share polish.
2. Buy and verify a domain (fixes email + brand).
3. Prove the league pivot is real: stand up a proof-of-concept by loading one current-season league via the config + data path, end to end, against the existing engine. If it loads and predicts in days (it should, per the audit), the "beyond the World Cup" story is no longer a claim, it is a demo.

---

## Appendix — generalization checklist

Pull from Section 2, Bucket C, in pivot order:
- Phase 1 (leagues, no knockout): C5, C6, C7, C8, C9
- Phase 2 (cups, knockout): C1, C2, C3, C4
- Config/data only (both phases): `backend/app/config.py`, `frontend/lib/constants.ts`, `pipeline/data/*.json`, `pipeline/ingest/wc26_structure.py`
