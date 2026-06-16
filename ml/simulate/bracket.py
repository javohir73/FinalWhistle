"""Full-tournament Monte-Carlo: group stage → knockout bracket → champion.

Extends the group simulation to the real WC2026 knockout format (12 groups,
top 2 + 8 best third-placed teams advance to a Round of 32). Each simulated
iteration plays all 72 group matches, ranks the qualifiers, seeds them into the
official bracket, then plays the single-elimination rounds — yielding, per team,
the probability of reaching each round and lifting the trophy.

Bracket structure (R32 pairings, third-place eligibility, and the bracket tree)
is sourced from the official 2026 FIFA World Cup knockout draw. The 8 best
third-placed teams are assigned to their slots by a constraint-respecting
matching over the official eligibility sets (the full 495-row Annex C table is
approximated by a valid random matching — which specific eligible slot a third
lands in does not change a team's own round-by-round odds materially).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, expected_goals_from_elo, score_cdf, sample_scoreline_from_cdf, sample_scoreline

# --- Round of 32: each side is a group placement or a third-place slot. ---
# ("pos", group_letter, position)  position 1 = winner, 2 = runner-up
# ("third",)                       a third-place slot (resolved via assignment)
R32: list[tuple[int, tuple, tuple]] = [
    (73, ("pos", "A", 2), ("pos", "B", 2)),
    (74, ("pos", "E", 1), ("third",)),
    (75, ("pos", "F", 1), ("pos", "C", 2)),
    (76, ("pos", "C", 1), ("pos", "F", 2)),
    (77, ("pos", "I", 1), ("third",)),
    (78, ("pos", "E", 2), ("pos", "I", 2)),
    (79, ("pos", "A", 1), ("third",)),
    (80, ("pos", "L", 1), ("third",)),
    (81, ("pos", "D", 1), ("third",)),
    (82, ("pos", "G", 1), ("third",)),
    (83, ("pos", "K", 2), ("pos", "L", 2)),
    (84, ("pos", "H", 1), ("pos", "J", 2)),
    (85, ("pos", "B", 1), ("third",)),
    (86, ("pos", "J", 1), ("pos", "H", 2)),
    (87, ("pos", "K", 1), ("third",)),
    (88, ("pos", "D", 2), ("pos", "G", 2)),
]

# Third-place slots: match number -> set of groups whose 3rd may fill it.
THIRD_SLOTS: list[tuple[int, set[str]]] = [
    (74, {"A", "B", "C", "D", "F"}),
    (77, {"C", "D", "F", "G", "H"}),
    (79, {"C", "E", "F", "H", "I"}),
    (80, {"E", "H", "I", "J", "K"}),
    (81, {"B", "E", "F", "I", "J"}),
    (82, {"A", "E", "H", "I", "J"}),
    (85, {"E", "F", "G", "I", "J"}),
    (87, {"D", "E", "I", "J", "L"}),
]

# Bracket tree: match -> (source match A, source match B), winners feed forward.
R16 = {89: (74, 77), 90: (73, 75), 91: (76, 78), 92: (79, 80),
       93: (83, 84), 94: (81, 82), 95: (86, 88), 96: (85, 87)}
QF = {97: (89, 90), 98: (93, 94), 99: (91, 92), 100: (95, 96)}
SF = {101: (97, 98), 102: (99, 100)}
FINAL = (101, 102)  # match 104

R32_NOS = [m[0] for m in R32]

# Round a team has reached (higher = further). 1=R32 .. 6=champion.
ROUND_KEYS = [
    (1, "make_knockout"),
    (2, "reach_r16"),
    (3, "reach_qf"),
    (4, "reach_sf"),
    (5, "reach_final"),
    (6, "win_title"),
]

# Penalty-shootout model: logistic on the Elo gap (stronger side slightly favoured).
PK_BETA = 0.0025


@dataclass
class GroupFixture:
    home_id: int
    away_id: int
    home_adv: float = 0.0
    # Final (home, away) score once the match has actually been played.
    # Played fixtures count as fact in every draw — only unplayed ones are sampled.
    score: tuple[int, int] | None = None


def _assign_thirds(qualified_groups: list[str], rng: np.random.Generator) -> dict[int, str]:
    """Match the 8 qualified third-place groups to the 8 slots, respecting each
    slot's eligibility. Most-constrained slot first, with backtracking."""
    slots = sorted(THIRD_SLOTS, key=lambda s: len(s[1] & set(qualified_groups)))
    assignment: dict[int, str] = {}
    used: set[str] = set()

    def backtrack(i: int) -> bool:
        if i == len(slots):
            return True
        mno, elig = slots[i]
        cands = [g for g in qualified_groups if g in elig and g not in used]
        rng.shuffle(cands)
        for g in cands:
            used.add(g)
            assignment[mno] = g
            if backtrack(i + 1):
                return True
            used.remove(g)
            del assignment[mno]
        return False

    backtrack(0)
    return assignment


