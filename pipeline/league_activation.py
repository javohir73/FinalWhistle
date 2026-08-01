"""Idempotent historical preparation for active club leagues.

The daily league pipeline calls this before fixture ingest. A populated league
does no network work; a fresh or partial database re-downloads the public
football-data.co.uk season files and relies on ``load_club_results``'s
competition-scoped idempotency. The minimum-row guard prevents predictions from
quietly starting on a truncated historical sample.
"""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import HistoricalMatch
from pipeline.ingest.club_results import download_club_results_df, load_club_results
from pipeline.leagues import LeagueConfig


def _history_count(db: Session, competition: str) -> int:
    return int(
        db.query(func.count(HistoricalMatch.id))
        .filter(HistoricalMatch.competition == competition)
        .scalar()
        or 0
    )


def ensure_club_history(
    db: Session,
    config: LeagueConfig,
    *,
    downloader: Callable[..., pd.DataFrame] | None = None,
) -> dict:
    """Ensure one league has a complete-enough historical replay source.

    ``downloader`` is injectable for deterministic tests. A partial prior load
    is safe: the loader deduplicates within the league and the final threshold
    is checked after the retry.
    """
    competition = config["club_competition"]
    minimum = config["history_min_matches"]
    before = _history_count(db, competition)
    if before >= minimum:
        return {
            "competition": competition,
            "matches": before,
            "downloaded": False,
            "minimum": minimum,
        }

    source = config.get("history_source", "football_data")
    if source == "football_data":
        division = config["club_division"]
        if not division:
            raise RuntimeError(f"{competition} has no football-data division configured")
        fetch = downloader or download_club_results_df
        frame = fetch(division=division)
        loaded = load_club_results(db, frame, competition=competition)
    elif source == "api_football":
        from app.config import settings
        from pipeline.ingest.api_football_club_results import (
            download_finished_fixtures,
            load_api_football_club_results,
        )

        seasons = config.get("history_seasons")
        if not seasons:
            raise RuntimeError(f"{competition} has no explicit API-Football history seasons")
        if not settings.api_football_api_key and downloader is None:
            raise RuntimeError(
                f"{competition} historical backfill requires API_FOOTBALL_API_KEY"
            )
        fetch = downloader or download_finished_fixtures
        rows = fetch(
            api_key=settings.api_football_api_key,
            league=config["league_id"],
            seasons=seasons,
        )
        loaded = load_api_football_club_results(db, rows, competition=competition)
    else:
        raise RuntimeError(f"unsupported historical source {source!r} for {competition}")
    after = _history_count(db, competition)
    if after < minimum:
        raise RuntimeError(
            f"{competition} historical backfill incomplete: "
            f"{after} rows, requires at least {minimum}"
        )
    return {
        "competition": competition,
        "matches": after,
        "downloaded": True,
        "minimum": minimum,
        **loaded,
    }
