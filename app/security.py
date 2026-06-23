"""
Bearer token authentication for protected endpoints.

The token is injected by systemd via EnvironmentFile=/etc/eternal-vanguard.env.
It is read at module import time; if missing, requests will fail with 500
rather than silently allowing anything through.
"""
import os
import secrets
from fastapi import Header, HTTPException, status

INGEST_TOKEN = os.environ.get("INGEST_TOKEN")


def require_ingest_token(authorization: str = Header(...)) -> None:
    """
    FastAPI dependency. Expects `Authorization: Bearer <token>` to match
    INGEST_TOKEN exactly. Constant-time comparison via secrets.compare_digest.
    """
    if INGEST_TOKEN is None:
        # Server-side misconfiguration -- don't leak this to the caller.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion not configured.",
        )
    expected = f"Bearer {INGEST_TOKEN}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
