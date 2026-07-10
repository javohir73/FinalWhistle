# Model Quality Phase 1 — Shadow Promotion Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the live shadow-twin evidence and the local walk-forward gate verdicts, present a per-twin evidence card for the owner's go/no-go, and (only for approved twins) promote via the existing params-only flow — before the WC26 semi-finals.

**Architecture:** One new read-only GitHub Actions workflow pulls the token-guarded internal records; all gate computation runs locally against the existing harness (`pipeline/experiment_model_eval.py`); promotion is a `model_params.json` flip through `pipeline/promote_blend.py` (or a params edit for `team_offsets`), shipped through the normal PR → stop gate → merge → `refresh.yml` sequence. No serving code changes.

**Tech Stack:** GitHub Actions + curl/jq (evidence pull), existing Python harness (walk-forward gates), params-only promotion.

**Spec:** `docs/superpowers/specs/2026-07-10-model-quality-v06-design.md` (Phase 1 section).

## Global Constraints

- **No new serving code mid-tournament.** Promotion = params flips only (`w_odds` ≤ 0.5 cap, `use_availability`, `team_offsets`). Twins without an existing params flag (`v0.5+bans`, `v0.5+rest`) appear on the evidence card as information only.
- **The repo's own gates govern**, per the runbook (`docs/RUNBOOK-WC26-ENDGAME.md`): odds blend requires **≥ 30 scored shadow pairs with the twin ahead** — the card must state plainly whether that gate is met (currently 14 pairs, so expect NOT MET unless grading has advanced); team offsets require `run_team_offsets_gate`'s ship rule; availability is live-only evidence via `/api/internal/availability-record`.
- **User go/no-go per twin** before any promotion; the promotion PR merging to main is **stop-gated** (plain-English summary + explicit "go", CI green first).
- Mid-tournament promoted version string is `poisson-elo-v0.5.1` — **not** v0.6 (v0.6 is the post-final research version).
- Evidence artifacts are committed under `docs/experiments/2026-07-10-phase1/` so verdicts are auditable.
- Python: `"/Users/macbookpro/Projects/FIFA WC26 Prediction/.venv/bin/python"` with `PYTHONPATH=backend:.` — the harness imports `app.db` and reads the local dev DB.
- Do not push `main` directly; never run alembic against prod (no migrations exist in this plan anyway).

---

### Task 1: `shadow-record` read-only ops workflow

**Files:**
- Create: `.github/workflows/shadow-record.yml`

**Interfaces:**
- Consumes: existing repo secrets `API_URL`, `RECOMPUTE_TOKEN` (same as `ops-flag-internal.yml`); prod endpoints `GET /api/internal/shadow-record` and `GET /api/internal/availability-record`, auth header `X-Recompute-Token`.
- Produces: workflow run logs containing two pretty-printed JSON blocks. `shadow-record` returns `{"production": {n, exact_hits, winner_acc, avg_brier, model_versions}, "shadow": {...}, "production_full_record": {...}}` (production is paired to the same match set as shadow — like-for-like by design).

- [ ] **Step 1: Write the workflow**

`.github/workflows/shadow-record.yml`:

```yaml
# Read-only evidence pull for the MANUAL shadow-promotion decision (FR-4.8):
# prints the production-vs-shadow record and the availability-twin record from
# the token-guarded internal endpoints. Writes nothing; manual dispatch only.
# Same secrets as refresh-live / ops-flag-internal:
#   API_URL          e.g. https://pitchprophet-api.onrender.com
#   RECOMPUTE_TOKEN  same value as the backend's RECOMPUTE_TOKEN env var
name: shadow-record

on:
  workflow_dispatch: {}

jobs:
  readout:
    runs-on: ubuntu-latest
    steps:
      - name: GET shadow-record + availability-record
        env:
          API_URL: ${{ secrets.API_URL }}
          RECOMPUTE_TOKEN: ${{ secrets.RECOMPUTE_TOKEN }}
        run: |
          set -euo pipefail
          if [ -z "${API_URL:-}" ] || [ -z "${RECOMPUTE_TOKEN:-}" ]; then
            echo "API_URL / RECOMPUTE_TOKEN secrets not set — cannot call the API." >&2
            exit 1
          fi
          echo "== shadow-record (production vs odds-anchored twin, paired matches) =="
          curl -sfS -H "X-Recompute-Token: ${RECOMPUTE_TOKEN}" \
            "${API_URL}/api/internal/shadow-record" | jq .
          echo
          echo "== availability-record (availability twin vs published forecast) =="
          curl -sfS -H "X-Recompute-Token: ${RECOMPUTE_TOKEN}" \
            "${API_URL}/api/internal/availability-record" | jq .
```

