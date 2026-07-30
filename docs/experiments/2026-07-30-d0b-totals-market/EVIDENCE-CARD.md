# D0-B — Totals market validation: EVIDENCE CARD

**Run 2026-07-30**, after the pre-registration was committed alone (`aa7a445`)
and corrected (`1e207a6`), both pushed before this code existed. Appended to;
never edited in place.

Command:

```bash
PYTHONPATH=backend:. python -m pipeline.run_club_totals_benchmark \
    --csv-dir data/raw/club --emit-json /tmp/d0b-totals.json
```

Scored window `2324`–`2425`; constant fitted on `1920`–`2223`; all nine
pre-confirmation seasons replayed for ratings. `2526` never opened.

---

## The headline

**The served model is behind the closing over/under 2.5 line in all three
leagues, credibly, at every clustering and under every sensitivity.**

| League | n | model LL | market LL | model − market | iso-week CI95 | resolved? |
|---|---|---|---|---|---|---|
| Bundesliga | 612 | 0.6704 | 0.6375 | **+0.0328** | [+0.0215, +0.0438] | yes |
| EPL | 760 | 0.6830 | 0.6613 | **+0.0216** | [+0.0081, +0.0350] | yes |
| La Liga | 760 | 0.6823 | 0.6578 | **+0.0245** | [+0.0123, +0.0371] | yes |

All three intervals sit entirely above zero. Positive = the model is *behind*.

## The finding that matters more than the gap

A gap in nats means nothing without the budget it is drawn against. Measured on
**the same matches, the same book, the same window and the same served
parameters**, against a climatology fitted on the same held-back seasons:

| League | 1X2 gap | 1X2 budget | **1X2 share** | O/U gap | O/U budget | **O/U share** |
|---|---|---|---|---|---|---|
| Bundesliga | +0.0420 | 0.1161 | **63.8%** | +0.0328 | 0.0308 | **−6.7%** |
| EPL | +0.0340 | 0.1331 | **74.4%** | +0.0216 | 0.0235 | **+7.9%** |
| La Liga | +0.0203 | 0.1249 | **83.8%** | +0.0245 | 0.0348 | **+29.5%** |

*Share* = the fraction of the closing line's information-over-climatology that
the model captures. The engine's errors are **similar in size on both markets**
(0.020–0.042 nats). The difference is the denominator: the 1X2 budget is
0.116–0.133 nats, the totals budget only 0.024–0.035. The same-sized error
therefore consumes essentially the whole totals budget.

**The engine captures roughly three quarters of what the market knows about who
wins, and approximately none of what it knows about how many goals.**

## Bundesliga's book is one-sided

Of 612 scored Bundesliga matches, the model assigned P(over 2.5) **below 0.5
exactly zero times.** Its range is 0.549 to 0.847.

That is not a tuning artifact, it is arithmetic. `λ_h · λ_a ≡ base²`, so the
expected total is `2·base·cosh(β·diff)` — minimised at parity. With
`base = 1.44` the floor is 2.88 goals, and P(over 2.5) cannot fall below ~0.549
no matter which two clubs are playing. **The Bundesliga model cannot predict a
low-scoring match.**

| League | min | median | max | P(over) < 0.5 | model sd | market sd | ratio |
|---|---|---|---|---|---|---|---|
| Bundesliga | 0.549 | 0.576 | 0.847 | **0 / 612** | 0.0626 | 0.0829 | 0.75 |
| EPL | 0.482 | 0.511 | 0.933 | 298 / 760 | 0.0762 | 0.0817 | 0.93 |
| La Liga | 0.430 | 0.458 | 0.784 | 553 / 760 | 0.0701 | 0.1081 | 0.65 |

## Did the shipped `base` overrides help? Yes. Enough? No.

O4, and the G5 check. `model − control` is the shipped per-league `base`
against the pre-override global `base = 1.20`:

| League | model − control | iso-week CI95 | reading |
|---|---|---|---|
| Bundesliga | **−0.0336** | [−0.0527, −0.0151] | override is credibly better |
| EPL | **−0.0187** | [−0.0264, −0.0109] | override is credibly better |
| La Liga | **+0.0000** | [0, 0] | no override exists — exact zero, as it must be |

Both shipped overrides moved the model **toward** the market, in the direction
#202 claimed and at a similar magnitude (Bundesliga −0.0336 here against the
−0.0447 it confirmed on 2025-26). **G5 does not fire**: no shipped decision is
revealed to be market-negative. La Liga's exact `+0.0000` is the wiring check —
`club_params_for("laliga")` carries no override, so the two columns must be
bit-identical, and they are.

The overrides were right. They moved the model from *much worse than a
constant* to *about level with a constant*, while the market sits 0.023–0.035
nats better than that constant.

## The defect T1.1 was created to fix is still present

`pipeline/leagues.py` justifies both overrides by the O/U book "LOSING to a
constant". Against the **pre-registered** constant (fitted on `1920`–`2223`):

| League | model LL | constant LL | model beats constant? |
|---|---|---|---|
| Bundesliga | 0.6704 | 0.6683 | **no**, by 0.0021 |
| EPL | 0.6830 | 0.6848 | yes, by 0.0018 |
| La Liga | 0.6823 | 0.6925 | yes, by 0.0102 |

And EPL's margin does not survive its own sensitivity. The fit window's
over-rate is 0.5217 against the scored window's 0.6066 — an **8.5 point regime
shift**, by far the largest of the three:

