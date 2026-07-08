"""Generate predictions for all upcoming WC2026 matches (PRD §4.2, §17).

For each scheduled group match it builds features, runs the Poisson engine,
derives confidence + reasons, and writes a Prediction row plus a §17-shaped
payload. It then simulates each group to fill predicted standings + qualification
probabilities. Designed to be called by the daily pipeline (task 7).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.availability import availability_for_match
from app.models import (
    Group,
    GroupTeam,
    HistoricalMatch,
    Match,
    Odds,
    Prediction,
    Standing,
    Team,
    TeamTournamentState,
    TournamentOdds,
)
from ml.evaluation.calibration import calibrate, effective_gap
from ml.explain.reasons import confidence_level, generate_reasons, top_features
from ml.features.build_features import build_match_features, estimate_strength
from ml.features.wdl_features import assemble_features, window_stats
from ml.models.knockout import ko_advance
from ml.models.odds_blend import blend_lambda_total, market_lambda_total
from ml.models.params import ModelParams, load_params
from ml.models.rest import DEFAULT_REST, rest_offsets
from ml.models.poisson import predict_from_lambdas, predict_match
from ml.models.poisson import predict_match
from ml.models.team_offsets import load_team_offsets, offsets_for
from ml.ratings.elo import HOME_ADVANTAGE
from ml.simulate.bracket import GroupFixture as KnockoutFixture, simulate_tournament
from ml.simulate.group_sim import GroupFixture, simulate_group

log = logging.getLogger(__name__)

#: Version tag for shadow rows (exact-score program FR-4.4): the odds-anchored
#: twin of every production prediction. Never served, never in the public
#: record — promotion to the headline is a manual owner decision (FR-4.8).
SHADOW_MODEL_VERSION = "poisson-elo-v0.3-shadow"

#: Version tag for the announced-XI availability twin. Mirrors SHADOW_MODEL_VERSION:
#: an is_shadow row, never served, logged pre-kickoff for the production-vs-
#: availability comparison (docs/superpowers/specs/2026-07-03-availability-signal-design.md).
AVAILABILITY_MODEL_VERSION = "poisson-elo-v0.3+avail"

#: Version tag for the StatsBomb xG-nudged team-offsets twin. Mirrors
#: AVAILABILITY_MODEL_VERSION: an is_shadow row, never served, loaded from
#: ml/models/team_offsets_xg.json INDEPENDENT of params.team_offsets (the
#: shadow-first invariant — this twin runs whether or not the served offsets
#: flag is ever flipped). docs/superpowers/plans/2026-07-04-statsbomb-xg-team-offsets.md.
OFFSETS_MODEL_VERSION = "poisson-elo-v0.3+xg"

#: Suspension twin (signal pack, v0.5): banned players (red card / yellow
#: accumulation) removed from the reference XI via the availability weights.
#: is_shadow, never served.
BANS_MODEL_VERSION = "poisson-elo-v0.5+bans"

#: Rest-days twin (signal pack, v0.5): schedule differential as a bounded
#: attack offset (ml/models/rest.py DEFAULT_REST). is_shadow, never served.
REST_MODEL_VERSION = "poisson-elo-v0.5+rest"


def _host_adv(match: Match, home: Team, home_advantage: float = HOME_ADVANTAGE) -> float:
    """Signed host bonus: + if home is host, - if away is host (boosts away)."""
    if match.host_team_id is None:
        return 0.0
    return home_advantage if match.host_team_id == home.id else -home_advantage


def _offsets_by_team_id(params: ModelParams, teams: list[Team]) -> dict[int, tuple[float, float]] | None:
    """{team_id: (atk, def)} from the enabled offsets store, or None when the
    flag is off (the shipped default). The ONE loader for the match cards AND
    both Monte-Carlo simulations, so a flipped team_offsets flag can never serve
    per-match probabilities and qualification/title odds from divergent lambdas
    (FR-5.3)."""
    if not params.team_offsets:
        return None
    store = load_team_offsets(params.team_offsets.get("file"))
    return {t.id: offsets_for(store, t.name) for t in teams}


def _form_offsets_by_team_id(
    db: Session, params: ModelParams, teams: list[Team]
) -> dict[int, tuple[float, float]] | None:
    """{team_id: (atk_form, def_form)} from the split/decayed form channels
    (model v2 C1), or None when params.form_channels is off (the shipped
    default — bit-identical serving). Reads each team's persisted
    TeamTournamentState.residual_ledger (written by
    pipeline.learning_loop.update_tournament_state, optionally seeded with
    pre-tournament history) and runs it through ml.ratings.form.form_offsets
    with the tuned config. A team with no state row / no ledger yet gets
    (0.0, 0.0) — the same "no evidence, no adjustment" behavior as the
    equivalent team_offsets path."""
    if not params.form_channels:
        return None
    from ml.ratings.form import FormConfig, form_offsets

    cfg = FormConfig(
        c_atk=params.form_channels["c_atk"],
        c_def=params.form_channels["c_def"],
        cap=params.form_channels["cap"],
        half_life=params.form_channels["half_life"],
    )
    team_ids = [t.id for t in teams]
    rows = (
        db.query(TeamTournamentState)
        .filter(TeamTournamentState.team_id.in_(team_ids))
        .all()
    )
    ledgers = {r.team_id: r.residual_ledger for r in rows if r.residual_ledger}
    return {
        tid: form_offsets([tuple(pair) for pair in ledgers.get(tid, [])], cfg)
        for tid in team_ids
    }


def _combined_offsets_by_team_id(
    db: Session, params: ModelParams, teams: list[Team]
) -> dict[int, tuple[float, float]] | None:
    """{team_id: (atk, def)} — the xG team offsets and the split form-channel
    offsets ADDED together per team, exactly how build_payload composes them
    onto atk_h/def_h/atk_a/def_a. The ONE combiner for the match cards AND
    both Monte-Carlo simulations (mirrors _offsets_by_team_id's FR-5.3
    invariant, extended to cover form_channels too — model v2 C1/C1-dark):
    a flipped team_offsets or form_channels flag can never serve per-match
    probabilities and qualification/title odds from divergent lambdas.
    Both sources off (the shipped default) -> None, a strict no-op —
    bit-identical to the pre-C1 sims."""
    xg = _offsets_by_team_id(params, teams)
    form = _form_offsets_by_team_id(db, params, teams)
    if xg is None and form is None:
        return None
    xg = xg or {}
    form = form or {}
    combined: dict[int, tuple[float, float]] = {}
    for t in teams:
        atk_xg, def_xg = xg.get(t.id, (0.0, 0.0))
        atk_form, def_form = form.get(t.id, (0.0, 0.0))
        combined[t.id] = (atk_xg + atk_form, def_xg + def_form)
    return combined


def _form_channels_reason(
    home_name: str, away_name: str,
    atk_form_h: float, def_form_h: float, atk_form_a: float, def_form_a: float,
) -> str:
    """One plain-English reason for whichever side's split form signal is
    strongest — mirrors generate_reasons' style (ml/explain/reasons.py)."""
    candidates = [
        (abs(atk_form_h), f"{home_name}'s recent form shows attacking output above the model's expectation."),
        (abs(def_form_h), f"{home_name}'s recent form shows defensive lapses above the model's expectation."),
        (abs(atk_form_a), f"{away_name}'s recent form shows attacking output above the model's expectation."),
        (abs(def_form_a), f"{away_name}'s recent form shows defensive lapses above the model's expectation."),
    ]
    _, text = max(candidates, key=lambda c: c[0])
    return text