- [ ] **Step 2: Commit and open the PR**

```bash
git checkout -b ops/shadow-record-workflow origin/main
git add .github/workflows/shadow-record.yml
git commit -m "ops: read-only shadow-record evidence workflow"
git push -u origin ops/shadow-record-workflow
gh pr create --title "ops: read-only shadow-record evidence workflow" --body "Manual-dispatch, read-only: prints the token-guarded shadow-record and availability-record so the Phase 1 promotion review (spec 2026-07-10-model-quality-v06) has its live evidence. No writes, no new secrets.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 3: STOP GATE — wait for CI green + the owner's "go", then merge**

`workflow_dispatch` workflows must exist on the default branch to be dispatchable, so this small merge is required. Present: "one new read-only workflow file, nothing else." After the explicit go: `gh pr merge <PR#> --merge`.

- [ ] **Step 4: Dispatch and capture the evidence**

```bash
gh workflow run shadow-record.yml
sleep 10 && RUN_ID=$(gh run list --workflow=shadow-record.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
mkdir -p docs/experiments/2026-07-10-phase1
gh run view "$RUN_ID" --log | sed -n '/== shadow-record/,$p' > docs/experiments/2026-07-10-phase1/live-records.txt
```

Expected: both JSON blocks present; `shadow.n` is the current pair count (14 at spec time — note the actual value), `shadow.model_versions` tells which twins actually write graded rows.

---

### Task 2: Local walk-forward gate runs

**Files:**
- Create: `docs/experiments/2026-07-10-phase1/model-eval.txt` (captured output)
- Create: `docs/experiments/2026-07-10-phase1/team-offsets-gate.json`
- Create: `docs/experiments/2026-07-10-phase1/xg-backtest.txt`

**Interfaces:**
- Consumes: `pipeline.experiment_model_eval.run` (via its CLI), `run_team_offsets_gate(rows, test_since=2018, n_boot=2000, half_life_days=DEFAULT_HALF_LIFE_DAYS, served_params=None)`, `pipeline.backtest_xg_offsets` CLI, `pipeline.backtest_data.build_enriched_rows(db)`.
- Produces: three committed evidence files Task 3 reads.

- [ ] **Step 1: Verify the local DB has replayable history**

```bash
cd "/Users/macbookpro/Projects/FIFA WC26 Prediction"
PYTHONPATH=backend:. .venv/bin/python - <<'EOF'
from app.db import SessionLocal
from pipeline.backtest_data import build_enriched_rows
db = SessionLocal(); rows = build_enriched_rows(db); db.close()
print("replayable rows:", len(rows))
EOF
```

Expected: several thousand rows. **If it prints < 1000, STOP this task** and report to the orchestrator — the local DB lacks history and the gates would be hollow; do not fabricate a verdict (the fix is seeding history via the pipeline, a separate decision).

- [ ] **Step 2: Run the main candidate evaluation**

```bash
mkdir -p docs/experiments/2026-07-10-phase1
PYTHONPATH=backend:. .venv/bin/python -m pipeline.experiment_model_eval --since 2004 --boot 2000 \
  | tee docs/experiments/2026-07-10-phase1/model-eval.txt
```

Expected: candidate table (log-loss/RPS/Brier/exactNLL/top-k/ECE), per-class ECE, paired bootstrap vs v0.1 with CI verdicts. This is long-running (bootstrap 2000) — allow up to ~30 min; do not kill it early.

- [ ] **Step 3: Run the team-offsets gate**

