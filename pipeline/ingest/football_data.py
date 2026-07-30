"""Parse football-data.co.uk club-match CSVs (docs/ROADMAP-ENGINE.md, Phase 1).

football-data.co.uk publishes free, per-league CSVs for the major club
divisions (E0 = Premier League, etc.). Each row is one match with full-time
goals/result plus a wide block of bookmaker odds columns.

Phase 1 generalises the WC26 engine to club football and asks the same
commercial question as Phase 0: does the model beat the CLOSING line? So this
parser prefers the CLOSING-odds columns and, per row, keeps only clean data —
present integer scores and three decimal odds each > 1.0. Malformed rows are
logged and skipped, never fatal.

Pure module — no DB, no network, no app imports. Orchestration lives in
pipeline/run_club_benchmark.py.

Closing vs pre-closing — the publisher's own rule
-------------------------------------------------
football-data.co.uk's notes.txt states it plainly: the documented odds
abbreviations "are for pre-closing odds. For the closing odds, as below but
with an additional 'C' character following the bookmaker abbreviation/Max/Avg
(e.g. B365CH = closing Bet365 home win odds)."

So the ``C`` is the whole distinction, and a family without one is **not** a
closing line. This module therefore records ``odds_basis`` on every record and
**refuses by default** to answer a closing-line question with pre-closing
prices. Passing ``require_basis="any"`` opts in explicitly and the records say
so; nothing silently substitutes (docs/experiments/2026-07-29-d0-market-
validation/PRE-REGISTRATION.md, A2).

Column reference (football-data.co.uk notes.txt):
  FTHG/FTAG  full-time home/away goals        FTR  full-time result (H/D/A)
  AvgC*      market-average CLOSING odds      PSC* Pinnacle CLOSING odds
  B365C*     Bet365 CLOSING odds              MaxC* market-maximum CLOSING odds
  Avg*/B365* the same books' PRE-CLOSING odds
"""
from __future__ import annotations

import logging
from typing import Literal, NamedTuple

import pandas as pd

log = logging.getLogger(__name__)

#: Where the captures come from. Duplicated deliberately from
#: ``pipeline.ingest.club_results.BASE_URL`` rather than imported: that module
#: pulls in ``app.db`` and builds a live SQLAlchemy engine at import time, which
#: would make this pure parser — and the offline census built on it — fail on a
#: machine with no database configured. A test pins the two strings equal.
DOWNLOAD_URL_TEMPLATE = "https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"

#: Provider provenance, carried onto every benchmark this module feeds
#: (D0 acceptance criterion A3). Lives here, next to the parser, so a caller
#: cannot report a number from these files without the terms attached.
#:
#: Licence position, verified on the publisher's own pages 2026-07-29: the site
#: says "Simply download for free the available files" and footers every page
#: with "© Football-Data. Liability Disclaimer. All Rights Reserved." Free
#: download is granted; **no redistribution grant appears anywhere on the
#: site** — hence stop gate G1 in docs/DATA-VALIDATION-PROGRAM.md, and hence
#: fingerprints in the repo rather than bytes.
PROVIDER = {
    "provider": "football-data.co.uk",
    "url": "https://www.football-data.co.uk/",
    "download_url_template": DOWNLOAD_URL_TEMPLATE,
    "column_notes_url": "https://www.football-data.co.uk/notes.txt",
    "cost": "free — no key, no account, no quota",
    "licence": "© Football-Data. All Rights Reserved. Free download granted; "
    "no redistribution grant published.",
    "redistribution": "NOT GRANTED — fingerprints are committed, bytes are not",
    "attribution": "Data © football-data.co.uk",
    # The publisher's own closing rule, quoted from notes.txt. It is the whole
    # basis on which a family is called closing or pre-closing.
    "closing_rule": 'notes.txt: documented odds abbreviations "are for '
    'pre-closing odds. For the closing odds, as below but with an additional '
    '\\"C\\" character following the bookmaker abbreviation/Max/Avg".',
    # One row per finished match, no capture time. "Closing" is a publisher
    # claim about a column family, not an observation this repo made, so the
    # strictly-pre-kickoff rule that governs live capture cannot be checked here.
    "timestamp_semantics": "no per-price timestamp; basis is a publisher "
    "column-family claim, not an observed capture time",
}

#: ``odds_basis`` values. "closing" is the publisher's ``C``-suffixed family;
#: "pre_closing" is everything else. There is no third state — a family is one
#: or the other by the publisher's documented rule.
OddsBasis = Literal["closing", "pre_closing"]


