"""Deterministic cross-provider match identity for validation sources.

Kept DELIBERATELY LOCAL rather than writing `entity_source_map`. That table has
an unmerged resolver in flight (#203); a second writer with different
confidence semantics and verification conventions would collide the moment it
lands. This module owns an explicit alias table and a pure matching rule, and
persists its result only on the validation rows themselves.

If the identity rule here ever proves insufficient without shared entity
state, the correct move is to STOP and report, not to invent a competing
convention.

Matching rule (deterministic, no fuzzy scoring):
  1. Both raw labels must map to a canonical club via `ALIASES` (exact match on
     a casefolded, punctuation-stripped key). An unmapped label yields no match
     and is reported -- never guessed.
  2. A candidate Match must share BOTH canonical clubs in the same orientation.
  3. Its kickoff must fall within `KICKOFF_TOLERANCE` of the observation's.
     Broadcasters move kick-offs by hours; a day-level window would risk
     colliding with the reverse fixture, so the window is deliberately tight.
  4. Exactly one candidate must survive. Zero -> unmatched. More than one ->
     ambiguous, which is reported as a conflict rather than resolved.

Pure module: no DB writes, no network.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: Kick-offs drift with TV scheduling; the reverse fixture is months away, so a
#: 36-hour window is safely inside "same fixture, moved" territory.
KICKOFF_TOLERANCE = timedelta(hours=36)

#: Canonical spellings are OUR names (football-data.co.uk D1 lineage, the same
#: universe pipeline/team_mapping.py normalizes club rows into).
_CANONICAL = (
    "Bayern Munich", "Dortmund", "RB Leipzig", "Leverkusen", "Ein Frankfurt",
    "Stuttgart", "Werder Bremen", "Freiburg", "Hoffenheim", "Wolfsburg",
    "M'gladbach", "Mainz", "Augsburg", "Union Berlin", "Heidenheim",
    "St Pauli", "Holstein Kiel", "Bochum", "Hertha", "Schalke 04", "Koln",
    "Darmstadt", "Hamburg", "Nurnberg", "Fortuna Dusseldorf", "Paderborn",
    "Greuther Furth", "Bielefeld", "SV Elversberg", "Karlsruhe",
)


def _key(label: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", label or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[.\-_'`]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _build_aliases() -> dict[str, str]:
    """Explicit alias table: provider spelling -> our canonical club.

    Every entry is written out. Nothing is inferred at runtime, so adding a
    provider means adding rows here and seeing the unmatched report shrink --
    never a silent near-miss.
    """
    spellings: dict[str, tuple[str, ...]] = {
        "Bayern Munich": ("FC Bayern München", "Bayern München", "FC Bayern Munchen",
                          "Bayern Munchen", "FC Bayern", "Bayern"),
        "Dortmund": ("Borussia Dortmund", "BV Borussia 09 Dortmund", "BVB",
                     "Bor. Dortmund"),
        "RB Leipzig": ("RasenBallsport Leipzig", "RB Leipzig", "Rasenballsport Leipzig"),
        "Leverkusen": ("Bayer 04 Leverkusen", "Bayer Leverkusen", "Bayer 04"),
        "Ein Frankfurt": ("Eintracht Frankfurt", "SG Eintracht Frankfurt",
                          "Eint Frankfurt"),
        "Stuttgart": ("VfB Stuttgart", "VfB Stuttgart 1893"),
        "Werder Bremen": ("SV Werder Bremen", "Werder Bremen"),
        "Freiburg": ("SC Freiburg", "Sport-Club Freiburg"),
        "Hoffenheim": ("TSG 1899 Hoffenheim", "TSG Hoffenheim", "1899 Hoffenheim"),
        "Wolfsburg": ("VfL Wolfsburg",),
        "M'gladbach": ("Borussia Mönchengladbach", "Borussia Monchengladbach",
                       "Bor. Mönchengladbach", "Bor. Monchengladbach",
                       "Mönchengladbach", "Monchengladbach", "Gladbach"),
        "Mainz": ("1. FSV Mainz 05", "FSV Mainz 05", "Mainz 05"),
        "Augsburg": ("FC Augsburg",),
        "Union Berlin": ("1. FC Union Berlin", "FC Union Berlin"),
        "Heidenheim": ("1. FC Heidenheim 1846", "FC Heidenheim", "1. FC Heidenheim"),
        "St Pauli": ("FC St. Pauli", "St. Pauli", "FC St Pauli"),
        "Holstein Kiel": ("Holstein Kiel", "KSV Holstein Kiel"),
        "Bochum": ("VfL Bochum 1848", "VfL Bochum"),
        "Hertha": ("Hertha BSC", "Hertha Berlin", "Hertha BSC Berlin"),
        "Schalke 04": ("FC Schalke 04", "Schalke"),
        "Koln": ("1. FC Köln", "1. FC Koln", "FC Köln", "FC Koln", "Köln", "Cologne"),
        "Darmstadt": ("SV Darmstadt 98", "Darmstadt 98"),
        "Hamburg": ("Hamburger SV", "Hamburg SV", "HSV"),
        "Nurnberg": ("1. FC Nürnberg", "1. FC Nurnberg", "Nürnberg"),
        "Fortuna Dusseldorf": ("Fortuna Düsseldorf", "Fortuna Dusseldorf",
                               "F. Düsseldorf"),
        "Paderborn": ("SC Paderborn 07", "SC Paderborn"),
        "Greuther Furth": ("SpVgg Greuther Fürth", "SpVgg Greuther Furth",
                           "Greuther Fürth"),
        "Bielefeld": ("DSC Arminia Bielefeld", "Arminia Bielefeld"),
        "SV Elversberg": ("SV 07 Elversberg", "SV Elversberg", "Elversberg"),
        "Karlsruhe": ("Karlsruher SC", "Karlsruher SC"),
    }
    table: dict[str, str] = {}
    for canonical, variants in spellings.items():
        table[_key(canonical)] = canonical
        for v in variants:
            table[_key(v)] = canonical
    return table


ALIASES: dict[str, str] = _build_aliases()


def canonical_club(label: str) -> str | None:
    """Canonical club for a provider spelling, or None if unmapped.

    None is a first-class outcome: it lands in the unmatched report so a
    missing alias is visible, instead of being papered over by a fuzzy guess.
    """
    return ALIASES.get(_key(label))


def _aware(dt):
    """Treat any datetime as UTC.

    Candidate kick-offs come from the DB (naive under SQLite, aware under
    Postgres) while observation kick-offs are parsed from provider ISO strings
    (always aware). Normalizing here keeps the comparison total instead of
    raising on one backend and not the other.
    """
    if dt is None or not isinstance(dt, datetime):
        return dt
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class MatchCandidate:
    """The minimum a caller must supply about one of our Match rows."""

    match_id: int
    canonical_home: str | None
    canonical_away: str | None
    kickoff_utc: object  # datetime; typed loosely so the module stays DB-free


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one observation. `status` drives the report."""

    canonical_home: str | None
    canonical_away: str | None
    match_id: int | None
    status: str  # matched | unmatched | conflict
    note: str | None = None


