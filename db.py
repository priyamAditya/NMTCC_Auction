import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# Local dev: .env via python-dotenv. Streamlit Community Cloud: secrets.toml
# entry surfaced through st.secrets. Either is fine; env wins if both set.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    try:
        import streamlit as st  # imported lazily to avoid a hard dep here

        DATABASE_URL = st.secrets.get("DATABASE_URL")  # type: ignore[attr-defined]
    except Exception:
        DATABASE_URL = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS players_master (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    mobile TEXT,
    email TEXT,
    role TEXT,
    dob DATE,
    photo BYTEA,
    photo_mime TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE players_master DROP COLUMN IF EXISTS base_price;

-- Case-insensitive uniqueness only when the field is populated
CREATE UNIQUE INDEX IF NOT EXISTS ux_players_mobile
    ON players_master (LOWER(mobile)) WHERE mobile IS NOT NULL AND mobile <> '';
CREATE UNIQUE INDEX IF NOT EXISTS ux_players_email
    ON players_master (LOWER(email)) WHERE email IS NOT NULL AND email <> '';

CREATE TABLE IF NOT EXISTS teams_master (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    captain TEXT,
    captain_id INT,
    color TEXT NOT NULL,
    text_color TEXT NOT NULL DEFAULT '#ffffff',
    logo BYTEA,
    logo_mime TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE teams_master ADD COLUMN IF NOT EXISTS text_color TEXT NOT NULL DEFAULT '#ffffff';
ALTER TABLE teams_master ADD COLUMN IF NOT EXISTS logo BYTEA;
ALTER TABLE teams_master ADD COLUMN IF NOT EXISTS logo_mime TEXT;
ALTER TABLE teams_master ADD COLUMN IF NOT EXISTS captain_id INT;

CREATE TABLE IF NOT EXISTS tournaments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    logo BYTEA,
    logo_mime TEXT,
    banner BYTEA,
    banner_mime TEXT,
    link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auctions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    auction_datetime TIMESTAMPTZ NOT NULL,
    players_per_team INT NOT NULL,
    purse INT NOT NULL,
    rtm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rtm_count INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'setup',
    bid_tiers JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE auctions ADD COLUMN IF NOT EXISTS bid_tiers JSONB;
ALTER TABLE auctions ADD COLUMN IF NOT EXISTS tournament_id UUID REFERENCES tournaments(id);

CREATE TABLE IF NOT EXISTS auction_teams (
    auction_id UUID REFERENCES auctions(id) ON DELETE CASCADE,
    team_id INT REFERENCES teams_master(id),
    remaining_purse INT NOT NULL,
    rtm_remaining INT NOT NULL DEFAULT 0,
    PRIMARY KEY (auction_id, team_id)
);

CREATE TABLE IF NOT EXISTS auction_players (
    id SERIAL PRIMARY KEY,
    auction_id UUID REFERENCES auctions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    set_name TEXT,
    base_price INT NOT NULL,
    order_index INT,
    is_captain BOOLEAN NOT NULL DEFAULT FALSE,
    unsold BOOLEAN NOT NULL DEFAULT FALSE,
    released BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE auction_players ADD COLUMN IF NOT EXISTS order_index INT;
ALTER TABLE auction_players ADD COLUMN IF NOT EXISTS is_captain BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE auction_players ADD COLUMN IF NOT EXISTS unsold BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE auction_players ADD COLUMN IF NOT EXISTS released BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS auction_results (
    id SERIAL PRIMARY KEY,
    auction_id UUID REFERENCES auctions(id) ON DELETE CASCADE,
    player_id INT REFERENCES auction_players(id),
    team_id INT REFERENCES teams_master(id),
    sold_price INT NOT NULL,
    is_rtm BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Put it in .env")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor(dict_cursor: bool = True):
    with get_conn() as conn:
        factory = psycopg2.extras.RealDictCursor if dict_cursor else None
        cur = conn.cursor(cursor_factory=factory)
        try:
            yield cur
        finally:
            cur.close()


_schema_ready = False
_schema_lock = threading.Lock()


def init_schema() -> None:
    """Idempotent; safe to call on every rerun. Network call only runs once per process."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with get_cursor(dict_cursor=False) as cur:
            cur.execute(SCHEMA_SQL)
        _schema_ready = True


# ---------- teams master ----------

_TEAM_COLS = "id, name, captain, captain_id, color, text_color, logo, logo_mime"


def list_master_teams():
    with get_cursor() as cur:
        cur.execute(f"SELECT {_TEAM_COLS} FROM teams_master ORDER BY name")
        return cur.fetchall()


def get_master_team_by_name(name: str):
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_TEAM_COLS} FROM teams_master WHERE name = %s",
            (name,),
        )
        return cur.fetchone()


def update_master_team_logo(team_id: int, logo_bytes, logo_mime: str | None) -> None:
    """logo_bytes=None clears the logo."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE teams_master SET logo = %s, logo_mime = %s WHERE id = %s",
            (
                psycopg2.Binary(logo_bytes) if logo_bytes else None,
                logo_mime if logo_bytes else None,
                team_id,
            ),
        )


def create_master_team(
    name: str,
    captain: str,
    color: str,
    text_color: str,
    captain_id: int | None = None,
) -> int:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO teams_master (name, captain, captain_id, color, text_color) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (name, captain, captain_id, color, text_color),
        )
        return cur.fetchone()["id"]


def update_master_team(
    team_id: int,
    name: str,
    captain: str,
    color: str,
    text_color: str,
    captain_id: int | None = None,
) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE teams_master SET name = %s, captain = %s, captain_id = %s, "
            "color = %s, text_color = %s WHERE id = %s",
            (name, captain, captain_id, color, text_color, team_id),
        )


# ---------- players master ----------

_PLAYER_COLS = "id, name, mobile, email, role, dob, photo, photo_mime, notes, created_at"


def _normalize_optional(s):
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def list_players(search: str | None = None):
    with get_cursor() as cur:
        if search:
            q = f"%{search.strip().lower()}%"
            cur.execute(
                f"SELECT {_PLAYER_COLS} FROM players_master "
                f"WHERE LOWER(name) LIKE %s OR LOWER(COALESCE(mobile,'')) LIKE %s "
                f"OR LOWER(COALESCE(email,'')) LIKE %s "
                f"ORDER BY name",
                (q, q, q),
            )
        else:
            cur.execute(f"SELECT {_PLAYER_COLS} FROM players_master ORDER BY name")
        return cur.fetchall()


def get_player(player_id: int):
    with get_cursor() as cur:
        cur.execute(f"SELECT {_PLAYER_COLS} FROM players_master WHERE id = %s", (player_id,))
        return cur.fetchone()


def _check_player_unique(mobile: str | None, email: str | None, exclude_id: int | None = None):
    """Raise ValueError with a friendly message if another player has this mobile/email."""
    checks = []
    params: list = []
    if mobile:
        checks.append("LOWER(mobile) = LOWER(%s)")
        params.append(mobile)
    if email:
        checks.append("LOWER(email) = LOWER(%s)")
        params.append(email)
    if not checks:
        return
    where = " OR ".join(checks)
    if exclude_id is not None:
        where = f"({where}) AND id <> %s"
        params.append(exclude_id)
    with get_cursor() as cur:
        cur.execute(
            f"SELECT id, mobile, email FROM players_master WHERE {where} LIMIT 1",
            tuple(params),
        )
        row = cur.fetchone()
    if row:
        if mobile and row.get("mobile") and mobile.lower() == (row["mobile"] or "").lower():
            raise ValueError(f"Mobile {mobile} is already registered")
        raise ValueError(f"Email {email} is already registered")


def create_player(
    name: str,
    mobile: str | None = None,
    email: str | None = None,
    role: str | None = None,
    dob=None,
    notes: str | None = None,
) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Name is required")
    mobile = _normalize_optional(mobile)
    email = _normalize_optional(email)
    _check_player_unique(mobile, email)
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO players_master (name, mobile, email, role, dob, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (name, mobile, email, _normalize_optional(role), dob, _normalize_optional(notes)),
        )
        return cur.fetchone()["id"]


def update_player(
    player_id: int,
    name: str,
    mobile: str | None,
    email: str | None,
    role: str | None,
    dob,
    notes: str | None,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Name is required")
    mobile = _normalize_optional(mobile)
    email = _normalize_optional(email)
    _check_player_unique(mobile, email, exclude_id=player_id)
    with get_cursor() as cur:
        cur.execute(
            "UPDATE players_master SET name=%s, mobile=%s, email=%s, role=%s, "
            "dob=%s, notes=%s WHERE id = %s",
            (
                name,
                mobile,
                email,
                _normalize_optional(role),
                dob,
                _normalize_optional(notes),
                player_id,
            ),
        )


def update_player_photo(player_id: int, photo_bytes, photo_mime: str | None) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE players_master SET photo = %s, photo_mime = %s WHERE id = %s",
            (
                psycopg2.Binary(photo_bytes) if photo_bytes else None,
                photo_mime if photo_bytes else None,
                player_id,
            ),
        )


def get_player_auctions(player_id: int):
    """Auctions where this master-player was sold, via auction_results → auction_players.name join."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.name AS auction_name, a.auction_datetime, a.status,
                   ar.sold_price, ar.is_rtm,
                   tm.name AS team_name, tm.color AS team_color, tm.text_color AS team_text_color
            FROM players_master pm
            JOIN auction_players ap ON LOWER(ap.name) = LOWER(pm.name)
            JOIN auction_results ar ON ar.player_id = ap.id
            JOIN auctions a ON a.id = ar.auction_id
            JOIN teams_master tm ON tm.id = ar.team_id
            WHERE pm.id = %s
            ORDER BY a.auction_datetime DESC
            """,
            (player_id,),
        )
        return cur.fetchall()


