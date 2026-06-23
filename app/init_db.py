"""
One-shot DB initializer. Idempotent: safe to run multiple times.

Usage (from /opt/dashboard):
    python -m app.init_db
"""
from sqlalchemy import select
from .db import engine, SessionLocal, Base, DB_PATH
from .models import Alliance


def main() -> None:
    print(f"DB file: {DB_PATH}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Creating tables...")
    Base.metadata.create_all(engine)

    print("Seeding Eternal Vanguard alliance row...")
    with SessionLocal() as db:
        existing = db.execute(
            select(Alliance).where(Alliance.name == "Eternal Vanguard")
        ).scalar_one_or_none()

        if existing:
            print(f"  -> already present (id={existing.id}), nothing to do.")
        else:
            ev = Alliance(name="Eternal Vanguard", kingdom_number=193, tag="EV")
            db.add(ev)
            db.commit()
            print(f"  -> created Eternal Vanguard (id={ev.id}, kingdom=193)")

    print("Done.")


if __name__ == "__main__":
    main()
