# Phase 1 Evidence Card — shadow promotion review (2026-07-10)

Live records: `live-records.txt` · Gates: `model-eval.txt`, `team-offsets-gate.json`, `xg-backtest.txt`
Runbook gate for the odds blend: ≥ 30 scored shadow pairs AND twin ahead (`docs/RUNBOOK-WC26-ENDGAME.md`).
Walk-forward sample: 49,403 replayed matches; hold-out 1,843 matches across 53 major-tournament editions.

## Load-bearing discovery

With the shipped `w_odds = 0.0`, the odds-anchored twin **writes an exact copy
of production** (`pipeline/generate_predictions.py:495-503` — "a clean null
test until odds exist and a weight is deliberately set"). The 15 live pairs
are therefore identical by construction (both: winner_acc 0.80, avg_brier
0.3733, 1 exact hit) — they are **not evidence for or against the blend**,
and the runbook's "twin ahead" gate is unsatisfiable until a weight is set.

Second gap, for Phase 2: `w_odds` is consumed **only** by the shadow writer —
the production `build_payload` path never reads it. `promote_blend.py`'s flag
flip would today arm the shadow, not change serving. Promoting the odds blend
for real requires a small serving-code change (out of scope mid-tournament by
the spec's own constraint).

## The card

| Twin | Params flag | Repo gate verdict | Live evidence | Recommendation | Owner decision |
|---|---|---|---|---|---|
| odds-total blend (v0.3-shadow) | `w_odds` | NOT MET — n=15 of 30, and twin is a copy, never ahead | none (null test unarmed; records identical by construction) | **HOLD promotion; ARM the null test instead** — params-only `w_odds=0.35` (promote_blend's own example weight, cap 0.5), version string unchanged, production bit-identical; real differentiated pairs start accruing from the semis | **GO (arm only)** — owner, 2026-07-10 |
| xG team offsets (v0.3+xg) | `team_offsets` | **do-not-ship** — top-1 CI[-0.0252, +0.0040], exact-NLL CI[-0.0080, +0.0114], both straddle 0 (`team-offsets-gate.json`); xg-backtest mixed/underpowered (2018 pro, 2022 con) | no separate graded live record | **NO-GO** | **NO-GO** — owner, 2026-07-10 |
| availability (v0.3+avail) | `use_availability` | live-only by design; n=1 | beats published on France–Morocco (log loss 0.518 vs 0.606, brier 0.253 vs 0.313) — favorable but a single match | **HOLD** — keep shadowing; n grows each remaining match; revisit in Phase 2 with a real sample | **HOLD** — owner, 2026-07-10 |
| suspensions (v0.5+bans) | none — info only | n/a | writes no graded PredictionResult pairs (shadow-record `model_versions` shows only v0.3-shadow) | not promotable in Phase 1 | n/a |
| rest days (v0.5+rest) | none — info only | n/a | same — no graded pairs | not promotable in Phase 1 | n/a |

Side observation from the walk-forward (Phase 2 input, not a Phase 1 action):
the only significant candidate in the main eval is **v0.2 full-tune** on
exact-score metrics (exactNLL d=-0.0167 CI[-0.0284,-0.0049]; top5 d=+0.0255
CI[+0.0109,+0.0410]); temperature / draw-inflation / vector-scaling variants
were all `ns` against v0.1.

Recommendation rule applied: promote only when the repo gate is met AND live
evidence is non-worse. No twin meets it. The single recommended action —
arming the odds-blend null test — changes nothing served and exists precisely
so the runbook gate can ever be met.
