# E2 — club-derived offset cap: EVIDENCE CARD

**Run 2026-07-31**, after the pre-registration was committed alone (`8bb0d72`)
and pushed before any E2 code. Appended to; never edited in place.

```bash
PYTHONPATH=backend:. python -m pipeline.run_e1_tempo \
    --csv-dir data/raw/club --emit-json /tmp/e2.json
```

`CLUB_OFFSET_CAP = 0.30`; scored `1819`–`2425`; nine seasons replayed;
`2526` never opened. Iso-week-clustered bootstrap, 2,000 resamples, **seed 26**,
Bonferroni **k = 3** → 98.3%.

---

## Result: REFUTED by the guardrail. S3 fired.

| League | O/U 2.5 (PRIMARY) | 98.3% CI | verdict | 1X2 (guardrail) | 98.3% CI | verdict |
|---|---|---|---|---|---|---|
| Bundesliga | −0.0006 | [−0.0058, +0.0048] | UNRESOLVED | **+0.0049** | **[+0.0007, +0.0090]** | **CREDIBLY WORSE** |
| EPL | +0.0021 | [−0.0032, +0.0075] | UNRESOLVED | +0.0041 | [−0.0010, +0.0088] | UNRESOLVED |
| La Liga | **−0.0080** | **[−0.0148, −0.0007]** | **CREDIBLY BETTER** | +0.0043 | [−0.0000, +0.0083] | UNRESOLVED |

Negative = candidate better. **S3**: the 1X2 guardrail is credibly worse in
Bundesliga. §7 stops the phase and forbids searching for a configuration that
satisfies both. §8's decision rule requires the guardrail not credibly worse
*anywhere*; it fails.

## The cap fix worked. That is what makes this result interpretable.

E1 could not answer its question because FR-5's ±0.075 bound 69.9–89.2% of
club-seasons. At the club-derived 0.30:

| League | E1 saturation | **E2 saturation** | both components |
|---|---|---|---|
| Bundesliga | 69.9% | **11.0%** | 0.0% |
| EPL | 78.4% | **19.6%** | 0.0% |
| La Liga | 89.2% | **13.9%** | 0.0% |

All three are under §7's 20% ceiling and **no club-season is pinned on both
components**. **S4 does not fire.** The instrument is now the right size for
the population, and E2's numbers mean something E1's did not.

The fitted tempo spread roughly doubled (sd 0.100 / 0.114 / 0.138 against E1's
0.066 / 0.088 / 0.102) and the range now reaches ±0.34 — the fit is expressing
tempo it was previously forbidden from expressing.

## The finding: the parameterisation couples tempo to strength

The 1X2 cost is the consistent number in this table:

> **+0.0049, +0.0041, +0.0043** — positive in all three leagues, tightly
> clustered, and credible in one.

The totals side is not consistent: −0.0006, +0.0021, −0.0080. One league
credible, one flat, one in the wrong direction.

**So the candidate reliably pays ~0.0044 nats on 1X2 to inconsistently maybe
gain on totals.** §5 predicted exactly this mechanism before the run:

> The guardrail matters more in E2 than it did in E1: a 4× looser cap gives the
> fit far more room to overfit, and `(a−d)` moves the ratio.

It does. Strength spread `(a−d)` rose to sd **0.074 / 0.088 / 0.078** — the
offsets are now perturbing the ratio substantially. Elo already handles the
ratio well (D0-B: **64–84%** of the 1X2 information budget captured), so a
perturbation there is almost pure added noise, while the tempo channel it buys
is worth less than the 1X2 channel it damages.

**The attack/defence parameterisation cannot add tempo without also moving
strength.** `(a+d)` and `(a−d)` are both free, so fitting one perturbs the
other. That is a property of the parameterisation, not of the cap, and no cap
value fixes it — which is why §7 forbids a third cap and §9 forbids
re-specifying here.

## La Liga: credible, and still not a result

La Liga's −0.0080 [−0.0148, −0.0007] clears the 0.005 practical floor and its
saturation is a clean 13.9%. It is the only genuinely favourable number E1 or
E2 has produced.

