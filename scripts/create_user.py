"""Create or update a user account.

Usage:
    python -m scripts.create_user <username> <role>

Reads the password interactively. Role is 'staff' or 'member'.
"""
import getpass
import sys
from datetime import datetime

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User
from sqlalchemy import select


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.create_user <username> <role>")
        sys.exit(1)

    username = sys.argv[1].lower().strip()
    role = sys.argv[2].lower().strip()
    if role not in ("staff", "member"):
        print("role must be 'staff' or 'member'")
        sys.exit(1)

    pw1 = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Confirm:  ")
    if pw1 != pw2:
        print("Passwords don't match.")
        sys.exit(1)
    if len(pw1) < 10:
        print("Password too short (min 10 chars).")
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.username == username))
        if existing:
            existing.password_hash = hash_password(pw1)
            existing.role = role
            existing.is_active = True
            db.commit()
            print(f"Updated user '{username}' (role={role}).")
        else:
            user = User(
                username=username,
                password_hash=hash_password(pw1),
                role=role,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            db.add(user)
            db.commit()
            print(f"Created user '{username}' (role={role}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