def _add_form_channels_factor(factors: list[dict], weight: float) -> list[dict]:
    """Fold a 'form_channels' entry into top_features' normalized weights,
    re-normalizing so the list still sums to 1.0."""
    if weight <= 0:
        return factors
    total = sum(f["weight"] for f in factors) + weight
    rescaled = [{"name": f["name"], "weight": round(f["weight"] / total, 3)} for f in factors]
    rescaled.append({"name": "form_channels", "weight": round(weight / total, 3)})
    return sorted(rescaled, key=lambda f: f["weight"], reverse=True)


def _recent_appearances(db: Session, team_id: int, limit: int = 10) -> list[tuple[int, int]]:
    """A team's most-recent (goals_for, goals_against) from played history."""
    rows = (
        db.query(HistoricalMatch)
        .filter(
            (HistoricalMatch.team_a_id == team_id) | (HistoricalMatch.team_b_id == team_id),
            HistoricalMatch.score_a.isnot(None), HistoricalMatch.score_b.isnot(None),
        )
        .order_by(HistoricalMatch.date.desc())
        .limit(limit)
        .all()
    )
    out: list[tuple[int, int]] = []
    for m in rows:
        if m.team_a_id == team_id:
            out.append((m.score_a, m.score_b))
        else:
            out.append((m.score_b, m.score_a))
    return out


def _boost_features(db: Session, home: Team, away: Team,
                    elo_home: float, elo_away: float, is_neutral: bool,
                    h2h: dict) -> dict:
    """Assemble the booster's feature dict for an upcoming match — same schema and
    reducer as training (leak-free: all of history precedes a scheduled fixture).
    `h2h` is reused from the caller's build_match_features (home perspective:
    a_wins/matches) to avoid a duplicate head-to-head query."""
    form_h, gf_h, ga_h, n_h = window_stats(_recent_appearances(db, home.id))
    form_a, gf_a, ga_a, n_a = window_stats(_recent_appearances(db, away.id))
    return assemble_features(
        elo_home=elo_home, elo_away=elo_away, is_neutral=is_neutral,
        form_home=form_h, form_away=form_a,
        gf_avg_home=gf_h, gf_avg_away=gf_a, ga_avg_home=ga_h, ga_avg_away=ga_a,
        h2h_home_wins=h2h["a_wins"], h2h_matches=h2h["matches"],
        data_points_home=n_h, data_points_away=n_a,
    )


