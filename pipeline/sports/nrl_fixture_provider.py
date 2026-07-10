"""Fixture-backed StatsProvider for tests and local dev (Wave 3).

Returns literal, hand-recorded fixture data supplied at construction time —
never makes an HTTP call. Used by pipeline/sports/nrl_team_lists_test.py's
ingest_round tests; later Wave 3 tasks (live poller tests) also use it.

Payload/protocol types are the real, frozen contract in
pipeline.sports.nrl_stats — this module does not redefine them.
"""
from __future__ import annotations

from pipeline.sports.nrl_stats import LivePayload, MatchStatsPayload, TeamListEntry


class RecordedFixtureStatsProvider:
    """StatsProvider backed by literal fixture dicts supplied at construction.

    With no fixtures configured it safely no-ops (matching
    NrlComStatsProvider's honest-empty/None behavior for fetch_team_list /
    fetch_live).
    """

    def __init__(
        self,
        team_lists: dict[tuple[int, int], list[TeamListEntry]] | None = None,
        live: dict[tuple[int, int, int], LivePayload] | None = None,
    ) -> None:
        self._team_lists = team_lists or {}
        self._live = live or {}

    def fetch_match_stats(self, season: int, round_no: int, match_no: int) -> MatchStatsPayload | None:
        return None  # not this wave's concern

    def fetch_team_list(self, season: int, round_no: int) -> list[TeamListEntry]:
        return list(self._team_lists.get((season, round_no), []))

    def fetch_live(self, season: int, round_no: int, match_no: int) -> LivePayload | None:
        return self._live.get((season, round_no, match_no))