class OddsFamily(NamedTuple):
    """One 1X2 odds column-triple, with what the publisher says it means."""

    key: str  # shared prefix, recorded as odds_source (e.g. "AvgC")
    columns: tuple[str, str, str]  # (home, draw, away)
    basis: OddsBasis
    bookmaker: str  # human label from the publisher's notes.txt


class ClosingOddsUnavailable(ValueError):
    """A closing family was required and the file has none.

    Raised rather than falling through to pre-closing prices. Callers that
    legitimately want a pre-closing series ask for it (``require_basis="any"``);
    callers benchmarking a *closing* line catch this and **abstain**, naming the
    file — they never quietly score a different market.
    """


#: Ordered preference of 1X2 odds families. CLOSING families come first (the
#: roadmap benchmarks vs the closing line); pre-closing families are reachable
#: only under ``require_basis="any"``.
#:
#: Public, because pipeline/market_coverage.py censuses exactly these families
#: and a second copy of the table would drift from this one.
ODDS_FAMILIES: tuple[OddsFamily, ...] = (
    OddsFamily("AvgC", ("AvgCH", "AvgCD", "AvgCA"), "closing", "market average"),
    OddsFamily("PSC", ("PSCH", "PSCD", "PSCA"), "closing", "Pinnacle"),
    OddsFamily("B365C", ("B365CH", "B365CD", "B365CA"), "closing", "Bet365"),
    OddsFamily("MaxC", ("MaxCH", "MaxCD", "MaxCA"), "closing", "market maximum"),
    OddsFamily("Avg", ("AvgH", "AvgD", "AvgA"), "pre_closing", "market average"),
    OddsFamily("B365", ("B365H", "B365D", "B365A"), "pre_closing", "Bet365"),
)

CLOSING_FAMILIES: tuple[OddsFamily, ...] = tuple(
    f for f in ODDS_FAMILIES if f.basis == "closing"
)


def available_families(columns) -> tuple[OddsFamily, ...]:
    """Every family in :data:`ODDS_FAMILIES` fully present in ``columns``.

    Preference order preserved. Used by the coverage census to describe a file
    rather than just pick from it.
    """
    present = set(columns)
    return tuple(f for f in ODDS_FAMILIES if all(c in present for c in f.columns))


def select_odds_family(
    columns, require_basis: Literal["closing", "any"] = "closing"
) -> OddsFamily:
    """Pick the preferred family present in ``columns``.

    ``require_basis="closing"`` (the default) considers only ``C``-suffixed
    families and raises :class:`ClosingOddsUnavailable` if the file has none.
    ``"any"`` walks the full chain and may return a pre-closing family — whose
    ``basis`` then says so on every record it produces.
    """
    found = available_families(columns)
    if require_basis == "closing":
        closing = [f for f in found if f.basis == "closing"]
        if not closing:
            raise ClosingOddsUnavailable(
                "no CLOSING odds columns in CSV header; expected one of "
                + ", ".join(f.key for f in CLOSING_FAMILIES)
                + (
                    "; pre-closing families present: "
                    + ", ".join(f.key for f in found)
                    if found
                    else "; no recognised odds columns at all"
                )
                + ". Pass require_basis='any' to accept pre-closing prices."
            )
        return closing[0]
    if not found:
        raise ValueError(
            "no recognised odds columns in CSV header; expected one of "
            + ", ".join(f.key for f in ODDS_FAMILIES)
        )
    return found[0]


class TotalsOddsFamily(NamedTuple):
    """One over/under column PAIR, with what the publisher says it means."""

    key: str  # shared prefix, recorded as odds_source (e.g. "AvgC")
    columns: tuple[str, str]  # (over, under) — ORDER IS LOAD-BEARING
    basis: OddsBasis
    bookmaker: str
    line: float  # the goals line these columns price


class ClosingTotalsUnavailable(ValueError):
    """A closing totals family was required and the file has none.

    The over/under analogue of :class:`ClosingOddsUnavailable`, and separate
    from it because the two markets abstain on *different* files: all 27 club
    captures carry a closing 1X2 family, but the nine 2016-17..2018-19 files
    carry no closing totals family at all.
    """