def get_team_auctions(team_id: int):
    """Auctions this team participated in, newest first."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.name, a.auction_datetime, a.status,
                   at.remaining_purse, at.rtm_remaining
            FROM auction_teams at
            JOIN auctions a ON a.id = at.auction_id
            WHERE at.team_id = %s
            ORDER BY a.auction_datetime DESC
            """,
            (team_id,),
        )
        return cur.fetchall()


# ---------- tournaments ----------

_TOURNAMENT_COLS = "id, name, logo, logo_mime, banner, banner_mime, link, created_at"


def list_tournaments():
    with get_cursor() as cur:
        cur.execute(f"SELECT {_TOURNAMENT_COLS} FROM tournaments ORDER BY name")
        return cur.fetchall()


def get_tournament(tournament_id: str):
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_TOURNAMENT_COLS} FROM tournaments WHERE id = %s",
            (tournament_id,),
        )
        return cur.fetchone()


def get_tournament_by_name(name: str):
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {_TOURNAMENT_COLS} FROM tournaments WHERE LOWER(name) = LOWER(%s)",
            (name,),
        )
        return cur.fetchone()


def create_tournament(name: str, link: str | None = None) -> str:
    nn = (name or "").strip()
    if not nn:
        raise ValueError("Tournament name required")
    existing = get_tournament_by_name(nn)
    if existing:
        raise ValueError(f"Tournament '{nn}' already exists")
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO tournaments (name, link) VALUES (%s, %s) RETURNING id",
            (nn, (link or "").strip() or None),
        )
        return str(cur.fetchone()["id"])


