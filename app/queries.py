"""
Read-side queries for the dashboard pages.

All functions take a SQLAlchemy session and return plain Python data
(ints, dicts, lists of dicts) so the templates have no SQLAlchemy
objects to dig into.
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Member, Score, Season, Snapshot, Stat


# --- Season / snapshot resolution ----------------------------------------
def get_active_season(db: Session) -> Optional[Season]:
    return db.scalar(select(Season).where(Season.is_active == True))


def get_scoring_snapshot(db: Session, season: Season) -> Optional[Snapshot]:
    """The latest cumulative snapshot used for the current scores.

    Per scoring.py convention: date_start == season.start_date
    AND date_end > season.start_date, ordered by date_end DESC.
    """
    return db.scalar(
        select(Snapshot)
        .where(Snapshot.season_id == season.id)
        .where(Snapshot.date_start == season.start_date)
        .where(Snapshot.date_end > season.start_date)
        .order_by(Snapshot.date_end.desc())
        .limit(1)
    )


def has_any_scores(db: Session, snapshot_id: int) -> bool:
    n = db.scalar(select(func.count(Score.id)).where(Score.snapshot_id == snapshot_id))
    return (n or 0) > 0


# --- Aggregate KPIs ------------------------------------------------------
def get_grade_distribution(
    db: Session, season_id: int, snapshot_id: int
) -> dict[str, int]:
    """Counts per grade (non-farm) for the snapshot."""
    rows = db.execute(
        select(Score.grade, func.count(Score.id))
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
        .where(Score.is_farm_account == False)
        .group_by(Score.grade)
    ).all()
    return {grade: count for grade, count in rows if grade is not None}


def get_dashboard_stats(
    db: Session, season_id: int, snapshot_id: int
) -> dict:
    """Aggregate KPIs displayed on the overview cards."""
    base = (
        lambda f: select(f)
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
    )

    count_scored = (
        db.scalar(base(func.count(Score.id)).where(Score.is_farm_account == False))
        or 0
    )
    count_farm = (
        db.scalar(base(func.count(Score.id)).where(Score.is_farm_account == True))
        or 0
    )
    total_merits = (
        db.scalar(
            base(func.sum(Score.merits_cumulative)).where(
                Score.is_farm_account == False
            )
        )
        or 0
    )
    mp_avg = db.scalar(
        base(func.avg(Score.mp_ratio)).where(Score.is_farm_account == False)
    )

    # SQLite has no percentile/median — compute in Python.
    powers = db.scalars(
        select(Score.end_power)
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
        .where(Score.is_farm_account == False)
    ).all()
    median_power = int(statistics.median(powers)) if powers else 0

    return {
        "count_scored": count_scored,
        "count_farm": count_farm,
        "total_merits": int(total_merits),
        "total_merits_short": format_number_short(int(total_merits)),
        "mp_avg": float(mp_avg) if mp_avg is not None else 0.0,
        "median_power": median_power,
        "median_power_short": format_number_short(median_power),
    }


def get_missing_count(
    db: Session, season: Season, current_snapshot_id: int
) -> int:
    """Members present at the start snapshot but absent from the current one."""
    if season.start_snapshot_id is None:
        return 0
    current_chars = select(Stat.character_id).where(
        Stat.snapshot_id == current_snapshot_id
    )
    return (
        db.scalar(
            select(func.count(Stat.id))
            .where(Stat.snapshot_id == season.start_snapshot_id)
            .where(Stat.character_id.not_in(current_chars))
        )
        or 0
    )


# --- Lists ---------------------------------------------------------------
def get_top_performers(
    db: Session, season_id: int, snapshot_id: int, limit: int = 15
) -> list[dict]:
    """Top N non-farm members by M/P%, joined with Member for display name."""
    rows = db.execute(
        select(Score, Member)
        .join(Member, Score.character_id == Member.character_id)
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
        .where(Score.is_farm_account == False)
        .order_by(Score.mp_ratio.desc())
        .limit(limit)
    ).all()

    return [
        {
            "name": member.current_name,
            "character_id": member.character_id,
            "grade": score.grade or "—",
            "mp_ratio": score.mp_ratio,
            "merits": score.merits_cumulative,
            "merits_short": format_number_short(score.merits_cumulative),
            "power": score.end_power,
            "power_short": format_number_short(score.end_power),
        }
        for score, member in rows
    ]


# --- Helpers -------------------------------------------------------------
def compute_season_progress(season: Season) -> dict:
    today = date.today()
    start = season.start_date
    days_elapsed = max(1, (today - start).days + 1)

    result = {
        "day_current": days_elapsed,
        "start_date": start.strftime("%d/%m/%Y"),
        "start_date_iso": start.isoformat(),
        "day_total": None,
        "days_remaining": None,
        "end_date": None,
        "progress_pct": None,
    }

    if season.end_date:
        days_total = (season.end_date - start).days + 1
        days_remaining = max(0, (season.end_date - today).days)
        result.update(
            {
                "day_total": days_total,
                "days_remaining": days_remaining,
                "end_date": season.end_date.strftime("%d/%m/%Y"),
                "progress_pct": min(100, int(100 * days_elapsed / days_total)),
            }
        )

    return result


def format_number_short(n: Optional[int]) -> str:
    """1_523_400 -> '1.5M'. None -> '—'."""
    if n is None:
        return "—"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
