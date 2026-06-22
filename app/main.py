"""
Eternal Vanguard — main FastAPI application.

Serves the public landing page at `/` and the alliance dashboard at
`/dashboard`. Data ingestion endpoints (POST /api/ingest) and the scoring
system will be added on Day 2 of the MVP sprint.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- Paths ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# --- Application ----------------------------------------------------------
app = FastAPI(
    title="Eternal Vanguard",
    description="Alliance management website for Call of Dragons — Kingdom 193.",
    version="0.1.0",
    # Hide auto-generated API docs in production; useful while developing.
    docs_url="/_docs",
    redoc_url=None,
)

# Serve /static/* from disk if the directory exists.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


# --- Routes ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    """Public landing page — alliance presentation and dashboard entry."""
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "alliance_name": "Eternal Vanguard",
            "kingdom": 193,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_overview(request: Request) -> HTMLResponse:
    """Dashboard overview — alliance snapshot at a glance.

    Placeholder values are used until the ingestion pipeline is wired on Day 2.
    """
    placeholder_stats = {
        "total_members": 142,
        "total_power": "—",
        "total_merit": "—",
        "active_players": "—",
    }
    return templates.TemplateResponse(
        request=request,
        name="dashboard/overview.html",
        context={"stats": placeholder_stats},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Health check — used by systemd and any monitoring layer."""
    return {"status": "ok"}