def resolve(raw_home: str, raw_away: str, kickoff_utc,
            candidates: list[MatchCandidate]) -> Resolution:
    """Deterministically resolve one provider observation to a Match, or not."""
    home, away = canonical_club(raw_home), canonical_club(raw_away)
    if home is None or away is None:
        missing = [lbl for lbl, c in ((raw_home, home), (raw_away, away)) if c is None]
        return Resolution(home, away, None, "unmatched",
                          f"no alias for {missing!r}; add it to identity.ALIASES")
    if kickoff_utc is None:
        return Resolution(home, away, None, "unmatched", "observation has no kickoff")

    target = _aware(kickoff_utc)
    hits = [
        c for c in candidates
        if c.canonical_home == home and c.canonical_away == away
        and c.kickoff_utc is not None
        and abs(_aware(c.kickoff_utc) - target) <= KICKOFF_TOLERANCE
    ]
    if not hits:
        return Resolution(home, away, None, "unmatched",
                          f"no Match for {home} v {away} within "
                          f"{KICKOFF_TOLERANCE} of {kickoff_utc}")
    if len(hits) > 1:
        return Resolution(home, away, None, "conflict",
                          f"ambiguous: {len(hits)} candidate matches "
                          f"({[c.match_id for c in hits]}) -- not resolved")
    return Resolution(home, away, hits[0].match_id, "matched")
