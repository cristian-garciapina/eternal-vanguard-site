"""
Recruitment endpoints.

Public:
  GET  /apply            application form
  POST /apply            submit form

Staff:
  GET  /staff/applications              review queue
  POST /staff/applications/{id}/status  update status
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_db, require_staff
from .models import Application, User

router = APIRouter(tags=["recruitment"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _empty_form() -> dict:
    return {
        "in_game_name": "",
        "player_id": "",
        "current_alliance": "",
        "server": "",
        "motivation": "",
        "discord_handle": "",
    }


@router.get("/apply", response_class=HTMLResponse)
async def apply_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="recruitment/apply.html",
        context={"form": _empty_form(), "error": None, "submitted": False},
    )


@router.post("/apply")
async def apply_submit(
    request: Request,
    in_game_name: str = Form(...),
    player_id: str = Form(...),
    current_alliance: str = Form(""),
    server: str = Form(...),
    motivation: str = Form(...),
    discord_handle: str = Form(""),
    db: Session = Depends(get_db),
):
    form = {
        "in_game_name": in_game_name,
        "player_id": player_id,
        "current_alliance": current_alliance,
        "server": server,
        "motivation": motivation,
        "discord_handle": discord_handle,
    }

    def render_error(msg: str):
        return templates.TemplateResponse(
            request=request,
            name="recruitment/apply.html",
            context={"form": form, "error": msg, "submitted": False},
            status_code=400,
        )

    name_clean = in_game_name.strip()
    if not name_clean or len(name_clean) > 64:
        return render_error("Please enter your in-game name.")

    try:
        player_id_int = int(player_id.strip())
    except ValueError:
        return render_error("Player ID must be a number.")

    try:
        server_int = int(server.strip())
    except ValueError:
        return render_error("Server must be a number.")

    motivation_clean = motivation.strip()
    if len(motivation_clean) < 20:
        return render_error("Please tell us a bit more about yourself (20+ characters).")

    app = Application(
        in_game_name=name_clean,
        player_id=player_id_int,
        current_alliance=current_alliance.strip()[:64] or None,
        server=server_int,
        motivation=motivation_clean,
        discord_handle=discord_handle.strip()[:64] or None,
        created_at=datetime.utcnow(),
        status="new",
    )
    db.add(app)
    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="recruitment/apply.html",
        context={"form": _empty_form(), "error": None, "submitted": True},
    )


# --- Staff side -----------------------------------------------------------
@router.get("/staff/applications", response_class=HTMLResponse)
async def list_applications(
    request: Request,
    status: str = "",
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    stmt = select(Application).order_by(Application.created_at.desc())
    if status in ("new", "reviewing", "accepted", "rejected"):
        stmt = stmt.where(Application.status == status)

    apps = list(db.scalars(stmt).all())
    counts = {}
    for st in ("new", "reviewing", "accepted", "rejected"):
        counts[st] = db.scalar(
            select(Application).where(Application.status == st)
        ) is not None and db.scalar(
            select(Application).where(Application.status == st).limit(1)
        ) is not None
    # simpler: just compute the counts properly
    from sqlalchemy import func as _func
    counts = {
        st: db.scalar(select(_func.count(Application.id)).where(Application.status == st)) or 0
        for st in ("new", "reviewing", "accepted", "rejected")
    }

    return templates.TemplateResponse(
        request=request,
        name="staff/applications.html",
        context={
            "user": user,
            "kingdom": 193,
            "apps": apps,
            "counts": counts,
            "current_filter": status,
        },
    )


@router.post("/staff/applications/{app_id}/status")
async def update_status(
    app_id: int,
    new_status: str = Form(...),
    notes: str = Form(""),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    app = db.get(Application, app_id)
    if app is None:
        return RedirectResponse(url="/staff/applications", status_code=303)

    if new_status in ("new", "reviewing", "accepted", "rejected"):
        app.status = new_status
        app.reviewed_by = user.username
        app.reviewed_at = datetime.utcnow()
    if notes.strip():
        app.notes = notes.strip()
    db.commit()

    return RedirectResponse(url="/staff/applications", status_code=303)