def update_tournament(tournament_id: str, name: str, link: str | None) -> None:
    nn = (name or "").strip()
    if not nn:
        raise ValueError("Tournament name required")
    # Enforce uniqueness excluding this id
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM tournaments WHERE LOWER(name) = LOWER(%s) AND id <> %s",
            (nn, tournament_id),
        )
        if cur.fetchone():
            raise ValueError(f"Another tournament is already named '{nn}'")
        cur.execute(
            "UPDATE tournaments SET name = %s, link = %s WHERE id = %s",
            (nn, (link or "").strip() or None, tournament_id),
        )


def update_tournament_logo(tournament_id: str, logo_bytes, logo_mime: str | None) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE tournaments SET logo = %s, logo_mime = %s WHERE id = %s",
            (
                psycopg2.Binary(logo_bytes) if logo_bytes else None,
                logo_mime if logo_bytes else None,
                tournament_id,
            ),
        )


def update_tournament_banner(tournament_id: str, banner_bytes, banner_mime: str | None) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE tournaments SET banner = %s, banner_mime = %s WHERE id = %s",
            (
                psycopg2.Binary(banner_bytes) if banner_bytes else None,
                banner_mime if banner_bytes else None,
                tournament_id,
            ),
        )


def list_tournament_auctions(tournament_id: str):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, auction_datetime, status, tournament_id
            FROM auctions
            WHERE tournament_id = %s
            ORDER BY auction_datetime DESC
            """,
            (tournament_id,),
        )
        return cur.fetchall()


# ---------- auctions ----------

def create_auction(
    auction_id: str,
    name: str,
    auction_datetime,
    players_per_team: int,
    purse: int,
    rtm_enabled: bool,
    rtm_count: int,
    bid_tiers=None,
    tournament_id: str | None = None,
) -> str:
    """Insert with a caller-supplied UUID so the UI doesn't block on this round-trip."""
    tiers_json = psycopg2.extras.Json(bid_tiers) if bid_tiers is not None else None
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO auctions (id, name, auction_datetime, players_per_team, purse,
                                  rtm_enabled, rtm_count, bid_tiers, tournament_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
            """,
            (auction_id, name, auction_datetime, players_per_team, purse,
             rtm_enabled, rtm_count, tiers_json, tournament_id),
        )
        return auction_id


def update_bid_tiers(auction_id: str, bid_tiers) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE auctions SET bid_tiers = %s WHERE id = %s",
            (psycopg2.extras.Json(bid_tiers), auction_id),
        )


def add_auction_team(auction_id: str, team_id: int, purse: int, rtm_remaining: int) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO auction_teams (auction_id, team_id, remaining_purse, rtm_remaining)
            VALUES (%s, %s, %s, %s)
            """,
            (auction_id, team_id, purse, rtm_remaining),
        )


