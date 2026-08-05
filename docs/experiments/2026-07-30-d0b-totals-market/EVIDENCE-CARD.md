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

> ⚠ **The share column is quoted with false precision — see Appendix B2.** It is
> a ratio of two noisy paired means; bootstrapped, the O/U shares are
> Bundesliga [−65.4%, +22.0%], EPL [−77.2%, +52.0%], La Liga [+4.3%, +51.8%].
> Only La Liga's excludes zero, so "approximately none" is **withdrawn as
> stated**. What survives, resting on the resolved comparisons rather than the
> ratio: the totals budget is ~a quarter of the 1X2 budget while the model's
> absolute error is similar on both, so the same error eats a far larger share
> of what is knowable about goals. How much larger is a wide band, not a point.

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

> ## ⚠ THIS ENTIRE SECTION IS WITHDRAWN — see **Appendix B1**.
> The model-vs-constant comparison below was computed as a difference of two
> log-loss *levels*, so it carries no interval. Given one, **neither the
> Bundesliga nor the EPL claim resolves**: +0.0021 [−0.0082, +0.0134] and
> −0.0018 [−0.0131, +0.0106]. Both sit inside the very 0.000–0.003 nat band
> this card dismisses as unresolvable sixty lines below. The "oracle constant"
> used for EPL is fitted in-sample — the contamination `score_totals` raises
> `ValueError` to prevent — and is valid only for showing that EPL's constant
> is stale. The numbers below are arithmetically correct and the conclusion
> drawn from them is not. Read B1 instead.

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

> Note the MDE (2.80σ, an 80%-power threshold) and the half-width (1.96σ) answer
> different questions; neither is "the conservative one". And this paragraph
> applies only to **model − market**. Applied to model − constant it condemns
> two of this card's own claims — see Appendix B1.

## Coverage

> ⚠ The "rows scored" column below is mislabelled — those are **priced** rows.
> Actually scored: **612 / 760 / 760 = 2,132**. See Appendix B4.

| League | captures priced | rows PRICED (not scored) | replayed | unjoined |
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
(Bundesliga / EPL / La Liga). ~~a different ordering across leagues than the
recorded numbers~~ — **withdrawn, see Appendix B5:** that was my own
transcription error, writing the two triples in different league orders. Aligned
by league the ordering is identical. Different window, different magnitudes, no
contradiction; but the two cannot both be described as "the model's 1X2 gap"
without saying which model and which seasons. Out of scope for this phase, not
fixed here.

---

# APPENDIX B — adversarial review, and what it withdrew

**2026-07-30.** A bounded adversarial review ran 31 independent agents whose
brief was to destroy the claims above: five attack lenses (arithmetic, leakage,
data/join, overclaiming, ordinary code defects), each finding then handed to a
separate verifier instructed to default to "not real". **26 findings raised, 22
survived verification.** Appended, not edited in place.

## B0. What survived unchanged

One reviewer reimplemented the headline from scratch — its own CSV reader,
de-vig, Poisson/Dixon–Coles grid, log loss and cluster bootstrap, calling none
of `score_totals`, `totals_probabilities`, `devig2`, `binary_log_loss` or
`information_share` — and reproduced it exactly:

| League | model | market | gap | CI95 |
|---|---|---|---|---|
| Bundesliga | 0.670364 | 0.637529 | +0.032835 | [+0.021511, +0.043737] |
| EPL | 0.682981 | 0.661346 | +0.021635 | [+0.008148, +0.034710] |
| La Liga | 0.682265 | 0.657753 | +0.024512 | [+0.012288, +0.037082] |

**C1 stands. The sign convention is correct.** So does C3 (Bundesliga never
prices an under), C4 (both overrides moved the model toward the market), and C6
(zero unjoined). C2's *direction* stands; its precision does not — see B2.

## B1. WITHDRAWN — "the model is beaten by a constant in EPL and Bundesliga"

**This was the card's worst error, and it is retracted.**

The section above computed model-vs-constant as a difference of two log-loss
*levels* and reported 0.0021 and 0.0018 nats as determinate findings. The
paired delta was never computed, so it never got an interval. It has one now,
at the pre-registered seed 26:

| Comparison | mean | iso-week CI95 | verdict |
|---|---|---|---|
| Bundesliga model − constant | **+0.0021** | [−0.0082, +0.0134] | **UNRESOLVED** |
| EPL model − constant | **−0.0018** | [−0.0131, +0.0106] | **UNRESOLVED** |
| La Liga model − constant | −0.0103 | [−0.0203, −0.0010] | resolved, barely |

Both straddle zero. Inverting the pre-registration's own MDE formula,
Bundesliga's +0.0021 would need **~31,700 matches** to resolve (52× the 612
scored) and EPL's −0.0018 **~69,900** (92× the 760).

And the error was worse than an omission, because §"Resolution" above dismissed
prior work in exactly this register:

> **Resolved in all three leagues** — unlike the 0.000–0.003 nat candidates of
> #202, which never could have been.

Bundesliga's +0.0021 and EPL's −0.0018 sit *inside that band*. The card applied
a standard to #202's numbers that condemns two of its own, sixty lines apart in
the same file. §11 pre-committed the remedy — *"If the realized totals CI
half-width exceeds the observed effect, the result is 'unresolved at this sample
size' — which is a finding, not a failure"* — and the card did not apply it.

**Compounding it:** the EPL half of that section leaned on an "oracle" constant
fitted in-sample, called it "fairly-fitted", and drew a conclusion from it. That
is the exact contamination `score_totals` raises `ValueError` to prevent. Its
own interval straddles zero too (+0.0127, [−0.0032, +0.0291]). The oracle
remains useful for one narrow purpose — showing EPL's constant is stale, an
8.5-point regime shift between fit and scored windows — and for **nothing else**.

**Corrected reading.** Whether the served model beats a constant on O/U 2.5 is
**not resolvable at this sample size in EPL or Bundesliga.** La Liga's model
does beat its constant, barely. The recorded #202 defect is neither confirmed
nor refuted here. What *is* resolved is that the model is behind the **market**
in all three leagues, and that is the finding.

## B2. CORRECTED — the information share has no meaningful precision

The card printed −6.7% / +7.9% / +29.5% to a tenth of a percent. It is a ratio
of two noisy paired means, and bootstrapped at the registered seed:

| League | share | CI95 | resamples with no budget |
|---|---|---|---|
| Bundesliga | −6.7% | **[−65.4%, +22.0%]** | 0 / 2000 |
| EPL | +7.9% | **[−77.2%, +52.0%]** | 1 / 2000 |
| La Liga | +29.5% | **[+4.3%, +51.8%]** | 0 / 2000 |

Only La Liga's excludes zero. **The sentence "the engine captures … approximately
none of what it knows about how many goals" is not supported at that
resolution** and is withdrawn as stated.

What the intervals *do* support, because it rests on the resolved comparisons
rather than on the ratio: the totals **budget** is 0.024–0.035 nats against
1X2's 0.116–0.133 (both resolved, all six intervals exclude zero), and the model
is behind the market by a similar absolute amount on both (0.020–0.042). So the
same-sized error consumes a far larger fraction of the totals budget than of the
1X2 budget. **The totals book is much weaker relative to what is knowable; how
much weaker is not pinned to better than a wide band.**

## B3. CORRECTED — ρ is vacuous to one ulp, not exactly

The card said "**exactly zero**, bit-for-bit". Measured on the real corpus under
the served `rho = −0.06`:

| League | n | rows differing | max abs Δ |
|---|---|---|---|
| Bundesliga | 2,754 | 137 | 1.110e-16 |
| EPL | 3,420 | 224 | 1.110e-16 |
| La Liga | 3,420 | 309 | 1.110e-16 |

The **numerator** of P(total ≥ 3) is bit-identical, as claimed — τ touches only
cells with total ≤ 2. But τ is mass-preserving in exact arithmetic and *not* in
floating point, so the grid's total mass moves in the last bit and the quotient
can shift by one ulp. The original test asserted exact equality and passed only
because its five synthetic λ pairs never tripped the rounding. It now asserts
the bound, plus a separate exact assertion on the numerator alone.

1.1e-16 is fourteen orders of magnitude below the smallest effect this study can
resolve, so nothing else changes — but "exactly" was wrong.

## B4. CORRECTED — the coverage table mislabelled its own denominator

