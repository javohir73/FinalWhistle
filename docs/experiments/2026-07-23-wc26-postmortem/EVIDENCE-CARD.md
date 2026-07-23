# WC26 Post-Tournament Evidence Card (2026-07-23)

The tournament is over: 104 of 104 matches finished, scored, and in the
prediction ledger (learning chain green, last success 2026-07-22, coverage
missing=0). This card is the post-final capture-and-compare wrap-up per
`docs/RUNBOOK-WC26-ENDGAME.md` §1/§3 and `docs/ROADMAP-ENGINE.md` Phase 0.

Raw artifacts in this directory:
`model-record.json` · `market-record.json` · `market-benchmark-live.txt` ·
`shadow-record-run-2026-07-22.log` · `form-regate-holdouts.txt` ·
`replay-wc26.txt`

## Final production record (poisson-elo v0.1→v0.5, n=104)

- Winner accuracy **66.35%** (69/104, CI95 [56.8%, 74.7%]), exact score 10/104
  (9.6%), best streak 9.
- Advancement calls **81.25%** (26/32, CI95 [64.7%, 91.1%]).
- avg Brier 0.5013, avg log loss 0.8584.

## Model vs market (final pre-kickoff consensus, n=7)

Only 7 matches carry captured bookmaker odds (capture infra shipped
mid-tournament; 97 finished matches have none). The final itself was captured
in all three phases — T-24h, T-6h, and 18:44 UTC (16 min before kickoff) as
the closing line.

- Model log loss **0.9843** vs market **1.0549**; model accuracy 3/7 vs
  market 2/7; model ahead on 4 of 7 (win rate 0.571), mean edge +0.022.
- Δ log loss −0.0706, CI95 [−0.1749, +0.0235] →
  **NO CREDIBLE DIFFERENCE (CI straddles 0)**.
- Honest read: directionally ahead on this slice, but see the full-tournament
  benchmark below — the n=7 window was favorable noise.

## Model vs exchanges, FULL tournament (added 2026-07-23)

Post-hoc reconstruction from public historical APIs (Kalshi settled-market
candlesticks, Polymarket CLOB price history): last pre-kickoff price for
every match. **Kalshi n=104 (complete), Polymarket n=93** (11 matches had no
complete 3-outcome market). Bookmakers not recoverable (API-Football purges
odds post-fixture; the n=7 above is all that exists). Grading: 90-minute
W/D/L, identical devig and argmax-favorite convention for every predictor —
which is why the model shows 61.5% here vs the 66.35% headline (the public
record credits ET/pens winners; here 90' draws count against everyone
equally). Raw data: `exchange-prices-n104.json`; full output incl. all
favorite disagreements: `exchange-benchmark-n104.txt`.

| | favorite hit | avg log loss | avg Brier |
|---|---|---|---|
| model (n=104) | 61.5% | 0.9042 | 0.5327 |
| **Kalshi (n=104)** | **63.5%** | **0.8402** | **0.4967** |
| model (n=93 overlap) | 63.4% | 0.8459 | 0.4953 |
| **Polymarket (n=93)** | **65.6%** | **0.8062** | **0.4732** |

- Paired Δ log loss model−Kalshi: **+0.0640, CI95 [+0.0173, +0.1105] →
  model credibly BEHIND** the exchange over the full tournament.
- Paired Δ model−Polymarket: +0.0397, CI95 [−0.0059, +0.0878] → no credible
  difference (leaning behind).
- The QF→final window (model 4/8 vs exchanges 2/8, incl. both contrarian
  semifinal calls) was real but unrepresentative; the markets won it back in
  the group stage. Of 12 outright disagreements with Kalshi: model 3,
  Kalshi 5, 4 draws nobody called.
- **This is the strongest evidence yet FOR the odds-anchored blend twin**
  (§gates: 22/30 pairs, marginally ahead): the market carries signal the
  pure Elo-Poisson engine lacks. It is also the definitive receipt behind
  the public "we don't claim to beat the market" stance.

## Promotion gates at tournament end (shadow-record run 2026-07-22)

| Gate | Rule | Result |
|---|---|---|
| Odds twin (v0.3-shadow) | ≥30 pairs AND twin ahead on avg LL | **NOT MET** — n=22/30, Δ=+0.0012 (twin 0.7189 vs prod 0.7201 — ahead, but underpowered) |
| Availability twin | ≥20 pairs AND diff CI95 upper < 0 | **NOT MET** — n=7/20, Δ=−0.0411, verdict no_credible_difference |

No WC matches remain, so neither gate can accrue further WC pairs; growth now
depends on NRL (and the next competition). Both twins keep shadowing.

## Form-channel re-gate (runbook §3, full group stage n=72)

| Variant | WC2018 LL | WC2022 LL | WC26 replay LL |
|---|---|---|---|
| v0.2-tuned | 0.9813 | 1.0943 | 0.8144 |
| v0.2+form | 0.9713 | 1.1071 | 0.8255 |
| v0.2+cal | 0.9791 | 1.0942 | **0.8140** |

**GATE NOT MET — form stays dark** (must win all three holdouts; wins 2018
only). Recorded in `docs/MODEL-V2-DESIGN.md` §5c. The calibrator (C2) again
holds or improves every holdout, confirming the shipped v0.4/v0.5 lineage.

## Ops actions taken with this card

- `market-intel.yml` was failing every run post-final (`RuntimeError: no rows
  ingested from any source` — zero recognizable markets is now the normal
  off-season state). Fixed: zero rows from reachable sources is a clean no-op;
  only all-sources-raised stays red. Cadence reduced hourly → every 3h per the
  workflow's own post-WC note.
- `odds-snapshots.yml` stays hourly: phased capture (t24/t6/closing) needs the
  resolution and is a clean no-op with no upcoming fixtures.

## What this means for the roadmap

The WC26 chapter closes with the track record above as the public receipt.
Next per `docs/ROADMAP-POST-WORLDCUP.md`: the league pivot (Phase 1) is what
gives every still-open gate (odds twin at 22/30, availability at 7/20) a
sample to finish on.