def add_auction_players(auction_id: str, rows) -> None:
    """Insert auction players. Each row: (name, set_name, base_price, order_index)
    OR (name, set_name, base_price, order_index, is_captain)."""
    normalized = []
    for row in rows:
        if len(row) == 4:
            n, s, b, oi = row
            is_cap = False
        else:
            n, s, b, oi, is_cap = row
        normalized.append((auction_id, n, s, int(b), int(oi), bool(is_cap)))
    with get_cursor(dict_cursor=False) as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO auction_players (auction_id, name, set_name, base_price, order_index, is_captain) VALUES %s",
            normalized,
        )


def update_auction_status(auction_id: str, status: str) -> None:
    with get_cursor() as cur:
        cur.execute("UPDATE auctions SET status = %s WHERE id = %s", (status, auction_id))


def list_auctions():
    """Return auctions with the tournament name (canonical) used as the display name."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, COALESCE(t.name, a.name) AS name,
                   a.auction_datetime, a.status, a.tournament_id
            FROM auctions a
            LEFT JOIN tournaments t ON t.id = a.tournament_id
            ORDER BY a.auction_datetime DESC
            LIMIT 50
            """
        )
        return cur.fetchall()


def get_auction(auction_id: str):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.id, COALESCE(t.name, a.name) AS name, a.auction_datetime,
                   a.players_per_team, a.purse, a.rtm_enabled, a.rtm_count,
                   a.status, a.bid_tiers, a.tournament_id,
                   t.logo AS tournament_logo, t.logo_mime AS tournament_logo_mime,
                   t.banner AS tournament_banner, t.banner_mime AS tournament_banner_mime,
                   t.link AS tournament_link
            FROM auctions a
            LEFT JOIN tournaments t ON t.id = a.tournament_id
            WHERE a.id = %s
            """,
            (auction_id,),
        )
        return cur.fetchone()


def get_auction_teams_full(auction_id: str):
    """Join auction_teams with teams_master so we have everything needed to render."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT at.team_id, at.remaining_purse, at.rtm_remaining,
                   tm.name, tm.captain, tm.color, tm.text_color, tm.logo, tm.logo_mime
            FROM auction_teams at
            JOIN teams_master tm ON tm.id = at.team_id
            WHERE at.auction_id = %s
            ORDER BY tm.name
            """,
            (auction_id,),
        )
        return cur.fetchall()


def get_auction_players_ordered(auction_id: str):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, set_name, base_price, order_index, is_captain, unsold, released
            FROM auction_players
            WHERE auction_id = %s
            ORDER BY COALESCE(order_index, id)
            """,
            (auction_id,),
        )
        return cur.fetchall()


