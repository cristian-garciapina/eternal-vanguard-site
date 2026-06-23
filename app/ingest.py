"""
Excel ingestion pipeline for Farlight K193 exports.

Endpoint
--------
POST /api/ingest
    multipart/form-data with field `file` containing the Farlight Excel
    export. Bearer-token authenticated.

Parser
------
Tolerant on filename, strict on the 9-column French header layout from
the Farlight kingdom-wide export. Header mapping (FR -> EN) is normalized
via casefold + accent stripping so 'Merites' and 'Merites' match alike.

Flow
----
1. Read upload bytes into openpyxl (read_only=True keeps memory flat).
2. Validate the 9 expected headers; abort 400 on mismatch.
3. Extract taken_at from filename (YYYY-MM-DD regex), fallback to now.
4. Reject 409 if a snapshot with same (filename, taken_at) already exists.
5. Upsert members (insert new character_ids, refresh current_name/last_seen).
6. Bulk-insert stat rows for the new snapshot.
7. Return JSON summary.
"""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Member, Snapshot, Stat
from .security import require_ingest_token

router = APIRouter(prefix="/api", tags=["ingest"])

# Header mapping: normalized FR header -> internal field name
HEADER_MAP = {
    "rang": "rank",
    "identifiant du personnage": "character_id",
    "nom du personnage": "current_name",
    "puissance actuelle": "power",
    "plus haute puissance historique": "peak_power",
    "morts (t4/t5)": "deaths_t45",
    "merites par type d'unite": "merits",
    "recolte": "harvest",
    "guerison (t4/t5)": "healing_t45",
}
EXPECTED_FIELDS = set(HEADER_MAP.values())
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _normalize(s) -> str:
    """Lowercase, strip accents (NFKD + drop combining marks), collapse ws."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _to_int(v) -> int:
    """Coerce Excel cell (str/int/float/None) to int. None -> 0."""
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(float(v))


def _extract_taken_at(filename: str) -> datetime:
    """Pull YYYY-MM-DD from filename, default to UTC now."""
    m = _DATE_RE.search(filename or "")
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _parse_workbook(content: bytes):
    """Parse Excel bytes -> (rows: list[dict], warnings: list[str])."""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise HTTPException(400, f"Could not open workbook: {exc}")

    ws = wb.active
    iterator = ws.iter_rows(values_only=True)

    try:
        raw_headers = next(iterator)
    except StopIteration:
        raise HTTPException(400, "Empty workbook.")

    column_fields = [HEADER_MAP.get(_normalize(h)) for h in raw_headers]
    found = {f for f in column_fields if f is not None}
    missing = EXPECTED_FIELDS - found
    if missing:
        raise HTTPException(
            400,
            f"Missing expected columns: {sorted(missing)}. "
            f"Got headers: {list(raw_headers)}",
        )

    rows, warnings = [], []
    for row_idx, row in enumerate(iterator, start=2):
        if row is None or all(v is None or v == "" for v in row):
            continue
        record = {}
        for field, cell in zip(column_fields, row):
            if field is None:
                continue
            if field in {"character_id", "current_name"}:
                record[field] = str(cell).strip() if cell is not None else ""
            else:
                record[field] = _to_int(cell)
        if not record.get("character_id"):
            warnings.append(f"Row {row_idx}: missing character_id, skipped.")
            continue
        if not record.get("current_name"):
            record["current_name"] = f"Lord{record['character_id']}"
        rows.append(record)

    if not rows:
        raise HTTPException(400, "No data rows found after the header.")
    return rows, warnings


@router.post(
    "/ingest",
    dependencies=[Depends(require_ingest_token)],
    status_code=status.HTTP_201_CREATED,
)
async def ingest_snapshot(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    """Ingest one Farlight Excel export as a new snapshot."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty upload.")

    rows, warnings = _parse_workbook(content)
    taken_at = _extract_taken_at(file.filename or "")
    fname = file.filename or ""

    # Idempotence guard: same file, same date -> reject
    dup = db.execute(
        select(Snapshot).where(
            Snapshot.source_filename == fname,
            Snapshot.taken_at == taken_at,
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            409,
            f"Snapshot already ingested (id={dup.id}, "
            f"taken_at={dup.taken_at.isoformat()}).",
        )

    now = datetime.now(timezone.utc)
    char_ids = [r["character_id"] for r in rows]
    existing = {
        m.character_id: m
        for m in db.execute(
            select(Member).where(Member.character_id.in_(char_ids))
        ).scalars()
    }

    created = updated = 0
    for r in rows:
        m = existing.get(r["character_id"])
        if m is None:
            db.add(Member(
                character_id=r["character_id"],
                current_name=r["current_name"],
                in_alliance=False,
                first_seen_at=now,
                last_seen_at=now,
            ))
            created += 1
        else:
            if m.current_name != r["current_name"]:
                m.current_name = r["current_name"]
            m.last_seen_at = now
            updated += 1
    db.flush()

    snap = Snapshot(
        taken_at=taken_at,
        source_filename=fname,
        row_count=len(rows),
    )
    db.add(snap)
    db.flush()

    db.bulk_save_objects([
        Stat(
            snapshot_id=snap.id,
            character_id=r["character_id"],
            rank=r["rank"],
            power=r["power"],
            peak_power=r["peak_power"],
            deaths_t45=r["deaths_t45"],
            merits=r["merits"],
            harvest=r["harvest"],
            healing_t45=r["healing_t45"],
        )
        for r in rows
    ])
    db.commit()

    return {
        "snapshot_id": snap.id,
        "taken_at": taken_at.isoformat(),
        "source_filename": fname,
        "row_count": len(rows),
        "members_created": created,
        "members_updated": updated,
        "warnings": warnings,
    }
