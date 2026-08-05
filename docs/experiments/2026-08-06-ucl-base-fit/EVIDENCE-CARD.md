# UCL Track-1 goal-rate fit — EVIDENCE CARD

Run 2026-08-06. Runner: `pipeline/experiment_ucl_eval.py` (the UCL analogue of
`pipeline/experiment_club_eval.py`; candidates pre-registered in the module,
same grids as the domestic T1.1/T1.5 tracks). Master ledger:
`docs/MODEL-EXPERIMENTS.md`.

## Why

The UCL activated with `"model_params": {}` — the global club defaults,
explicitly recorded as "no competition-specific fit has cleared the model
gate" (2026-08-01 activation card). Served symptoms: the flattest competition
on the platform (favourite win probabilities capped near 65%, 95% of headline
scorelines 1-0/1-1) while the real competition averages ~3 goals a match.

## Data

The four completed API-Football editions (2022–2025) — the same bounded
window the activation backfill used. Regulation-time scores via
`parse_finished_fixtures` (AET/PEN ties enter at 90'). 988 rows total:
2022+2023+2024 = 707 (fit window), 2025 = 281 (quarantined confirmation).
Raw season payloads cached locally; **not committed** (public repo, provider
data).

## Protocol deltas from the domestic runner, declared

- Selection walk-forward scores 2023 and 2024 only (2022 opens the replay;
  2025 quarantined behind the runner's own guard).
- Bootstrap clusters are ISO **matchweeks** in both phases (2,000 resamples):
  two season clusters would make the selection CI a two-point range; the
  domestic confirmation run already uses matchweek clustering for the same
  reason.
- Ratings replay UCL history only, from the documented 1500 cold start.
  Serving injects domestic ratings for shared clubs (`owns_served_rating`);
  that context is not reproducible offline, so the fit reads primarily on the
  goal environment. Finals (4 of 988 rows) are neutral in serving but
  replayed with home advantage here — declared approximation.

## Selection (walk-forward, 493 matches / 49 matchweek clusters)

| Candidate | Metric | Mean Δ | CI95 | Picks | Verdict |
|---|---|---|---|---|---|
| `U1_base` | O/U 2.5 log loss | **−0.0332** | [−0.0462, −0.0191] | 2023→1.32, 2024→1.38 | **BETTER (credible)** |
| `U2_home_adv` | 1X2 log loss | +0.0010 | [−0.0038, +0.0061] | 2023→80, 2024→70 | not credible — **home_adv stays 60, not shipped** |

Frozen config: `base` = argmin of mean O/U loss on ALL pre-confirmation
editions (707 matches, 2025 never read) = **1.44** (LL 0.6832 vs 0.7116 at
the served 1.20). Sanity anchor: observed 2.97 goals/match 2022–2024 vs the
2.40 the served base implies. (That 1.44 equals Bundesliga's fitted base is a
coincidence of two high-scoring environments, not a copied value.)

## Confirmation (quarantined 2025 edition, one shot, frozen config)

281 matches / 25 matchweek clusters. **The edition is now consumed** — do not
re-run `--confirm`; the next clean holdout is the live 2026-27 edition, which
the `+baseline` twin scores continuously.

| Metric | Mean Δ | CI95 | Verdict |
|---|---|---|---|
| 1X2 log loss | **−0.0119** | [−0.0170, −0.0061] | **CONFIRMED — credibly better** |
| O/U 2.5 log loss | **−0.0356** | [−0.0640, −0.0005] | **CONFIRMED — credibly better** |

Credible on both metrics — a stronger result than EPL's own base refit
(favourable, not credible, shipped on the defect-fix bar).

## Ship list

- `LEAGUES["ucl"]["model_params"] = {"base": 1.44}`; `home_advantage` stays
  60.0 (refit not credible).
- `model_version` → `poisson-elo-ucl-v0.2` (v0.2 names the fit process, same
  convention as `CLUB_MODEL_VERSION`).
- `shadow_baseline: True` with `shadow_baseline_version:
  "poisson-elo-ucl-v0.1"` — the unfitted predecessor rides along as the live
  `+baseline` twin (rows `poisson-elo-ucl-v0.2+baseline`), so the promotion
  is measurable in live conditions from the league phase onward.

## Reproduction receipt

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_ucl_eval \
    --all --cache-dir <dir>          # selection (fetches/caches 4 editions)
PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_ucl_eval \
    --confirm --cache-dir <dir>      # ONE SHOT — already consumed 2026-08-06
```
