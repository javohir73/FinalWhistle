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

    fetch = downloader or download_club_results_df
    frame = fetch(division=config["club_division"])
    loaded = load_club_results(db, frame, competition=competition)
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
