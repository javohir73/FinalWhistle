# Dual-Basis Record + WC26 Endgame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the knockout-advancement grading basis alongside the strict 90-minute record, and stage the odds/availability promotions so flipping them on gate-clearance day is a params-only PR.

**Architecture:** Backend adds advancement metrics to the existing `/api/model/record` aggregate (same graded ledger, second grading basis). Frontend surfaces them on the Track Record page and the methodology benchmark footnote. Promotion staging = a params-flip script for `w_odds` plus a `use_availability` ModelParams flag wiring the existing shadow-twin availability math into the production path, dark by default with proven bit-identity. A runbook captures the endgame procedure (gate readout → flip → verify, form re-gate after QFs).

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js + Jest/RTL (frontend), pytest, existing ml/ Poisson-Elo engine.

## Global Constraints

- **Base branch:** cut from `main` AFTER PR #124 (benchmark table) merges — Task 3 edits the section #124 introduces. If #124 is not merged, stop and say so.
- Track 1 of spec `docs/superpowers/specs/2026-07-08-universal-engine-design.md`; do not start Track 2 work.
- Test gates before any "done" claim: `.venv/bin/python -m pytest backend ml pipeline` and `cd frontend && npm run typecheck && npm run lint && npm test`. Paste real output.
- Never merge, never push to `main`; feature branch + PR only. Prod deploys and `refresh.yml` are owner actions.
- The append-only, frozen-at-kickoff predictions rule is untouchable.
- `w_odds` hard cap **0.5** (market is never primary — standing product rule).
- Every new flag defaults OFF with a bit-identity test proving zero behavior change while off (same standard as `form_channels`).
- Python commands from repo root need `PYTHONPATH=backend:.` when running pipeline modules.

---

### Task 1: Advancement metrics on `/api/model/record`

**Files:**
- Modify: `backend/app/api/model_record.py` (aggregate block, ~lines 101-150)
- Test: `backend/tests/test_model_record_api.py`

**Interfaces:**
- Consumes: existing `rows` list of `(PredictionResult, Prediction, Match)` tuples and `wilson_ci95(k, n)` already in the module.
- Produces: response fields `advancement_matches: int`, `advancement_correct: int`, `advancement_accuracy: float|None`, `advancement_ci95: [lo, hi]|None` — Tasks 2 and 3 consume these exact names.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_model_record_api.py`; `Team`, `Tournament`, `Match`, `Prediction`, `PredictionResult` are already imported at the top of that file)

```python
def test_record_advancement_basis_credits_shootout_wins(client):
    """A knockout drawn at 90' but won on penalties by our picked side is an
    advancement hit even though strict W/D/L grading scores it a miss; group
    matches never enter the advancement sample."""
    from datetime import datetime, timezone

    c, TestingSession = client
    db = TestingSession()
    fra = Team(name="France", country_code="FR", confederation="UEFA")
    mar = Team(name="Morocco", country_code="MA", confederation="CAF")
    wc = Tournament(name="FIFA World Cup 2026", year=2026)
    db.add_all([wc, fra, mar])
    db.flush()

    def make(stage, score, pens, probs, winner_ok, kick_day):
        m = Match(tournament_id=wc.id, team_home_id=fra.id, team_away_id=mar.id,
                  stage=stage, status="finished",
                  score_home=score[0], score_away=score[1],
                  penalty_home=pens[0] if pens else None,
                  penalty_away=pens[1] if pens else None,
                  kickoff_utc=datetime(2026, 7, kick_day, tzinfo=timezone.utc))
        db.add(m)
        db.flush()
        p = Prediction(match_id=m.id, model_version="poisson-elo-v0.4",
                       prob_home_win=probs[0], prob_draw=probs[1], prob_away_win=probs[2],
                       predicted_score_home=1, predicted_score_away=0)
        db.add(p)
        db.flush()
        db.add(PredictionResult(
            match_id=m.id, prediction_id=p.id, model_version="poisson-elo-v0.4",
            actual_score_home=score[0], actual_score_away=score[1],
            outcome="draw" if score[0] == score[1] else "home",
            winner_correct=winner_ok, exact_score_correct=False,
            prob_assigned=probs[0], brier=0.5, log_loss=0.9, goal_error=0,
        ))

    # QF drawn 1-1, France win the shootout; we favoured France:
    # strict-basis miss, advancement hit.
    make("QF", (1, 1), (4, 2), (0.55, 0.27, 0.18), False, 9)
    # R16 won outright 2-0 by France; hit on both bases.
    make("R16", (2, 0), None, (0.60, 0.25, 0.15), True, 5)
    # Group draw — must NOT enter the advancement sample.
    make("group", (0, 0), None, (0.50, 0.28, 0.22), False, 1)
    db.commit()

    body = c.get("/api/model/record").json()
    assert body["advancement_matches"] == 2
    assert body["advancement_correct"] == 2
    assert body["advancement_accuracy"] == 1.0
    assert body["advancement_ci95"] is not None
    # Strict basis unchanged by the new fields: 1 of 3 winner calls correct.
    assert body["winners_correct"] == 1


