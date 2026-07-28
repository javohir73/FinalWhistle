# P4 gate status — not yet runnable

- Status date: 2026-07-27
- Held-out cutoff: 2026-10-01T00:00:00Z
- Precommit: `docs/experiments/2026-07-27-inplay-benchmark-precommit.json`
- Gate implementation: `pipeline.p4_gate`
- Current result: **insufficient** — the held-out capture window has not begun.
- Selected branch: **none**. P5A and P5B remain blocked.

The classifier is mechanical: CI95 entirely below zero is `beating` and selects
P5B; entirely above zero is `beaten`; touching or crossing zero is
`inconclusive`. `beaten` and `inconclusive` select P5A. Missing or insufficient
evidence selects neither branch. No point estimate can select a branch.
