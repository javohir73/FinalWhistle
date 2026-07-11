"""Canonical State of Origin team names (design 2026-07-11).

The two data sources disagree on naming (fixturedownload: "Blues"/"Maroons";
TheSportsDB: "New South Wales Blues"/"Queensland Maroons"). Everything is
mapped to the canonical pair below BEFORE any DB write so the sources can
never create duplicate SportTeam rows. Unknown names are absent from the map
on purpose — callers treat a miss as malformed data, not a new team.
"""
from __future__ import annotations

NSW = "NSW Blues"
QLD = "QLD Maroons"

CANONICAL: dict[str, str] = {
    "Blues": NSW,
    "New South Wales Blues": NSW,
    "New South Wales": NSW,
    "NSW": NSW,
    NSW: NSW,
    "Maroons": QLD,
    "Queensland Maroons": QLD,
    "Queensland": QLD,
    "QLD": QLD,
    QLD: QLD,
}

# Stable indices for DB-free replay (ml.sports.origin.backtest).
TEAM_INDEX: dict[str, int] = {NSW: 0, QLD: 1}
