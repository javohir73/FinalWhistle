# WC26 venue-calibration public audit evidence card

- Frozen input: `docs/experiments/2026-07-23-wc26-postmortem/exchange-prices-n104.json`
- Generator: `PYTHONPATH=backend:. python -m pipeline.publish_venue_audit`
- Generated output: `frontend/lib/venue-audit-data.json`
- Public route: `/research/venue-calibration`
- Population: 104 regulation-time WC26 matches; Kalshi n=104, Polymarket n=93 complete 1X2 overlaps.
- De-vigging: proportional normalization of home/draw/away prices.
- Grading: regulation-time home/draw/away.
- Timing: last reconstructed pre-kickoff observations, collected post-hoc; venues were not sampled simultaneously.
- Scope boundary: no claim about in-play or derived markets.
- Bootstrap provenance limitation: the 2026-07-23 experiment did not record its seed. The peer-checked published CI values are frozen. The generator also emits a fresh deterministic match bootstrap using seed `20260727` and 10,000 samples; it is labeled separately rather than silently replacing the historical interval.

The generator recomputes sample sizes, favourite hit rates, log loss, Brier,
paired point deltas, divergence, favourite disagreements, and consensus from the
match-level artifact. Tests lock the headline values and reproduce the committed
JSON byte-for-byte.