**It does not survive §8.** The decision rule requires the guardrail not
credibly worse in *any* league, and Bundesliga's is. §8 also imposed an extra
burden on a favourable result given §2's pessimistic prior, and the relevant
half of that test fails: **the guardrail does degrade with cap.** At `hl365`/
`n0=30`, La Liga's own 1X2 penalty rises monotonically across the sensitivity
bracket, and all three leagues' guardrail point estimates are positive.

Reporting La Liga alone would be picking the one league of three that cleared,
on a phase whose stated prior was that none would.

## Cap sensitivity — reported, never eligible to win

O/U 2.5 at `hl365`/`n0=30`:

| League | cap 0.20 | **cap 0.30 (frozen)** | cap 0.45 |
|---|---|---|---|
| Bundesliga | +0.0005 | +0.0004 | +0.0007 |
| EPL | +0.0056 | +0.0066 | +0.0068 |
| La Liga | −0.0047 | −0.0038 | −0.0036 |

Flat across a 2.25× cap range, and **not one is credible**. Combined with E1's
0.05–0.15 bracket, the effect is now flat across a **9× span** of cap values
from 0.05 to 0.45. Whatever is or is not there, the cap is not what was hiding
it — which retires the question E2 was created to ask.

## §2's prior was right, and it is worth saying so

The pre-registration declared, before the run: *"the honest prior is that E2
finds nothing, or finds the candidate credibly worse."* It found the second.
E1's cap-sensitivity signal — point estimates flat or worse as the cap widened
— pointed the right way, and E2's job was to check it under a cap that was
not itself binding. It was worth running for that reason and the answer is now
firmer than a sensitivity table could make it.

## Diagnostics

| League | club-seasons | saturated | both | tempo (a+d) sd | range | strength (a−d) sd | no offset |
|---|---|---|---|---|---|---|---|
| Bundesliga | 173 | 11.0% | 0.0% | 0.1005 | [−0.300, +0.262] | 0.0741 | 7.9% |
| EPL | 204 | 19.6% | 0.0% | 0.1137 | [−0.339, +0.299] | 0.0883 | 7.9% |
| La Liga | 194 | 13.9% | 0.0% | 0.1383 | [−0.334, +0.341] | 0.0780 | 5.0% |

Selected grid points collapsed onto the short half-life and weak shrinkage
(`hl180`, `n0` 30–60) in every league — with the cap no longer compressing the
fit, the walk-forward prefers a fast-decaying, lightly-shrunk estimate.

## What E2 settles, and what it does not

**Settles:** FR-5's cap really was the wrong size for club football (84% → ~15%
binding), and fixing it does **not** rescue the candidate. Across caps from
0.05 to 0.45 the totals effect is flat and the 1X2 cost is consistently
positive. **The attack/defence offset parameterisation is refuted for club
totals**, on the guardrail rather than on power.

**Does not settle:** whether a *tempo channel* helps. D0-B's structural finding
stands — `λ_h·λ_a ≡ base²`, and Bundesliga still cannot price an under. E2
refutes one way of adding tempo, the way that also moves strength.

**The obvious next candidate, which E2 may not run:** constrain `(a−d) = 0` so
only `(a+d)` is free — a pure tempo channel with no strength side-effect, which
is precisely the coupling this phase identified. §9 forbids re-specifying here,
and §7 S3 forbids searching for a configuration that satisfies both. That needs
its own pre-registration, and it is the human's call whether it is worth one.

## Compliance

| Promised | Delivered |
|---|---|
| §1 cap frozen at 0.30 from burn-in dispersion | pinned by test; grid carries one cap value |
| §3 nine selectable points, cap off-grid | test asserts `{p.cap for p in GRID} == {0.30}` |
| §3 sensitivity never eligible to win | separate tuple; test asserts the two off-anchor points are not in GRID |
| §4 `2526` never opened | guard raises; test |
| §5 O/U primary, 1X2 non-inferiority on the same selected point | both; the guardrail is what stopped the phase |
| §6 iso-week primary, seed 26, <20 clusters not an interval | 245–247 clusters; the 7-cluster season figure is printed and flagged |
| §6 saturation on the RAW pre-policy fit | E1's fix inherited; test |
| §7 stop conditions | S3 fired, applied mechanically by `stop_conditions()` |
| §8 no promotion | git-diff test over all four §8 files; `"team_offsets"` still `null` |
| §9 no third cap, no transfer test | neither run; I1/F1 still undownloaded |

`2666 passed`
