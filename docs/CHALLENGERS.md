# Adding a model challenger (through the gate)

The engine ships a change only when it beats the champion on held-out data —
never in-sample, never on a hunch. This is the discipline for proposing a new
model challenger (roadmap Phase 4). The authoritative record of every gate run
— wins AND losses — is [`docs/MODEL-EXPERIMENTS.md`](MODEL-EXPERIMENTS.md); this
doc is the *how*, that file is the *ledger*.

## The champion

Served model: **poisson-elo-v0.2** (`ml/models/params.py`) — Elo → expected
goals → Dixon–Coles Poisson scoreline grid → W/D/L + most-likely score. Every
challenger is measured against it.

## The gate (`pipeline/experiment_model_eval.py`)

Walk-forward, edition-clustered bootstrap CI on the metric delta vs the champion:

1. **Walk-forward, leak-free.** Major-tournament finals are grouped into
   `(competition, year)` editions since 2004. For each edition the candidate is
   fit only on a validation window *before* that edition's first match, then
   scored on the edition's matches. No hindsight.
2. **Edition-clustered bootstrap CI.** Whole editions are resampled with
   replacement to get a percentile CI (2.5%, 97.5%) on the mean per-match delta.
   Clustering by edition (not by match) respects that matches within a
   tournament are correlated — the honest unit of resampling.
3. **Ship rule.** The CI must **exclude zero in the candidate's favour** (lower
   log-loss / exact-NLL, or higher top-1 with the production pick rule). A CI
   that straddles zero is noise — not shipped, and the loss is recorded.

## How to add one

1. Add a factory to the `CANDIDATES` dict in `experiment_model_eval.py` — a
   function taking the validation window and returning a per-match scorer
   (mirror an existing candidate).
2. Run the gate (see the file's CLI) and read the CI.
3. **Record the result in `MODEL-EXPERIMENTS.md` — win or loss.** A refuted idea
   is never retried; that is the point of the ledger.
4. Ship (bump params/version) only if the CI cleared the gate.

## Why the current lever is NOT "more ML features"

The model is at its **accuracy ceiling on the current signal** — every
directional hypothesis tried so far was refuted through this gate (see the
ledger). The Phase-4 feature-rich challengers (gradient boosting on xG /
lineups / schedule congestion / market-derived features) are **data-blocked**,
not idea-blocked:

| Feature | What it needs | Status |
|---|---|---|
| **xG** | per-shot xG ingestion + a historical xG feed backfilled to the training set | no pipeline; WC26-only xG has no historical comparator → gate unpowered |
| **Lineups / availability** | player-level stats + injury/suspension flags + a cross-provider player entity + historical lineup backfill | lineups are display-only and late (≤2h pre-KO); no history |
| **Schedule congestion** | historical fixture dates/travel in normalized form, with variance to learn from | the WC group schedule is near-constant (~every 3 days) → near-zero variance |
| **Market-derived** | historical closing odds backfilled to the training set; open→close line moves | only post-2026-06 WC26 odds snapshots; no history |

Until a data stream is integrated and backfilled, a challenger built on it cannot
clear the gate for lack of a powered held-out sample. That is a data-integration
project (tracked behind the Phase-1 club-data build-out), not a modelling tweak.

## The fork

The business fork — edge path vs product path (see `ROADMAP-ENGINE.md`) — is
taken with a full season of immutable model-vs-close records, which needs
Phase 1/2 to generate and real-world time to accrue. It is a decision to make on
evidence, not an engineering task to complete here.
