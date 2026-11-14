"""Server-side admin commands. Run on the web service: `railway ssh -s web` then `python -m app.cli reset-password`.

reset-password [email]   set a new password (typed hidden), optionally clear 2FA. No email = lists admins.
"""
from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app import auth
from app.db import SessionLocal
from app.models import User


def reset_password(email: str = "") -> int:
    with SessionLocal() as s:
        if not email:
            for u in s.scalars(select(User).where(User.role == "admin")):
                print(f"admin: {u.email}{'' if u.active else ' (inactive)'}")
            email = input("Email to reset: ").strip()
        u = s.scalar(select(User).where(User.email == email.strip().lower()))
        if u is None:
            print("No user with that email.")
            return 1
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat it: "):
            print("Passwords don't match, nothing changed.")
            return 1
        if auth.password_problem(pw):
            print("Rejected:", auth.password_problem(pw).replace("+", " "))
            return 1
        u.password_hash, u.active = auth.hash_password(pw), True
        if u.totp_secret and input("Also turn off 2FA for this user? [y/N] ").strip().lower() == "y":
            u.totp_secret = ""
        s.commit()
        print(f"Password updated for {u.email}. Log in at /login.")
        return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["reset-password"]:
        sys.exit(reset_password(args[1] if len(args) > 1 else ""))
    print(__doc__)