def test_empty_record_advancement_fields(client):
    c, _ = client
    body = c.get("/api/model/record").json()
    assert body["advancement_matches"] == 0
    assert body["advancement_correct"] == 0
    assert body["advancement_accuracy"] is None
    assert body["advancement_ci95"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_model_record_api.py -q`
Expected: 2 FAIL with `KeyError: 'advancement_matches'`

- [ ] **Step 3: Implement** in `backend/app/api/model_record.py`

Add module-level helper (below `wilson_ci95`):

```python
def _advancer(match: Match) -> str | None:
    """Which side progressed a knockout tie: final score (incl. extra time),
    then penalties. None when it cannot be determined (defensive)."""
    sh, sa = match.score_home, match.score_away
    if sh is None or sa is None:
        return None
    if sh != sa:
        return "home" if sh > sa else "away"
    ph, pa = match.penalty_home, match.penalty_away
    if ph is not None and pa is not None and ph != pa:
        return "home" if ph > pa else "away"
    return None
```

Inside `model_record()`, after the `best_streak` block:

```python
    # Knockout advancement basis (universal-engine spec §4.1): pick = higher
    # side probability from the frozen production row; actual = side that
    # went through. Group matches are excluded by definition.
    adv_n = adv_ok = 0
    for r, p, m in rows:
        if (m.stage or "group") == "group":
            continue
        went = _advancer(m)
        if went is None:
            continue
        pick = "home" if (p.prob_home_win or 0.0) >= (p.prob_away_win or 0.0) else "away"
        adv_n += 1
        adv_ok += pick == went
```

Add to the populated `out` dict (after `"best_streak": best_streak,`):

```python
        "advancement_matches": adv_n,
        "advancement_correct": adv_ok,
        "advancement_accuracy": round(adv_ok / adv_n, 4) if adv_n else None,
        "advancement_ci95": wilson_ci95(adv_ok, adv_n) if adv_n else None,
```

Add to the empty-record `out` dict (after `"best_streak": 0,`):

```python
            "advancement_matches": 0,
            "advancement_correct": 0,
            "advancement_accuracy": None,
            "advancement_ci95": None,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_model_record_api.py -q`
Expected: all pass (9 tests)

- [ ] **Step 5: Run the backend suite**

Run: `.venv/bin/python -m pytest backend -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/model_record.py backend/tests/test_model_record_api.py
git commit -m "feat(record): knockout advancement basis on /api/model/record"
```

---

### Task 2: Track Record page — knockout-progression stat card

**Files:**
- Modify: `frontend/lib/types.ts` (ModelRecord interface, ~line 275)
- Modify: `frontend/components/RecordView.tsx` (hero section, lines 26-39)
- Test: `frontend/components/__tests__/recordView.test.tsx`

**Interfaces:**
- Consumes: Task 1's response fields, exact names `advancement_matches`, `advancement_correct`, `advancement_accuracy`, `advancement_ci95`.
- Produces: `ModelRecord` TypeScript fields of the same names (Task 3 reuses them).

- [ ] **Step 1: Extend the type.** In `frontend/lib/types.ts`, inside `interface ModelRecord`, after `best_streak: number;`:

```ts
  advancement_matches: number;
  advancement_correct: number;
  advancement_accuracy: number | null;
  advancement_ci95: [number, number] | null;
```

- [ ] **Step 2: Write the failing test.** In `frontend/components/__tests__/recordView.test.tsx`: add the four fields to BOTH existing fixtures (populated fixture: `advancement_matches: 24, advancement_correct: 19, advancement_accuracy: 0.7917, advancement_ci95: [0.59, 0.91],`; empty/zero fixture: `advancement_matches: 0, advancement_correct: 0, advancement_accuracy: null, advancement_ci95: null,`). Then append, following the file's existing render helpers:

```tsx
it("shows the knockout progression card when advancement data exists", () => {
  render(<RecordView record={baseRecord} />);
  expect(screen.getByText("Knockout progression")).toBeInTheDocument();
  expect(screen.getByText("79%")).toBeInTheDocument();
  expect(screen.getByText(/19 of 24 ties/)).toBeInTheDocument();
});

it("hides the knockout progression card before any knockouts are graded", () => {
  render(<RecordView record={{ ...baseRecord, advancement_matches: 0, advancement_correct: 0, advancement_accuracy: null, advancement_ci95: null }} />);
  expect(screen.queryByText("Knockout progression")).not.toBeInTheDocument();
});
```

(`baseRecord` = whatever the populated fixture object in that file is named — reuse it, do not create a duplicate fixture.)

- [ ] **Step 3: Run tests to verify the new ones fail**

Run: `cd frontend && npx jest components/__tests__/recordView.test.tsx`
Expected: the two new tests FAIL ("Knockout progression" not found)

- [ ] **Step 4: Implement the card.** In `frontend/components/RecordView.tsx`, `cn` is already imported. Replace the hero section (currently a 2-column grid holding the two `StatCI` cards) with:

```tsx
      {/* Hero row — the headline rates, front and centre. */}
      <section className={cn("grid gap-4", record.advancement_matches > 0 ? "sm:grid-cols-3" : "sm:grid-cols-2")}>
        <StatCI title="Winner accuracy" value={pct(record.winner_accuracy)} />
        {record.advancement_matches > 0 && (
          <StatCI
            title="Knockout progression"
            value={pct(record.advancement_accuracy)}
            sub={`${record.advancement_correct} of ${record.advancement_matches} ties — picked who goes through`}
          />
        )}
        <StatCI
          title="Exact scores"
          value={pct(record.exact_score_rate)}
          sub={`${record.exact_score_hits} of ${n} scorelines exact`}
        />
      </section>
```

Also add one sentence to the footer section's first `<p>` (after the model-version line) so the basis is explained where the numbers live:

```tsx
        <p className="mt-1">
          Winner accuracy grades every match on the 90-minute result, draws
          included — the strictest basis. Knockout progression grades ties on
          who went through (extra time and penalties count), the basis most
          public picking contests use.
        </p>
```

- [ ] **Step 5: Run the frontend gates**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/types.ts frontend/components/RecordView.tsx frontend/components/__tests__/recordView.test.tsx
git commit -m "feat(record): knockout progression card on the Track Record page"
```

---

### Task 3: Methodology benchmark footnote — live advancement number

**Files:**
- Modify: `frontend/app/methodology/page.tsx` (the "How does it compare to other predictors?" section's footnote paragraph)

**Interfaces:**
- Consumes: the page's existing `record: ModelRecord | null` (already fetched via `getModelRecordServer()` for the benchmark table) and Task 2's type fields.

- [ ] **Step 1: Replace the footnote paragraph.** Find the `<p className="mt-3 text-xs leading-relaxed text-muted">` footnote in that section ("Apples-to-oranges caveats…") and replace the whole paragraph with:

```tsx
        <p className="mt-3 text-xs leading-relaxed text-muted">
          Apples-to-oranges caveats, stated plainly: the contests grade slightly
          different match sets (their table implies ~94 picks; we grade every
          finished match with a frozen pre-kickoff prediction), and picking rules
          differ — our headline number grades the 90-minute result, draws
          included, which is a stricter test than knockout-winner-only picks. On
          the advancement basis those contests use for knockouts, our record is{" "}
          {record && record.advancement_matches > 0
            ? `${record.advancement_correct} of ${record.advancement_matches} (${((record.advancement_accuracy ?? 0) * 100).toFixed(1)}%)`
            : "still building as the knockouts finish"}
          . We publish the comparison anyway because pretending benchmarks
          don&apos;t exist is worse than imperfect ones. Source: The Athletic,
          July 2026.
        </p>
```

- [ ] **Step 2: Run the frontend gates**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: all pass

- [ ] **Step 3: Verify in the preview.** Start the `backend` and `frontend` servers from `.claude/launch.json` (preview tools), open `/methodology`, and confirm: the footnote renders the advancement clause (local DB has no knockouts, so expect the "still building" branch), no console errors. On `/record` confirm the third stat card is absent locally (advancement_matches 0) — the card's presence is covered by the Task 2 unit test.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/methodology/page.tsx
git commit -m "feat(methodology): live advancement-basis clause in the benchmark footnote"
```

---

### Task 4: `promote_blend.py` — params-only odds promotion, dry-run default

**Files:**
- Create: `pipeline/promote_blend.py`
- Test: `pipeline/promote_blend_test.py`

**Interfaces:**
- Consumes: `ml.models.params.load_params/save_params/ModelParams` (existing), `dataclasses.replace`.
- Produces: CLI `python -m pipeline.promote_blend --w-odds 0.35 [--use-availability] [--ship] [--version poisson-elo-v0.5]`; a pure helper `promoted_params(params, w_odds, use_availability, version)` used by the test and Task 6's runbook.

- [ ] **Step 1: Write the failing tests** in `pipeline/promote_blend_test.py` (follow `ml/models/params_test.py` for the params-file monkeypatch fixture style):

```python
import pytest

from ml.models.params import DEFAULT_PARAMS
from pipeline.promote_blend import promoted_params


def test_promoted_params_sets_capped_w_odds_and_version():
    out = promoted_params(DEFAULT_PARAMS, w_odds=0.35, use_availability=False,
                          version="poisson-elo-v0.5")
    assert out.w_odds == 0.35
    assert out.version == "poisson-elo-v0.5"
    assert out.use_availability is False


def test_promoted_params_rejects_weight_above_cap():
    with pytest.raises(ValueError):
        promoted_params(DEFAULT_PARAMS, w_odds=0.51, use_availability=False,
                        version="poisson-elo-v0.5")


def test_promoted_params_rejects_nonpositive_weight_without_availability():
    with pytest.raises(ValueError):
        promoted_params(DEFAULT_PARAMS, w_odds=0.0, use_availability=False,
                        version="poisson-elo-v0.5")


def test_promoted_params_availability_only_flip_is_allowed():
    out = promoted_params(DEFAULT_PARAMS, w_odds=0.0, use_availability=True,
                          version="poisson-elo-v0.5")
    assert out.w_odds == 0.0
    assert out.use_availability is True
```

Note: `use_availability` does not exist on ModelParams until Task 5. Task 4 and Task 5 land TOGETHER in review order 5-then-4 if executed by separate workers; if executed sequentially by one worker, do Task 5 first. (Dependency: Task 4 tests import the field.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest pipeline/promote_blend_test.py -q`
Expected: FAIL with `ModuleNotFoundError: pipeline.promote_blend`

- [ ] **Step 3: Implement** `pipeline/promote_blend.py`:

```python
"""Promote the market-odds blend / availability adjustment (spec §4.2).

Params-only: flips ``w_odds`` (hard cap 0.5 — the market is never primary)
and/or ``use_availability`` on model_params.json and bumps the version.
Dry-run by default; --ship writes the file. Merge + deploy stay human-gated.

Run this ONLY after the shadow gate clears: >=30 scored shadow pairs with the
blended twin ahead of production on log loss (see docs/RUNBOOK-WC26-ENDGAME.md).

Usage:
    PYTHONPATH=backend:. python -m pipeline.promote_blend --w-odds 0.35 [--use-availability] [--ship]
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import replace

from ml.models.params import ModelParams, load_params, save_params

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

W_ODDS_CAP = 0.5


def promoted_params(params: ModelParams, w_odds: float, use_availability: bool,
                    version: str) -> ModelParams:
    """The promoted engine: same params with the blend legs flipped on."""
    if w_odds > W_ODDS_CAP:
        raise ValueError(f"w_odds {w_odds} exceeds cap {W_ODDS_CAP} (market is never primary)")
    if w_odds < 0:
        raise ValueError(f"w_odds must be >= 0, got {w_odds}")
    if w_odds == 0 and not use_availability:
        raise ValueError("nothing to promote: w_odds is 0 and use_availability is False")
    return replace(params, w_odds=w_odds, use_availability=use_availability, version=version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--w-odds", type=float, default=0.0)
    parser.add_argument("--use-availability", action="store_true")
    parser.add_argument("--version", default="poisson-elo-v0.5")
    parser.add_argument("--ship", action="store_true")
    args = parser.parse_args()

    shipped = promoted_params(load_params(), args.w_odds, args.use_availability, args.version)
    log.info("promoted engine: %s", shipped.to_dict())
    if not args.ship:
        log.info("dry run — pass --ship to write model_params.json")
        return 0
    save_params(shipped)
    log.info("shipped %s to model_params.json", args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass** (requires Task 5's field)

Run: `.venv/bin/python -m pytest pipeline/promote_blend_test.py -q`
Expected: 4 passed

- [ ] **Step 5: Verify the dry run leaves the file untouched**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pipeline.promote_blend --w-odds 0.3 && git diff --stat ml/models/model_params.json`
Expected: dry-run log line; empty diff

- [ ] **Step 6: Commit**

```bash
git add pipeline/promote_blend.py pipeline/promote_blend_test.py
git commit -m "feat(pipeline): promote_blend flip script (dry-run default, w_odds cap 0.5)"
```

---

### Task 5: `use_availability` param — availability offsets in the production path, dark

**Files:**
- Modify: `ml/models/params.py` (ModelParams + load/save round-trip)
- Modify: `pipeline/generate_predictions.py` (production path in `build_payload`; extract the lambda-scaling block from `write_availability_prediction`, ~lines 331-370, into a shared helper)
- Test: `ml/models/params_test.py`, `pipeline/generate_predictions_test.py`

**Interfaces:**
- Consumes: `app.availability.availability_for_match(db, match)` (already imported in generate_predictions.py, returns per-side offsets or None), `ml.models.poisson` grid helpers (`score_matrix`, `outcome_probabilities`, `most_likely_score`), `ml.evaluation.calibration.calibrate`.
- Produces: `ModelParams.use_availability: bool = False` (Task 4 imports it); shared helper `apply_availability(pred, off_home, off_away, params, eff_gap)` used by both the production path and the shadow twin.

- [ ] **Step 1: Params field, test-first.** In `ml/models/params_test.py` add:

```python
def test_use_availability_round_trips_and_defaults_false(tmp_params_file):
    from dataclasses import replace
    from ml.models.params import load_params, save_params

    assert load_params().use_availability is False  # absent key -> False
    save_params(replace(load_params(), use_availability=True))
    assert load_params().use_availability is True
```

(`tmp_params_file` = the existing fixture in that file that redirects `_PARAMS_FILE`; reuse its actual name.) Run `.venv/bin/python -m pytest ml/models/params_test.py -q` — expect FAIL. Then in `ml/models/params.py`: add `use_availability: bool = False` to `ModelParams` (after `w_odds`), and `use_availability=bool(data.get("use_availability", False)),` in `load_params()`. Re-run — expect PASS.

- [ ] **Step 2: Production-path behavior, test-first.** In `pipeline/generate_predictions_test.py`, following that file's existing fixture style for building a scheduled match with two teams (reuse its helpers), add:

```python
def test_build_payload_use_availability_scales_lambdas(monkeypatch, db_with_scheduled_match):
    """With use_availability on and an availability offset present, production
    lambdas scale by exp(offset) and the triple is recomputed; with the flag
    off, payload is bit-identical whether or not offsets exist."""
    import math
    from dataclasses import replace

    import pipeline.generate_predictions as gp
    from ml.models.params import load_params

    db, match = db_with_scheduled_match
    offsets = {"home": -0.20, "away": 0.05}
    monkeypatch.setattr(gp, "availability_for_match",
                        lambda _db, _m: type("A", (), {"off_home": -0.20, "off_away": 0.05})())

    params_off = replace(load_params(), form_channels=None, use_availability=False)
    params_on = replace(params_off, use_availability=True)

    base = gp.build_payload(db, match, "test-model", params=params_off)
    adjusted = gp.build_payload(db, match, "test-model", params=params_on)

    assert adjusted["lambda_home"] == pytest.approx(base["lambda_home"] * math.exp(-0.20), rel=1e-3)
    assert adjusted["lambda_away"] == pytest.approx(base["lambda_away"] * math.exp(0.05), rel=1e-3)
    assert adjusted["probabilities"] != base["probabilities"]

    # Dark = bit-identical even with offsets available.
    again = gp.build_payload(db, match, "test-model", params=params_off)
    assert again["probabilities"] == base["probabilities"]
    assert again["lambda_home"] == base["lambda_home"]
```

Adapt the monkeypatched return object to whatever `availability_for_match` actually returns (read `backend/app/availability.py:73-100` first — match its real shape; the shadow twin's consumption in `write_availability_prediction` shows the exact attribute names). Run — expect FAIL (flag not consumed).

- [ ] **Step 3: Implement.** In `pipeline/generate_predictions.py`: extract the lambda-scale-and-rebuild block from `write_availability_prediction` (~lines 331-370) into a module-level helper with this shape (match the twin's existing code exactly — same `exp` scaling, same grid rebuild via `score_matrix`/`outcome_probabilities`, same calibrate call with `eff_gap`, same `most_likely_score` headline):

```python
def _availability_adjusted(pred, off_home, off_away, params, eff_gap):
    """Rebuild a MatchPrediction from availability-scaled lambdas — shared by
    the production path (use_availability) and the shadow twin (FR-4.x)."""
    lam_h = pred.lambda_home * math.exp(off_home)
    lam_a = pred.lambda_away * math.exp(off_away)
    ...  # identical body to the twin's current block, returning the same
         # structure the twin builds its payload from
```

Then in `build_payload`, immediately after `pred = predict_match(...)`:

```python
    if params.use_availability:
        adj = availability_for_match(db, match)
        if adj is not None:
            pred = _availability_adjusted(
                pred, adj.off_home, adj.off_away, params,
                eff_gap=effective_gap(elo_home, elo_away, host_adv),
            )
```

and refactor `write_availability_prediction` to call the same helper (no behavior change — its tests must stay green). Keep attribute names consistent with the real `availability_for_match` return object discovered in Step 2.

- [ ] **Step 4: Run the affected suites**

Run: `.venv/bin/python -m pytest pipeline/generate_predictions_test.py ml/models/params_test.py backend/tests/test_availability_serving.py -q`
Expected: all pass (twin behavior unchanged, flag dark by default)

- [ ] **Step 5: Full Python suite**

Run: `.venv/bin/python -m pytest backend ml pipeline -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ml/models/params.py ml/models/params_test.py pipeline/generate_predictions.py pipeline/generate_predictions_test.py
git commit -m "feat(model): use_availability param — availability offsets in production path, dark by default"
```

---

### Task 6: WC26 endgame runbook

**Files:**
- Create: `docs/RUNBOOK-WC26-ENDGAME.md`

**Interfaces:**
- Consumes: Task 4's CLI, Task 5's flag, existing `pipeline/run_experiments.py` + `pipeline/replay_wc26.py`.

- [ ] **Step 1: Write the runbook** with exactly these sections (concrete commands, no placeholders):

```markdown
# WC26 Endgame Runbook

## 1. Shadow-gate readout (owner action, after each knockout round)
- Readout: GET /api/internal/shadow-record with the internal token (or query
  prediction_results WHERE is_shadow=true on the prod replica).
- Gate: >= 30 scored shadow pairs AND the odds-anchored twin
  (poisson-elo-v0.3-shadow) ahead of production on avg log loss. Same rule
  for the availability twin (poisson-elo-v0.3+avail).

## 2. Promotion (only after the gate clears)
1. `PYTHONPATH=backend:. .venv/bin/python -m pipeline.promote_blend --w-odds <weight from shadow readout, cap 0.5> [--use-availability] --ship`
2. Bump MODEL_VERSION in render.yaml to poisson-elo-v0.5 (lockstep with params).
3. Branch, PR with the shadow-readout numbers in the description, CI green,
   stop gate, human merges. No migration involved.
4. Verify: /api/health ok; next pipeline run writes model_version
   poisson-elo-v0.5 rows for the remaining scheduled matches.

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
```

- [ ] **Step 2: Commit**

```bash
git add docs/RUNBOOK-WC26-ENDGAME.md
git commit -m "docs(runbook): WC26 endgame — gate readout, promotion, form re-gate"
```

---

## Execution order

Task 1 → Task 2 → Task 3 (record chain), then Task 5 → Task 4 (Task 4's tests import Task 5's field), then Task 6. One PR for the whole plan; stop gate before merge as always.

## Self-review notes

- Spec §4.1 → Tasks 1-3; §4.2 → Tasks 4-6; §4.2 form re-gate → Task 6 §3. Track 2 intentionally not in this plan (separate plan post-final per spec §7).
- Task 4/5 ordering dependency stated in both tasks.
- Field names consistent across Tasks 1-3 (`advancement_*`); `use_availability` consistent across Tasks 4-5.
- Two adaptation points are explicitly delegated to the implementer with read-first instructions (RTL fixture name in Task 2; `availability_for_match` return shape in Task 5) because they must match live code, not this document.
