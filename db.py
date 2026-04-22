import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams_master (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    captain TEXT,
    color TEXT NOT NULL,
    text_color TEXT NOT NULL DEFAULT '#ffffff',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE teams_master ADD COLUMN IF NOT EXISTS text_color TEXT NOT NULL DEFAULT '#ffffff';

CREATE TABLE IF NOT EXISTS auctions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    auction_datetime TIMESTAMPTZ NOT NULL,
    players_per_team INT NOT NULL,
    purse INT NOT NULL,
    rtm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rtm_count INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'setup',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
    order_index INT
);

ALTER TABLE auction_players ADD COLUMN IF NOT EXISTS order_index INT;

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

def list_master_teams():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, captain, color, text_color FROM teams_master ORDER BY name")
        return cur.fetchall()


def get_master_team_by_name(name: str):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, captain, color, text_color FROM teams_master WHERE name = %s",
            (name,),
        )
        return cur.fetchone()


def create_master_team(name: str, captain: str, color: str, text_color: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO teams_master (name, captain, color, text_color) VALUES (%s, %s, %s, %s) RETURNING id",
            (name, captain, color, text_color),
        )
        return cur.fetchone()["id"]


# ---------- auctions ----------

def create_auction(
    auction_id: str,
    name: str,
    auction_datetime,
    players_per_team: int,
    purse: int,
    rtm_enabled: bool,
    rtm_count: int,
) -> str:
    """Insert with a caller-supplied UUID so the UI doesn't block on this round-trip."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO auctions (id, name, auction_datetime, players_per_team, purse, rtm_enabled, rtm_count, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
            """,
            (auction_id, name, auction_datetime, players_per_team, purse, rtm_enabled, rtm_count),
        )
        return auction_id


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
    # rows: iterable of (name, set_name, base_price, order_index)
    with get_cursor(dict_cursor=False) as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO auction_players (auction_id, name, set_name, base_price, order_index) VALUES %s",
            [(auction_id, n, s, int(b), int(oi)) for (n, s, b, oi) in rows],
        )


def update_auction_status(auction_id: str, status: str) -> None:
    with get_cursor() as cur:
        cur.execute("UPDATE auctions SET status = %s WHERE id = %s", (status, auction_id))


def list_auctions():
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, auction_datetime, status FROM auctions ORDER BY auction_datetime DESC LIMIT 50"
        )
        return cur.fetchall()


def get_auction(auction_id: str):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, name, auction_datetime, players_per_team, purse, rtm_enabled, rtm_count, status "
            "FROM auctions WHERE id = %s",
            (auction_id,),
        )
        return cur.fetchone()


def get_auction_teams_full(auction_id: str):
    """Join auction_teams with teams_master so we have everything needed to render."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT at.team_id, at.remaining_purse, at.rtm_remaining,
                   tm.name, tm.captain, tm.color, tm.text_color
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
            SELECT id, name, set_name, base_price, order_index
            FROM auction_players
            WHERE auction_id = %s
            ORDER BY COALESCE(order_index, id)
            """,
            (auction_id,),
        )
        return cur.fetchall()


def get_auction_results_detailed(auction_id: str):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ar.id, ar.team_id, ar.sold_price, ar.is_rtm, ar.created_at,
                   ap.name AS player_name, ap.set_name, ap.base_price,
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
