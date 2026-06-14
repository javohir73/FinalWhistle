"""Guard tests for the FIFA rankings seed file (pipeline/data/fifa_rankings.csv).

The seed is the FIFA Men's World Ranking edition of 11 June 2026, restricted to
the 48 teams in the 2026 World Cup field (sources: en.wikipedia.org FIFA Men's
World Ranking + Bleacher Report, which agree on the full top 20). fifa_rank is a
secondary / cold-start signal — Elo is primary — but it is shown verbatim on team
pages, so these tests pin the data: a future edit can't silently drop a team,
duplicate a position, or introduce a name that doesn't resolve to the canonical
WC roster (which would leave that team's fifa_rank null in production).
"""
from __future__ import annotations

import json

from app.models import Team
from pipeline.ingest.fifa_rankings import DATA_DIR, apply_rankings, load_rankings_df
from pipeline.team_mapping import normalize_team_name

WC_TEAMS_JSON = DATA_DIR / "wc26_teams.json"


def _wc_team_names() -> set[str]:
    """Canonical names of the 48 WC2026 teams, straight from the structure seed."""
    data = json.loads(WC_TEAMS_JSON.read_text(encoding="utf-8"))
    return {t["name"] for t in data["teams"]}


def test_seed_csv_is_well_formed():
    df = load_rankings_df()
    assert {"team", "rank"} <= set(df.columns)
    assert len(df) == 48  # the full 48-team field, one row each
    ranks = [int(r) for r in df["rank"]]
    assert all(r > 0 for r in ranks)        # FIFA positions are 1-based
    assert len(set(ranks)) == len(ranks)    # no two teams share a position
    assert ranks == sorted(ranks)           # file kept in rank order for readability


def test_seed_covers_exactly_the_wc_field():
    df = load_rankings_df()
    seeded = {normalize_team_name(str(t)) for t in df["team"]}
    expected = _wc_team_names()
    # Every seeded name resolves to a canonical WC team, and every WC team is seeded.
    assert seeded == expected, {
        "missing_from_seed": sorted(expected - seeded),
        "unknown_in_seed": sorted(seeded - expected),
    }


def test_apply_populates_every_team_with_no_unmatched(db_session):
    """End-to-end: the real seed file, applied to the real roster, fills all 48."""
    db_session.add_all([Team(name=n) for n in _wc_team_names()])
    db_session.commit()

    summary = apply_rankings(db_session, load_rankings_df())

    assert summary["updated"] == 48
    assert summary["unmatched"] == []
    by_name = {t.name: t.fifa_rank for t in db_session.query(Team).all()}
    assert by_name["Argentina"] == 1
    assert by_name["South Africa"] == 60
    assert by_name["Curaçao"] == 82  # no alias entry — must match the cedilla spelling
