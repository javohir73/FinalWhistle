"""Adapters for the independent validation sources.

Each adapter is split in two: a PURE parser over an already-fetched payload,
and a best-effort fetcher. Everything the tests care about lives in the parser,
so the whole module is exercisable with zero credentials and zero network.

Sources
  football_data_org  fixtures/results, competition BL1. Free tier. Key via
                     FOOTBALL_DATA_API_KEY.
  openligadb         fixtures/results, league bl1. Free, NO key.
  the_odds_api       pre-match 1X2. Key via ODDS_API_KEY. Historical endpoints
                     are a PAID add-on -- nothing here purchases anything.
  betfair_historical IMPORTER ONLY. Reads an archive the operator downloaded
                     themselves. Never logs in, never fetches, never touches a
                     betting account.

Contract for every fetcher: unconfigured, timed-out, rate-limited or malformed
returns an empty result and a reason. It never raises, so a dead source can
never affect a production or shadow write.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

FOOTBALL_DATA_ENV = "FOOTBALL_DATA_API_KEY"
ODDS_API_ENV = "ODDS_API_KEY"

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
OPENLIGADB_BASE = "https://api.openligadb.de"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

#: Bundesliga only. Pooling EPL/La Liga/lower divisions is forbidden, so the
#: competition code is fixed rather than parameterised.
COMPETITION = "BL1"
_TIMEOUT = 20


def _sha256(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class FixtureObservation:
    source: str
    source_event_id: str
    competition_code: str
    season: str | None
    kickoff_utc: datetime | None
    raw_home_label: str
    raw_away_label: str
    status: str | None
    score_home: int | None
    score_away: int | None
    source_updated_at: datetime | None
    payload_sha256: str


@dataclass
class MarketObservation:
    source: str
    source_market_id: str
    source_event_id: str | None
    competition_code: str
    kickoff_utc: datetime | None
    raw_home_label: str
    raw_away_label: str
    bookmaker_key: str
    outcome: str
    price_decimal: float | None
    captured_at: datetime
    payload_sha256: str
    archive_sha256: str | None = None
    acquisition_note: str | None = None


@dataclass
class FetchResult:
    """Never an exception. `reason` explains an empty list."""

    ok: bool
    items: list = field(default_factory=list)
    reason: str | None = None


# --- football-data.org ------------------------------------------------------

def parse_football_data_org(payload: dict) -> list[FixtureObservation]:
    """Parse a /v4/competitions/BL1/matches payload. Malformed rows are skipped."""
    out = []
    for m in (payload or {}).get("matches") or []:
        try:
            mid = m.get("id")
            home = ((m.get("homeTeam") or {}).get("name") or "").strip()
            away = ((m.get("awayTeam") or {}).get("name") or "").strip()
            if mid is None or not home or not away:
                continue
            ft = ((m.get("score") or {}).get("fullTime")) or {}
            out.append(FixtureObservation(
                source="football_data_org", source_event_id=str(mid),
                competition_code=COMPETITION,
                season=str(((m.get("season") or {}).get("startDate") or ""))[:4] or None,
                kickoff_utc=_parse_dt(m.get("utcDate")),
                raw_home_label=home, raw_away_label=away,
                status=(m.get("status") or "").lower() or None,
                score_home=ft.get("home"), score_away=ft.get("away"),
                source_updated_at=_parse_dt(m.get("lastUpdated")),
                payload_sha256=_sha256(m),
            ))
        except (AttributeError, TypeError, ValueError) as exc:
            log.warning("football_data_org: skipping malformed match: %s", exc)
    return out


def fetch_football_data_org(season: int, *, api_key: str | None = None,
                            requests_mod=None) -> FetchResult:
    key = api_key if api_key is not None else os.getenv(FOOTBALL_DATA_ENV, "")
    if not key:
        return FetchResult(False, [], f"{FOOTBALL_DATA_ENV} not configured")
    try:
        import requests as _r
        r = (requests_mod or _r).get(
            f"{FOOTBALL_DATA_BASE}/competitions/{COMPETITION}/matches",
            headers={"X-Auth-Token": key}, params={"season": season},
            timeout=_TIMEOUT)
        if getattr(r, "status_code", 0) == 429:
            return FetchResult(False, [], "rate limited (429)")
        if getattr(r, "status_code", 0) != 200:
            return FetchResult(False, [], f"http {getattr(r, 'status_code', '?')}")
        return FetchResult(True, parse_football_data_org(r.json()))
    except Exception as exc:  # noqa: BLE001 - a dead source must never propagate
        return FetchResult(False, [], f"{type(exc).__name__}: {exc}")


# --- OpenLigaDB -------------------------------------------------------------

def parse_openligadb(payload: list) -> list[FixtureObservation]:
    """Parse /getmatchdata/bl1/{season}. No key required by this provider."""
    out = []
    for m in payload or []:
        try:
            mid = m.get("matchID")
            home = ((m.get("team1") or {}).get("teamName") or "").strip()
            away = ((m.get("team2") or {}).get("teamName") or "").strip()
            if mid is None or not home or not away:
                continue
            sh = sa = None
            for res in m.get("matchResults") or []:
                # resultTypeID 2 = final result; 1 = half time.
                if res.get("resultTypeID") == 2:
                    sh, sa = res.get("pointsTeam1"), res.get("pointsTeam2")
            out.append(FixtureObservation(
                source="openligadb", source_event_id=str(mid),
                competition_code=COMPETITION,
                season=str(m.get("leagueSeason") or "") or None,
                kickoff_utc=_parse_dt(m.get("matchDateTimeUTC")),
                raw_home_label=home, raw_away_label=away,
                status="finished" if m.get("matchIsFinished") else "scheduled",
                score_home=sh, score_away=sa,
                source_updated_at=_parse_dt(m.get("lastUpdateDateTime")),
                payload_sha256=_sha256(m),
            ))
        except (AttributeError, TypeError, ValueError) as exc:
            log.warning("openligadb: skipping malformed match: %s", exc)
    return out


def fetch_openligadb(season: int, *, requests_mod=None) -> FetchResult:
    try:
        import requests as _r
        r = (requests_mod or _r).get(
            f"{OPENLIGADB_BASE}/getmatchdata/bl1/{season}", timeout=_TIMEOUT)
        if getattr(r, "status_code", 0) == 429:
            return FetchResult(False, [], "rate limited (429)")
        if getattr(r, "status_code", 0) != 200:
            return FetchResult(False, [], f"http {getattr(r, 'status_code', '?')}")
        return FetchResult(True, parse_openligadb(r.json()))
    except Exception as exc:  # noqa: BLE001
        return FetchResult(False, [], f"{type(exc).__name__}: {exc}")


# --- The Odds API -----------------------------------------------------------

_ODDS_OUTCOME = {"home": "home", "draw": "draw", "away": "away"}


def parse_odds_api(payload: list) -> list[MarketObservation]:
    """Parse /v4/sports/soccer_germany_bundesliga/odds (h2h market).

    One row per (event, bookmaker, outcome). `captured_at` is the BOOKMAKER's
    own last_update, never our retrieval time -- admissibility is judged on
    when the price existed, not when we asked for it.
    """
    out = []
    for ev in payload or []:
        try:
            eid = ev.get("id")
            home = (ev.get("home_team") or "").strip()
            away = (ev.get("away_team") or "").strip()
            if not eid or not home or not away:
                continue
            kickoff = _parse_dt(ev.get("commence_time"))
            for bk in ev.get("bookmakers") or []:
                bkey = (bk.get("key") or "").strip()
                captured = _parse_dt(bk.get("last_update"))
                if not bkey or captured is None:
                    continue
                for mk in bk.get("markets") or []:
                    if mk.get("key") != "h2h":
                        continue
                    for oc in mk.get("outcomes") or []:
                        name = (oc.get("name") or "").strip()
                        if name == home:
                            side = "home"
                        elif name == away:
                            side = "away"
                        elif name.lower() == "draw":
                            side = "draw"
                        else:
                            continue
                        price = oc.get("price")
                        out.append(MarketObservation(
                            source="the_odds_api",
                            source_market_id=f"{eid}:{bkey}:h2h",
                            source_event_id=str(eid), competition_code=COMPETITION,
                            kickoff_utc=kickoff, raw_home_label=home,
                            raw_away_label=away, bookmaker_key=bkey,
                            outcome=_ODDS_OUTCOME[side],
                            price_decimal=float(price) if price else None,
                            captured_at=captured, payload_sha256=_sha256(oc),
                        ))
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            log.warning("the_odds_api: skipping malformed event: %s", exc)
    return out


def fetch_odds_api(*, api_key: str | None = None, requests_mod=None) -> FetchResult:
    """Pre-match 1X2 only. Historical endpoints are a PAID add-on and are not
    called here -- this never spends money."""
    key = api_key if api_key is not None else os.getenv(ODDS_API_ENV, "")
    if not key:
        return FetchResult(False, [], f"{ODDS_API_ENV} not configured")
    try:
        import requests as _r
        r = (requests_mod or _r).get(
            f"{ODDS_API_BASE}/sports/soccer_germany_bundesliga/odds",
            params={"apiKey": key, "regions": "eu", "markets": "h2h",
                    "oddsFormat": "decimal"}, timeout=_TIMEOUT)
        if getattr(r, "status_code", 0) == 429:
            return FetchResult(False, [], "rate limited (429)")
        if getattr(r, "status_code", 0) != 200:
            return FetchResult(False, [], f"http {getattr(r, 'status_code', '?')}")
        return FetchResult(True, parse_odds_api(r.json()))
    except Exception as exc:  # noqa: BLE001
        return FetchResult(False, [], f"{type(exc).__name__}: {exc}")


# --- Betfair Historical: IMPORTER ONLY --------------------------------------

#: Betfair eventTypeId for Soccer, and the only market type we accept.
BETFAIR_SOCCER_EVENT_TYPE = "1"
BETFAIR_MARKET_TYPE = "MATCH_ODDS"

#: MATCH_ODDS runner ordering. Betfair sorts home=1, away=2, the draw=3; the
#: draw is additionally confirmed by name, because relying on order alone for
#: which side is "home" is exactly the mistake that silently inverts a market.
_SORT_PRIORITY_SIDE = {1: "home", 2: "away", 3: "draw"}


class BetfairArchiveUnsupported(ValueError):
    """The archive lacks what a coherent back-price snapshot requires.

    Raised rather than degraded. Betfair's BASIC historical tier ships market
    definitions and last-traded price only -- no available-to-back ladder --
    so a Basic file cannot produce back prices at all. Falling back to `ltp`
    would silently relabel last-traded as available-to-back, which is a
    different number and a different market.

    Required tier: ADVANCED or PRO (ladder data, `atb` in runner changes).
    """


def _best_back(ladder: dict[float, float]) -> float | None:
    """Best available-to-back price = highest price still offered.

    Levels with zero size have been removed by a delta and are dropped by the
    caller before this runs.
    """
    return max(ladder) if ladder else None


def parse_betfair_archive(lines, *, archive_sha256: str, acquisition_note: str,
                          competition_id: str) -> list[MarketObservation]:
    """Parse a Betfair Exchange historical market-change archive.

    IMPORTER ONLY, by design. Betfair historical archives sit behind an account
    login and a data licence, so this reads a file the OPERATOR downloaded and
    never authenticates, fetches, or touches a betting account. Both the
    archive digest and the operator's acquisition note are required: an offline
    source must still be citable.

    What this emits: **available-to-back** prices, reconstructed statefully.

      - `rc` runner changes are PARTIAL DELTAS. Each carries `atb` entries as
        [price, size]; a size of 0 REMOVES that price level. Per-runner ladders
        are therefore accumulated across messages, not read from any single one.
      - The best back price is the highest price still on offer.
      - A snapshot is emitted only once ALL THREE runners have a best back, and
        only at publish times strictly BEFORE kickoff. Emission is deduplicated:
        a new row appears only when a best-back actually moved, which is what
        "last available price at or before t" means.
      - Sides come from `marketDefinition.runners[].sortPriority`, never list
        order, with the draw cross-checked by name.

    Positively required metadata -- anything else is rejected, not stamped:
      - `eventTypeId == "1"` (Soccer)
      - `marketType == "MATCH_ODDS"`
      - `competitionId == competition_id` (operator-supplied, validated against
        the archive rather than assumed)

    In-play is excluded: once a market definition reports `inPlay`, later
    publish times for it stop producing snapshots.

    Raises BetfairArchiveUnsupported when no `atb` ladder is present anywhere,
    i.e. the archive tier is too low. Never falls back to `ltp`.
    """
    if not archive_sha256 or not acquisition_note:
        raise ValueError(
            "betfair import requires archive_sha256 AND acquisition_note -- an "
            "importer-only source must record where its file came from")
    if not competition_id:
        raise ValueError(
            "betfair import requires competition_id: the archive's competition "
            "is validated against it, never assumed from runner count")

    out: list[MarketObservation] = []
    meta: dict[str, dict] = {}
    ladders: dict[tuple[str, int], dict[float, float]] = {}
    last_emitted: dict[str, tuple] = {}
    saw_any_atb = False
    saw_any_candidate_market = False

    for raw in lines:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("betfair: skipping unparseable line")
            continue

        pt = msg.get("pt")
        ts = (datetime.fromtimestamp(pt / 1000, tz=timezone.utc)
              if isinstance(pt, (int, float)) else None)

        for mc in msg.get("mc") or []:
            mid = mc.get("id")
            if not mid:
                continue

            md = mc.get("marketDefinition")
            if md:
                event_type = str(md.get("eventTypeId") or "")
                market_type = str(md.get("marketType") or "")
                comp = str(md.get("competitionId") or "")
                if (event_type != BETFAIR_SOCCER_EVENT_TYPE
                        or market_type != BETFAIR_MARKET_TYPE
                        or comp != str(competition_id)):
                    meta[mid] = {"rejected": True}
                    continue
                saw_any_candidate_market = True
                sides, names = {}, {}
                for r in md.get("runners") or []:
                    rid, sp = r.get("id"), r.get("sortPriority")
                    name = (r.get("name") or "").strip()
                    if rid is None or sp not in _SORT_PRIORITY_SIDE:
                        continue
                    side = _SORT_PRIORITY_SIDE[sp]
                    # Cross-check: sortPriority 3 must actually be the draw.
                    if side == "draw" and name.lower() not in ("the draw", "draw"):
                        continue
                    sides[rid] = side
                    names[side] = name
                prev = meta.get(mid) or {}
                meta[mid] = {
                    "rejected": False,
                    "kickoff": _parse_dt(md.get("marketTime")),
                    "sides": sides,
                    "home": names.get("home", ""),
                    "away": names.get("away", ""),
                    # Once in-play, stay in-play for the rest of the archive.
                    "in_play": bool(md.get("inPlay")) or prev.get("in_play", False),
                }

            info = meta.get(mid)
            if not info or info.get("rejected") or ts is None:
                continue

            for rc in mc.get("rc") or []:
                rid = rc.get("id")
                atb = rc.get("atb")
                if rid is None or atb is None:
                    continue
                saw_any_atb = True
                ladder = ladders.setdefault((mid, rid), {})
                for level in atb:
                    try:
                        price, size = float(level[0]), float(level[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    if size > 0:
                        ladder[price] = size
                    else:
                        ladder.pop(price, None)  # zero size removes the level

            if info.get("in_play"):
                continue
            kickoff = info.get("kickoff")
            if kickoff is None or ts >= kickoff:
                continue  # strictly before kickoff, never at or after

            sides = info.get("sides") or {}
            if len(sides) != 3:
                continue
            triple: dict[str, tuple[int, float]] = {}
            for rid, side in sides.items():
                best = _best_back(ladders.get((mid, rid), {}))
                if best is None:
                    break
                triple[side] = (rid, best)
            if len(triple) != 3:
                continue  # not yet coherent; wait for the missing runner

            signature = tuple(sorted((s, p) for s, (_r, p) in triple.items()))
            if last_emitted.get(mid) == signature:
                continue  # nothing moved
            last_emitted[mid] = signature

            for side, (rid, price) in triple.items():
                out.append(MarketObservation(
                    source="betfair_historical",
                    # The MARKET id, not per-runner: the loader groups by
                    # (source, source_market_id, bookmaker, captured_at) to
                    # de-vig, so a per-runner id would create three
                    # one-outcome groups that can never form a triple.
                    source_market_id=str(mid), source_event_id=str(mid),
                    competition_code=COMPETITION, kickoff_utc=kickoff,
                    raw_home_label=info["home"], raw_away_label=info["away"],
                    bookmaker_key="betfair_exchange", outcome=side,
                    price_decimal=price, captured_at=ts,
                    payload_sha256=_sha256({"m": mid, "r": rid, "p": price,
                                            "t": ts.isoformat()}),
                    archive_sha256=archive_sha256,
                    acquisition_note=acquisition_note,
                ))

    if saw_any_candidate_market and not saw_any_atb:
        raise BetfairArchiveUnsupported(
            "archive contains no available-to-back ladder (`atb`) -- this is the "
            "BASIC historical tier, which ships market definitions and "
            "last-traded price only. Back prices require the ADVANCED or PRO "
            "tier. Refusing to substitute `ltp`: last-traded is a different "
            "number from available-to-back.")
    return out


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
