# WC26 Endgame Runbook

## 1. Shadow-gate readout (automated daily; owner reads the summary)
- `shadow-record.yml` runs on its own every day at 07:30 UTC (after the 06:00
  UTC refresh has scored new pairs) — manual dispatch still works too. It GETs
  shadow-record + availability-record and writes **GATE MET / GATE NOT MET
  (n=X/30, Δ avg log-loss)** to the workflow job summary. No more manual
  curls or a prod-replica SQL query to check status: GET
  /api/internal/shadow-record now reports avg_log_loss directly alongside
  winner_acc/brier.
- Availability twin readout: same workflow run GETs
  /api/internal/availability-record (paired log losses + diff CI + verdict;
  the +avail twin writes NO prediction_results rows, so shadow-record cannot
  answer its gate) and writes its own **Availability promotion gate** section
  to the job summary — no more reading the raw JSON by hand, see §4.
- Gate (odds twin): >= 30 scored shadow pairs AND the odds-anchored twin
  (poisson-elo-v0.3-shadow) ahead of production on avg log loss. The
  availability twin uses a different, lower-n rule — see §4.

## 2. Promotion (only after the summary says GATE MET)
1. `PYTHONPATH=backend:. .venv/bin/python -m pipeline.promote_blend --w-odds 0.35 --use-odds [--use-availability] --ship`
   (`--use-odds` flips the production serving path added 2026-07-11 —
   `--w-odds` alone only arms the shadow twin, it won't serve). Ship it via
   PR through the stop gate; promotion stays a manual owner decision.
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

## 4. Availability promotion

The availability twin is measured live only (no XI data pre-2026 means it can't
be historically backtested), so its promotion gate is its own machine check
with a lower n floor than the odds twin's — not the same >=30-pairs rule.

- Read it from the same shadow-record run summary: `shadow-record.yml`'s
  "Availability promotion gate" section (`pipeline.availability_gate
  .availability_gate` over the fetched availability-record — tested Python,
  not jq) reports GATE MET / GATE NOT MET, n vs min_n, Δ log-loss, and a reason.
- Criteria: n >= 20 scored pairs (production + availability twin both present
  on the same finished match) AND diff_ci95's upper bound < 0 (availability
  credibly ahead of production on log loss across the whole interval — same
  CI convention as the odds gate, just a lower n floor given how few matches
  carry announced-XI data).
- Promote only after GATE MET: `PYTHONPATH=backend:. .venv/bin/python -m
  pipeline.promote_blend --use-availability --ship`, shipped via PR through
  the stop gate — model_params.json changes are a manual owner decision, same
  as the odds twin. Served version derives from model_params.json — no
  render.yaml change needed.

## 5. Post-deploy verification (any promotion)
- GET /api/health → status ok.
- GET /api/model/record → model_version reflects the new env pin.
- Spot-check one scheduled match card: probabilities present, availability
  note consistent with the adjusted triple when use_availability is on.
