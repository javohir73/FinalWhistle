# WC26 Endgame Runbook

## 1. Shadow-gate readout (owner action, after each knockout round)
- Odds twin readout: query prediction_results WHERE is_shadow=true on the prod
  replica (log_loss is a column there; GET /api/internal/shadow-record reports
  winner_acc/brier only — no log loss).
- Availability twin readout: GET /api/internal/availability-record (paired
  log losses + diff CI + verdict; the +avail twin writes NO prediction_results
  rows, so shadow-record/SQL cannot answer its gate).
- Gate: >= 30 scored shadow pairs AND the odds-anchored twin
  (poisson-elo-v0.3-shadow) ahead of production on avg log loss. Same rule
  for the availability twin (poisson-elo-v0.3+avail).

## 2. Promotion (only after the gate clears)
1. `PYTHONPATH=backend:. .venv/bin/python -m pipeline.promote_blend --w-odds <weight from shadow readout, cap 0.5> [--use-availability] --ship`
2. Bump MODEL_VERSION in render.yaml to poisson-elo-v0.6 (lockstep with params).
3. Branch, PR with the shadow-readout numbers in the description, CI green,
   stop gate, human merges. No migration involved.
4. Verify: /api/health ok; next pipeline run writes model_version
   poisson-elo-v0.6 rows for the remaining scheduled matches.

## 3. Form-channel re-gate (after the QFs)
1. `PYTHONPATH=backend:. .venv/bin/python -m pipeline.run_experiments --years 2018 2022`
2. `PYTHONPATH=backend:. .venv/bin/python -m pipeline.replay_wc26`
3. Promote form_channels ONLY if v0.x+form beats the no-form variant on log
   loss on ALL THREE holdouts (2018, 2022, WC26 replay). Otherwise it stays
   dark; record the result in docs/MODEL-V2-DESIGN.md §5b either way.

## 4. Post-deploy verification (any promotion)
- GET /api/health → status ok.
- GET /api/model/record → model_version reflects the new env pin.
- Spot-check one scheduled match card: probabilities present, availability
  note consistent with the adjusted triple when use_availability is on.