```bash
PYTHONPATH=backend:. .venv/bin/python - <<'EOF' | tee docs/experiments/2026-07-10-phase1/team-offsets-gate.json
import json
from app.db import SessionLocal
from pipeline.backtest_data import build_enriched_rows
from pipeline.experiment_model_eval import run_team_offsets_gate
db = SessionLocal(); rows = build_enriched_rows(db); db.close()
res = run_team_offsets_gate(rows, test_since=2018, n_boot=2000)
print(json.dumps(res, indent=2, default=str))
EOF
```

Expected: JSON with the paired gate summary (top-1 hit CI / exact-score NLL CI and a ship verdict field). The gate's ship rule is the repo's own (`_paired_gate_summary`): top-1 CI up OR exact-score NLL CI down without top-1 regression.

- [ ] **Step 4: Run the xG offsets backtest**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.backtest_xg_offsets \
  | tee docs/experiments/2026-07-10-phase1/xg-backtest.txt
```

Expected: A/B/C per-edition comparison (2018, 2022) — goals-only vs xG-nudged offsets. Note in the file's header comment that live xG coverage starts 2023–24, so this is underpowered by construction (the build script's own caveat).

- [ ] **Step 5: Commit the evidence**

```bash
git checkout -b docs/phase1-evidence origin/main 2>/dev/null || git checkout docs/phase1-evidence
git add docs/experiments/2026-07-10-phase1/
git commit -m "docs: phase 1 gate evidence — model eval, team-offsets gate, xg backtest"
```

(Reuse this branch in Task 3; one PR carries the evidence + card.)

---

### Task 3: Evidence card + owner go/no-go

**Files:**
- Create: `docs/experiments/2026-07-10-phase1/EVIDENCE-CARD.md`

**Interfaces:**
- Consumes: `live-records.txt` (Task 1), the three gate files (Task 2), runbook thresholds (`docs/RUNBOOK-WC26-ENDGAME.md`: odds gate = ≥30 pairs AND twin ahead).
- Produces: the card the owner decides from; decisions recorded in the same file.

- [ ] **Step 1: Confirm the shadow twin's blend weight (needed if odds blend is approved)**

```bash
grep -n "w_odds" pipeline/generate_predictions.py | head -5
```

Expected: the line constructing the shadow twin's params shows the w_odds value the live shadow actually ran with (the runbook says promote "the weight from the shadow readout" — record this exact value on the card; do not invent a different weight).

- [ ] **Step 2: Write the card**

`docs/experiments/2026-07-10-phase1/EVIDENCE-CARD.md`, filled from the captured artifacts — this template with every `<...>` replaced by real numbers:

```markdown
# Phase 1 Evidence Card — shadow promotion review (2026-07-10)

Live records: live-records.txt · Gates: model-eval.txt, team-offsets-gate.json, xg-backtest.txt
Runbook gate for the odds blend: >= 30 scored shadow pairs AND twin ahead (docs/RUNBOOK-WC26-ENDGAME.md).

| Twin | Params flag | Repo gate verdict | Live evidence | Recommendation | Owner decision |
|---|---|---|---|---|---|
| odds-total blend (v0.3-shadow, w=<w>) | w_odds | <met / NOT met: n=<n> of 30 pairs> | shadow brier <x> vs prod <y>, winner acc <a> vs <b> | <promote / hold> | _pending_ |
| xG team offsets (v0.3+xg) | team_offsets | <ship / no-ship from team-offsets-gate.json> | xg-backtest: <one-line per-edition summary> | <promote / hold> | _pending_ |
| availability (v0.3+avail) | use_availability | live-only (no backtest gate by design) | availability-record: <paired numbers> | <promote / hold> | _pending_ |
| suspensions (v0.5+bans) | none — info only | n/a | <from live-records if present> | not promotable in Phase 1 | n/a |
| rest days (v0.5+rest) | none — info only | n/a | <from live-records if present> | not promotable in Phase 1 | n/a |