The card's coverage table headed a column "rows scored" and printed
1,835 / 2,280 / 2,280 (6,395). Those are **priced** rows. The rows actually
scored are **612 / 760 / 760 (2,132)** — the §4 split scores only `2324`–`2425`;
the other **4,263 priced rows fit the constant and are never scored.** The
headline table 55 lines above says n = 612/760/760, so the card contradicted
itself. The runner now prints all three numbers on one line and the JSON
carries `n_priced_rows`, `n_fit` and `n_matches` separately.

## B5. CORRECTED — "a different ordering across leagues" was my own transcription

The "Open question" section claimed D0-B's 1X2 triple showed "a different
ordering across leagues" than the recorded numbers. **False, and the fault was
mine:** I wrote the two triples in different league orders. Aligned properly:

| League | recorded (#202 audit) | D0-B, served params, 2324–2425 |
|---|---|---|
| Bundesliga | +0.0326 | +0.0420 |
| EPL | +0.0312 | +0.0340 |
| La Liga | +0.0279 | +0.0203 |

Bundesliga > EPL > La Liga in the recorded set; Bundesliga > EPL > La Liga in
D0-B's. **Same ordering.** The magnitudes differ, on a different window, which
is unremarkable. The genuinely open question is unchanged and narrower than the
card implied: `pipeline/run_club_benchmark.py:98` scores unserved defaults, and
whether the recorded numbers came from it is still not established.

## B6. Also fixed, and now covered by tests

| # | Defect | Fix |
|---|---|---|
| 1 | Headline CIs used seed 12345 (`season_clustered_ci`'s default), not the pre-registered 26 | `BOOTSTRAP_SEED = 26` passed at every call; test recomputes and pins |
| 2 | `build_matched_totals` priced the model at its own `line` default while label and market used `rec["line"]` | line derived from the records; mixed lines raise |
| 3 | Duplicate `(date, home, away)` would silently overwrite — dropping a match *and* still reporting `unjoined == 0` | raises |
| 4 | §7's closed drop-reason set was one bucket named `unusable_price_or_score` | five attributed reasons summing exactly to the shortfall |
| 5 | §10's per-family booksum absent from the receipt | recorded per file: 1.036–1.066, **0 underround rows**, so the Shin fallback was never taken |
| 6 | §2's "and pooled" objectives never computed | `pooled_result`, with the caveat that pooling against ONE constant would inflate the budget (+27% vs the +13% a weighted mean gives) |
| 7 | Season-clustered "CI95" over 2 clusters presented as an interval | flagged `is_an_interval: false` and printed "(NOT an interval)" |
| 8 | `--n-bootstrap 0` crashed with a bare `IndexError` inside the bootstrap | rejected by argparse |
| 9 | La Liga's exact `+0.0000` (no override) printed as "UNRESOLVED" | prints "EXACTLY ZERO (identical columns)" — a wiring check that passed |
| 10 | MDE (2.80σ, a power threshold) described as comparable to a 1.96σ half-width | both printed, neither called "the conservative one" |

## B7. Refuted by verification — recorded so they are not re-raised

- A reported `TypeError` in `format_report` on a `None` half-width was
  demonstrated only by hand-mutating a result dict into a state the shipping
  code cannot produce.
- "C5 is false as stated: EPL's model beats the fairly-fitted constant" — the
  numbers were right but they do not establish the defect, since neither
  comparison resolves (B1 supersedes it).
- The claim that the Resolution paragraph's σ mismatch invalidated a result: the
  arithmetic reproduces but it indicts a pre-data expectation, not a number.

## B8. Net effect on the phase's conclusion

**Unchanged:** the served model is credibly behind the closing over/under 2.5
line in all three leagues; the totals information budget is roughly a quarter of
the 1X2 budget; both shipped `base` overrides helped; no served parameter was
touched; G5 does not fire.

**Withdrawn:** that the model is beaten by a constant in EPL and Bundesliga, and
any quotation of the information share to better than a wide interval.

**The direction of the phase's recommendation does not change** — a totals
channel is where the headroom is — but the size of the prize is known less
precisely than the first cut claimed, and the "still beaten by a constant"
framing must not be cited by any later phase.
