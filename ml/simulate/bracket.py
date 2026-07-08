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

from dataclasses import dataclass

import numpy as np

from ml.models.poisson import BASE_GOALS, ELO_TO_GOALS_BETA, expected_goals_from_elo, score_cdf, sample_scoreline_from_cdf, sample_scoreline
from ml.models.knockout import ET_FRACTION, PK_BAND, PK_PRIOR_WEIGHT, fit_pk_beta, shootout_p  # noqa: F401  (re-export)

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

# Penalty shootout model — moved to ml.models.knockout (penalties are a match-
# model concern shared with the per-match advance decomposition). Re-exported
# here so existing importers (tests, tuners) keep working.


@dataclass
class GroupFixture:
    home_id: int
    away_id: int
    home_adv: float = 0.0
    # Final (home, away) score once the match has actually been played.
    # Played fixtures count as fact in every draw — only unplayed ones are sampled.
    score: tuple[int, int] | None = None


def _assign_thirds(
    qualified_groups: list[str],
    rng: np.random.Generator,
    pinned: dict[int, str] | None = None,
) -> dict[int, str]:
    """Match the 8 qualified third-place groups to the 8 slots, respecting each
    slot's eligibility. Most-constrained slot first, with backtracking.

    ``pinned`` fixes some slots to a specific group (a played R32 tie whose
    third-placed side is a known fact); those slots and groups are held out and
    the remaining ones are matched around them."""
    pinned = pinned or {}
    slots = sorted(
        (s for s in THIRD_SLOTS if s[0] not in pinned),
        key=lambda s: len(s[1] & set(qualified_groups)),
    )
    assignment: dict[int, str] = dict(pinned)
    used: set[str] = set(pinned.values())

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
    pk_beta: float = 0.0,
    et_tempo: float = 1.0,
    home_adv: float = 0.0,
    ko_host_by_match: dict[int, int] | None = None,
    ko_results: dict[int, tuple[int, int, int]] | None = None,
    team_offsets: dict[int, tuple[float, float]] | None = None,
) -> dict[int, dict]:
    """Return {team_id: {make_knockout, reach_r16, reach_qf, reach_sf,
    reach_final, win_title}} as probabilities over n_sims tournaments.

    ``team_offsets`` maps team_id -> (atk, def) log-lambda offsets (FR-5.3) so
    every simulated match — group stage and knockout — runs on the SAME
    adjusted lambdas as the match cards. Omitted or empty -> bit-identical to
    the historical symmetric-Elo behavior.

    ``ko_results`` pins already-played knockout ties as facts (analogous to a
    played ``GroupFixture.score``): ``{official_match_no: (home_id, away_id,
    winner_id)}``. A pinned tie forces its winner forward and its loser out in
    every draw, so the winner's reach_* for that round is 1.0 and the loser's is
    0.0. The R32 third-place side of a pinned tie is also held to its real slot,
    so a beaten third can't re-enter the bracket via the random slot assignment.
    """
    ko_host = ko_host_by_match or {}
    ko_results = ko_results or {}
    offsets = team_offsets or {}

    def _lambdas(h: int, a: int, adv: float) -> tuple[float, float]:
        """Expected goals for one pairing, offsets included — the one lambda
        builder for both the group stage and the knockout rounds."""
        atk_h, def_h = offsets.get(h, (0.0, 0.0))
        atk_a, def_a = offsets.get(a, (0.0, 0.0))
        return expected_goals_from_elo(
            team_elos[h], team_elos[a], home_adv=adv, base=base, beta=beta,
            atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
        )
    # Forced winners, keyed by match number, applied at every played tie.
    ko_win = {mno: winner for mno, (_h, _a, winner) in ko_results.items()}
    # A played R32 tie whose third-placed side is known: hold that team to its
    # real slot when the per-draw third assignment runs (below).
    r32_sides = {mno: (hs, as_) for mno, hs, as_ in R32}
    pinned_third_slot: dict[int, int] = {}
    for mno, (home_id, away_id, _w) in ko_results.items():
        sides = r32_sides.get(mno)
        if sides is None:
            continue
        hs, as_ = sides
        if hs == ("third",):
            pinned_third_slot[mno] = home_id
        elif as_ == ("third",):
            pinned_third_slot[mno] = away_id
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
                lh, la = _lambdas(fx.home_id, fx.away_id, fx.home_adv)
                lams.append((fx.home_id, fx.away_id, score_cdf(lh, la, rho)))
        base_tallies[letter] = (bp, bgf, bga)
        sampled[letter] = lams

    # Extra time: same engine at 30-minute rates (model v0.5 — matches the
    # per-match ko_advance decomposition, ml/models/knockout.py).
    et_scale = ET_FRACTION * et_tempo

    def play(mno: int, h: int, a: int) -> int:
        """One knockout match. Draw -> extra time -> penalties via Elo logistic.
        Host advantage applied when ko_host maps mno to h or a."""
        host = ko_host.get(mno)
        adv = home_adv if host == h else -home_adv if host == a else 0.0
        lh, la = _lambdas(h, a, adv)
        sh, sa = sample_scoreline(rng, lh, la, rho)
        if sh > sa:
            return h
        if sa > sh:
            return a
        if et_scale > 0.0:
            eh, ea = sample_scoreline(rng, lh * et_scale, la * et_scale, rho)
            if eh > ea:
                return h
            if ea > eh:
                return a
        return h if rng.random() < shootout_p(team_elos[h], team_elos[a], pk_beta) else a

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
        # Hold played R32 thirds to their real slots (a beaten third must stay put,
        # never advance from a slot it was randomly reassigned to). Only pin a team
        # that actually made the top-8 this draw; otherwise it can't advance anyway.
        group_of_third = {tid: g for g, tid in third_team_by_group.items()}
        pinned_groups = {
            mno: group_of_third[tid]
            for mno, tid in pinned_third_slot.items()
            if tid in group_of_third
        }
        assignment = _assign_thirds(list(third_team_by_group), rng, pinned=pinned_groups)

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
            w = ko_win.get(mno)
            if w is None:
                w = play(mno, h, a)
            winners[mno] = w
            mark(w, 2)

        for tree, rnd in ((R16, 3), (QF, 4), (SF, 5)):
            for mno, (s1, s2) in tree.items():
                w = ko_win.get(mno)
                if w is None:
                    w = play(mno, winners[s1], winners[s2])
                winners[mno] = w
                mark(w, rnd)

        champion = ko_win.get(104)
        if champion is None:
            champion = play(104, winners[FINAL[0]], winners[FINAL[1]])
        mark(champion, 6)

        for tid, rnd in reached.items():
            for threshold, key in ROUND_KEYS:
                if rnd >= threshold:
                    counts[tid][key] += 1

    return {
        tid: {key: round(counts[tid][key] / n_sims, 4) for _, key in ROUND_KEYS}
        for tid in all_ids
    }