Recommendation rule applied: promote only when the repo gate is met AND live evidence is non-worse.
```

- [ ] **Step 3: Commit and present**

```bash
git add docs/experiments/2026-07-10-phase1/EVIDENCE-CARD.md
git commit -m "docs: phase 1 evidence card for shadow promotion review"
```

**STOP — present the card to the owner in plain English, one line per twin, and ask for go/no-go per twin.** Record the decisions in the card (edit `_pending_` → `GO`/`NO-GO`, amend the commit). If every decision is NO-GO, open a docs-only PR with the evidence + card, and this plan ends after its merge — Task 4 is skipped.

---

### Task 4 (conditional — only for twins the owner approved): promotion

**Files:**
- Modify: `ml/models/model_params.json` (via the tools below, never hand-edited except `team_offsets`)
- Modify: `render.yaml:28` (`MODEL_VERSION` — sync the drift while we're here)
- Modify: `CLAUDE.md` (the "Model version string" line, same drift)

**Interfaces:**
- Consumes: owner decisions from Task 3; `pipeline.promote_blend` CLI (`--w-odds <float ≤ 0.5> [--use-availability] --version <str> --ship`); `ml.models.params.load_params/save_params` for `team_offsets`.
- Produces: `poisson-elo-v0.5.1` params, one promotion PR through the stop gate.

- [ ] **Step 1: Flip the approved flags**

If odds blend and/or availability approved (use the shadow's exact weight from Task 3 Step 1; skip `--use-availability` if not approved):

```bash
PYTHONPATH=backend:. .venv/bin/python -m pipeline.promote_blend \
  --w-odds <shadow_w> --use-availability --version poisson-elo-v0.5.1
# review the dry-run output, then re-run with --ship
PYTHONPATH=backend:. .venv/bin/python -m pipeline.promote_blend \
  --w-odds <shadow_w> --use-availability --version poisson-elo-v0.5.1 --ship
```

If xG team offsets approved (params-only; the artifact `ml/models/team_offsets_xg.json` already exists):

```bash
PYTHONPATH=backend:. .venv/bin/python - <<'EOF'
from dataclasses import replace
from ml.models.params import load_params, save_params
p = load_params()
save_params(replace(p, team_offsets={"file": "team_offsets_xg.json"},
                    version="poisson-elo-v0.5.1"))
print("team_offsets ->", load_params().team_offsets)
EOF
```

- [ ] **Step 2: Sync the version-string drift**

In `render.yaml` set `MODEL_VERSION: poisson-elo-v0.5.1`; in `CLAUDE.md` update the "Model version string" line to `poisson-elo-v0.5.1 (render.yaml)`.

- [ ] **Step 3: Full test gate**

```bash
.venv/bin/python -m pytest -p no:warnings
cd frontend && npm run typecheck && npm run lint && npm test
```

Expected: exit 0 across the board (params flips must not break any serving test — `w_odds`/`team_offsets` load paths are already exercised by existing tests).

- [ ] **Step 4: Promotion PR**

```bash
# Branch from the evidence branch (Tasks 2-3) so the card and gate outputs
# ride in the same PR as the params flip they justify.
git checkout -b feat/promote-shadow-twins docs/phase1-evidence
git add ml/models/model_params.json render.yaml CLAUDE.md docs/experiments/2026-07-10-phase1/
git commit -m "feat: promote gated shadow twins to serving (poisson-elo-v0.5.1)"
git push -u origin feat/promote-shadow-twins
gh pr create --title "feat: promote gated shadow twins (poisson-elo-v0.5.1)" --body "Params-only promotion per the Phase 1 evidence card (docs/experiments/2026-07-10-phase1/EVIDENCE-CARD.md): <list the approved flags and their evidence one line each>. No serving code changes; frozen past predictions untouched; NRL untouched.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 5: STOP GATE — summary + owner "go", CI green, then merge and roll out**

After the explicit go:

```bash
gh pr merge <PR#> --merge
gh workflow run refresh.yml        # regenerates predictions for the 4 remaining fixtures
gh run watch <run-id> --exit-status
curl -s https://pitchprophet-api.onrender.com/api/health | jq .model_version
# expect "poisson-elo-v0.5.1"; then spot-check one SF fixture:
curl -s "https://pitchprophet-api.onrender.com/api/matches/upcoming" | jq '[.[] | select(.status=="scheduled")][0]'
# open that match's detail and confirm model_version + changed probabilities
```

Expected: health reports the new version; the next scheduled fixture's prediction carries `poisson-elo-v0.5.1` and probabilities that differ from the pre-promotion values (capture both in the PR thread for the audit trail).
