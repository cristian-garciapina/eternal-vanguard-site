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

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .models import Member, Score, Season, Snapshot, Stat


# --- Season / snapshot resolution ----------------------------------------
def get_active_season(db: Session) -> Optional[Season]:
    return db.scalar(select(Season).where(Season.is_active == True))


def get_scoring_snapshot(db: Session, season: Season) -> Optional[Snapshot]:
    """The latest cumulative snapshot used for the current scores."""
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
    rows = db.execute(
        select(Score.grade, func.count(Score.id))
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
        .where(Score.is_farm_account == False)
        .group_by(Score.grade)
    ).all()
    return {grade: count for grade, count in rows if grade is not None}


def get_dashboard_stats(db: Session, season_id: int, snapshot_id: int) -> dict:
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
    """Top N non-farm members by M/P%. Joined with Member + Stat for the
    snapshot so the template has every metric available (not just the
    three used in the M/P% formula).
    """
    rows = db.execute(
        select(Score, Member, Stat)
        .join(Member, Score.character_id == Member.character_id)
        .join(
            Stat,
            and_(
                Stat.character_id == Score.character_id,
                Stat.snapshot_id == Score.snapshot_id,
            ),
        )
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
        .where(Score.is_farm_account == False)
        .order_by(Score.mp_ratio.desc())
        .limit(limit)
    ).all()

    return [_row_to_dict(score, member, stat) for score, member, stat in rows]


def _row_to_dict(score: Score, member: Member, stat: Stat) -> dict:
    """Project every visible metric. `*_short` variants are the formatted
    "1.5M" strings; raw integers are also exposed for sorting or future use.
    """
    return {
        # Identity
        "name": member.current_name,
        "character_id": member.character_id,

        # Scoring outputs
        "grade": score.grade or "—",
        "mp_ratio": score.mp_ratio,

        # Power
        "power": stat.power,
        "power_short": format_number_short(stat.power),
        "peak_power": stat.peak_power or 0,
        "peak_power_short": format_number_short(stat.peak_power or 0),

        # Combat
        "deaths_t45": stat.deaths_t45,
        "deaths_t45_short": format_number_short(stat.deaths_t45),
        "destruction_time": stat.destruction_time,
        "destruction_time_short": format_number_short(stat.destruction_time),

        # Merits (total + breakdown)
        "merits_total": stat.merits_total,
        "merits_total_short": format_number_short(stat.merits_total),
        "merits_infantry": stat.merits_infantry,
        "merits_infantry_short": format_number_short(stat.merits_infantry),
        "merits_cavalry": stat.merits_cavalry,
        "merits_cavalry_short": format_number_short(stat.merits_cavalry),
        "merits_archers": stat.merits_archers,
        "merits_archers_short": format_number_short(stat.merits_archers),
        "merits_magic": stat.merits_magic,
        "merits_magic_short": format_number_short(stat.merits_magic),
        "merits_other": stat.merits_other,
        "merits_other_short": format_number_short(stat.merits_other),

        # Support
        "healing_t45": stat.healing_t45,
        "healing_t45_short": format_number_short(stat.healing_t45),

        # Economy
        "harvest": stat.harvest,
        "harvest_short": format_number_short(stat.harvest),
        "build_time": stat.build_time,
        "build_time_short": format_number_short(stat.build_time),

        # Alliance contribution
        "alliance_donations": stat.alliance_donations,
        "alliance_donations_short": format_number_short(stat.alliance_donations),
        "behemoth_victories": stat.behemoth_victories,
    }


# --- Helpers -------------------------------------------------------------
def compute_season_progress(season: Season) -> dict:
    today = date.today()
    start = season.start_date
    days_elapsed = max(1, (today - start).days + 1)

    result = {
        "day_current": days_elapsed,
        "start_date": start.strftime("%Y-%m-%d"),
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
                "end_date": season.end_date.strftime("%Y-%m-%d"),
                "progress_pct": min(100, int(100 * days_elapsed / days_total)),
            }
        )

    return result


def format_number_short(n: Optional[int]) -> str:
    """1_523_400 -> '1.5M'. None or 0 -> '0' / '—'."""
    if n is None:
        return "—"
    if n == 0:
        return "0"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# --- Full roster (Excel-like view) ----------------------------------------
ROSTER_SORTABLE_COLUMNS: dict[str, object] = {
    # Map URL param -> SQL column. Whitelist for safety.
    "name": Member.current_name,
    "grade": Score.grade,
    "mp": Score.mp_ratio,
    "merits_total": Stat.merits_total,
    "power": Stat.power,
    "peak_power": Stat.peak_power,
    "deaths": Stat.deaths_t45,
    "healing": Stat.healing_t45,
    "destruction": Stat.destruction_time,
    "build_time": Stat.build_time,
    "behemoth": Stat.behemoth_victories,
    "harvest": Stat.harvest,
    "donations": Stat.alliance_donations,
    "merits_infantry": Stat.merits_infantry,
    "merits_cavalry": Stat.merits_cavalry,
    "merits_archers": Stat.merits_archers,
    "merits_magic": Stat.merits_magic,
    "merits_other": Stat.merits_other,
}


def get_full_roster(
    db: Session,
    season_id: int,
    snapshot_id: int,
    *,
    search: Optional[str] = None,
    grade: Optional[str] = None,
    include_farms: bool = False,
    sort: str = "mp",
    order: str = "desc",
) -> list[dict]:
    """Full roster query with search/filter/sort. Returns every member with
    a score for the given snapshot.

    - `search`: case-insensitive substring match on Member.current_name
    - `grade`: filter to a specific grade ('S'/'A'/'B'/'C'/'D'); None = all
    - `include_farms`: include farm accounts (default: exclude)
    - `sort` / `order`: column key from ROSTER_SORTABLE_COLUMNS + asc/desc
    """
    stmt = (
        select(Score, Member, Stat)
        .join(Member, Score.character_id == Member.character_id)
        .join(
            Stat,
            and_(
                Stat.character_id == Score.character_id,
                Stat.snapshot_id == Score.snapshot_id,
            ),
        )
        .where(Score.season_id == season_id)
        .where(Score.snapshot_id == snapshot_id)
    )

    if not include_farms:
        stmt = stmt.where(Score.is_farm_account == False)

    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(Member.current_name.ilike(like))

    if grade and grade.upper() in ("S", "A", "B", "C", "D"):
        stmt = stmt.where(Score.grade == grade.upper())

    sort_col = ROSTER_SORTABLE_COLUMNS.get(sort, Score.mp_ratio)
    if order.lower() == "asc":
        stmt = stmt.order_by(sort_col.asc().nulls_last())
    else:
        stmt = stmt.order_by(sort_col.desc().nulls_last())

    rows = db.execute(stmt).all()
    return [_row_to_dict(score, member, stat) for score, member, stat in rows]


def count_total_roster(db: Session, season_id: int, snapshot_id: int) -> int:
    """Total scored members (non-farm) for the snapshot."""
    return (
        db.scalar(
            select(func.count(Score.id))
            .where(Score.season_id == season_id)
            .where(Score.snapshot_id == snapshot_id)
            .where(Score.is_farm_account == False)
        )
        or 0
    )
