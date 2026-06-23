"""
ORM models for the Eternal Vanguard dashboard.

Design notes
------------
- Farlight exports are kingdom-wide (~370 rows for K193). Only ~142 of
  those players belong to our alliance. We store everything and use
  members.in_alliance to filter at query time.
- character_id is the Farlight stable key. Names change; IDs don't.
  All foreign keys point at the ID, never the name.
- stats is append-only. Each snapshot creates fresh rows; we never
  update an existing stat row.
"""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, ForeignKey,
    DateTime, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Alliance(Base):
    __tablename__ = "alliances"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    kingdom_number: Mapped[int] = mapped_column(Integer)
    tag: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    members: Mapped[list["Member"]] = relationship(back_populates="alliance")


class Member(Base):
    __tablename__ = "members"

    character_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    current_name: Mapped[str] = mapped_column(String(128))
    alliance_id: Mapped[int | None] = mapped_column(
        ForeignKey("alliances.id"), nullable=True
    )
    in_alliance: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    alliance: Mapped[Alliance | None] = relationship(back_populates="members")
    stats: Mapped[list["Stat"]] = relationship(back_populates="member")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_filename: Mapped[str] = mapped_column(String(256))
    row_count: Mapped[int] = mapped_column(Integer)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    stats: Mapped[list["Stat"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class Stat(Base):
    """
    One row from a Farlight export.

    Field mapping from the French raw headers:
      rank        <- Rang
      power       <- Puissance actuelle
      peak_power  <- Plus haute puissance historique
      deaths_t45  <- Morts (T4/T5)
      merits      <- Merites par type d'unite
      harvest     <- Recolte
      healing_t45 <- Guerison (T4/T5)
    """
    __tablename__ = "stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE")
    )
    character_id: Mapped[str] = mapped_column(ForeignKey("members.character_id"))

    rank: Mapped[int] = mapped_column(Integer)
    power: Mapped[int] = mapped_column(BigInteger)
    peak_power: Mapped[int] = mapped_column(BigInteger)
    deaths_t45: Mapped[int] = mapped_column(BigInteger)
    merits: Mapped[int] = mapped_column(BigInteger)
    harvest: Mapped[int] = mapped_column(BigInteger)
    healing_t45: Mapped[int] = mapped_column(BigInteger)

    snapshot: Mapped[Snapshot] = relationship(back_populates="stats")
    member: Mapped[Member] = relationship(back_populates="stats")

    __table_args__ = (
        UniqueConstraint("snapshot_id", "character_id", name="uq_snapshot_member"),
        Index("ix_stats_snapshot_character", "snapshot_id", "character_id"),
    )