#: Ordered preference of over/under 2.5 families, closing first. Mirrors
#: :data:`ODDS_FAMILIES` so the totals benchmark and the 1X2 benchmark score
#: the same book wherever both exist — ``AvgC`` leads both tables.
#:
#: **Pinnacle's totals prefix is ``PC``, not ``PSC``.** The 1X2 columns are
#: ``PSCH/PSCD/PSCA`` but the totals columns are ``PC>2.5``/``PC<2.5``. The
#: publisher is inconsistent here; this table follows the file, not the
#: pattern.
#:
#: **Betbrain (``BbAv``/``BbMx``) is deliberately absent.** The nine
#: 2016-17..2018-19 captures carry ``BbMx>2.5``, ``BbAv>2.5``, ``BbMx<2.5``
#: and ``BbAv<2.5`` — pre-closing prices, and the *only* over/under columns
#: those files have. Admitting them would widen the sample by ~50% with rows
#: that are pre-closing to a market this program benchmarks as closing: D0's
#: founding defect, re-entered through the totals door. They stay out, the
#: nine files abstain, and a test pins that abstention so including them later
#: requires a visible change to this table rather than a drifting default.
TOTALS_FAMILIES: tuple[TotalsOddsFamily, ...] = (
    TotalsOddsFamily("AvgC", ("AvgC>2.5", "AvgC<2.5"), "closing", "market average", 2.5),
    TotalsOddsFamily("PC", ("PC>2.5", "PC<2.5"), "closing", "Pinnacle", 2.5),
    TotalsOddsFamily("B365C", ("B365C>2.5", "B365C<2.5"), "closing", "Bet365", 2.5),
    TotalsOddsFamily("MaxC", ("MaxC>2.5", "MaxC<2.5"), "closing", "market maximum", 2.5),
    TotalsOddsFamily("Avg", ("Avg>2.5", "Avg<2.5"), "pre_closing", "market average", 2.5),
    TotalsOddsFamily("B365", ("B365>2.5", "B365<2.5"), "pre_closing", "Bet365", 2.5),
)

CLOSING_TOTALS_FAMILIES: tuple[TotalsOddsFamily, ...] = tuple(
    f for f in TOTALS_FAMILIES if f.basis == "closing"
)


def available_totals_families(columns) -> tuple[TotalsOddsFamily, ...]:
    """Every family in :data:`TOTALS_FAMILIES` fully present in ``columns``.

    Preference order preserved. Returns ``()`` for a file whose only over/under
    columns are Betbrain's — by design; see :data:`TOTALS_FAMILIES`.
    """
    present = set(columns)
    return tuple(f for f in TOTALS_FAMILIES if all(c in present for c in f.columns))


def select_totals_family(
    columns, require_basis: Literal["closing", "any"] = "closing"
) -> TotalsOddsFamily:
    """Pick the preferred over/under family present in ``columns``.

    Closing-only by default, raising :class:`ClosingTotalsUnavailable` rather
    than answering a closing-line question with pre-closing prices.
    """
    found = available_totals_families(columns)
    if require_basis == "closing":
        closing = [f for f in found if f.basis == "closing"]
        if not closing:
            raise ClosingTotalsUnavailable(
                "no CLOSING over/under columns in CSV header; expected one of "
                + ", ".join(f.key for f in CLOSING_TOTALS_FAMILIES)
                + (
                    "; pre-closing families present: " + ", ".join(f.key for f in found)
                    if found
                    else "; no recognised over/under columns at all"
                )
                + ". Pass require_basis='any' to accept pre-closing prices."
            )
        return closing[0]
    if not found:
        raise ValueError(
            "no recognised over/under columns in CSV header; expected one of "
            + ", ".join(f.key for f in TOTALS_FAMILIES)
        )
    return found[0]