def build_payload(
    db: Session, match: Match, model_version: str,
    strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
    booster: "WdlBoost | None" = None,
) -> dict | None:
    """Build the PRD §17 prediction payload for a match (None if teams unknown).

    ``strengths`` (team_id -> effective Elo) lets the learning loop inject
    tournament-adjusted ratings; absent entries fall back to the base rating.
    ``params`` are the tuned engine parameters (base/beta/rho/temperature/
    home_adv); they default to the loaded model_params.json or the v0.1 constants.
    """
    if match.team_home_id is None or match.team_away_id is None:
        return None
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)

    params = params or load_params()
    feats = build_match_features(db, home, away, host_team_id=match.host_team_id)
    host_adv = _host_adv(match, home, params.home_adv)
    strengths = strengths or {}
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    # Keep the explanation layer consistent with the probabilities: reasons and
    # top_features must describe the SAME effective ratings the model used,
    # not the pre-tournament base.
    feats.elo_home = elo_home
    feats.elo_away = elo_away
    feats.elo_diff = elo_home - elo_away
    # Per-team attack/defence offsets (FR-5.3): opt-in via model_params.json
    # ("team_offsets": null keeps this a strict no-op — bit-identical lambdas).
    # Loaded through the same helper the group/tournament sims use, so the card
    # and the simulations always agree on a team's offsets.
    offs = _offsets_by_team_id(params, [home, away]) or {}
    atk_h, def_h = offs.get(home.id, (0.0, 0.0))
    atk_a, def_a = offs.get(away.id, (0.0, 0.0))
    # Split, decayed, boundary-free form channels (model v2 C1): opt-in via
    # model_params.json ("form_channels": null keeps this a strict no-op —
    # bit-identical lambdas). Additive to the xG team offsets above — both
    # channels are independent log-lambda nudges applied to the same
    # atk_home/def_home/atk_away/def_away parameters (ml/models/poisson.py).
    # When active, effective_elos() has already stopped adding the legacy
    # scalar form_adjustment (pipeline/learning_loop.py), so these offsets
    # are the ONLY form signal in the served lambdas — no double counting.
    form_offs = _form_offsets_by_team_id(db, params, [home, away]) or {}
    atk_form_h, def_form_h = form_offs.get(home.id, (0.0, 0.0))
    atk_form_a, def_form_a = form_offs.get(away.id, (0.0, 0.0))
    atk_h += atk_form_h
    def_h += def_form_h
    atk_a += atk_form_a
    def_a += def_form_a
    # Signal pack (v0.5): suspensions + rest days join the same additive
    # log-lambda channel. Both ship OFF (model_params.json nulls keep this a
    # strict no-op); flipping the param is the promotion step once their
    # shadow twins validate against the record.
    if params.suspensions:
        from pipeline.suspensions import suspension_offsets_for_match  # lazy: avoids cycle

        susp = suspension_offsets_for_match(db, match)
        if susp is not None:
            atk_h += susp[0]
            atk_a += susp[1]
    if params.rest_days:
        rest = _rest_days_for_match(db, match)
        if rest is not None:
            r_offs = rest_offsets(
                rest[0], rest[1],
                float(params.rest_days.get("coef", DEFAULT_REST["coef"])),
                float(params.rest_days.get("cap", DEFAULT_REST["cap"])),
            )
            if r_offs is not None:
                atk_h += r_offs[0]
                atk_a += r_offs[1]
    pred = predict_match(
        elo_home, elo_away, home_adv=host_adv,
        base=params.base, beta=params.beta, rho=params.rho,
        temperature=params.temperature, calibrator=params.calibrator,
        atk_home=atk_h, def_home=def_h, atk_away=atk_a, def_away=def_a,
    )

    # Poisson W/D/L is the base. If a booster blend is shipped (and a trained
    # booster is supplied), blend toward it and re-calibrate. The SCORELINE stays
    # Poisson's — the booster only refines the W/D/L triple (spec §1).
    # NOTE: the argmax of the blended triple may disagree with the Poisson scoreline
    # (e.g. bars lean draw while the score reads 1-0). That is intentional per the
    # design boundary; the predicted score is a separate Poisson-derived signal.
    p_home, p_draw, p_away = pred.prob_home_win, pred.prob_draw, pred.prob_away_win
    if params.wdl_blend and booster is not None:
        from ml.models.wdl_boost import blend_triples  # deferred: keeps sklearn off the blend-off path

        feats_v = _boost_features(db, home, away, elo_home, elo_away, match.is_neutral, feats.h2h)
        b = booster.predict_proba(feats_v)
        p_home, p_draw, p_away = blend_triples(
            (p_home, p_draw, p_away), (b["H"], b["D"], b["A"]), params.wdl_blend["weight"]
        )
        p_home, p_draw, p_away = calibrate(
            (p_home, p_draw, p_away), params.wdl_blend.get("calibrator")
        )

    cold_start = feats.strength_source_home != "elo" or feats.strength_source_away != "elo"
    confidence = confidence_level(
        p_home, p_draw, p_away,
        feats.data_points_home, feats.data_points_away, cold_start,
    )
    reasons = generate_reasons(
        feats, home.name, away.name,
        p_home, p_draw, p_away,
    )
    factors = top_features(feats)
    # Surface the split form channels alongside the existing explanation
    # layer (model v2 C1) — additive, so explanations stay consistent with
    # the lambdas above without perturbing generate_reasons/top_features'
    # own MatchFeatures-only contract (form_channels off is a strict no-op:
    # both offsets are 0.0 and nothing is appended here).
    if params.form_channels and (atk_form_h or def_form_h or atk_form_a or def_form_a):
        reasons = reasons + [
            _form_channels_reason(home.name, away.name, atk_form_h, def_form_h, atk_form_a, def_form_a)
        ]
        form_weight = (
            abs(atk_form_h) + abs(def_form_h) + abs(atk_form_a) + abs(def_form_a)
        ) * 8
        factors = _add_form_channels_factor(factors, form_weight)

    # Knockout ties resolve past the 90th minute: decompose "who goes through"
    # into win-in-90 / extra-time / penalties on top of the SERVED triple, so
    # the advance numbers always reconcile with the visible W/D/L bar
    # (ml/models/knockout.py). Group games: a draw is final, no block.
    knockout = None
    if match.stage != "group":
        # Shootout context (v0.5): a missing first-choice keeper nudges the
        # pens split by params.pk_keeper_delta (0.0 = no-op, the shipped
        # default; shootout_p clamps inside PK_BAND regardless).
        pk_shift = _keeper_pk_shift_for_match(db, match, params) if params.pk_keeper_delta else 0.0
        knockout = ko_advance(
            p_home, p_draw, p_away,
            pred.lambda_home, pred.lambda_away,
            elo_home, elo_away,
            rho=params.rho, pk_beta=params.pk_beta, et_tempo=params.et_tempo,
            pk_shift=pk_shift,
        ).to_payload()

    return {
        "match_id": match.id,
        "model_version": model_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teams": {"home": home.name, "away": away.name},
        "is_neutral": match.is_neutral,
        "knockout": knockout,
        "probabilities": {
            "home_win": round(p_home, 4),
            "draw": round(p_draw, 4),
            "away_win": round(p_away, 4),
        },
        "predicted_score": {
            "home": pred.score_home,
            "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "lambda_home": round(pred.lambda_home, 4),
        "lambda_away": round(pred.lambda_away, 4),
        "rho": params.rho,
        "confidence": confidence,
        "reasons": reasons,
        "top_features": factors,
        "head_to_head": {
            "matches": feats.h2h["matches"],
            "home_wins": feats.h2h["a_wins"],
            "draws": feats.h2h["draws"],
            "away_wins": feats.h2h["b_wins"],
        },
        "odds_comparison": {"available": False},
        "disclaimer": "For analytics and entertainment only. Not betting advice.",
    }


def _write_prediction(db: Session, match: Match, payload: dict, model_version: str,
                      is_shadow: bool = False) -> None:
    """Append one prediction row for ``match`` (production or shadow twin).

    Append-only, frozen at kickoff (ROADMAP Standing Rule #2): the log is never
    UPDATEd/DELETEd, and once a match leaves "scheduled" no further row may be
    added — the pre-kickoff prediction stays the verified record forever. Both
    public entry points already filter to scheduled matches, so this guard is a
    defensive no-op for them; it exists so no call path can ever append after the
    whistle.
    """
    if match.status != "scheduled":
        log.warning(
            "skip prediction append for match %s: status=%s "
            "(append-only log is frozen at kickoff)",
            match.id, match.status,
        )
        return
    p = payload["probabilities"]
    s = payload["predicted_score"]
    db.add(
        Prediction(
            match_id=payload["match_id"],
            model_version=model_version,
            prob_home_win=p["home_win"],
            prob_draw=p["draw"],
            prob_away_win=p["away_win"],
            predicted_score_home=s["home"],
            predicted_score_away=s["away"],
            predicted_score_prob=s["probability"],
            lambda_home=payload.get("lambda_home"),
            lambda_away=payload.get("lambda_away"),
            rho=payload.get("rho"),
            knockout=payload.get("knockout"),
            confidence=payload["confidence"],
            reasons=payload["reasons"],
            top_features=payload["top_features"],
            is_shadow=is_shadow,
        )
    )


def _latest_odds(db: Session, match_id: int) -> Odds | None:
    """Freshest stored bookmaker consensus for a match (None when unpriced)."""
    return (
        db.query(Odds)
        .filter(Odds.match_id == match_id)
        .order_by(Odds.captured_at.desc(), Odds.id.desc())
        .first()
    )


def write_shadow_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """Write the shadow twin of a just-built production payload (FR-4.4).

    With a stored market total AND ``params.w_odds`` > 0, the twin's lambda
    SUM is anchored toward the market (Elo split preserved, FR-4.3) and the
    grid/triple/headline are recomputed through the same calibrated pipeline
    (``predict_from_lambdas``). Otherwise the twin copies the production
    numbers exactly, so the production-vs-shadow comparison is a clean null
    test until odds exist and a weight is deliberately set. Explanation
    fields (confidence/reasons/top_features) always mirror production — the
    twin is internal-only and never rendered. NOTE: the anchored triple is
    pure Poisson (no W/D/L booster leg even if wdl_blend ever ships) so the
    comparison attributes divergence to the odds anchor alone.

    The ``w_odds`` gate runs FIRST: with the shipped 0.0 the blend is the
    identity, so the odds lookup and the market inversion (whose 1X2 fallback
    is a costly double bisection) are skipped entirely — this path executes
    synchronously inside latency-sensitive request chains.
    """
    shadow = payload
    if params.w_odds <= 0.0:
        _write_prediction(db, match, shadow, SHADOW_MODEL_VERSION, is_shadow=True)
        return
    odds = _latest_odds(db, match.id)
    market_total = None
    if odds is not None:
        market_total = market_lambda_total(
            odds_over25=odds.odds_over25, odds_under25=odds.odds_under25,
            odds_home=odds.odds_home, odds_draw=odds.odds_draw, odds_away=odds.odds_away,
        )
    if market_total is not None:
        lam_h, lam_a = blend_lambda_total(
            payload["lambda_home"], payload["lambda_away"], market_total, params.w_odds
        )
        home = db.get(Team, match.team_home_id)
        away = db.get(Team, match.team_away_id)
        elo_home = strengths.get(home.id, estimate_strength(home)[0])
        elo_away = strengths.get(away.id, estimate_strength(away)[0])
        pred = predict_from_lambdas(
            lam_h, lam_a, rho=params.rho, temperature=params.temperature,
            calibrator=params.calibrator,
            eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
        )
        shadow = {
            **payload,
            "probabilities": {
                "home_win": round(pred.prob_home_win, 4),
                "draw": round(pred.prob_draw, 4),
                "away_win": round(pred.prob_away_win, 4),
            },
            "predicted_score": {
                "home": pred.score_home,
                "away": pred.score_away,
                "probability": round(pred.score_prob, 4),
            },
            "lambda_home": round(pred.lambda_home, 4),
            "lambda_away": round(pred.lambda_away, 4),
        }
    _write_prediction(db, match, shadow, SHADOW_MODEL_VERSION, is_shadow=True)


def write_availability_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """Write the announced-XI availability twin of a production payload, when BOTH
    sides have a stored XI (availability_for_match gates this). The per-team attack
    offset scales the production lambdas (lambda *= exp(offset)); the grid/triple/
    headline are recomputed through the same calibrated pipeline
    (predict_from_lambdas). No XI on either side -> no row (partial coverage is
    expected). Never served — is_shadow=True, tagged AVAILABILITY_MODEL_VERSION."""
    adj = availability_for_match(db, match)
    if adj is None:
        return
    off_home, off_away, _expl_home, _expl_away = adj
    lam_h = payload["lambda_home"] * math.exp(off_home)
    lam_a = payload["lambda_away"] * math.exp(off_away)
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    pred = predict_from_lambdas(
        lam_h, lam_a, rho=params.rho, temperature=params.temperature,
        calibrator=params.calibrator,
        eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
    )
    twin = {
        **payload,
        "probabilities": {
            "home_win": round(pred.prob_home_win, 4),
            "draw": round(pred.prob_draw, 4),
            "away_win": round(pred.prob_away_win, 4),
        },
        "predicted_score": {
            "home": pred.score_home, "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "lambda_home": round(pred.lambda_home, 4),
        "lambda_away": round(pred.lambda_away, 4),
    }
    _write_prediction(db, match, twin, AVAILABILITY_MODEL_VERSION, is_shadow=True)


def write_offsets_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """Write the StatsBomb xG-nudged team-offsets twin of a production payload.

    Loads ml/models/team_offsets_xg.json INDEPENDENT of params.team_offsets —
    the shadow-first invariant: this twin runs whether or not the served
    offsets flag is ever flipped, so it never depends on a promotion decision.
    Both sides all-zero (no coverage for either team) -> no row (clean null
    test, mirrors write_availability_prediction's ``if adj is None: return``).
    Otherwise the production lambdas are scaled by the SAME cross-term the
    served engine already applies when team_offsets is enabled
    (ml/models/poisson.py:66-69): lambda_home *= exp(atk_home + def_away),
    lambda_away *= exp(atk_away + def_home). The grid/triple/headline are
    recomputed through the same calibrated pipeline (predict_from_lambdas).
    Never served — is_shadow=True, tagged OFFSETS_MODEL_VERSION."""
    store = load_team_offsets("ml/models/team_offsets_xg.json")
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    atk_h, def_h = offsets_for(store, home.name)
    atk_a, def_a = offsets_for(store, away.name)
    if not (atk_h or def_h or atk_a or def_a):
        return
    lam_h = payload["lambda_home"] * math.exp(atk_h + def_a)
    lam_a = payload["lambda_away"] * math.exp(atk_a + def_h)
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    pred = predict_from_lambdas(
        lam_h, lam_a, rho=params.rho, temperature=params.temperature,
        calibrator=params.calibrator,
        eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
    )
    twin = {
        **payload,
        "probabilities": {
            "home_win": round(pred.prob_home_win, 4),
            "draw": round(pred.prob_draw, 4),
            "away_win": round(pred.prob_away_win, 4),
        },
        "predicted_score": {
            "home": pred.score_home, "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "lambda_home": round(pred.lambda_home, 4),
        "lambda_away": round(pred.lambda_away, 4),
    }
    _write_prediction(db, match, twin, OFFSETS_MODEL_VERSION, is_shadow=True)


def _rest_days_for_match(db: Session, match: Match) -> tuple[float, float] | None:
    """Days since each side's last finished match, or None when either side has
    no prior tournament match (openers — the signal is undefined there)."""
    from pipeline.suspensions import _finished_before  # lazy: avoids cycle

    out = []
    for team_id in (match.team_home_id, match.team_away_id):
        if team_id is None:
            return None
        prior = _finished_before(db, team_id, match)
        if not prior:
            return None
        out.append((match.kickoff_utc - prior[-1].kickoff_utc).total_seconds() / 86400.0)
    return out[0], out[1]


def _keeper_pk_shift_for_match(db: Session, match: Match, params: ModelParams) -> float:
    """params.pk_keeper_delta resolved against this match: suspension statuses
    plus any ingested injury statuses, checked for the first-choice keeper."""
    from app.availability import _injury_statuses, _squad_dicts  # lazy: avoids cycle
    from pipeline.suspensions import keeper_pk_shift, suspension_statuses

    squads: dict[str, list[dict]] = {}
    statuses: dict[str, dict[int, dict]] = {}
    for side in ("home", "away"):
        team_id = match.team_home_id if side == "home" else match.team_away_id
        squads[side] = _squad_dicts(db, team_id)
        st = dict(suspension_statuses(db, match, side, squads[side]))
        st.update(_injury_statuses(match, side, {p.get("provider_player_id") for p in squads[side]}))
        statuses[side] = st
    return keeper_pk_shift(squads, statuses, params.pk_keeper_delta)


def _write_scaled_twin(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
    off_home: float, off_away: float, version: str,
) -> None:
    """Shared body of the attack-offset twins (+bans, +rest): scale the
    production lambdas by exp(offset), recompute grid/triple/headline through
    the same calibrated pipeline, append as is_shadow. Mirrors
    write_availability_prediction, which predates this helper."""
    lam_h = payload["lambda_home"] * math.exp(off_home)
    lam_a = payload["lambda_away"] * math.exp(off_away)
    home = db.get(Team, match.team_home_id)
    away = db.get(Team, match.team_away_id)
    elo_home = strengths.get(home.id, estimate_strength(home)[0])
    elo_away = strengths.get(away.id, estimate_strength(away)[0])
    pred = predict_from_lambdas(
        lam_h, lam_a, rho=params.rho, temperature=params.temperature,
        calibrator=params.calibrator,
        eff_gap=effective_gap(elo_home, elo_away, _host_adv(match, home, params.home_adv)),
    )
    twin = {
        **payload,
        "probabilities": {
            "home_win": round(pred.prob_home_win, 4),
            "draw": round(pred.prob_draw, 4),
            "away_win": round(pred.prob_away_win, 4),
        },
        "predicted_score": {
            "home": pred.score_home, "away": pred.score_away,
            "probability": round(pred.score_prob, 4),
        },
        "lambda_home": round(pred.lambda_home, 4),
        "lambda_away": round(pred.lambda_away, 4),
    }
    _write_prediction(db, match, twin, version, is_shadow=True)


def write_suspension_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """+bans twin: suspended players (red card / yellow accumulation) removed
    from the reference XI via the availability weight machinery. Runs whether
    or not params.suspensions is ever flipped (shadow-first invariant). No
    suspension on either side -> no row (clean null, like the other twins)."""
    from pipeline.suspensions import suspension_offsets_for_match  # lazy: avoids cycle

    res = suspension_offsets_for_match(db, match)
    if res is None:
        return
    _write_scaled_twin(db, match, payload, strengths, params, res[0], res[1], BANS_MODEL_VERSION)


def write_rest_prediction(
    db: Session, match: Match, payload: dict,
    strengths: dict[int, float], params: ModelParams,
) -> None:
    """+rest twin on DEFAULT_REST, independent of params.rest_days (shadow-first
    invariant). Openers and equal-rest matches produce no row — the twin would
    be bit-identical to production and grade nothing."""
    rest = _rest_days_for_match(db, match)
    if rest is None:
        return
    offs = rest_offsets(rest[0], rest[1], DEFAULT_REST["coef"], DEFAULT_REST["cap"])
    if offs is None or (offs[0] == 0.0 and offs[1] == 0.0):
        return
    _write_scaled_twin(db, match, payload, strengths, params, offs[0], offs[1], REST_MODEL_VERSION)


def _played_score(m: Match) -> tuple[int, int] | None:
    """The final score when a match has actually been played, else None.
    In-play matches stay None — they aren't final until the whistle."""
    if m.status == "finished" and m.score_home is not None and m.score_away is not None:
        return (m.score_home, m.score_away)
    return None


def _simulate_standings(
    db: Session, group: Group, model_version: str, n_sims: int,
    strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
) -> None:
    params = params or load_params()
    members = [gt.team for gt in group.group_teams]
    strengths = strengths or {}
    team_elos = {t.id: strengths.get(t.id, estimate_strength(t)[0]) for t in members}
    fixtures = []
    for m in db.query(Match).filter_by(group_id=group.id).all():
        if m.team_home_id and m.team_away_id:
            home = db.get(Team, m.team_home_id)
            fixtures.append(
                GroupFixture(m.team_home_id, m.team_away_id,
                             home_adv=_host_adv(m, home, params.home_adv),
                             score=_played_score(m))
            )

    results = simulate_group(
        team_elos, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
        # Combined xG team offsets + split form-channel offsets (model v2
        # C1): the SAME per-team sum build_payload applies to the match
        # cards, so the standings table and the cards never disagree on a
        # team's adjustment (FR-5.3, extended by C1).
        team_offsets=_combined_offsets_by_team_id(db, params, members),
    )
    # Persist REAL tallies (finished matches only) — the table users see is the
    # actual league table; only qualification_prob comes from the simulation.
    from app.serializers import live_group_table

    real = live_group_table(db, group.id, include_in_play=False)
    now = datetime.now(timezone.utc)
    for team_id, r in results.items():
        row = db.query(Standing).filter_by(group_id=group.id, team_id=team_id).one_or_none()
        if row is None:
            row = Standing(group_id=group.id, team_id=team_id)
            db.add(row)
        t = real.get(team_id, {"played": 0, "won": 0, "drawn": 0, "lost": 0,
                               "points": 0, "gf": 0, "ga": 0})
        row.qualification_prob = r["qualification_prob"]
        row.played = t["played"]
        row.won = t["won"]
        row.drawn = t["drawn"]
        row.lost = t["lost"]
        row.points = t["points"]
        row.goals_for = t["gf"]
        row.goals_against = t["ga"]
        row.goal_diff = t["gf"] - t["ga"]
        row.as_of = now


def _simulate_tournament(
    db: Session, n_sims: int, strengths: dict[int, float] | None = None,
    params: ModelParams | None = None,
) -> int:
    """Run the full group→knockout Monte-Carlo and persist per-team round/title
    probabilities. Returns the number of teams with odds written."""
    params = params or load_params()
    groups: dict[str, list[int]] = {}
    fixtures: dict[str, list[KnockoutFixture]] = {}
    team_elos: dict[int, float] = {}
    strengths = strengths or {}
    all_members: list[Team] = []

    for group in db.query(Group).all():
        letter = group.name.split()[-1]  # "Group A" -> "A"
        members = [gt.team for gt in group.group_teams]
        all_members.extend(members)
        groups[letter] = [t.id for t in members]
        for t in members:
            team_elos[t.id] = strengths.get(t.id, estimate_strength(t)[0])
        fx: list[KnockoutFixture] = []
        for m in db.query(Match).filter_by(group_id=group.id).all():
            if m.team_home_id and m.team_away_id:
                home = db.get(Team, m.team_home_id)
                fx.append(KnockoutFixture(m.team_home_id, m.team_away_id,
                                          _host_adv(m, home, params.home_adv),
                                          score=_played_score(m)))
        fixtures[letter] = fx

    # Need the full 12-group structure to run the bracket; skip cleanly otherwise.
    if len(groups) < 12:
        return 0

    hosts = {t.name: t.id for t in db.query(Team).filter_by(is_host=True).all()}
    country_to_team = {"United States": hosts.get("United States"),
                       "Mexico": hosts.get("Mexico"),
                       "Canada": hosts.get("Canada")}
    ko_host_by_match: dict[int, int] = {}
    for m in db.query(Match).filter(Match.group_id.is_(None), Match.venue_country.isnot(None)).all():
        team_id = country_to_team.get(m.venue_country)
        if team_id is not None:
            ko_host_by_match[m.id] = team_id

    # Already-played knockout ties are facts: pin them so a finished match forces
    # its winner forward and its loser out in every draw (analogous to a played
    # group fixture's score). Keyed by official match number.
    from app.scoring import knockout_played_from_db

    ko_results = knockout_played_from_db(db)

    results = simulate_tournament(
        team_elos, groups, fixtures, n_sims=n_sims, seed=2026,
        base=params.base, beta=params.beta, rho=params.rho,
        pk_beta=params.pk_beta, et_tempo=params.et_tempo, home_adv=params.home_adv,
        ko_host_by_match=ko_host_by_match, ko_results=ko_results,
        # Combined xG team offsets + split form-channel offsets (model v2
        # C1) — see _simulate_standings' comment; same invariant, extended
        # to the full-tournament simulator.
        team_offsets=_combined_offsets_by_team_id(db, params, all_members),
    )
    now = datetime.now(timezone.utc)
    for team_id, r in results.items():
        row = db.query(TournamentOdds).filter_by(team_id=team_id).one_or_none()
        if row is None:
            row = TournamentOdds(team_id=team_id)
            db.add(row)
        row.make_knockout = r["make_knockout"]
        row.reach_r16 = r["reach_r16"]
        row.reach_qf = r["reach_qf"]
        row.reach_sf = r["reach_sf"]
        row.reach_final = r["reach_final"]
        row.win_title = r["win_title"]
        row.as_of = now
    return len(results)


def generate_predictions(
    db: Session,
    model_version: str | None = None,
    n_sims: int = 5000,
    tournament_sims: int = 2000,
) -> dict:
    """Predict every upcoming match with both teams set — all group fixtures plus
    any drawn knockout ties — simulate every group's standings, and run the
    full-tournament (knockout) Monte-Carlo.

    Engine parameters come from ml.models.params.load_params() — the tuned
    model_params.json if present, else the v0.1 constants. The served model
    version follows the loaded params (so v0.2 predictions are tagged v0.2)
    unless an explicit ``model_version`` is passed.
    """
    # Tournament-adjusted strengths (base Elo + conservative delta + capped
    # form) so match predictions and both simulations move together once the
    # learning loop has run. Falls back to base ratings when no state exists.
    from pipeline.learning_loop import effective_elos

    params = load_params()
    active_model_version = model_version or params.version
    strengths = effective_elos(db)

    booster = None
    if params.wdl_blend:
        from pipeline.backtest_data import build_enriched_rows
        from ml.features.training_rows import build_training_rows, training_weight
        from ml.models.wdl_boost import WdlBoost  # deferred: sklearn loads only when the blend ships

        train_rows = build_training_rows(build_enriched_rows(db))
        if train_rows:
            ref = max(r["date"] for r in train_rows)
            weights = [training_weight(r, ref) for r in train_rows]
            booster = WdlBoost().fit(train_rows, sample_weight=weights)

    # Every upcoming match with both teams set: all group fixtures plus any drawn
    # knockout ties. The official bracket links each tie to its match-detail page,
    # which needs a prediction, so KO matches must be predicted once their teams are
    # known (build_payload skips a teamless placeholder defensively anyway).
    matches = (
        db.query(Match)
        .filter(
            Match.status == "scheduled",
            Match.team_home_id.isnot(None),
            Match.team_away_id.isnot(None),
        )
        .all()
    )
    predicted = 0
    for match in matches:
        payload = build_payload(db, match, active_model_version,
                                strengths=strengths, params=params, booster=booster)
        if payload is None:
            continue
        _write_prediction(db, match, payload, active_model_version)
        # Shadow twin (FR-4.4): odds-anchored when a market total is stored and
        # w_odds > 0, otherwise an exact copy — either way never served.
        write_shadow_prediction(db, match, payload, strengths, params)
        write_availability_prediction(db, match, payload, strengths, params)
        write_offsets_prediction(db, match, payload, strengths, params)
        write_suspension_prediction(db, match, payload, strengths, params)
        write_rest_prediction(db, match, payload, strengths, params)
        predicted += 1

    groups = db.query(Group).all()
    for group in groups:
        _simulate_standings(db, group, active_model_version, n_sims, strengths=strengths, params=params)

    teams_simulated = _simulate_tournament(db, tournament_sims, strengths=strengths, params=params)

    db.commit()
    return {
        "matches_predicted": predicted,
        "groups_simulated": len(groups),
        "tournament_teams": teams_simulated,
    }