def mark_player_unsold(auction_id: str, player_name: str, is_unsold: bool = True) -> None:
    """Park (or un-park) a player in the unsold bucket. Persisted so a refresh
    or a resume rebuilds the bucket faithfully."""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE auction_players
            SET unsold = %s
            WHERE auction_id = %s
              AND LOWER(name) = LOWER(%s)
              AND is_captain = FALSE
            """,
            (bool(is_unsold), auction_id, player_name),
        )


def mark_player_released(auction_id: str, player_name: str) -> None:
    """Player was popped from the unsold bucket without being sold. Marking
    'released' keeps them out of the bucket on resume without unwinding the
    unsold flag (which set_index uses to know main-phase advanced past them)."""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE auction_players
            SET released = TRUE
            WHERE auction_id = %s
              AND LOWER(name) = LOWER(%s)
              AND is_captain = FALSE
            """,
            (auction_id, player_name),
        )


def get_auction_results_detailed(auction_id: str):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ar.id, ar.team_id, ar.sold_price, ar.is_rtm, ar.created_at,
                   ap.name AS player_name, ap.set_name, ap.base_price, ap.is_captain,
                   tm.name AS team_name
            FROM auction_results ar
            JOIN auction_players ap ON ap.id = ar.player_id
            JOIN teams_master tm ON tm.id = ar.team_id
            WHERE ar.auction_id = %s
            ORDER BY ar.created_at, ar.id
            """,
            (auction_id,),
        )
        return cur.fetchall()


def update_player_team(auction_id: str, player_name: str, new_team_id: int) -> None:
    """Move a player to a new team — used by trades. Updates ALL result rows
    for that player in this auction. Purse is not touched."""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE auction_results
            SET team_id = %s
            WHERE auction_id = %s AND player_id IN (
                SELECT id FROM auction_players
                WHERE auction_id = %s AND LOWER(name) = LOWER(%s)
            )
            """,
            (new_team_id, auction_id, auction_id, player_name),
        )


def record_captain_enrollment(auction_id: str, captain_name: str, team_id: int, cap_value: int) -> None:
    """Captain is auto-assigned to their team at auction start. No purse deduction;
    just writes a result row so the roster persists for resume and reports."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM auction_players WHERE auction_id = %s AND name = %s AND is_captain = TRUE",
            (auction_id, captain_name),
        )
        row = cur.fetchone()
        player_id = row["id"] if row else None
        cur.execute(
            """
            INSERT INTO auction_results (auction_id, player_id, team_id, sold_price, is_rtm)
            VALUES (%s, %s, %s, %s, FALSE)
            """,
            (auction_id, player_id, team_id, cap_value),
        )


def record_sale(auction_id: str, player_name: str, team_id: int, sold_price: int, is_rtm: bool) -> None:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM auction_players WHERE auction_id = %s AND name = %s",
            (auction_id, player_name),
        )
        row = cur.fetchone()
        player_id = row["id"] if row else None
        cur.execute(
            """
            INSERT INTO auction_results (auction_id, player_id, team_id, sold_price, is_rtm)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (auction_id, player_id, team_id, sold_price, is_rtm),
        )
        cur.execute(
            "UPDATE auction_teams SET remaining_purse = remaining_purse - %s WHERE auction_id = %s AND team_id = %s",
            (sold_price, auction_id, team_id),
        )
        if is_rtm:
            cur.execute(
                "UPDATE auction_teams SET rtm_remaining = rtm_remaining - 1 WHERE auction_id = %s AND team_id = %s",
                (auction_id, team_id),
            )