def load_football_data_totals_csv(
    path: str,
    normalize=str.strip,
    require_basis: Literal["closing", "any"] = "closing",
) -> list[dict]:
    """Load a football-data.co.uk CSV into join-ready OVER/UNDER records.

    The over/under sibling of :func:`load_football_data_csv`, with identical
    row-level discipline: day-first dates, present integer scores, and both
    prices decimal and > 1.0, NaN rejected before the bound.

    That NaN-before-bound ordering is not stylistic. ``D1_1920.csv`` line 261
    (``FC Koln 2-4 RB Leipzig``, a realized Over) carries ``AvgC>2.5 = 0.42``,
    which is not a decimal price at all; de-vigged it would read as
    ``p_over = 0.871`` and score as one of the market's best calls of the
    decade. The same row prices sanely under ``PC``, and is still dropped —
    families are selected per FILE, never per row, or the market series ends up
    composed of whichever book happened to be clean on the rows the publisher
    got wrong.

    Returns a list of dicts with keys: date (datetime.date), home_team,
    away_team, home_score (int), away_score (int), odds_over, odds_under
    (float), line (float), odds_source (str), odds_basis
    ("closing"/"pre_closing"), odds_bookmaker (str).
    """
    df = pd.read_csv(path)
    family = select_totals_family(df.columns, require_basis=require_basis)
    over_col, under_col = family.columns

    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")

    records: list[dict] = []
    for i, row in df.iterrows():
        line = i + 2  # +1 for 0-index, +1 for the header row
        parsed_date = dates.iloc[i]
        if pd.isna(parsed_date):
            log.warning("skipping row %d: unparseable date %r", line, row.get("Date"))
            continue
        try:
            home_score = int(row["FTHG"])
            away_score = int(row["FTAG"])
        except (KeyError, TypeError, ValueError):
            log.warning("skipping row %d: missing/invalid score", line)
            continue

        try:
            odds_over = float(row[over_col])
            odds_under = float(row[under_col])
        except (KeyError, TypeError, ValueError):
            log.warning("skipping row %d: missing/invalid %s totals odds", line, family.key)
            continue
        if any(x != x for x in (odds_over, odds_under)):
            log.warning("skipping row %d: blank %s totals odds", line, family.key)
            continue
        if min(odds_over, odds_under) <= 1.0:
            log.warning(
                "skipping row %d: %s totals odds not all > 1.0 (%r/%r)",
                line, family.key, odds_over, odds_under,
            )
            continue

        records.append(
            {
                "date": parsed_date.date(),
                "home_team": normalize(str(row["HomeTeam"])),
                "away_team": normalize(str(row["AwayTeam"])),
                "home_score": home_score,
                "away_score": away_score,
                "odds_over": odds_over,
                "odds_under": odds_under,
                "line": family.line,
                "odds_source": family.key,
                "odds_basis": family.basis,
                "odds_bookmaker": family.bookmaker,
            }
        )
    return records


def load_football_data_csv(
    path: str,
    normalize=str.strip,
    require_basis: Literal["closing", "any"] = "closing",
) -> list[dict]:
    """Load a football-data.co.uk CSV into join-ready match records.

    Chooses the preferred odds family present in the header via
    :func:`select_odds_family` — **closing-only by default**, which raises
    :class:`ClosingOddsUnavailable` on a file that carries none rather than
    answering with pre-closing prices. Parses the Date column day-first, and
    keeps only rows with present integer scores and three decimal odds each
    > 1.0. Team names pass through ``normalize`` (default ``str.strip`` — club
    names must NOT go through the national-team mapper, which could mangle
    them). Rows are returned in file order; sorting is the caller's job.

    Returns a list of dicts with keys: date (datetime.date), home_team,
    away_team, home_score (int), away_score (int), odds_home, odds_draw,
    odds_away (float), odds_source (str, e.g. "AvgC"), odds_basis
    ("closing"/"pre_closing"), odds_bookmaker (str).
    """
    df = pd.read_csv(path)
    family = select_odds_family(df.columns, require_basis=require_basis)
    home_col, draw_col, away_col = family.columns

    # Day-first covers DD/MM/YY and DD/MM/YYYY; to_datetime also accepts ISO.
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")

    records: list[dict] = []
    for i, row in df.iterrows():
        line = i + 2  # +1 for 0-index, +1 for the header row
        parsed_date = dates.iloc[i]
        if pd.isna(parsed_date):
            log.warning("skipping row %d: unparseable date %r", line, row.get("Date"))
            continue
        try:
            home_score = int(row["FTHG"])
            away_score = int(row["FTAG"])
        except (KeyError, TypeError, ValueError):
            log.warning("skipping row %d: missing/invalid score", line)
            continue

        try:
            odds_home = float(row[home_col])
            odds_draw = float(row[draw_col])
            odds_away = float(row[away_col])
        except (KeyError, TypeError, ValueError):
            log.warning("skipping row %d: missing/invalid %s odds", line, family.key)
            continue
        # NaN first: `float("nan")` does not raise above, and every comparison
        # against NaN is False — so `min(nan, ...) <= 1.0` is False and a blank
        # price used to survive both guards. Downstream that scored as a
        # PERFECT market prediction on a match the book never priced.
        if any(x != x for x in (odds_home, odds_draw, odds_away)):
            log.warning("skipping row %d: blank %s odds", line, family.key)
            continue
        if min(odds_home, odds_draw, odds_away) <= 1.0:
            log.warning("skipping row %d: %s odds not all > 1.0", line, family.key)
            continue

        records.append(
            {
                "date": parsed_date.date(),
                "home_team": normalize(str(row["HomeTeam"])),
                "away_team": normalize(str(row["AwayTeam"])),
                "home_score": home_score,
                "away_score": away_score,
                "odds_home": odds_home,
                "odds_draw": odds_draw,
                "odds_away": odds_away,
                "odds_source": family.key,
                "odds_basis": family.basis,
                "odds_bookmaker": family.bookmaker,
            }
        )
    return records
