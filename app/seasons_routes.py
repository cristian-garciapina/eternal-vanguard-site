"""
Staff seasons management: upload exports + season lifecycle.

GET  /staff/seasons                 unified view (active season + snapshots + upload + wizard CTA)
POST /staff/seasons/upload          upload a cumulative export (ingest + recompute)
GET  /staff/seasons/new             wizard step 1: upload start snapshot
POST /staff/seasons/new/upload      wizard step 1 handler
GET  /staff/seasons/new/confirm     wizard step 2: confirm season metadata
POST /staff/seasons/new/confirm     wizard step 3: commit (close previous, create new)

Both 'staff' and 'owner' can access. Every state-changing action is
recorded in audit_log.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_db, require_staff
from .ingest import _ingest_upload, _extract_dates_from_filename
from .models import AuditLog, Season, Snapshot, User
from .scoring import recompute_scores_for_active_season

router = APIRouter(tags=["staff-seasons"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --- Helpers --------------------------------------------------------------
def _active_season(db: Session) -> Optional[Season]:
    return db.scalar(select(Season).where(Season.is_active == True))


def _list_snapshots(db: Session, season_id: int) -> list[Snapshot]:
    return list(db.scalars(
        select(Snapshot)
        .where(Snapshot.season_id == season_id)
        .order_by(Snapshot.date_end.desc(), Snapshot.ingested_at.desc())
    ).all())


def _audit(db: Session, user: User, action: str, target_type: str,
           target_id: str, old: Optional[dict], new: Optional[dict]):
    db.add(AuditLog(
        user=user.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        old_value=old,
        new_value=new,
        timestamp=datetime.utcnow(),
    ))


def _render(request: Request, db: Session, user: User,
            error: Optional[str] = None, success: Optional[str] = None,
            recompute_info: Optional[dict] = None):
    season = _active_season(db)
    snapshots = _list_snapshots(db, season.id) if season else []
    start_snap = (
        db.get(Snapshot, season.start_snapshot_id)
        if season and season.start_snapshot_id else None
    )
    latest_cum = next(
        (s for s in snapshots
         if season and s.date_start == season.start_date and s.date_end > season.start_date),
        None,
    )

    return templates.TemplateResponse(
        request=request,
        name="staff/seasons.html",
        context={
            "user": user,
            "kingdom": 193,
            "season": season,
            "snapshots": snapshots,
            "start_snap": start_snap,
            "latest_cum": latest_cum,
            "error": error,
            "success": success,
            "recompute": recompute_info,
        },
    )


# --- Main page -----------------------------------------------------------
@router.get("/staff/seasons", response_class=HTMLResponse)
async def seasons_view(
    request: Request,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return _render(request, db, user)


# --- Upload cumulative export -------------------------------------------
@router.post("/staff/seasons/upload")
async def seasons_upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    season = _active_season(db)
    if season is None:
        return _render(request, db, user, error="No active season. Start one first.")

    try:
        result = await _ingest_upload(db, file, ingested_by=user.username)
    except Exception as exc:
        return _render(request, db, user, error=f"Upload failed: {exc}")

    _audit(db, user, "ingest", "snapshot", str(result["snapshot_id"]),
           None, {"file": result["filename"], "rows": result["rows"]})
    db.commit()

    # Recompute scores so the new data takes effect immediately.
    recompute_info = recompute_scores_for_active_season(db)
    return _render(
        request, db, user,
        success=f"Ingested {result['rows']} rows from {result['filename']} and recomputed scores.",
        recompute_info=recompute_info,
    )


# --- Wizard: new season --------------------------------------------------
@router.get("/staff/seasons/new", response_class=HTMLResponse)
async def new_season_wizard(
    request: Request,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="staff/season_new.html",
        context={
            "user": user,
            "kingdom": 193,
            "step": 1,
            "error": None,
            "pending_snapshot": None,
            "current_season": _active_season(db),
        },
    )


@router.post("/staff/seasons/new/upload")
async def new_season_upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Step 1 handler: ingest the start-of-season snapshot under the
    active season (it'll be reassigned in step 3 when the new season
    is created)."""
    try:
        result = await _ingest_upload(db, file, ingested_by=user.username)
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="staff/season_new.html",
            context={
                "user": user, "kingdom": 193, "step": 1,
                "error": f"Upload failed: {exc}",
                "pending_snapshot": None,
                "current_season": _active_season(db),
            },
        )

    snap = db.get(Snapshot, result["snapshot_id"])
    # Sanity: a start snapshot should be a single-day export.
    if snap.date_start != snap.date_end:
        return templates.TemplateResponse(
            request=request,
            name="staff/season_new.html",
            context={
                "user": user, "kingdom": 193, "step": 1,
                "error": (
                    "This export covers a date range, not a single day. "
                    "A start-of-season snapshot must be a single-day export "
                    "(date_start = date_end). The file was ingested anyway, "
                    "but you should pick a 1-day export to start a new season."
                ),
                "pending_snapshot": None,
                "current_season": _active_season(db),
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="staff/season_new.html",
        context={
            "user": user, "kingdom": 193, "step": 2,
            "error": None,
            "pending_snapshot": snap,
            "current_season": _active_season(db),
            "default_name": f"Season {snap.date_start.strftime('%Y')}-S{((snap.date_start.month - 1) // 3) + 1}",
        },
    )


@router.post("/staff/seasons/new/confirm")
async def new_season_confirm(
    request: Request,
    snapshot_id: int = Form(...),
    name: str = Form(...),
    start_date: str = Form(...),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Step 3 handler: close the active season + create the new one."""
    snap = db.get(Snapshot, snapshot_id)
    if snap is None:
        return RedirectResponse(url="/staff/seasons/new", status_code=303)

    try:
        start_d = date.fromisoformat(start_date.strip())
    except ValueError:
        return templates.TemplateResponse(
            request=request,
            name="staff/season_new.html",
            context={
                "user": user, "kingdom": 193, "step": 2,
                "error": "Invalid start date (expected YYYY-MM-DD).",
                "pending_snapshot": snap,
                "current_season": _active_season(db),
                "default_name": name,
            },
        )

    name_clean = name.strip()
    if not name_clean or len(name_clean) > 64:
        return templates.TemplateResponse(
            request=request,
            name="staff/season_new.html",
            context={
                "user": user, "kingdom": 193, "step": 2,
                "error": "Invalid season name.",
                "pending_snapshot": snap,
                "current_season": _active_season(db),
                "default_name": name,
            },
        )

    now = datetime.utcnow()

    # Close the active season(s)
    actives = list(db.scalars(select(Season).where(Season.is_active == True)).all())
    for s in actives:
        _audit(db, user, "close", "season", str(s.id),
               {"is_active": True}, {"is_active": False, "closed_at": now.isoformat()})
        s.is_active = False
        s.closed_at = now
        if s.end_date is None:
            s.end_date = start_d  # the new season starts where the old one ends

    # Create the new season; reassign the start snapshot to it
    new_season = Season(
        name=name_clean,
        start_date=start_d,
        is_active=True,
        start_snapshot_id=snap.id,
        created_at=now,
    )
    db.add(new_season)
    db.flush()  # get new_season.id
    snap.season_id = new_season.id

    _audit(db, user, "create", "season", str(new_season.id),
           None, {"name": name_clean, "start_date": start_date,
                  "start_snapshot_id": snap.id})
    db.commit()

    # Recompute scores under the new season (probably empty until a
    # cumulative is uploaded, but we run it for consistency).
    recompute_scores_for_active_season(db)

    return RedirectResponse(url="/staff/seasons", status_code=303)
