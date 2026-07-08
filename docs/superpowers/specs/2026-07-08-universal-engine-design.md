# Universal Prediction Engine & WC26 Endgame — Design Spec

Date: 2026-07-08 · Status: approved direction, spec for review
Owner: ML/engineering. Companion docs: `docs/MODEL-V2-DESIGN.md` (July audit),
`docs/ROADMAP-POST-WORLDCUP.md`.

## 1. Context

WC26 through the round of 16: FinalWhistle is 62/96 (64.6%) on strict
90-minute W/D/L grading vs The Athletic's published contest leader at 69%
(~94 picks, knockouts graded on advancement). Miss autopsy over all 96 graded
matches (2026-07-08, production feed, pure-90' basis — 60/96; the official
ledger's 62/96 additionally credits two knockouts decided in extra time):

- **26 of 36 misses are "picked a side, draw happened"** (draws ran 27.1%).
- 8 genuine upsets (incl. Norway–Brazil, stored at 49%), 2 coin-flips.
- Pick-policy counterfactuals (never-draw, draw thresholds) on the same
  stored probabilities all score 62.5% — pick policy is a dead lever.
- **Knockout advancement basis: 19/24 = 79.2%** — on the basis contests
  actually grade, the model is already strong.

Strategic driver: after the final (July 19) the platform expands to
**NRL → NFL → NBA**. NRL 2026 is mid-season now (finals September), NFL kicks
off ~September 10, NBA late October. All three are draw-free — the single
biggest football miss category does not exist there.

## 2. Goals & success criteria

1. **Scoreboard honesty upgrade (this week):** the public record reports both
   grading bases — strict 90' W/D/L and knockout advancement — with the basis
   explained. Success: `/api/model/record` exposes `advancement_accuracy`
   (currently 19/24) and the Track Record + methodology pages surface it.
2. **Tournament endgame (by the final):** odds blend (`w_odds`, cap 0.5) and
   availability promotion flip **iff** the shadow gate clears (≥30 scored
   pairs, blended twin beats production log loss). No gate-lowering. Form
   channels re-gated after the QFs.
3. **Universal core (by early August):** football served by a sport-agnostic
   `core/` + `sports/football/` plugin, bit-identical outputs proven by the
   existing test suite.
4. **NRL live mid-season (~2 weeks post-final), NFL by Sept 10, NBA by
   opening night** — each launching with the full governance apparatus from
   day one: frozen pre-kickoff predictions, graded public ledger, shadow
   twins, walk-forward gates.
5. Every model change on any sport ships only on held-out evidence; negative
   results are documented publicly (as with the July form-channel result).

## 3. Non-goals

- Chasing the 69% with anything that cannot survive a walk-forward gate.
- Lowering the shadow-promotion threshold to force a flip this tournament.
- Paid data before a sport proves out on free feeds.
- Any change to the append-only, frozen-at-kickoff prediction rule.
- Betting products or advice; the disclaimer posture is unchanged.

## 4. Track 1 — WC26 endgame (days)

### 4.1 Dual-basis record
- `backend/app/api/model_record.py`: add `advancement_matches`,
  `advancement_correct`, `advancement_accuracy` — knockout matches only,
  pick = higher of the two side probabilities from the frozen production row,
  actual = side that progressed (ET, then penalties). Wilson CI as elsewhere.
- Track Record page: knockout-progression stat card beside winner accuracy.
- Methodology benchmark table: footnote gains one sentence naming the basis
  difference explicitly against the contest numbers.

### 4.2 Promotions (unchanged criteria, ready-to-flip)
- Shadow ledger at 14 scored pairs; QFs+SFs → ~26, bronze+final → 30.
- When ≥30 and blended twin leads production on log loss: one-line params
  change (`w_odds` ≤ 0.5), availability twin promoted the same way, PR + stop
  gate + migration-free deploy. Prepared in advance so the flip is same-day.
- Form channels: re-run `pipeline/run_experiments.py` + WC26 replay after the
  QFs; promote only on consistent held-out wins across all three holdouts.

## 5. Track 2 — the universal core (weeks)

### 5.1 Layering (extract, don't rewrite)
Sport-agnostic `core/` extracted from today's `ml/`:

| Layer | Today | Universal form |
|---|---|---|
| Ratings | `ml/ratings/elo.py` (football K-factors) | Elo family; per-sport K, home-adv, rest handling |
| Form | residual ledgers (`ml/ratings/form.py`, dark) | decayed per-team ledgers over model residuals |
| Availability | XI/injury offsets | roster-impact offsets (NBA load mgmt, NFL injury reports) |
| Market anchor | odds median + `w_odds` blend | identical; per-sport odds ingest |
| Calibration | segmented vector scaling | identical (bucket by rating gap) |
| Evaluation | walk-forward tuner, ablation runner, shadow twins, graded ledger | identical — this is the moat |

Sport plugin interface (each sport implements):
- **Outcome space** — football: {W, D, L} 90'; NRL/NFL/NBA: {W, L} with
  OT/golden-point rules; margin as the underlying variable.
- **Scoring process** — football: Poisson goals + Dixon–Coles (unchanged);
  NRL/NFL/NBA: rating-driven margin model (normal/Skellam family), points
  totals derived from pace/efficiency parameters.
- **Data adapters** — schedule, results, availability, odds sources.

### 5.2 Migration path
1. Extract `core/` interfaces around existing football code; football tests
   are the regression net (bit-identical outputs required — same standard as
   the July form-channel work).
2. `sports/nrl/` first: results history for Elo warm-start, margin model fit
   on past seasons walk-forward, shadow-run live rounds before public launch.
3. NFL, then NBA, same recipe. Backtest per sport before anything is public.

### 5.3 Football next-cycle experiments (harness-gated, in priority order)
1. **Stakes-aware draw channel** — the only credible attack on the 26-draw
   miss pile: draw propensity conditioned on stakes (mutual-benefit final
   group matchdays, knockout caginess) and low combined lambdas.
2. **Squad-strength prior** from the ingested players table (club
   goals/minutes → team attack index) — also the template for NBA/NFL roster
   quality.
3. xG team offsets promotion when StatsBomb coverage warrants.

## 6. Risks

- **Two-track bandwidth (highest):** Track 1 is deliberately small; core
  extraction starts only after the dual-basis record ships.
- **NRL/NFL data quality:** free feeds first; a sport launches shadow-only
  until its backtest + live shadow round clears the same gate football uses.
- **New-sport calibration:** margin models miscalibrate differently than
  Poisson; per-sport reliability curves are launch blockers, not follow-ups.
- **Timeline slip:** NFL date is hard; NRL mid-season launch has slack — if
  squeezed, NRL shadow-runs longer and NFL launches first publicly.

## 7. Sequencing

| When | What |
|---|---|
| This week | Dual-basis record shipped; promotion PRs staged |
| By the final (Jul 19) | Odds/availability flip if gate clears; form re-gate after QFs |
| Jul 20 – early Aug | Core extraction; football on plugin, bit-identical |
| ~Aug | NRL shadow → public mid-season |
| Sep 10 | NFL live from week 1 |
| Late Oct | NBA live from opening night |