def simulate_tournament(
    team_elos: dict[int, float],
    groups: dict[str, list[int]],
    group_fixtures: dict[str, list[GroupFixture]],
    n_sims: int = 2000,
    seed: int | None = 2026,
    base: float = BASE_GOALS,
    beta: float = ELO_TO_GOALS_BETA,
    *,
    rho: float,
) -> dict[int, dict]:
    """Return {team_id: {make_knockout, reach_r16, reach_qf, reach_sf,
    reach_final, win_title}} as probabilities over n_sims tournaments."""
    rng = np.random.default_rng(seed)
    all_ids = [t for members in groups.values() for t in members]
    counts = {tid: {k: 0 for _, k in ROUND_KEYS} for tid in all_ids}

    # Per group: fixed tallies from already-played fixtures (facts, identical in
    # every draw) + Poisson means for the games still to be played.
    base_tallies: dict[str, tuple[dict, dict, dict]] = {}
    sampled: dict[str, list[tuple]] = {}
    for letter, members in groups.items():
        bp = {t: 0 for t in members}
        bgf = {t: 0 for t in members}
        bga = {t: 0 for t in members}
        lams: list[tuple] = []
        for fx in group_fixtures[letter]:
            if fx.score is not None:
                sh, sa = fx.score
                bgf[fx.home_id] += sh; bga[fx.home_id] += sa
                bgf[fx.away_id] += sa; bga[fx.away_id] += sh
                if sh > sa:
                    bp[fx.home_id] += 3
                elif sa > sh:
                    bp[fx.away_id] += 3
                else:
                    bp[fx.home_id] += 1; bp[fx.away_id] += 1
            else:
                lh, la = expected_goals_from_elo(
                    team_elos[fx.home_id], team_elos[fx.away_id], home_adv=fx.home_adv,
                    base=base, beta=beta,
                )
                lams.append((fx.home_id, fx.away_id, score_cdf(lh, la, rho)))
        base_tallies[letter] = (bp, bgf, bga)
        sampled[letter] = lams

    def play(h: int, a: int) -> int:
        """One knockout match (neutral). Draw -> penalties via Elo logistic."""
        lh, la = expected_goals_from_elo(team_elos[h], team_elos[a], home_adv=0.0,
                                         base=base, beta=beta)
        sh, sa = sample_scoreline(rng, lh, la, rho)
        if sh > sa:
            return h
        if sa > sh:
            return a
        p_home = 1.0 / (1.0 + math.exp(-PK_BETA * (team_elos[h] - team_elos[a])))
        return h if rng.random() < p_home else a

    for _ in range(n_sims):
        placement: dict[str, list[int]] = {}
        thirds: list[tuple] = []

        # --- group stage (facts fixed, remaining games sampled) ---
        for letter, members in groups.items():
            bp, bgf, bga = base_tallies[letter]
            pts = dict(bp)
            gf = dict(bgf)
            ga = dict(bga)
            for home_id, away_id, cdf in sampled[letter]:
                sh, sa = sample_scoreline_from_cdf(rng, cdf)
                gf[home_id] += sh; ga[home_id] += sa
                gf[away_id] += sa; ga[away_id] += sh
                if sh > sa:
                    pts[home_id] += 3
                elif sa > sh:
                    pts[away_id] += 3
                else:
                    pts[home_id] += 1; pts[away_id] += 1
            order = sorted(
                members,
                key=lambda t: (pts[t], gf[t] - ga[t], gf[t], rng.random()),
                reverse=True,
            )
            placement[letter] = order
            third = order[2]
            thirds.append(
                (pts[third], gf[third] - ga[third], gf[third], rng.random(), letter, third)
            )

        # --- best 8 third-placed teams ---
        thirds.sort(key=lambda x: x[:4], reverse=True)
        third_team_by_group = {t[4]: t[5] for t in thirds[:8]}
        assignment = _assign_thirds(list(third_team_by_group), rng)

        # --- seed Round of 32 ---
        def resolve(slot: tuple, mno: int) -> int:
            if slot[0] == "pos":
                return placement[slot[1]][slot[2] - 1]
            return third_team_by_group[assignment[mno]]

        reached: dict[int, int] = {}

        def mark(tid: int, rnd: int) -> None:
            if reached.get(tid, 0) < rnd:
                reached[tid] = rnd

        winners: dict[int, int] = {}
        for mno, hs, as_ in R32:
            h, a = resolve(hs, mno), resolve(as_, mno)
            mark(h, 1); mark(a, 1)
            w = play(h, a)
            winners[mno] = w
            mark(w, 2)

        for tree, rnd in ((R16, 3), (QF, 4), (SF, 5)):
            for mno, (s1, s2) in tree.items():
                w = play(winners[s1], winners[s2])
                winners[mno] = w
                mark(w, rnd)

        champion = play(winners[FINAL[0]], winners[FINAL[1]])
        mark(champion, 6)

        for tid, rnd in reached.items():
            for threshold, key in ROUND_KEYS:
                if rnd >= threshold:
                    counts[tid][key] += 1

    return {
        tid: {key: round(counts[tid][key] / n_sims, 4) for _, key in ROUND_KEYS}
        for tid in all_ids
    }