| League | fit rate | scored rate | drift | share (pre-reg constant) | share (oracle constant) |
|---|---|---|---|---|---|
| Bundesliga | 0.6067 | 0.6111 | +0.0044 | −6.7% | −6.9% |
| EPL | 0.5217 | 0.6066 | **+0.0849** | +7.9% | **−142.9%** |
| La Liga | 0.4539 | 0.4737 | +0.0197 | +29.5% | +27.9% |

An *oracle* constant (fitted in-sample, so not a legitimate baseline — only a
sensitivity) scores EPL at 0.6703, which beats the model's 0.6830. The
−142.9% is not meaningful as a percentage: the oracle budget is 0.0090 nats and
the ratio explodes on a small denominator. The **ordering** is what matters and
it is unambiguous:

> model 0.6830 > oracle constant 0.6703 > market 0.6613

**So EPL's apparent win over a constant is an artifact of the constant being
fitted on a lower-scoring era, not of skill.** Under a fairly-fitted constant
the served model is beaten by a constant on O/U 2.5 in **EPL and Bundesliga** —
the same two leagues, and the same defect, that T1.1 was pre-registered to fix.
La Liga is the only league whose model beats a constant, and it is the only
league that received no override.

## Sensitivities — the headline rests on none of them

**De-vig.** Proportional (primary) vs Shin, two-way:

| League | proportional | Shin | Δ |
|---|---|---|---|
| Bundesliga | 0.6375 | 0.6364 | −0.00109 |
| EPL | 0.6613 | 0.6613 | +0.00000 |
| La Liga | 0.6578 | 0.6573 | −0.00045 |

≤ 0.0011 nats against a gap of 0.022–0.033. As pre-registered: a two-way market
has one fewer degree of freedom in the overround split than the three-way one
D0 measured at ≤ 0.0007.

**Book.** Market LL on the matches all four closing families price:

| League | AvgC | PC | B365C | MaxC | n common |
|---|---|---|---|---|---|
| Bundesliga | 0.6400 | 0.6409 | 0.6395 | 0.6394 | 589 |
| EPL | 0.6634 | 0.6632 | 0.6632 | 0.6632 | 750 |
| La Liga | 0.6588 | 0.6577 | 0.6585 | 0.6586 | 758 |

Spread ≤ 0.0015 nats. The choice of book does not carry the result.

**Clustering.** Iso-week (primary, 67–73 clusters) and season (sensitivity, 2
clusters) give identical point estimates; the season intervals are narrower and
are **not** the ones to quote — two clusters cannot cover, exactly as §11
predicted when it declined to make them primary.

**Resolution.** Paired sd 0.147–0.194; naive 80%-power MDE 0.0166–0.0197;
clustered CI half-width 0.0111–0.0134. Every observed effect exceeds its own
half-width. **Resolved in all three leagues** — unlike the 0.000–0.003 nat
candidates of #202, which never could have been.

## Coverage

| League | captures priced | rows scored | replayed | unjoined |
|---|---|---|---|---|
| Bundesliga | 6 / 9 | 1,835 | 2,754 | 0 |
| EPL | 6 / 9 | 2,280 | 3,420 | 0 |
| La Liga | 6 / 9 | 2,280 | 3,420 | 0 |

**Zero unjoined rows** across 6,395 priced matches — both sides parse the same
CSVs under `str.strip`, so the join is exact by construction and any miss would
have raised.

Nine captures abstained (`{E0,SP1,D1}_{1617,1718,1819}`): they carry Betbrain
over/under but **no closing totals family**. Excluded under §9's closing rule.
Admitting them would have widened the sample ~50% with pre-closing rows
reported as a closing-line benchmark.

**The guard earned its keep on real data.** The run logged:

```
skipping row 261: AvgC totals odds not all > 1.0 (0.42/2.83)
```

`D1_1920.csv`, `FC Koln 2–4 RB Leipzig` — six goals, a realized Over, priced
`AvgC>2.5 = 0.42`. De-vigged that reads `p_over ≈ 0.871` and would have scored
as one of the market's best calls of the decade. It is the single row missing
from the 6,396.

## What this does NOT license

Per §12, and restated because the result is the kind that invites action:

- **Nothing here changes a served parameter.** Not `base`, not `rho`, nothing.
- **The model column is in-sample.** T1.1 chose `base` on this exact metric over
  `1718`–`2425`, a superset of the scored window. A favourable reading would
  have been inflated by construction; the reading is unfavourable anyway, which
  makes it *conservative* rather than suspect — an in-sample advantage that
  still loses is a lower bound on the true gap.
- **No candidate is proposed here.** The `λ_h·λ_a ≡ base²` observation is
  recorded as a measured property of the code (§A4), not as a design.
- **The only clean holdout is 2026-27.** `2526` is consumed. Anything that
  proposes to close this gap needs its own pre-registration and that holdout.

## Open question handed to the human

§A5 recorded that `pipeline/run_club_benchmark.py:98` calls `model_probs` with
all defaults — `base = 1.35`, `beta = 0.0019`, `rho = 0.0`, no calibrator —
which production serves nowhere. Whether the 1X2 closing-line gaps recorded in
`docs/MODEL-EXPERIMENTS.md` (+0.0312 / +0.0279 / +0.0326) came from that runner
is **still not established**, and D0-B did not investigate it.

It is now worth establishing, because D0-B computed the 1X2 gap independently
on served parameters over `2324`–`2425` and got **+0.0420 / +0.0340 / +0.0203**
— a different ordering across leagues than the recorded numbers. Different
window, so not a contradiction; but the two cannot both be described as "the
model's 1X2 gap" without saying which model and which seasons. Out of scope for
this phase, not fixed here.
