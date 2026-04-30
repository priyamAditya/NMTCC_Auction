import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt

from db import get_cursor

SESSION_TTL = timedelta(days=7)


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def has_any_admin() -> bool:
    with get_cursor() as cur:
        cur.execute("SELECT 1 FROM admins LIMIT 1")
        return cur.fetchone() is not None


def create_admin(username: str, password: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
            (username.strip(), _hash(password)),
        )


def check_admin(username: str, password: str) -> bool:
    with get_cursor() as cur:
        cur.execute("SELECT password_hash FROM admins WHERE username = %s", (username.strip(),))
        row = cur.fetchone()
    if not row:
        return False
    return _verify(password, row["password_hash"])


# ---------------- Persistent session tokens ----------------

def create_session(username: str) -> tuple[str, datetime]:
    """Insert a random session token for this admin and return (token, expires_at)."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (token, username, expires_at) VALUES (%s, %s, %s)",
            (token, username.strip(), expires_at),
        )
    return token, expires_at


def lookup_session(token: Optional[str]) -> Optional[str]:
    """Return the username if the token is valid and unexpired, else None."""
    if not token:
        return None
    with get_cursor() as cur:
        cur.execute(
            "SELECT username FROM sessions WHERE token = %s AND expires_at > NOW()",
            (token,),
        )
        row = cur.fetchone()
    return row["username"] if row else None


def delete_session(token: Optional[str]) -> None:
    if not token:
        return
    with get_cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))


def cleanup_expired_sessions() -> None:
    with get_cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE expires_at < NOW()")
