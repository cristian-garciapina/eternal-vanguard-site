"""
Eternal Vanguard — main FastAPI application.

- `/`              public landing
- `/login`         public
- `/logout`        public (POST)
- `/dashboard`     authenticated
- `/api/ingest`    bearer-token protected
- `/healthz`       public
"""
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import RequiresLoginException, get_current_user, require_user
from .auth_routes import router as auth_router
from .ingest import router as ingest_router
from .models import User

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Eternal Vanguard",
    description="Alliance management website for Call of Dragons — Kingdom 193.",
    version="0.2.1",
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
    """Anonymous visitor on a protected route → redirect to /login."""
    return RedirectResponse(
        url=f"/login?next={exc.next_url}",
        status_code=303,
    )


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
) -> HTMLResponse:
    """Dashboard placeholder — real data wiring in the next step."""
    placeholder_stats = {
        "total_members": 142,
        "total_power": "—",
        "total_merit": "—",
        "active_players": "—",
    }
    return templates.TemplateResponse(
        request=request,
        name="dashboard/overview.html",
        context={"stats": placeholder_stats, "user": user},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
