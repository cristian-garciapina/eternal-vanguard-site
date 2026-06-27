"""
Auth routes: /login (GET + POST), /logout (POST).
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    COOKIE_NAME,
    _clear_cookie,
    _set_cookie,
    create_session,
    delete_session,
    get_db,
    verify_password,
)
from .models import User

router = APIRouter(tags=["auth"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/dashboard"):
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"next": next, "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username.lower().strip()))

    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={
                "next": next,
                "error": "Identifiants invalides.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Open-redirect guard
    if not next.startswith("/") or next.startswith("//"):
        next = "/dashboard"

    session = create_session(
        db,
        user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    response = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    _set_cookie(response, session.session_id)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        delete_session(db, session_id)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    _clear_cookie(response)
    return response
