import bcrypt

from db import get_cursor


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
