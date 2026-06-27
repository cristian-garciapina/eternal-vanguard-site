"""
Eternal Vanguard — main FastAPI application.

- `/`              public landing
- `/login`         public
- `/logout`        public (POST)
- `/dashboard`     authenticated, all members
- `/api/ingest`    bearer-token protected
- `/healthz`       public
"""
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import queries
from .auth import (
    RequiresLoginException,
    get_current_user,
    get_db,
    require_user,
)
from .auth_routes import router as auth_router
from .ingest import router as ingest_router
from .models import User

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Eternal Vanguard",
    description="Alliance management website for Call of Dragons — Kingdom 193.",
    version="0.3.0",
    docs_url="/_docs",
    redoc_url=None,
)

app.include_router(ingest_router)
app.include_router(auth_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --- Exception handlers ---------------------------------------------------
@app.exception_handler(RequiresLoginException)
async def requires_login_handler(request: Request, exc: RequiresLoginException):
    return RedirectResponse(url=f"/login?next={exc.next_url}", status_code=303)


# --- Routes ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "alliance_name": "Eternal Vanguard",
            "kingdom": 193,
            "user": user,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_overview(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Alliance overview — visible to any authenticated member."""
    context: dict = {
        "user": user,
        "kingdom": 193,
        "season": None,
        "season_progress": None,
        "snapshot": None,
        "stats": None,
        "distribution": {},
        "top_performers": [],
        "has_scores": False,
    }

    season = queries.get_active_season(db)
    if season is None:
        return templates.TemplateResponse(
            request=request, name="dashboard/overview.html", context=context
        )

    context["season"] = season
    context["season_progress"] = queries.compute_season_progress(season)

    snapshot = queries.get_scoring_snapshot(db, season)
    if snapshot is None or not queries.has_any_scores(db, snapshot.id):
        return templates.TemplateResponse(
            request=request, name="dashboard/overview.html", context=context
        )

    stats = queries.get_dashboard_stats(db, season.id, snapshot.id)
    stats["count_missing"] = queries.get_missing_count(db, season, snapshot.id)

    context.update(
        {
            "snapshot": snapshot,
            "stats": stats,
            "distribution": queries.get_grade_distribution(db, season.id, snapshot.id),
            "top_performers": queries.get_top_performers(
                db, season.id, snapshot.id, limit=15
            ),
            "has_scores": True,
        }
    )

    return templates.TemplateResponse(
        request=request, name="dashboard/overview.html", context=context
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
