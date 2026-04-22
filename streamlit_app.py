import html
import random
import urllib.parse
import uuid
from datetime import date, datetime, time
from io import BytesIO

import pandas as pd
import streamlit as st

import extra_streamlit_components as stx
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, GridUpdateMode

from auth import (
    check_admin,
    create_admin,
    create_session,
    delete_session,
    has_any_admin,
    lookup_session,
)
from db import (
    add_auction_players,
    add_auction_team,
    create_auction,
    create_master_team,
    create_player,
    get_auction,
    get_auction_players_ordered,
    get_auction_results_detailed,
    get_auction_teams_full,
    get_master_team_by_name,
    get_player,
    get_player_auctions,
    get_team_auctions,
    init_schema,
    list_auctions,
    list_master_teams,
    list_players,
    record_captain_enrollment,
    record_sale,
    update_auction_status,
    update_bid_tiers,
    update_master_team,
    update_master_team_logo,
    update_player,
    update_player_photo,
)
from logos import avatar_html, logo_data_uri, process_uploaded_logo
from event_log import log_event, read_events
from sync_queue import enqueue, stats as sync_stats


# ---------------- Bid ladder ----------------
DEFAULT_BID_TIERS = [
    {"up_to": 15, "step": 2},
    {"up_to": 40, "step": 5},
    {"up_to": 10000, "step": 10},  # effectively unbounded
]


def step_for_bid(current_bid: int, tiers: list[dict]) -> int:
    for tier in tiers:
        if current_bid < int(tier["up_to"]):
            return int(tier["step"])
    return int(tiers[-1]["step"])

st.set_page_config(page_title="NMTCC Auction", layout="wide", page_icon="🏏")

# Global styles
st.markdown(
    """
    <style>
    /* Tighter top padding — default is ~6rem of whitespace. */
    .block-container { padding-top: 1.4rem !important; padding-bottom: 2rem !important; }
    header[data-testid="stHeader"] { height: 0; visibility: hidden; }

    .hero-title { font-size: 3.2rem; font-weight: 800; text-align: center; margin: 0; letter-spacing: 2px; }
    .hero-sub { font-size: 1.2rem; text-align: center; color: #888; margin-top: 0.3rem; margin-bottom: 1.2rem; }
    .purse-badge {
        background: linear-gradient(135deg, #f59e0b, #ef4444);
        color: white; padding: 1.2rem 2rem; border-radius: 14px;
        text-align: center; margin-bottom: 1.2rem;
    }
    .purse-badge .label { font-size: 0.9rem; opacity: 0.9; text-transform: uppercase; letter-spacing: 2px; }
    .purse-badge .value { font-size: 3rem; font-weight: 800; line-height: 1.1; }
    .team-chip {
        display: inline-block; padding: 0.4rem 0.9rem; border-radius: 999px;
        font-weight: 600; margin: 0.25rem 0.3rem 0.25rem 0;
        text-decoration: none;
        transition: transform 0.12s ease, box-shadow 0.12s ease, opacity 0.12s ease;
    }
    a.team-chip { cursor: pointer; }
    a.team-chip:hover {
        opacity: 0.9;
        box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.6);
        transform: translateY(-1px);
    }
    a.team-chip:hover .chip-x { opacity: 1; }
    .chip-x {
        margin-left: 0.5rem; font-weight: 700; opacity: 0.65;
        border-left: 1px solid rgba(255,255,255,0.35); padding-left: 0.5rem;
    }
    .team-head {
        display: inline-block; padding: 0.3rem 0.8rem; border-radius: 8px;
        font-weight: 700; margin-bottom: 0.4rem;
    }
    .auction-id { font-family: monospace; font-size: 0.8rem; color: #888; }

    /* ---- Auction hero ---- */
    .hero {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: white; padding: 1.8rem 2.2rem; border-radius: 18px;
        margin: 0.5rem 0 1.2rem 0;
        box-shadow: 0 12px 40px rgba(0,0,0,0.18);
    }
    .hero-player-name { font-size: 2.4rem; font-weight: 800; margin: 0; line-height: 1.1; }
    .hero-player-meta {
        font-size: 0.95rem; opacity: 0.75; margin: 0.2rem 0 1rem 0;
        letter-spacing: 1px;
    }
    .hero-bid-label {
        font-size: 0.78rem; opacity: 0.6; text-transform: uppercase;
        letter-spacing: 4px; text-align: center; margin: 0.2rem 0 0 0;
    }
    .hero-bid-value {
        font-size: 4.2rem; font-weight: 800; text-align: center;
        color: #fbbf24; line-height: 1.05; margin: 0 0 0.4rem 0;
        text-shadow: 0 0 32px rgba(251, 191, 36, 0.45);
    }
    .hero-bidder {
        text-align: center; font-size: 0.95rem; opacity: 0.85;
        margin: 0 0 0.8rem 0;
    }
    .hero-bidder b { color: #fbbf24; }

    /* ---- Progress strip ---- */
    .progress-strip {
        display: flex; justify-content: space-between; align-items: center;
        padding: 0.7rem 1.2rem; background: #f8fafc;
        border-radius: 10px; margin-bottom: 0.8rem; font-size: 0.9rem;
        color: #475569;
    }
    .progress-strip b { color: #0f172a; }

    /* ---- RTM strip ---- */
    .rtm-strip {
        display: flex; gap: 0.6rem; flex-wrap: wrap;
        padding: 0.9rem 1.1rem; background: #fef3c7;
        border: 1px solid #fcd34d; border-radius: 12px;
        margin-bottom: 1.1rem;
    }
    .rtm-item {
        display: flex; align-items: center; gap: 0.55rem;
        padding: 0.3rem 0.55rem 0.3rem 0.75rem;
        background: white; border-radius: 999px;
        font-weight: 600; font-size: 0.88rem;
    }
    .rtm-team-dot {
        width: 10px; height: 10px; border-radius: 50%;
    }
    .rtm-count {
        min-width: 1.6rem; text-align: center; padding: 0.1rem 0.5rem;
        border-radius: 999px; font-weight: 700; color: white;
        font-size: 0.85rem;
    }
    .rtm-count.has { background: #22c55e; }
    .rtm-count.none { background: #ef4444; }

    /* ---- Team cards ---- */
    .team-card {
        border: 2px solid #e5e7eb;
        border-radius: 14px;
        background: white;
        overflow: hidden;
        margin-bottom: 1rem;
        transition: transform 0.15s, box-shadow 0.2s, border-color 0.2s;
    }
    .team-card.active {
        border-color: #fbbf24;
        box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.4), 0 8px 24px rgba(0,0,0,0.08);
        transform: translateY(-2px);
    }
    .team-card-header { padding: 0.85rem 1rem; }
    .team-card-title { font-size: 1.15rem; font-weight: 800; line-height: 1.1; }
    .team-card-captain { font-size: 0.8rem; opacity: 0.85; margin-top: 0.15rem; }
    .team-card-body { padding: 0.9rem 1rem 1rem 1rem; }
    .purse-row {
        display: flex; justify-content: space-between; align-items: flex-start;
        gap: 0.5rem;
    }
    .micro-label {
        font-size: 0.68rem; text-transform: uppercase; letter-spacing: 1.5px;
        color: #94a3b8; font-weight: 700;
    }
    .team-purse { font-size: 1.8rem; font-weight: 800; color: #065f46; line-height: 1.1; }
    .team-squad { font-size: 1.3rem; font-weight: 700; color: #1e293b; line-height: 1.1; text-align: right; }
    .team-squad .squad-hint { font-size: 0.7rem; color: #64748b; font-weight: 500; display: block; letter-spacing: 0.5px; }
    .progress-bar {
        width: 100%; height: 7px; background: #e5e7eb; border-radius: 999px;
        margin: 0.7rem 0 0.8rem 0; overflow: hidden;
    }
    .progress-bar-fill {
        height: 100%; background: linear-gradient(90deg, #10b981, #14b8a6);
        border-radius: 999px; transition: width 0.3s;
    }
    .progress-bar-fill.low { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
    .progress-bar-fill.critical { background: linear-gradient(90deg, #ef4444, #dc2626); }
    .player-list {
        max-height: 240px; overflow-y: auto; font-size: 0.88rem;
        border-top: 1px solid #f3f4f6; padding-top: 0.2rem;
    }
    .player-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 0.35rem 0.1rem; border-bottom: 1px solid #f3f4f6;
    }
    .player-row:last-child { border-bottom: none; }
    .player-cell-name { color: #334155; }
    .player-cell-price { font-weight: 700; color: #059669; }
    .player-cell-price.rtm { color: #7c3aed; }
    .rtm-tag {
        font-size: 0.65rem; background: #ede9fe; color: #6d28d9;
        padding: 0.05rem 0.4rem; border-radius: 4px; margin-left: 0.4rem;
        font-weight: 700; letter-spacing: 0.5px;
    }
    .empty-squad {
        text-align: center; padding: 1.1rem 0.5rem; color: #94a3b8;
        font-style: italic; font-size: 0.85rem;
    }
    .rtm-pill {
        display: inline-flex; align-items: center; gap: 0.35rem;
        padding: 0.1rem 0.55rem; border-radius: 999px;
        font-weight: 700; font-size: 0.72rem; letter-spacing: 1px;
        background: rgba(255,255,255,0.18); backdrop-filter: blur(4px);
    }
    .rtm-pill.none { opacity: 0.55; }

    /* ---- Timeline ---- */
    .timeline { max-height: 460px; overflow-y: auto; padding-right: 0.5rem; }
    .tl-item {
        display: flex; gap: 0.65rem; padding: 0.5rem 0.4rem;
        border-bottom: 1px solid #f1f5f9; font-size: 0.88rem;
    }
    .tl-item:last-child { border: none; }
    .tl-icon {
        font-size: 1.05rem; width: 1.5rem; text-align: center; flex-shrink: 0;
    }
    .tl-body { flex: 1; color: #334155; }
    .tl-ts { font-size: 0.72rem; color: #94a3b8; font-variant-numeric: tabular-nums; }
    .tl-body b { color: #0f172a; }

    /* ---- Sold modal ---- */
    @keyframes sold-slam {
        0%   { transform: scale(0.35) rotate(-6deg); opacity: 0; }
        55%  { transform: scale(1.12) rotate(2.5deg); opacity: 1; }
        80%  { transform: scale(0.97) rotate(-1deg); }
        100% { transform: scale(1) rotate(0); opacity: 1; }
    }
    @keyframes price-pulse {
        0%, 100% { transform: scale(1);    text-shadow: 0 0 20px rgba(251,191,36,0.4); }
        50%      { transform: scale(1.08); text-shadow: 0 0 44px rgba(251,191,36,0.9); }
    }
    @keyframes shimmer {
        0%   { background-position: -200% 0; }
        100% { background-position:  200% 0; }
    }
    .sold-card {
        animation: sold-slam 0.7s cubic-bezier(0.34, 1.56, 0.64, 1);
        padding: 2rem 1.6rem;
        border-radius: 18px;
        text-align: center;
        box-shadow: 0 18px 60px rgba(0,0,0,0.35), 0 0 0 6px rgba(255,255,255,0.08);
        position: relative; overflow: hidden;
        margin-bottom: 1.2rem;
    }
    .sold-card::before {
        content: ''; position: absolute; inset: 0;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.22), transparent);
        background-size: 200% 100%;
        animation: shimmer 1.8s ease-in-out 0.5s infinite;
        pointer-events: none;
    }
    .sold-label {
        font-size: 1rem; letter-spacing: 8px; font-weight: 900;
        opacity: 0.85; margin-bottom: 0.6rem;
    }
    .sold-player {
        font-size: 2.4rem; font-weight: 900; line-height: 1.1;
        margin-bottom: 0.6rem; letter-spacing: -0.5px;
    }
    .sold-to {
        font-size: 0.85rem; opacity: 0.75; font-weight: 700;
        text-transform: uppercase; letter-spacing: 4px; margin-bottom: 0.2rem;
    }
    .sold-team {
        font-size: 1.5rem; font-weight: 800; line-height: 1; margin-bottom: 1.1rem;
    }
    .sold-price {
        font-size: 4rem; font-weight: 900; color: #fbbf24; line-height: 1;
        animation: price-pulse 1.4s ease-in-out 0.6s infinite;
    }
    .sold-rtm {
        display: inline-block;
        background: linear-gradient(135deg, #8b5cf6, #c026d3);
        color: white; font-weight: 800;
        padding: 0.25rem 0.9rem; border-radius: 999px;
        font-size: 0.8rem; letter-spacing: 2px;
        margin-bottom: 0.9rem;
        box-shadow: 0 0 20px rgba(139,92,246,0.5);
        animation: sold-slam 0.55s 0.3s both;
    }

    /* Compact, prominent bid amount in the hero's right column */
    .bid-now {
        display: flex; flex-direction: column; align-items: center;
        padding: 1.4rem 1rem; background: linear-gradient(135deg,#1e293b,#0f172a);
        border-radius: 16px; color: white; margin-bottom: 0.8rem;
    }
    .bid-now .label { font-size: 0.7rem; letter-spacing: 4px; opacity: 0.6; text-transform: uppercase; }
    .bid-now .amount { font-size: 3.2rem; font-weight: 800; color: #fbbf24; line-height: 1.05; }
    .bid-now .bidder { font-size: 0.88rem; opacity: 0.85; }
    .bid-now .bidder b { color: #fbbf24; }
    .stButton > button { border-radius: 8px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Ensure schema exists (init_schema itself is no-op after first success)
try:
    init_schema()
except Exception as e:
    st.error(f"Database error: {e}")
    st.stop()


# ---------------- Cached reads ----------------
def _bytea_to_bytes(row: dict) -> dict:
    """psycopg2 returns BYTEA as memoryview which won't pickle. Copy + normalize."""
    d = dict(row)
    v = d.get("logo")
    if isinstance(v, memoryview):
        d["logo"] = bytes(v)
    return d


@st.cache_data(ttl=30, show_spinner=False)
def cached_master_teams():
    return [_bytea_to_bytes(r) for r in list_master_teams()]


def _player_row_to_bytes(row: dict) -> dict:
    d = dict(row)
    v = d.get("photo")
    if isinstance(v, memoryview):
        d["photo"] = bytes(v)
    return d


@st.cache_data(ttl=30, show_spinner=False)
def cached_all_players():
    return [_player_row_to_bytes(r) for r in list_players()]


def invalidate_players_cache():
    cached_all_players.clear()


@st.cache_data(ttl=15, show_spinner=False)
def cached_recent_auctions():
    return list_auctions()


@st.cache_data(ttl=30, show_spinner=False)
def cached_team_auctions(team_id: int):
    return get_team_auctions(team_id)


def invalidate_master_teams_cache():
    cached_master_teams.clear()


def invalidate_auctions_cache():
    cached_recent_auctions.clear()


def invalidate_team_auctions_cache():
    cached_team_auctions.clear()


def _load_auction_from_db(auction_id: str) -> dict:
    """Read an auction + its teams/players/results and assemble the same shape
    the runtime state uses. Used for Resume and for the Report page."""
    a = get_auction(auction_id)
    if not a:
        raise ValueError(f"auction {auction_id} not found")
    teams_rows = get_auction_teams_full(auction_id)
    player_rows = get_auction_players_ordered(auction_id)
    result_rows = get_auction_results_detailed(auction_id)

    set_order: list[str] = []
    set_players: dict[str, list[dict]] = {}
    for p in player_rows:
        # Captains are auto-enrolled; never enter the bid queue
        if p.get("is_captain"):
            continue
        s = p["set_name"]
        if s not in set_players:
            set_players[s] = []
            set_order.append(s)
        set_players[s].append(
            {"player_name": p["name"], "set": s, "base_price": p["base_price"]}
        )

    teams: dict[str, dict] = {}
    team_id_to_name: dict[int, str] = {}
    for t in teams_rows:
        teams[t["name"]] = {
            "team_id": t["team_id"],
            "captain": t["captain"],
            "color": t["color"],
            "text_color": t.get("text_color") or "#ffffff",
            "logo": t.get("logo"),
            "logo_mime": t.get("logo_mime"),
            "purse": t["remaining_purse"],
            "players": [],
            "rtm_remaining": t["rtm_remaining"],
        }
        team_id_to_name[t["team_id"]] = t["name"]

    sold_per_set: dict[str, int] = {s: 0 for s in set_order}
    for r in result_rows:
        tname = team_id_to_name.get(r["team_id"])
        if not tname:
            continue
        teams[tname]["players"].append(
            {
                "player": r["player_name"],
                "base": r["base_price"],
                "sold": r["sold_price"],
                "is_rtm": bool(r["is_rtm"]),
                "is_captain": bool(r.get("is_captain")),
            }
        )
        if r["set_name"] in sold_per_set:
            sold_per_set[r["set_name"]] += 1

    set_index = {s: min(sold_per_set.get(s, 0), len(set_players[s])) for s in set_order}
    current_set_idx = len(set_order)
    for i, s in enumerate(set_order):
        if set_index[s] < len(set_players[s]):
            current_set_idx = i
            break

    return {
        "auction_id": auction_id,
        "auction": dict(a),
        "teams": teams,
        "set_order": set_order,
        "set_players": set_players,
        "set_index": set_index,
        "current_set_idx": current_set_idx,
        "results": [dict(r) for r in result_rows],
    }


def resume_auction(auction_id: str) -> None:
    snap = _load_auction_from_db(auction_id)
    a = snap["auction"]
    st.session_state.auction_id = snap["auction_id"]
    st.session_state.teams = snap["teams"]
    st.session_state.players_per_team = int(a["players_per_team"])
    st.session_state.purse = int(a["purse"])
    st.session_state.rtm_enabled = bool(a["rtm_enabled"])
    st.session_state.rtm_count = int(a["rtm_count"])
    st.session_state.bid_tiers = a.get("bid_tiers") or DEFAULT_BID_TIERS
    st.session_state.set_order = snap["set_order"]
    st.session_state.set_players = snap["set_players"]
    st.session_state.set_index = snap["set_index"]
    st.session_state.current_set_idx = snap["current_set_idx"]
    st.session_state.bid = 0
    # Reset transient state; resume starts clean
    st.session_state.unsold_bucket = []
    st.session_state.last_sold = None
    st.session_state.current_sale_id = 0
    st.session_state.shown_sale_id = 0
    st.session_state.rtm_stage = None
    st.session_state.rtm_player = None
    st.session_state.rtm_price = 0
    st.session_state.rtm_counter_price = 0
    st.session_state.rtm_new_team = None
    st.session_state.rtm_old_team = None
    st.session_state.current_bid_team = None
    st.session_state.page = "auction"


# ---------------- Sidebar: sync + session ----------------
def render_sidebar():
    s = sync_stats()
    with st.sidebar:
        if st.session_state.get("authenticated"):
            st.caption(f"Signed in as **{st.session_state.admin_username}**")
            if st.button("Log out", key="logout_sidebar", use_container_width=True):
                tok = st.session_state.get("session_token")
                if tok:
                    delete_session(tok)
                    cookie_mgr.delete(AUTH_COOKIE)
                st.session_state.authenticated = False
                st.session_state.admin_username = None
                st.session_state.session_token = None
                st.rerun()
            st.divider()

        st.markdown("### DB Sync")
        backlog = s["backlog"]
        if backlog == 0:
            st.success(f"Up to date · {s['succeeded']} synced")
        else:
            st.warning(f"Syncing… {backlog} pending")
        st.caption(
            f"enqueued: {s['enqueued']} · succeeded: {s['succeeded']} · "
            f"retried: {s['retried']} · failed: {s['failed']}"
        )
        if s["last_error"]:
            st.caption(f"last error: {s['last_error']}")
        if st.button("Refresh status", key="refresh_sync", use_container_width=True):
            st.rerun()


render_sidebar()


# ---------------- Cookie manager (persistent auth) ----------------
AUTH_COOKIE = "nmtcc_auth"


# CookieManager is a widget — instantiate directly. The fixed key keeps
# the component identity stable across reruns (no cache_resource needed).
cookie_mgr = stx.CookieManager(key="cookie_mgr")


# ---------------- SESSION STATE ----------------
defaults = {
    "authenticated": False,
    "admin_username": None,
    "session_token": None,
    "page": "home",
    # Auction runtime
    "auction_id": None,
    "teams": {},  # name -> {captain, color, purse, players:[], team_id, rtm_remaining}
    "players_df": None,
    "players_per_team": 11,
    "purse": 100,
    "bid": 5,
    "set_order": [],
    "set_players": {},
    "set_index": {},
    "current_set_idx": 0,
    "rtm_enabled": False,
    "rtm_count": 0,
    "current_bid_team": None,
    "rtm_stage": None,
    "rtm_player": None,
    "rtm_price": 0,
    "rtm_counter_price": 0,
    "rtm_new_team": None,
    "rtm_old_team": None,
    # Setup wizard
    "setup_selected_teams": [],  # list of dicts {name, captain, color, id (or None)}
    "setup_draft": None,  # Screen-1 config, stashed while screen 2 picks players
    "setup_selected_player_ids": [],  # IDs of players picked on screen 2, in display order
    "setup_player_sets": {},  # player_id -> set (int)
    "setup_random_in_set": False,
    # Report
    "report_auction_id": None,
    # Bid ladder for the currently running auction
    "bid_tiers": None,
    # Dedup flag so we only emit new_player once per distinct player
    "last_logged_player": None,
    # Players pushed to the unsold pile to be re-auctioned at the end
    "unsold_bucket": [],
    # Sold-modal plumbing — show once per sale, don't reopen after native dismiss
    "last_sold": None,
    "current_sale_id": 0,
    "shown_sale_id": 0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================================================
# PUBLIC ROUTE — player self-registration (no auth)
# =========================================================
if st.query_params.get("page") == "register":
    st.markdown("<h1 class='hero-title'>🏏 Player Registration</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='hero-sub'>Register yourself with the club for upcoming auctions</p>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("public_register"):
            r_name = st.text_input("Name *")
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                r_mobile = st.text_input("Mobile *")
            with r_col2:
                r_email = st.text_input("Email *")
            r_role = st.selectbox(
                "Role",
                options=["", "Batsman", "Bowler", "All-rounder", "Wicket-keeper"],
                index=0,
            )
            r_dob = st.date_input("Date of birth", value=None)
            r_notes = st.text_area("Anything else we should know?", placeholder="(optional)")
            submitted = st.form_submit_button("Register", type="primary", use_container_width=True)
            if submitted:
                errors = []
                if not r_name.strip():
                    errors.append("Name is required")
                if not r_mobile.strip():
                    errors.append("Mobile is required")
                if not r_email.strip():
                    errors.append("Email is required")
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    try:
                        pid = create_player(
                            name=r_name,
                            mobile=r_mobile,
                            email=r_email,
                            role=r_role or None,
                            dob=r_dob,
                            notes=r_notes,
                        )
                        st.success(f"Registered! Your player ID is {pid}.")
                    except ValueError as ve:
                        st.error(str(ve))
                    except Exception as e:
                        st.error(f"Could not register: {e}")
    st.stop()


# =========================================================
# AUTH GATE
# =========================================================
# Restore session from cookie if present + valid
if not st.session_state.authenticated:
    existing_token = cookie_mgr.get(AUTH_COOKIE)
    if existing_token:
        _user = lookup_session(existing_token)
        if _user:
            st.session_state.authenticated = True
            st.session_state.admin_username = _user
            st.session_state.session_token = existing_token


def render_auth():
    st.markdown("<h1 class='hero-title'>🏏 NMTCC AUCTION</h1>", unsafe_allow_html=True)
    st.markdown("<p class='hero-sub'>Admin Sign-in Required</p>", unsafe_allow_html=True)

    first_run = not has_any_admin()

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        if first_run:
            st.info("No admin exists yet. Create the first admin account.")
            with st.form("create_admin"):
                u = st.text_input("Username")
                p1 = st.text_input("Password", type="password")
                p2 = st.text_input("Confirm Password", type="password")
                submitted = st.form_submit_button("Create Admin", use_container_width=True)
                if submitted:
                    if not u or not p1:
                        st.error("Username and password required")
                    elif p1 != p2:
                        st.error("Passwords do not match")
                    elif len(p1) < 6:
                        st.error("Password must be at least 6 characters")
                    else:
                        create_admin(u, p1)
                        st.success("Admin created. Please log in.")
                        st.rerun()
        else:
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in", use_container_width=True)
                if submitted:
                    if check_admin(u, p):
                        token, expires_at = create_session(u)
                        st.session_state.authenticated = True
                        st.session_state.admin_username = u
                        st.session_state.session_token = token
                        cookie_mgr.set(
                            AUTH_COOKIE,
                            token,
                            expires_at=expires_at,
                        )
                        st.rerun()
                    else:
                        st.error("Invalid username or password")


if not st.session_state.authenticated:
    render_auth()
    st.stop()


# =========================================================
# HOME
# =========================================================
if st.session_state.page == "home":
    st.markdown("<h1 class='hero-title'>🏏 NMTCC AUCTION</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p class='hero-sub'>Flamingo Cup · Season 1 · Part 2</p>",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("🚀 Start New Auction", use_container_width=True, type="primary"):
            # reset any prior setup
            st.session_state.setup_selected_teams = []
            st.session_state.page = "setup"
            st.rerun()

        btn_row = st.columns(2)
        with btn_row[0]:
            if st.button("🧑‍🤝‍🧑 Manage Teams", use_container_width=True):
                st.session_state.page = "teams"
                st.rerun()
        with btn_row[1]:
            if st.button("🏏 Players", use_container_width=True):
                st.session_state.page = "players"
                st.rerun()

        st.caption(
            f"Public player registration: `{st.context.url if hasattr(st, 'context') else '?'}?page=register`"
            if False
            else "Share the public registration link: `/?page=register`"
        )

        st.markdown("&nbsp;", unsafe_allow_html=True)

        with st.expander("📋 Past Auctions", expanded=False):
            auctions = cached_recent_auctions()
            if st.button("↻ Refresh list", key="refresh_auctions"):
                invalidate_auctions_cache()
                st.rerun()
            if not auctions:
                st.caption("No past auctions yet.")
            else:
                for a in auctions:
                    dt = a["auction_datetime"].strftime("%Y-%m-%d %H:%M")
                    name = a["name"] or "(unnamed)"
                    aid = str(a["id"])
                    status = a["status"]

                    row_l, row_r = st.columns([4, 2])
                    with row_l:
                        st.markdown(
                            f"**{name}** — {dt} · status: `{status}` "
                            f"<br><span class='auction-id'>ID: {aid}</span>",
                            unsafe_allow_html=True,
                        )
                    with row_r:
                        if status == "active":
                            if st.button("▶ Resume", key=f"resume_{aid}", use_container_width=True):
                                try:
                                    resume_auction(aid)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Could not resume: {e}")
                        elif status == "completed":
                            if st.button("📊 View report", key=f"report_{aid}", use_container_width=True):
                                st.session_state.report_auction_id = aid
                                st.session_state.page = "report"
                                st.rerun()
                        else:
                            st.caption(f"_{status}_")
                    st.divider()


# =========================================================
# PLAYERS — master player management (edit + auction history + CSV import)
# =========================================================
elif st.session_state.page == "players":
    top_l, top_r = st.columns([5, 1])
    with top_l:
        st.title("Players")
        st.caption(
            "Master list of all registered players. Public registration URL: `/?page=register`"
        )
    with top_r:
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        if st.button("← Home", key="players_back_home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()

    tabs = st.tabs(["Directory", "Add player", "CSV import"])

    # -------- Directory tab --------
    with tabs[0]:
        search = st.text_input("Search by name, mobile, or email", key="players_search")
        rows = list_players(search or None)
        st.caption(f"{len(rows)} player(s) match")
        if not rows:
            st.info("No players yet. Share `/?page=register` or use the Add / Import tabs.")
        for p in rows:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                with c1:
                    photo_bytes = p.get("photo")
                    if isinstance(photo_bytes, memoryview):
                        photo_bytes = bytes(photo_bytes)
                    avatar = avatar_html(
                        p["name"],
                        photo_bytes,
                        p.get("photo_mime"),
                        bg="#1e293b",
                        fg="#ffffff",
                        size_px=48,
                    )
                    meta_bits = [
                        f"Role: {html.escape(p['role'])}" if p.get("role") else None,
                        f"📱 {html.escape(p['mobile'])}" if p.get("mobile") else None,
                        f"✉️ {html.escape(p['email'])}" if p.get("email") else None,
                    ]
                    meta = " · ".join(b for b in meta_bits if b)
                    st.markdown(
                        f"<div style='display:flex; align-items:center; gap:0.9rem;'>"
                        f"{avatar}"
                        f"<div><div style='font-size:1.05rem; font-weight:700;'>"
                        f"{html.escape(p['name'])}</div>"
                        f"<div style='color:#64748b; font-size:0.85rem;'>{meta}</div></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with c2:
                    with st.popover("⚙️ Edit", use_container_width=True):
                        pid = p["id"]
                        e_name = st.text_input("Name *", value=p["name"], key=f"p_name_{pid}")
                        e_role = st.selectbox(
                            "Role",
                            options=["", "Batsman", "Bowler", "All-rounder", "Wicket-keeper"],
                            index=(
                                ["", "Batsman", "Bowler", "All-rounder", "Wicket-keeper"].index(p["role"])
                                if p.get("role") in ["Batsman", "Bowler", "All-rounder", "Wicket-keeper"]
                                else 0
                            ),
                            key=f"p_role_{pid}",
                        )
                        e_mob, e_eml = st.columns(2)
                        with e_mob:
                            e_mobile = st.text_input(
                                "Mobile", value=p.get("mobile") or "", key=f"p_mob_{pid}"
                            )
                        with e_eml:
                            e_email = st.text_input(
                                "Email", value=p.get("email") or "", key=f"p_eml_{pid}"
                            )
                        e_dob = st.date_input(
                            "DOB",
                            value=p.get("dob"),
                            key=f"p_dob_{pid}",
                        )
                        e_notes = st.text_area(
                            "Notes", value=p.get("notes") or "", key=f"p_notes_{pid}"
                        )
                        e_photo = st.file_uploader(
                            "Replace photo",
                            type=["png", "jpg", "jpeg", "webp"],
                            key=f"p_photo_{pid}",
                        )
                        new_photo_bytes = None
                        new_photo_mime = None
                        if e_photo is not None:
                            try:
                                new_photo_bytes, new_photo_mime = process_uploaded_logo(e_photo)
                            except Exception as ex:
                                st.error(f"Could not read photo: {ex}")
                        if st.button("Save", key=f"p_save_{pid}", type="primary", use_container_width=True):
                            try:
                                update_player(
                                    pid,
                                    name=e_name,
                                    mobile=e_mobile,
                                    email=e_email,
                                    role=e_role or None,
                                    dob=e_dob,
                                    notes=e_notes,
                                )
                                if new_photo_bytes:
                                    update_player_photo(pid, new_photo_bytes, new_photo_mime)
                                st.success("Saved")
                                st.rerun()
                            except ValueError as ve:
                                st.error(str(ve))
                            except Exception as ex:
                                st.error(f"Could not save: {ex}")

                with st.expander("📊 Auction history"):
                    hist = get_player_auctions(p["id"])
                    if not hist:
                        st.caption("No auction sales recorded for this player yet.")
                    for a in hist:
                        dt = (
                            a["auction_datetime"].strftime("%Y-%m-%d")
                            if a.get("auction_datetime")
                            else ""
                        )
                        rtm_tag = " · 🔁 RTM" if a.get("is_rtm") else ""
                        left, right = st.columns([4, 1])
                        with left:
                            st.markdown(
                                f"**{html.escape(a['auction_name'] or '(unnamed)')}** — {dt} · "
                                f"Sold to <b style='color:{a['team_color']}'>"
                                f"{html.escape(a['team_name'])}</b> for **₹{a['sold_price']}**"
                                f"{rtm_tag}",
                                unsafe_allow_html=True,
                            )
                        with right:
                            if a["status"] == "completed":
                                if st.button(
                                    "Report",
                                    key=f"phist_{p['id']}_{a['id']}",
                                    use_container_width=True,
                                ):
                                    st.session_state.report_auction_id = str(a["id"])
                                    st.session_state.page = "report"
                                    st.rerun()

    # -------- Add player tab --------
    with tabs[1]:
        with st.form("add_player_form"):
            a_name = st.text_input("Name *")
            c1, c2 = st.columns(2)
            with c1:
                a_mobile = st.text_input("Mobile")
            with c2:
                a_email = st.text_input("Email")
            a_role = st.selectbox(
                "Role",
                options=["", "Batsman", "Bowler", "All-rounder", "Wicket-keeper"],
                index=0,
            )
            a_dob = st.date_input("Date of birth", value=None)
            a_notes = st.text_area("Notes")
            if st.form_submit_button("Add player", type="primary"):
                try:
                    pid = create_player(
                        name=a_name,
                        mobile=a_mobile,
                        email=a_email,
                        role=a_role or None,
                        dob=a_dob,
                        notes=a_notes,
                    )
                    invalidate_players_cache()
                    st.success(f"Added player (id: {pid})")
                    st.rerun()
                except ValueError as ve:
                    st.error(str(ve))
                except Exception as ex:
                    st.error(f"Could not add: {ex}")

    # -------- CSV import tab --------
    with tabs[2]:
        st.caption(
            "Upload a CSV with headers: `name` (required), plus any of "
            "`mobile`, `email`, `role`, `dob` (YYYY-MM-DD), `notes`. "
            "Rows with duplicate mobile/email already in the DB are skipped."
        )
        csv_file = st.file_uploader("Players CSV", type=["csv"], key="players_csv")
        if csv_file is not None:
            try:
                csv_df = pd.read_csv(csv_file)
                csv_df.columns = csv_df.columns.str.strip().str.lower().str.replace(" ", "_")
                if "name" not in csv_df.columns:
                    st.error("CSV must have a `name` column")
                else:
                    st.dataframe(csv_df.head(10), use_container_width=True)
                    st.caption(f"{len(csv_df)} rows detected (preview of first 10)")
                    if st.button("Import all", type="primary"):
                        ok = 0
                        skipped = 0
                        errors = []
                        for _, r in csv_df.iterrows():
                            try:
                                create_player(
                                    name=str(r.get("name") or "").strip(),
                                    mobile=str(r.get("mobile") or "").strip() or None,
                                    email=str(r.get("email") or "").strip() or None,
                                    role=str(r.get("role") or "").strip() or None,
                                    dob=pd.to_datetime(r["dob"]).date() if r.get("dob") and pd.notna(r.get("dob")) else None,
                                    notes=str(r.get("notes") or "").strip() or None,
                                )
                                ok += 1
                            except ValueError:
                                skipped += 1
                            except Exception as ex:
                                errors.append(str(ex))
                        st.success(f"Imported {ok}, skipped {skipped} duplicates")
                        if errors:
                            st.warning(f"{len(errors)} row(s) failed with other errors")
                            for e in errors[:5]:
                                st.caption(f"• {e}")
            except Exception as e:
                st.error(f"Could not parse CSV: {e}")


# =========================================================
# TEAMS — master team management (edit + auction history)
# =========================================================
elif st.session_state.page == "teams":
    top_l, top_r = st.columns([5, 1])
    with top_l:
        st.title("Teams")
        st.caption("Edit saved teams and jump to any auction they've played.")
    with top_r:
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        if st.button("← Home", key="teams_back_home", use_container_width=True):
            st.session_state.page = "home"
            st.rerun()

    teams = cached_master_teams()
    if not teams:
        st.info("No saved teams yet. Teams are saved when you add them during auction setup.")
    else:
        for t in teams:
            with st.container(border=True):
                c1, c2, c3 = st.columns([4, 1, 1])
                with c1:
                    fg = t.get("text_color") or "#ffffff"
                    avatar = avatar_html(
                        t["name"],
                        t.get("logo"),
                        t.get("logo_mime"),
                        t["color"],
                        fg,
                        size_px=48,
                    )
                    st.markdown(
                        f"<div style='display:flex; align-items:center; gap:0.9rem;'>"
                        f"{avatar}"
                        f"<div><div style='font-size:1.15rem; font-weight:700;'>"
                        f"{html.escape(t['name'])}</div>"
                        f"<div style='color:#64748b; font-size:0.88rem;'>"
                        f"Captain: {html.escape(t.get('captain') or '—')}</div></div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with c2:
                    with st.popover("⚙️ Edit", use_container_width=True):
                        # Edit form (plain widgets so colour preview updates live)
                        new_name = st.text_input(
                            "Team Name",
                            value=t["name"],
                            key=f"edit_name_{t['id']}",
                        )
                        # Captain picker: searchable dropdown of players_master
                        _edit_players = cached_all_players()
                        _edit_player_label = {
                            p["id"]: f"{p['name']}" + (f" ({p['role']})" if p.get("role") else "")
                            for p in _edit_players
                        }
                        _edit_player_ids = [p["id"] for p in _edit_players]
                        # Pre-select existing captain if known
                        _current_cap_id = t.get("captain_id")
                        if _current_cap_id is None and t.get("captain"):
                            _current_cap_id = next(
                                (p["id"] for p in _edit_players
                                 if p["name"].lower() == (t["captain"] or "").lower()),
                                None,
                            )
                        _edit_options = [None] + _edit_player_ids
                        _edit_index = (
                            _edit_options.index(_current_cap_id)
                            if _current_cap_id in _edit_options
                            else 0
                        )
                        new_cap_id = st.selectbox(
                            "Captain (search players)",
                            options=_edit_options,
                            index=_edit_index,
                            format_func=lambda pid: "— pick a player —" if pid is None else _edit_player_label.get(pid, "?"),
                            key=f"edit_cap_id_{t['id']}",
                        )
                        new_cap = (
                            next((p["name"] for p in _edit_players if p["id"] == new_cap_id), "")
                            if new_cap_id
                            else ""
                        )
                        bg_col, fg_col = st.columns(2)
                        with bg_col:
                            new_bg = st.color_picker(
                                "Background",
                                value=t["color"],
                                key=f"edit_bg_{t['id']}",
                            )
                        with fg_col:
                            new_fg = st.color_picker(
                                "Text",
                                value=t.get("text_color") or "#ffffff",
                                key=f"edit_fg_{t['id']}",
                            )

                        # Logo management
                        new_logo_upload = st.file_uploader(
                            "Replace logo",
                            type=["png", "jpg", "jpeg", "webp"],
                            key=f"edit_logo_{t['id']}",
                        )
                        new_logo_bytes = None
                        new_logo_mime = None
                        if new_logo_upload is not None:
                            try:
                                new_logo_bytes, new_logo_mime = process_uploaded_logo(new_logo_upload)
                            except Exception as e:
                                st.error(f"Could not read logo: {e}")

                        # Preview uses the (possibly new) values
                        preview_logo_bytes = new_logo_bytes or t.get("logo")
                        preview_logo_mime = new_logo_mime or t.get("logo_mime")
                        preview_avatar = avatar_html(
                            new_name.strip() or "T",
                            preview_logo_bytes,
                            preview_logo_mime,
                            new_bg,
                            new_fg,
                            size_px=40,
                        )
                        preview_label = (
                            (new_name.strip() or "Team")
                            + " · "
                            + (new_cap or "Captain")
                        )
                        st.markdown(
                            f"<div style='display:flex; align-items:center; gap:0.6rem; margin:0.4rem 0;'>"
                            f"{preview_avatar}"
                            f"<div style='padding:0.5rem 1rem; border-radius:999px; "
                            f"background:{new_bg}; color:{new_fg}; font-weight:600;'>"
                            f"{html.escape(preview_label)}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                        btn_save, btn_clear = st.columns([2, 1])
                        with btn_save:
                            save_clicked = st.button(
                                "Save",
                                key=f"edit_save_{t['id']}",
                                use_container_width=True,
                                type="primary",
                            )
                        with btn_clear:
                            clear_logo_clicked = st.button(
                                "Clear logo",
                                key=f"edit_clear_{t['id']}",
                                use_container_width=True,
                                disabled=t.get("logo") is None and new_logo_bytes is None,
                            )

                        if save_clicked:
                            nn = new_name.strip()
                            if not nn:
                                st.error("Team name required")
                            elif not new_cap_id:
                                st.error("Pick a captain from the player list")
                            else:
                                existing = get_master_team_by_name(nn)
                                if existing and existing["id"] != t["id"]:
                                    st.error(f"Another team already named '{nn}'")
                                else:
                                    update_master_team(
                                        t["id"],
                                        nn,
                                        new_cap,
                                        new_bg,
                                        new_fg,
                                        captain_id=int(new_cap_id),
                                    )
                                    if new_logo_bytes:
                                        update_master_team_logo(
                                            t["id"], new_logo_bytes, new_logo_mime
                                        )
                                    invalidate_master_teams_cache()
                                    st.success("Updated")
                                    st.rerun()

                        if clear_logo_clicked:
                            update_master_team_logo(t["id"], None, None)
                            invalidate_master_teams_cache()
                            st.success("Logo cleared")
                            st.rerun()
                with c3:
                    st.markdown("<div style='height:0.1rem'></div>", unsafe_allow_html=True)

                with st.expander(f"📊 Auctions this team played in"):
                    auc_list = cached_team_auctions(t["id"])
                    if not auc_list:
                        st.caption("Not in any auctions yet.")
                    else:
                        for a in auc_list:
                            aid = str(a["id"])
                            dt = (
                                a["auction_datetime"].strftime("%Y-%m-%d %H:%M")
                                if a.get("auction_datetime")
                                else ""
                            )
                            name = a["name"] or "(unnamed)"
                            row_l, row_r = st.columns([4, 1])
                            with row_l:
                                st.markdown(
                                    f"**{html.escape(name)}** — {dt} · "
                                    f"`{a['status']}` · purse left ₹{a['remaining_purse']}"
                                    f"<br><span class='auction-id'>ID: {aid}</span>",
                                    unsafe_allow_html=True,
                                )
                            with row_r:
                                if a["status"] == "active":
                                    if st.button(
                                        "▶ Resume",
                                        key=f"t{t['id']}_resume_{aid}",
                                        use_container_width=True,
                                    ):
                                        try:
                                            resume_auction(aid)
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Could not resume: {e}")
                                elif a["status"] == "completed":
                                    if st.button(
                                        "📊 Report",
                                        key=f"t{t['id']}_report_{aid}",
                                        use_container_width=True,
                                    ):
                                        st.session_state.report_auction_id = aid
                                        st.session_state.page = "report"
                                        st.rerun()
                                else:
                                    st.caption(f"_{a['status']}_")


# =========================================================
# SETUP — reordered: Tournament basics → Players → Teams
# =========================================================
elif st.session_state.page == "setup":
    # Handle click-to-remove on team pills
    if "remove_team" in st.query_params:
        _rm = st.query_params["remove_team"]
        st.session_state.setup_selected_teams = [
            x for x in st.session_state.setup_selected_teams if x["name"] != _rm
        ]
        st.query_params.clear()
        st.rerun()

    st.title("Auction Setup")
    st.caption(f"Signed in as **{st.session_state.admin_username}**")

    # --- Tournament Basics ---
    st.subheader("1 · Tournament Basics")
    b1, b2 = st.columns(2)
    with b1:
        auction_name = st.text_input("Auction Name", placeholder="Flamingo Cup S1 P2")
        auction_date = st.date_input("Auction Date", value=date.today())
    with b2:
        auction_time = st.time_input("Auction Time", value=time(19, 0))
        players_per_team = st.number_input("Players per Team", 1, 20, 11)

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        purse = st.number_input("Auction Purse", 10, 1000, 100, step=5)
    with c2:
        rtm_enabled = st.toggle("RTM Enabled", value=False)
    with c3:
        rtm_count = st.number_input(
            "RTMs per Team", 0, 5, 2, disabled=not rtm_enabled
        )

    st.markdown("**Bid ladder** — how much each successive bid raises")
    l1, l2, l3, l4, l5, l6 = st.columns([1, 1, 1, 1, 1, 1])
    with l1:
        t1_up = st.number_input("Tier 1: below ₹", 1, 500, 15, key="ladder_t1_up")
    with l2:
        t1_step = st.number_input("step ₹", 1, 100, 2, key="ladder_t1_step")
    with l3:
        t2_up = st.number_input("Tier 2: below ₹", 1, 1000, 40, key="ladder_t2_up")
    with l4:
        t2_step = st.number_input("step ₹", 1, 100, 5, key="ladder_t2_step")
    with l5:
        final_step = st.number_input("Tier 3: step ₹", 1, 100, 10, key="ladder_t3_step")
    with l6:
        default_base_price = st.number_input(
            "Default base ₹", 1, 100, 5, key="default_base_price",
            help="Applied to every player in the auction pool",
        )

    st.divider()

    # --- Teams ---
    st.subheader("2 · Teams Participating")
    st.caption("Max 15 teams. Each team name must be unique. Colours are saved for reuse.")

    master_teams = cached_master_teams()
    master_names = [t["name"] for t in master_teams]
    selected_names = [t["name"] for t in st.session_state.setup_selected_teams]

    def _on_saved_team_pick():
        picked = st.session_state.get("add_saved_team")
        if not picked:
            return
        if len(st.session_state.setup_selected_teams) >= 15:
            return
        if any(x["name"] == picked for x in st.session_state.setup_selected_teams):
            st.session_state.add_saved_team = None
            return
        team = next((t for t in master_teams if t["name"] == picked), None)
        if not team:
            return
        st.session_state.setup_selected_teams.append(
            {
                "id": team["id"],
                "name": team["name"],
                "captain": team["captain"],
                "captain_id": team.get("captain_id"),
                "color": team["color"],
                "text_color": team.get("text_color") or "#ffffff",
                "logo": team.get("logo"),
                "logo_mime": team.get("logo_mime"),
            }
        )
        # Reset the selectbox so it returns to the placeholder
        st.session_state.add_saved_team = None

    t1, t2 = st.columns([3, 2])
    with t1:
        st.selectbox(
            "Add saved team",
            options=[n for n in master_names if n not in selected_names],
            index=None,
            placeholder="Select a saved team...",
            key="add_saved_team",
            on_change=_on_saved_team_pick,
        )

    with t2:
        with st.popover("➕ Add new team"):
            # Plain widgets (not inside a form) so the preview updates live
            new_name = st.text_input("Team Name", key="new_team_name")

            # Captain picker: searchable dropdown backed by players_master.
            _all_players = cached_all_players()
            _player_id_to_label = {
                p["id"]: f"{p['name']}" + (f" ({p['role']})" if p.get("role") else "")
                for p in _all_players
            }
            new_captain_id = st.selectbox(
                "Captain (search players)",
                options=[None] + [p["id"] for p in _all_players],
                index=0,
                format_func=lambda pid: "— pick a player —" if pid is None else _player_id_to_label.get(pid, "?"),
                key="new_team_captain_id",
            )
            new_captain = (
                next((p["name"] for p in _all_players if p["id"] == new_captain_id), "")
                if new_captain_id
                else ""
            )

            c_bg, c_fg = st.columns(2)
            with c_bg:
                new_color = st.color_picker("Background", value="#3b82f6", key="new_team_bg")
            with c_fg:
                new_text_color = st.color_picker("Text Colour", value="#ffffff", key="new_team_fg")
            new_logo_upload = st.file_uploader(
                "Logo (optional)",
                type=["png", "jpg", "jpeg", "webp"],
                key="new_team_logo",
            )

            logo_bytes = None
            logo_mime = None
            if new_logo_upload is not None:
                try:
                    logo_bytes, logo_mime = process_uploaded_logo(new_logo_upload)
                except Exception as e:
                    st.error(f"Could not read logo: {e}")

            preview_avatar = avatar_html(
                new_name.strip() or "T",
                logo_bytes,
                logo_mime,
                new_color,
                new_text_color,
                size_px=36,
            )
            preview_label = (new_name.strip() or "Team") + " · " + (new_captain or "Captain")
            st.markdown(
                f"<div style='display:flex; align-items:center; gap:0.6rem; margin:0.4rem 0;'>"
                f"{preview_avatar}"
                f"<div style='padding:0.5rem 1rem; border-radius:999px; background:{new_color}; "
                f"color:{new_text_color}; font-weight:600;'>{html.escape(preview_label)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            if st.button("Save & Add", key="new_team_save"):
                nn = new_name.strip()
                if not nn:
                    st.error("Team name required")
                elif not new_captain_id:
                    st.error("Pick a captain from the player list")
                elif len(st.session_state.setup_selected_teams) >= 15:
                    st.error("Maximum 15 teams reached")
                elif nn.lower() in [n.lower() for n in selected_names]:
                    st.error("Team already added to this auction")
                else:
                    existing = get_master_team_by_name(nn)
                    if existing:
                        st.error(f"Team '{nn}' already exists in saved teams. Use the dropdown to add it.")
                    else:
                        team_id = create_master_team(
                            nn,
                            new_captain,
                            new_color,
                            new_text_color,
                            captain_id=int(new_captain_id),
                        )
                        if logo_bytes:
                            update_master_team_logo(team_id, logo_bytes, logo_mime)
                        invalidate_master_teams_cache()
                        st.session_state.setup_selected_teams.append(
                            {
                                "id": team_id,
                                "name": nn,
                                "captain": new_captain,
                                "captain_id": int(new_captain_id),
                                "color": new_color,
                                "text_color": new_text_color,
                                "logo": logo_bytes,
                                "logo_mime": logo_mime,
                            }
                        )
                        # clear the form fields for the next entry
                        for k in ("new_team_name", "new_team_captain_id", "new_team_logo"):
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

    # Selected teams display — click a chip to remove it
    if st.session_state.setup_selected_teams:
        st.markdown("**Selected Teams** · _click a team to remove_")
        chips = "".join(
            f"<a class='team-chip' "
            f"href='?remove_team={urllib.parse.quote(t['name'])}' "
            f"target='_self' "
            f"title='Click to remove {t['name']}' "
            f"style='background:{t['color']}; color:{t.get('text_color', '#ffffff')};'>"
            f"{t['name']} · {t['captain'] or '—'}"
            f"<span class='chip-x'>✕</span>"
            f"</a>"
            for t in st.session_state.setup_selected_teams
        )
        st.markdown(chips, unsafe_allow_html=True)
    else:
        st.caption("No teams added yet.")

    st.divider()

    # --- Validate & Next ---
    nav_l, nav_r = st.columns([1, 1])
    with nav_l:
        if st.button("← Back to Home"):
            st.session_state.page = "home"
            st.rerun()
    with nav_r:
        if st.button("Next → Pick players", type="primary", use_container_width=True):
            errors = []
            if len(st.session_state.setup_selected_teams) < 2:
                errors.append("Add at least 2 teams")
            if len(st.session_state.setup_selected_teams) > 15:
                errors.append("Maximum 15 teams")
            if any(not t.get("captain_id") for t in st.session_state.setup_selected_teams):
                errors.append("Every team must have a captain picked from the player list")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                # Stash the screen-1 state for the player-selection screen.
                st.session_state.setup_draft = {
                    "name": auction_name.strip() or None,
                    "date": auction_date,
                    "time": auction_time,
                    "players_per_team": int(players_per_team),
                    "purse": int(purse),
                    "rtm_enabled": bool(rtm_enabled),
                    "rtm_count": int(rtm_count) if rtm_enabled else 0,
                    "default_base_price": int(default_base_price),
                    "bid_tiers": [
                        {"up_to": int(t1_up), "step": int(t1_step)},
                        {"up_to": int(t2_up), "step": int(t2_step)},
                        {"up_to": 10000, "step": int(final_step)},
                    ],
                }
                st.session_state.page = "setup_players"
                st.rerun()


# =========================================================
# SETUP PLAYERS — pick + order the auction pool
# =========================================================
elif st.session_state.page == "setup_players":
    draft = st.session_state.get("setup_draft")
    if not draft:
        st.warning("Finish the first setup step first.")
        if st.button("← Back to setup"):
            st.session_state.page = "setup"
            st.rerun()
        st.stop()

    teams_in_auction = st.session_state.setup_selected_teams
    captain_ids = {int(t["captain_id"]) for t in teams_in_auction if t.get("captain_id")}
    captain_id_to_team = {int(t["captain_id"]): t for t in teams_in_auction if t.get("captain_id")}

    head_l, head_r = st.columns([5, 1])
    with head_l:
        st.title("Setup · Pick auction pool")
        st.caption(
            f"{draft.get('name') or '(unnamed auction)'} · "
            f"{len(teams_in_auction)} teams · "
            f"purse ₹{draft['purse']} · "
            f"base price ₹{draft['default_base_price']}"
        )
    with head_r:
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        if st.button("← Back", key="spx_back", use_container_width=True):
            st.session_state.page = "setup"
            st.rerun()

    # ---- Captains preview ----
    st.subheader("Captains (auto-enrolled in their team)")
    cap_cols = st.columns(min(4, len(teams_in_auction)))
    cap_value = int(round(draft["purse"] * 0.6))
    for i, t in enumerate(teams_in_auction):
        with cap_cols[i % len(cap_cols)]:
            captain_name = t.get("captain") or "—"
            fg = t.get("text_color") or "#ffffff"
            st.markdown(
                f"<div style='padding:0.55rem 0.85rem; border-radius:10px; "
                f"background:{t['color']}; color:{fg}; margin-bottom:0.4rem;'>"
                f"<div style='font-weight:700;'>{html.escape(t['name'])}</div>"
                f"<div style='font-size:0.82rem; opacity:0.9;'>"
                f"👑 {html.escape(captain_name)} · ₹{cap_value} (placeholder)"
                f"</div></div>",
                unsafe_allow_html=True,
            )
    st.caption(
        f"Captains count toward the squad minimum ({draft['players_per_team']} "
        f"per team). Their value (60% of purse) is a placeholder and is NOT "
        f"deducted from the team's remaining purse."
    )

    st.divider()

    # ---- Available player pool ----
    st.subheader("Pick players for the auction pool")
    st.caption(
        "Use the column filters to search (works on every keystroke). "
        "Drag rows by the ⠿ handle to reorder. "
        "Edit the Set column to group players — lower sets are auctioned first."
    )

    all_master = cached_all_players()
    pool_players = [p for p in all_master if p["id"] not in captain_ids]

    # Seed per-player set values (default 1), preserving prior choices if the user navigates back
    existing_sets: dict = st.session_state.setup_player_sets or {}
    df_rows = []
    for p in pool_players:
        df_rows.append(
            {
                "id": int(p["id"]),
                "Name": p["name"],
                "Role": p.get("role") or "",
                "Set": int(existing_sets.get(p["id"], 1)),
            }
        )
    import pandas as _pd
    pool_df = _pd.DataFrame(df_rows)

    gb = GridOptionsBuilder.from_dataframe(pool_df)
    gb.configure_default_column(
        filter=True, floatingFilter=True, sortable=False,
        resizable=True, editable=False,
    )
    gb.configure_column("id", hide=True)
    gb.configure_column(
        "Name",
        rowDrag=True,
        checkboxSelection=True,
        headerCheckboxSelection=True,
        minWidth=260,
        flex=2,
    )
    gb.configure_column("Role", minWidth=140, flex=1)
    gb.configure_column(
        "Set",
        editable=True,
        type=["numericColumn", "numberColumnFilter"],
        minWidth=80,
    )
    gb.configure_selection("multiple", use_checkbox=True)
    gb.configure_grid_options(
        rowDragManaged=True,
        animateRows=True,
        suppressRowClickSelection=True,
    )
    grid_options = gb.build()

    prev_selected = st.session_state.setup_selected_player_ids or []
    # Tell AgGrid to pre-select previously picked rows
    for row in grid_options.get("rowData", []) or []:
        row["_selected"] = row["id"] in prev_selected

    grid_response = AgGrid(
        pool_df,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.MODEL_CHANGED,
        data_return_mode=DataReturnMode.AS_INPUT,
        fit_columns_on_grid_load=True,
        allow_unsafe_jscode=True,
        height=520,
        key="player_pool_grid",
    )

    updated_df = grid_response.get("data")
    selected_rows = grid_response.get("selected_rows")

    # selected_rows can be list-of-dict or DataFrame depending on version
    if hasattr(selected_rows, "to_dict"):
        selected_rows = selected_rows.to_dict("records")
    selected_rows = selected_rows or []
    selected_id_set = {int(r["id"]) for r in selected_rows}

    random_in_set = st.toggle(
        "Randomise draw within each set",
        value=bool(st.session_state.setup_random_in_set),
        help="When on, players within the same set are shuffled before the auction queue is built.",
    )
    st.session_state.setup_random_in_set = bool(random_in_set)

    st.caption(f"**{len(selected_id_set)}** player(s) selected for the auction pool.")

    st.divider()

    # ---- Validate & start ----
    nav_l, nav_r = st.columns([1, 1])
    with nav_l:
        if st.button("← Back to setup", key="spx_back2"):
            st.session_state.page = "setup"
            st.rerun()
    with nav_r:
        if st.button("🚀 Start Auction", type="primary", use_container_width=True, key="spx_start"):
            errors = []
            if len(selected_id_set) == 0:
                errors.append("Pick at least one player")
            # Each team must have at least (players_per_team - 1) non-captain slots available
            min_non_captain = (int(draft["players_per_team"]) - 1) * len(teams_in_auction)
            if len(selected_id_set) < min_non_captain:
                errors.append(
                    f"Need at least {min_non_captain} non-captain players for "
                    f"{len(teams_in_auction)} teams × {draft['players_per_team']} slots"
                )

            if errors:
                for e in errors:
                    st.error(e)
            else:
                # Persist per-player set choices + selection order into session state
                ordered_rows = updated_df.to_dict("records") if hasattr(updated_df, "to_dict") else list(updated_df)
                selected_ordered = [
                    {
                        "id": int(r["id"]),
                        "name": str(r["Name"]),
                        "role": str(r.get("Role") or ""),
                        "set": int(r["Set"]) if r.get("Set") is not None else 1,
                    }
                    for r in ordered_rows
                    if int(r["id"]) in selected_id_set
                ]
                st.session_state.setup_player_sets = {r["id"]: r["set"] for r in selected_ordered}
                st.session_state.setup_selected_player_ids = [r["id"] for r in selected_ordered]

                # Build the auction
                auction_id = str(uuid.uuid4())
                dt = datetime.combine(draft["date"], draft["time"])
                purse = int(draft["purse"])
                rtm_count_val = int(draft["rtm_count"]) if draft["rtm_enabled"] else 0

                enqueue(
                    create_auction,
                    auction_id=auction_id,
                    name=draft["name"],
                    auction_datetime=dt,
                    players_per_team=int(draft["players_per_team"]),
                    purse=purse,
                    rtm_enabled=bool(draft["rtm_enabled"]),
                    rtm_count=rtm_count_val,
                    bid_tiers=draft["bid_tiers"],
                )

                teams_state = {}
                for t in teams_in_auction:
                    enqueue(
                        add_auction_team,
                        auction_id,
                        t["id"],
                        purse,
                        rtm_count_val,
                    )
                    teams_state[t["name"]] = {
                        "team_id": t["id"],
                        "captain": t["captain"],
                        "captain_id": t.get("captain_id"),
                        "color": t["color"],
                        "text_color": t.get("text_color") or "#ffffff",
                        "logo": t.get("logo"),
                        "logo_mime": t.get("logo_mime"),
                        "purse": purse,  # captain placeholder is NOT deducted
                        "players": [
                            {
                                "player": t["captain"],
                                "base": cap_value,
                                "sold": cap_value,
                                "is_rtm": False,
                                "is_captain": True,
                            }
                        ],
                        "rtm_remaining": rtm_count_val,
                    }

                # Build the player queue grouped by set (asc), optionally shuffled within set
                by_set: dict = {}
                for r in selected_ordered:
                    by_set.setdefault(int(r["set"]), []).append(r)
                ordered_sets = sorted(by_set.keys())
                set_players_buf: dict = {}
                set_order: list = []
                auction_player_rows: list = []
                oi = 0
                default_base = int(draft["default_base_price"])

                # Captains go in first as is_captain rows with the placeholder value,
                # so resume + reports reflect them.
                for t in teams_in_auction:
                    auction_player_rows.append(
                        (t["captain"], "Captain", cap_value, oi, True)
                    )
                    oi += 1

                for s in ordered_sets:
                    bucket = list(by_set[s])
                    if random_in_set:
                        import random as _r
                        _r.shuffle(bucket)
                    set_key = f"Set {s}"
                    set_order.append(set_key)
                    set_players_buf[set_key] = [
                        {
                            "player_name": row["name"],
                            "set": set_key,
                            "base_price": default_base,
                        }
                        for row in bucket
                    ]
                    for row in bucket:
                        auction_player_rows.append(
                            (row["name"], set_key, default_base, oi, False)
                        )
                        oi += 1

                enqueue(add_auction_players, auction_id, auction_player_rows)

                # Record each captain's placeholder enrollment so reports /
                # resume see them in the roster. Purse is NOT decremented.
                for tname, td in teams_state.items():
                    enqueue(
                        record_captain_enrollment,
                        auction_id,
                        td["captain"],
                        td["team_id"],
                        cap_value,
                    )

                invalidate_auctions_cache()

                # Hydrate runtime state
                st.session_state.auction_id = auction_id
                st.session_state.teams = teams_state
                st.session_state.players_per_team = int(draft["players_per_team"])
                st.session_state.purse = purse
                st.session_state.rtm_enabled = bool(draft["rtm_enabled"])
                st.session_state.rtm_count = rtm_count_val
                st.session_state.bid_tiers = draft["bid_tiers"]
                st.session_state.bid = 0
                st.session_state.current_bid_team = None
                st.session_state.last_sold = None
                st.session_state.current_sale_id = 0
                st.session_state.shown_sale_id = 0
                st.session_state.unsold_bucket = []
                st.session_state.set_order = set_order
                st.session_state.current_set_idx = 0
                st.session_state.set_players = set_players_buf
                st.session_state.set_index = {s: 0 for s in set_order}

                # Leave setup_draft in case user comes back
                st.session_state.page = "auction"
                st.rerun()


# =========================================================
# AUCTION
# =========================================================
elif st.session_state.page == "auction":
    # Ensure bid tiers are present even for auctions created before this feature
    if not st.session_state.bid_tiers:
        st.session_state.bid_tiers = DEFAULT_BID_TIERS

    # ---------------- Helpers ----------------
    def _render_team_card(name: str, data: dict, is_active: bool, min_players: int, rtm_enabled: bool, total_purse: int) -> str:
        bought = len(data["players"])
        over = bought > min_players
        purse_left = int(data["purse"])
        pct = min(100, max(0, int(round(100 * purse_left / max(1, total_purse)))))
        if pct >= 50:
            bar_cls = ""
        elif pct >= 20:
            bar_cls = " low"
        else:
            bar_cls = " critical"
        safe_name = html.escape(name)
        safe_cap = html.escape(data.get("captain") or "—")
        bg = data["color"]
        fg = data.get("text_color") or "#ffffff"

        if data["players"]:
            rows = []
            for p in data["players"]:
                tags = []
                if p.get("is_captain"):
                    tags.append("👑")
                if p.get("is_rtm"):
                    tags.append("<span class='rtm-tag'>RTM</span>")
                tag_html = " ".join(tags)
                prefix = f"{tag_html} " if tag_html else ""
                rows.append(
                    f"<div class='player-row'>"
                    f"<div class='player-cell-name'>{prefix}{html.escape(str(p['player']))}</div>"
                    f"<div class='player-cell-price{' rtm' if p.get('is_rtm') else ''}'>₹{p['sold']}</div>"
                    f"</div>"
                )
            player_html = f"<div class='player-list'>{''.join(rows)}</div>"
        else:
            player_html = "<div class='empty-squad'>No players yet</div>"

        min_hint = f"min {min_players}" if not over else f"+{bought - min_players} over min"

        rtm_html = ""
        if rtm_enabled:
            cnt = int(data.get("rtm_remaining", 0))
            cls = "rtm-pill" if cnt > 0 else "rtm-pill none"
            rtm_html = f"<div class='{cls}' style='margin-top:0.35rem;'>RTM × {cnt}</div>"

        avatar = avatar_html(name, data.get("logo"), data.get("logo_mime"), bg, fg, size_px=42)
        return (
            f"<div class='team-card{' active' if is_active else ''}'>"
            f"<div class='team-card-header' style='background:{bg}; color:{fg};'>"
            f"<div style='display:flex; justify-content:space-between; align-items:flex-start; gap:0.6rem;'>"
            f"<div style='display:flex; gap:0.7rem; align-items:center;'>"
            f"{avatar}"
            f"<div><div class='team-card-title'>{safe_name}</div>"
            f"<div class='team-card-captain'>Captain: {safe_cap}</div></div>"
            f"</div>"
            f"{rtm_html}"
            f"</div>"
            f"</div>"
            f"<div class='team-card-body'>"
            f"<div class='purse-row'>"
            f"<div><div class='micro-label'>Purse</div><div class='team-purse'>₹{data['purse']}</div></div>"
            f"<div><div class='micro-label' style='text-align:right;'>Squad</div>"
            f"<div class='team-squad'>{bought}/{min_players}"
            f"<span class='squad-hint'>{min_hint}</span></div></div>"
            f"</div>"
            f"<div class='progress-bar' title='Purse remaining'>"
            f"<div class='progress-bar-fill{bar_cls}' style='width:{pct}%'></div>"
            f"</div>"
            f"{player_html}"
            f"</div>"
            f"</div>"
        )

    def _render_teams_grid(active_team):
        teams_items = list(st.session_state.teams.items())
        n = len(teams_items)
        cols_per_row = 3 if n <= 9 else 4 if n <= 12 else 5
        min_players = int(st.session_state.players_per_team)
        total_purse = int(st.session_state.purse)
        rtm_on = bool(st.session_state.rtm_enabled)

        for row_start in range(0, n, cols_per_row):
            row = teams_items[row_start:row_start + cols_per_row]
            cols = st.columns(cols_per_row)
            for i, (name, data) in enumerate(row):
                with cols[i]:
                    st.markdown(
                        _render_team_card(name, data, name == active_team, min_players, rtm_on, total_purse),
                        unsafe_allow_html=True,
                    )

    def _finalize_sale(player_obj, team_name: str, price: int, is_rtm: bool):
        td = st.session_state.teams[team_name]
        td["players"].append(
            {
                "player": player_obj["player_name"],
                "base": player_obj["base_price"],
                "sold": price,
                "is_rtm": is_rtm,
            }
        )
        td["purse"] -= price
        if is_rtm:
            td["rtm_remaining"] -= 1
        enqueue(
            record_sale,
            st.session_state.auction_id,
            player_obj["player_name"],
            td["team_id"],
            price,
            is_rtm=is_rtm,
        )
        log_event(
            st.session_state.auction_id,
            "sell" if not is_rtm else "rtm_used",
            player=player_obj["player_name"],
            team=team_name,
            amount=int(price),
        )
        # Queue the sold-modal for the next rerun
        st.session_state.last_sold = {
            "player": player_obj["player_name"],
            "team": team_name,
            "color": td["color"],
            "text_color": td.get("text_color") or "#ffffff",
            "logo": td.get("logo"),
            "logo_mime": td.get("logo_mime"),
            "price": int(price),
            "is_rtm": bool(is_rtm),
        }
        st.session_state.current_sale_id = int(st.session_state.get("current_sale_id", 0)) + 1

    # ---------------- Sold modal (shows once per sale) ----------------
    if (
        st.session_state.get("last_sold")
        and st.session_state.get("current_sale_id", 0) > st.session_state.get("shown_sale_id", 0)
    ):
        st.session_state.shown_sale_id = int(st.session_state.current_sale_id)

        @st.dialog("🎉 SOLD!", width="large")
        def _show_sold_modal():
            info = st.session_state.last_sold or {}
            rtm_badge = "<div class='sold-rtm'>⚡ VIA RTM</div>" if info.get("is_rtm") else ""
            logo_uri = logo_data_uri(info.get("logo"), info.get("logo_mime"))
            if logo_uri:
                logo_html = (
                    f"<img src='{logo_uri}' class='sold-logo' "
                    f"style='width:92px; height:92px; border-radius:16px; object-fit:cover; "
                    f"background:rgba(255,255,255,0.15); margin-bottom:0.8rem;' alt='' />"
                )
            else:
                logo_html = ""

            st.markdown(
                f"<div class='sold-card' style='background:{info.get('color','#1e293b')}; "
                f"color:{info.get('text_color','#ffffff')};'>"
                f"{rtm_badge}"
                f"{logo_html}"
                f"<div class='sold-label'>SOLD</div>"
                f"<div class='sold-player'>{html.escape(str(info.get('player','')))}</div>"
                f"<div class='sold-to'>to</div>"
                f"<div class='sold-team'>{html.escape(str(info.get('team','')))}</div>"
                f"<div class='sold-price'>₹{info.get('price',0)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Golden confetti, rendered on the parent document so it covers the dialog.
            import streamlit.components.v1 as _components
            _components.html(
                """
                <script src='https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.2/dist/confetti.browser.min.js'></script>
                <script>
                (function(){
                  try {
                    const parentDoc = window.parent.document;
                    const canvas = parentDoc.createElement('canvas');
                    canvas.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647';
                    parentDoc.body.appendChild(canvas);
                    const myConfetti = confetti.create(canvas, { resize: true, useWorker: true });
                    const gold = ['#fde047','#facc15','#eab308','#fbbf24','#f59e0b','#d97706','#b45309'];
                    myConfetti({
                      particleCount: 160, spread: 160, startVelocity: 55,
                      origin: { y: 0.45 }, colors: gold,
                      shapes: ['square','circle'], scalar: 1.2,
                      gravity: 0.7, ticks: 300,
                    });
                    setTimeout(function(){
                      myConfetti({ particleCount: 70, angle: 60, spread: 70,
                        origin: { x: 0, y: 0.7 }, colors: gold, scalar: 1.1 });
                      myConfetti({ particleCount: 70, angle: 120, spread: 70,
                        origin: { x: 1, y: 0.7 }, colors: gold, scalar: 1.1 });
                    }, 280);
                    setTimeout(function(){
                      myConfetti({ particleCount: 50, spread: 110, startVelocity: 40,
                        origin: { y: 0.35 }, colors: gold, shapes: ['star'], scalar: 0.9 });
                    }, 600);
                    setTimeout(function(){ canvas.remove(); }, 6000);
                  } catch(e) { console.error('confetti failed', e); }
                })();
                </script>
                """,
                height=0,
            )

            if st.button("Continue →", type="primary", use_container_width=True, key="dismiss_sold"):
                st.rerun()

        _show_sold_modal()

    # ---------------- Walk to next player (main phase, then unsold phase) ----------------
    player = None
    current_set = None
    phase = "main"

    while st.session_state.current_set_idx < len(st.session_state.set_order):
        current_set = st.session_state.set_order[st.session_state.current_set_idx]
        idx = st.session_state.set_index[current_set]
        if idx < len(st.session_state.set_players[current_set]):
            player = st.session_state.set_players[current_set][idx]
            break
        st.session_state.current_set_idx += 1

    if player is None and st.session_state.unsold_bucket:
        phase = "unsold"
        player = st.session_state.unsold_bucket[0]
        current_set = str(player.get("set", "Unsold"))

    if player is None:
        enqueue(update_auction_status, st.session_state.auction_id, "completed")
        invalidate_auctions_cache()
        log_event(st.session_state.auction_id, "auction_over")
        st.session_state.page = "trade"
        st.rerun()

    def _advance(is_unsold_phase: bool, current_set_name: str):
        """After a sale / unsold action, move to the next player."""
        if is_unsold_phase:
            # Pop the head of the unsold bucket regardless of sale or skip
            if st.session_state.unsold_bucket:
                st.session_state.unsold_bucket.pop(0)
        else:
            st.session_state.set_index[current_set_name] += 1

    # Fresh player → start bid at base price + reset top bidder
    base_price = int(player["base_price"])
    if st.session_state.last_logged_player != player["player_name"]:
        st.session_state.bid = base_price
        st.session_state.current_bid_team = None
        st.session_state.last_logged_player = player["player_name"]
        log_event(
            st.session_state.auction_id,
            "new_player",
            player=player["player_name"],
            set=str(current_set),
            base=base_price,
        )
    if st.session_state.bid < base_price:
        st.session_state.bid = base_price

    # ---------------- Progress strip ----------------
    total_players = sum(len(ps) for ps in st.session_state.set_players.values())
    sold_players = sum(len(t["players"]) for t in st.session_state.teams.values())
    bucket_size = len(st.session_state.unsold_bucket)
    phase_label = (
        f"🔁 Unsold round · {bucket_size} left"
        if phase == "unsold"
        else f"Set: <b>{html.escape(str(current_set))}</b>"
    )
    st.markdown(
        f"<div class='progress-strip'>"
        f"<div>{phase_label}</div>"
        f"<div>Progress: <b>{sold_players}/{total_players}</b> sold · "
        f"<b>{bucket_size}</b> unsold</div>"
        f"<div class='auction-id'>Auction: {st.session_state.auction_id[:8]}…</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ---------------- Hero (left) + Controls (right) ----------------
    tiers = st.session_state.bid_tiers or DEFAULT_BID_TIERS
    next_step = step_for_bid(int(st.session_state.bid), tiers)
    bid_team_current = st.session_state.current_bid_team or "—"

    left, right = st.columns([1, 1], gap="medium")

    with left:
        st.markdown(
            f"""
            <div class='hero'>
              <div class='hero-player-name'>{html.escape(str(player['player_name']))}</div>
              <div class='hero-player-meta'>Set: {html.escape(str(current_set))} · Base: ₹{base_price}</div>
              <div class='hero-bid-label'>Current Bid</div>
              <div class='hero-bid-value'>₹{st.session_state.bid}</div>
              <div class='hero-bidder'>Top bidder: <b>{html.escape(str(bid_team_current))}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        # Header row: next-step indicator + base reset
        r1, r2 = st.columns([4, 1])
        with r1:
            ladder_parts = [f"<{t['up_to']}→+{t['step']}" for t in tiers]
            ladder_str = "; ".join(ladder_parts)
            st.caption(f"Next bid step: **+₹{next_step}** (ladder: {ladder_str})")
        with r2:
            if st.button("↺ Base", key="reset_bid", use_container_width=True, help="Reset bid and top bidder"):
                st.session_state.bid = base_price
                st.session_state.current_bid_team = None
                st.rerun()

        # Per-team bid buttons — native st.button, styled per-team via the
        # .st-key-<key> class Streamlit attaches to keyed elements. No href,
        # no URL params, no page navigation.
        st.markdown(
            "<div class='micro-label' style='margin:0.4rem 0 0.3rem 0;'>Tap a team to bid</div>",
            unsafe_allow_html=True,
        )
        team_items = list(st.session_state.teams.items())

        # Inject per-team CSS for the buttons we're about to render
        css_rules = []
        for i, (tname, tdata) in enumerate(team_items):
            bg = tdata["color"]
            fg = tdata.get("text_color") or "#ffffff"
            is_active = (tname == st.session_state.current_bid_team)
            glow = "box-shadow: 0 0 0 3px rgba(251,191,36,0.55);" if is_active else ""
            css_rules.append(
                f".st-key-bid_btn_{i} button {{"
                f"  background: {bg} !important; color: {fg} !important;"
                f"  border: 2px solid {bg} !important; font-weight: 700 !important;"
                f"  padding: 0.6rem 0.8rem !important; border-radius: 10px !important;"
                f"  {glow}"
                f"}}"
                f".st-key-bid_btn_{i} button:hover:not(:disabled) {{"
                f"  filter: brightness(1.08); transform: translateY(-1px);"
                f"}}"
                f".st-key-bid_btn_{i} button:disabled {{ opacity: 0.4; }}"
            )
        st.markdown(f"<style>{''.join(css_rules)}</style>", unsafe_allow_html=True)

        btn_cols = st.columns(2)
        for i, (tname, tdata) in enumerate(team_items):
            if st.session_state.current_bid_team is None:
                preview_next = int(st.session_state.bid)
            else:
                preview_next = int(st.session_state.bid) + step_for_bid(int(st.session_state.bid), tiers)

            can_afford = tdata["purse"] >= preview_next
            is_active = (tname == st.session_state.current_bid_team)
            # Can't bid against your own standing bid
            is_disabled = (not can_afford) or is_active
            if is_active:
                label = f"👑 {tname}  ·  ₹{int(st.session_state.bid)}"
            else:
                label = f"{tname}  ·  ₹{preview_next}"

            with btn_cols[i % 2]:
                clicked = st.button(
                    label,
                    key=f"bid_btn_{i}",
                    use_container_width=True,
                    disabled=is_disabled,
                )
            if clicked:
                st.session_state.bid = preview_next
                st.session_state.current_bid_team = tname
                log_event(
                    st.session_state.auction_id,
                    "bid",
                    team=tname,
                    amount=preview_next,
                )
                st.rerun()

        # SELL + RTM + Unsold actions
        sell_cols = st.columns([3, 1, 1])
        with sell_cols[0]:
            sell_disabled = st.session_state.current_bid_team is None
            sell_label = (
                f"✅ SELL to {st.session_state.current_bid_team} @ ₹{st.session_state.bid}"
                if st.session_state.current_bid_team
                else "Pick a bidding team"
            )
            sell_clicked = st.button(
                sell_label,
                type="primary",
                use_container_width=True,
                disabled=sell_disabled,
            )
        with sell_cols[1]:
            rtm_disabled = (
                not st.session_state.rtm_enabled
                or st.session_state.current_bid_team is None
            )
            with st.popover(
                "🔁 RTM",
                use_container_width=True,
                disabled=rtm_disabled,
            ):
                st.caption(
                    f"Pick the team exercising RTM at ₹{st.session_state.bid}. "
                    f"They win the player and their RTM count drops by 1."
                )
                for tname, tdata in st.session_state.teams.items():
                    rtm_left = int(tdata.get("rtm_remaining", 0))
                    if rtm_left <= 0:
                        continue
                    if tdata["purse"] < int(st.session_state.bid):
                        continue
                    if tname == st.session_state.current_bid_team:
                        continue
                    if st.button(
                        f"{tname} — RTM × {rtm_left}",
                        key=f"rtm_pick_{tname}",
                        use_container_width=True,
                    ):
                        _finalize_sale(
                            player,
                            tname,
                            int(st.session_state.bid),
                            is_rtm=True,
                        )
                        _advance(phase == "unsold", current_set)
                        st.session_state.bid = 0
                        st.session_state.current_bid_team = None
                        st.rerun()
        with sell_cols[2]:
            unsold_help = (
                "Remove this player for good (no one wants them)"
                if phase == "unsold"
                else "Park this player in the unsold pile; they return after all sets are done"
            )
            if st.button(
                "🚫 Unsold",
                key="unsold_btn",
                use_container_width=True,
                help=unsold_help,
            ):
                log_event(
                    st.session_state.auction_id,
                    "unsold",
                    player=player["player_name"],
                    set=str(current_set),
                    phase=phase,
                )
                if phase == "main":
                    # park for later
                    st.session_state.unsold_bucket.append(player)
                # In unsold phase, _advance pops the head regardless — player is gone.
                _advance(phase == "unsold", current_set)
                st.session_state.bid = 0
                st.session_state.current_bid_team = None
                st.rerun()

        # Bid-ladder editor (editable mid-auction)
        with st.expander("⚙️ Bid ladder", expanded=False):
            l1, l2, l3, l4, l5 = st.columns(5)
            with l1:
                nt1_up = st.number_input("T1 below ₹", 1, 500, int(tiers[0]["up_to"]), key="auc_t1_up")
            with l2:
                nt1_step = st.number_input("step ₹", 1, 100, int(tiers[0]["step"]), key="auc_t1_step")
            with l3:
                nt2_up = st.number_input("T2 below ₹", 1, 1000, int(tiers[1]["up_to"]), key="auc_t2_up")
            with l4:
                nt2_step = st.number_input("step ₹", 1, 100, int(tiers[1]["step"]), key="auc_t2_step")
            with l5:
                nt3_step = st.number_input("T3 step ₹", 1, 100, int(tiers[-1]["step"]), key="auc_t3_step")
            if st.button("Save ladder", key="save_ladder"):
                new_tiers = [
                    {"up_to": int(nt1_up), "step": int(nt1_step)},
                    {"up_to": int(nt2_up), "step": int(nt2_step)},
                    {"up_to": 10000, "step": int(nt3_step)},
                ]
                st.session_state.bid_tiers = new_tiers
                enqueue(update_bid_tiers, st.session_state.auction_id, new_tiers)
                st.success("Ladder updated")
                st.rerun()

    # ---------------- Sell action ----------------
    if sell_clicked:
        final_team = st.session_state.current_bid_team
        price = int(st.session_state.bid)
        if st.session_state.teams[final_team]["purse"] < price:
            st.error(f"{final_team} does not have enough purse!")
        else:
            _finalize_sale(player, final_team, price, is_rtm=False)
            _advance(phase == "unsold", current_set)
            st.session_state.bid = 0
            st.session_state.current_bid_team = None
            st.rerun()

    # ---------------- Team cards grid (RTM remaining is rendered inside each card) ----------------
    _render_teams_grid(active_team=st.session_state.current_bid_team)

    # ---------------- Timeline panel ----------------
    with st.expander("⏱ Event timeline", expanded=False):
        events = read_events(st.session_state.auction_id)
        if not events:
            st.caption("No events yet.")
        else:
            icons = {
                "bid": "📈", "sell": "💰", "rtm_triggered": "🔁", "rtm_used": "🔁",
                "rtm_skipped": "⏭", "new_player": "🆕", "trade_proposed": "🤝",
                "trade_accepted": "✅", "trade_rejected": "❌", "unsold": "🚫", "auction_over": "🏁",
            }
            rows = []
            for ev in reversed(events):
                ic = icons.get(ev["type"], "•")
                ts = ev.get("ts", "")[11:19]
                etype = ev["type"]
                if etype == "bid":
                    body = f"<b>{html.escape(ev.get('team',''))}</b> bid <b>₹{ev.get('amount','')}</b>"
                elif etype == "sell":
                    body = f"Sold <b>{html.escape(ev.get('player',''))}</b> to <b>{html.escape(ev.get('team',''))}</b> for <b>₹{ev.get('amount','')}</b>"
                elif etype == "rtm_used":
                    body = f"<b>{html.escape(ev.get('team',''))}</b> used RTM on <b>{html.escape(ev.get('player',''))}</b> (₹{ev.get('amount','')})"
                elif etype == "rtm_triggered":
                    body = f"RTM offered to <b>{html.escape(ev.get('old_team',''))}</b> against <b>{html.escape(ev.get('new_team',''))}</b> on <b>{html.escape(ev.get('player',''))}</b> @ ₹{ev.get('amount','')}"
                elif etype == "rtm_skipped":
                    body = f"<b>{html.escape(ev.get('old_team',''))}</b> skipped RTM on <b>{html.escape(ev.get('player',''))}</b>"
                elif etype == "new_player":
                    body = f"New player: <b>{html.escape(ev.get('player',''))}</b> (set {html.escape(str(ev.get('set','')))}, base ₹{ev.get('base','')})"
                elif etype in ("trade_proposed", "trade_accepted", "trade_rejected"):
                    body = f"Trade {etype.split('_')[1]}: <b>{html.escape(ev.get('team_a',''))}</b> ↔ <b>{html.escape(ev.get('team_b',''))}</b>"
                elif etype == "unsold":
                    phase_tag = " (bucket)" if ev.get("phase") == "unsold" else ""
                    body = f"<b>{html.escape(ev.get('player',''))}</b> unsold{phase_tag}"
                elif etype == "auction_over":
                    body = "Auction completed"
                else:
                    body = html.escape(str(ev))
                rows.append(
                    f"<div class='tl-item'>"
                    f"<div class='tl-icon'>{ic}</div>"
                    f"<div class='tl-body'>{body}<div class='tl-ts'>{ts}</div></div>"
                    f"</div>"
                )
            st.markdown(f"<div class='timeline'>{''.join(rows)}</div>", unsafe_allow_html=True)

    # Finish-early escape hatch
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        if st.button("Finish auction now", key="finish_auction"):
            enqueue(update_auction_status, st.session_state.auction_id, "completed")
            invalidate_auctions_cache()
            log_event(st.session_state.auction_id, "auction_over")
            st.session_state.page = "trade"
            st.rerun()
    with c2:
        if st.button("Back to Home", key="auction_home"):
            st.session_state.page = "home"
            st.rerun()


# =========================================================
# TRADE WINDOW
# =========================================================
elif st.session_state.page == "trade":
    st.title("Trade Window")
    teams = list(st.session_state.teams.keys())
    col1, col2 = st.columns(2)
    with col1:
        t1 = st.selectbox("Team 1", teams)
        st.dataframe(pd.DataFrame(st.session_state.teams[t1]["players"]))
    with col2:
        t2 = st.selectbox("Team 2", teams)
        st.dataframe(pd.DataFrame(st.session_state.teams[t2]["players"]))

    p1 = st.selectbox("Player Team 1", [p["player"] for p in st.session_state.teams[t1]["players"]])
    p2 = st.selectbox("Player Team 2", [p["player"] for p in st.session_state.teams[t2]["players"]])

    trade_cols = st.columns(3)
    with trade_cols[0]:
        if st.button("Propose Trade", key="trade_propose"):
            log_event(
                st.session_state.auction_id,
                "trade_proposed",
                team_a=t1, team_b=t2, player_a=p1, player_b=p2,
            )
            st.info(f"Proposed: {p1} ↔ {p2}")
    with trade_cols[1]:
        if st.button("Accept Trade", key="trade_accept", type="primary"):
            team1 = st.session_state.teams[t1]["players"]
            team2 = st.session_state.teams[t2]["players"]
            player1 = next(p for p in team1 if p["player"] == p1)
            player2 = next(p for p in team2 if p["player"] == p2)
            team1.remove(player1)
            team2.remove(player2)
            team1.append(player2)
            team2.append(player1)
            log_event(
                st.session_state.auction_id,
                "trade_accepted",
                team_a=t1, team_b=t2, player_a=p1, player_b=p2,
            )
            st.success("Trade Completed")
    with trade_cols[2]:
        if st.button("Reject Trade", key="trade_reject"):
            log_event(
                st.session_state.auction_id,
                "trade_rejected",
                team_a=t1, team_b=t2, player_a=p1, player_b=p2,
            )
            st.warning("Trade rejected")

    if st.button("Finish Trade"):
        st.session_state.page = "summary"
        st.rerun()


# =========================================================
# REPORT (read-only view of a completed auction)
# =========================================================
elif st.session_state.page == "report":
    aid = st.session_state.get("report_auction_id")
    if not aid:
        st.error("No auction selected.")
        if st.button("Back to Home"):
            st.session_state.page = "home"
            st.rerun()
        st.stop()

    try:
        snap = _load_auction_from_db(aid)
    except Exception as e:
        st.error(f"Could not load auction: {e}")
        if st.button("Back to Home"):
            st.session_state.page = "home"
            st.rerun()
        st.stop()

    a = snap["auction"]
    teams = snap["teams"]
    results = snap["results"]

    header_l, header_r = st.columns([4, 1])
    with header_l:
        st.title(a.get("name") or "Auction Report")
        dt = a["auction_datetime"].strftime("%Y-%m-%d %H:%M") if a.get("auction_datetime") else ""
        st.caption(
            f"{dt} · status: {a['status']} · purse: ₹{a['purse']} · "
            f"players/team (min): {a['players_per_team']} · "
            f"RTM: {'on' if a['rtm_enabled'] else 'off'}"
        )
        st.markdown(f"<div class='auction-id'>ID: {aid}</div>", unsafe_allow_html=True)
    with header_r:
        if st.button("← Back to Home", key="report_home"):
            st.session_state.page = "home"
            st.session_state.report_auction_id = None
            st.rerun()

    total_sold = len(results)
    total_spend = sum(r["sold_price"] for r in results)
    max_player = max(results, key=lambda r: r["sold_price"]) if results else None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Players sold", total_sold)
    m2.metric("Total spend", f"₹{total_spend}")
    m3.metric("Teams", len(teams))
    if max_player:
        m4.metric(
            "Top buy",
            f"₹{max_player['sold_price']}",
            delta=f"{max_player['player_name']} → {max_player['team_name']}",
            delta_color="off",
        )

    st.divider()
    st.subheader("Teams")

    # Reuse the card renderer from the auction page — but we're outside that
    # elif block so define a thin local version for the report.
    def _report_card(name: str, data: dict, min_players: int) -> str:
        bought = len(data["players"])
        over = bought > min_players
        total_purse = int(a["purse"])
        purse_left = int(data["purse"])
        pct = min(100, max(0, int(round(100 * purse_left / max(1, total_purse)))))
        if pct >= 50:
            bar_cls = ""
        elif pct >= 20:
            bar_cls = " low"
        else:
            bar_cls = " critical"
        safe_name = html.escape(name)
        safe_cap = html.escape(data.get("captain") or "—")
        bg = data["color"]
        fg = data.get("text_color") or "#ffffff"

        if data["players"]:
            rows = []
            for p in sorted(data["players"], key=lambda x: -x["sold"]):
                tags = []
                if p.get("is_captain"):
                    tags.append("👑")
                if p.get("is_rtm"):
                    tags.append("<span class='rtm-tag'>RTM</span>")
                tag_html = " ".join(tags)
                prefix = f"{tag_html} " if tag_html else ""
                rows.append(
                    f"<div class='player-row'>"
                    f"<div class='player-cell-name'>{prefix}{html.escape(str(p['player']))}</div>"
                    f"<div class='player-cell-price{' rtm' if p.get('is_rtm') else ''}'>₹{p['sold']}</div>"
                    f"</div>"
                )
            player_html = f"<div class='player-list' style='max-height:none;'>{''.join(rows)}</div>"
        else:
            player_html = "<div class='empty-squad'>No players</div>"

        min_hint = f"min {min_players}" if not over else f"+{bought - min_players} over min"
        spent = int(a["purse"]) - int(data["purse"])
        avatar = avatar_html(name, data.get("logo"), data.get("logo_mime"), bg, fg, size_px=42)
        return (
            f"<div class='team-card'>"
            f"<div class='team-card-header' style='background:{bg}; color:{fg};'>"
            f"<div style='display:flex; gap:0.7rem; align-items:center;'>"
            f"{avatar}"
            f"<div><div class='team-card-title'>{safe_name}</div>"
            f"<div class='team-card-captain'>Captain: {safe_cap}</div></div>"
            f"</div>"
            f"</div>"
            f"<div class='team-card-body'>"
            f"<div class='purse-row'>"
            f"<div><div class='micro-label'>Spent</div><div class='team-purse'>₹{spent}</div></div>"
            f"<div><div class='micro-label' style='text-align:right;'>Remaining</div>"
            f"<div class='team-squad' style='color:#065f46;'>₹{data['purse']}</div></div>"
            f"</div>"
            f"<div class='purse-row' style='margin-top:0.6rem;'>"
            f"<div><div class='micro-label'>Squad</div><div class='team-squad'>{bought}/{min_players}"
            f"<span class='squad-hint'>{min_hint}</span></div></div>"
            f"</div>"
            f"<div class='progress-bar' title='Purse remaining'>"
            f"<div class='progress-bar-fill{bar_cls}' style='width:{pct}%'></div>"
            f"</div>"
            f"{player_html}"
            f"</div>"
            f"</div>"
        )

    n = len(teams)
    cols_per_row = 3 if n <= 9 else 4 if n <= 12 else 5
    team_items = list(teams.items())
    for row_start in range(0, n, cols_per_row):
        row = team_items[row_start:row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for i, (name, data) in enumerate(row):
            with cols[i]:
                st.markdown(
                    _report_card(name, data, int(a["players_per_team"])),
                    unsafe_allow_html=True,
                )

    st.divider()
    st.subheader("All sales")
    if results:
        sales_df = pd.DataFrame(
            [
                {
                    "Player": r["player_name"],
                    "Set": r["set_name"],
                    "Base": r["base_price"],
                    "Sold to": r["team_name"],
                    "Price": r["sold_price"],
                    "RTM": "✓" if r["is_rtm"] else "",
                    "Time": r["created_at"].strftime("%H:%M:%S") if r.get("created_at") else "",
                }
                for r in results
            ]
        )
        st.dataframe(sales_df, use_container_width=True, hide_index=True)

        # Downloadable Excel, one sheet per team + a summary
        def export_report():
            output = BytesIO()
            with pd.ExcelWriter(output) as writer:
                sales_df.to_excel(writer, sheet_name="All sales", index=False)
                for tname, tdata in teams.items():
                    if tdata["players"]:
                        pd.DataFrame(tdata["players"]).to_excel(
                            writer, sheet_name=tname[:30], index=False
                        )
            return output.getvalue()

        st.download_button(
            "⬇ Download report (xlsx)",
            export_report(),
            file_name=f"auction-{aid[:8]}.xlsx",
        )
    else:
        st.caption("No sales recorded.")

    st.divider()
    st.subheader("Event timeline")
    events = read_events(aid)
    if not events:
        st.caption("No events recorded for this auction.")
    else:
        icons = {
            "bid": "📈", "sell": "💰", "rtm_triggered": "🔁", "rtm_used": "🔁",
            "rtm_skipped": "⏭", "new_player": "🆕", "trade_proposed": "🤝",
            "trade_accepted": "✅", "trade_rejected": "❌", "unsold": "🚫", "auction_over": "🏁",
        }
        rows = []
        for ev in reversed(events):
            ic = icons.get(ev["type"], "•")
            ts = ev.get("ts", "")[11:19]
            etype = ev["type"]
            if etype == "bid":
                body = f"<b>{html.escape(ev.get('team',''))}</b> bid <b>₹{ev.get('amount','')}</b>"
            elif etype == "sell":
                body = f"Sold <b>{html.escape(ev.get('player',''))}</b> to <b>{html.escape(ev.get('team',''))}</b> for <b>₹{ev.get('amount','')}</b>"
            elif etype == "rtm_used":
                body = f"<b>{html.escape(ev.get('team',''))}</b> used RTM on <b>{html.escape(ev.get('player',''))}</b> (₹{ev.get('amount','')})"
            elif etype == "rtm_triggered":
                body = f"RTM offered to <b>{html.escape(ev.get('old_team',''))}</b> against <b>{html.escape(ev.get('new_team',''))}</b> on <b>{html.escape(ev.get('player',''))}</b> @ ₹{ev.get('amount','')}"
            elif etype == "rtm_skipped":
                body = f"<b>{html.escape(ev.get('old_team',''))}</b> skipped RTM on <b>{html.escape(ev.get('player',''))}</b>"
            elif etype == "new_player":
                body = f"New player: <b>{html.escape(ev.get('player',''))}</b> (set {html.escape(str(ev.get('set','')))}, base ₹{ev.get('base','')})"
            elif etype in ("trade_proposed", "trade_accepted", "trade_rejected"):
                body = f"Trade {etype.split('_')[1]}: <b>{html.escape(ev.get('team_a',''))}</b> ↔ <b>{html.escape(ev.get('team_b',''))}</b>"
            elif etype == "auction_over":
                body = "Auction completed"
            else:
                body = html.escape(str(ev))
            rows.append(
                f"<div class='tl-item'>"
                f"<div class='tl-icon'>{ic}</div>"
                f"<div class='tl-body'>{body}<div class='tl-ts'>{ts}</div></div>"
                f"</div>"
            )
        st.markdown(f"<div class='timeline'>{''.join(rows)}</div>", unsafe_allow_html=True)


# =========================================================
# SUMMARY
# =========================================================
elif st.session_state.page == "summary":
    st.title("Auction Summary")
    st.markdown(f"<div class='auction-id'>Auction ID: {st.session_state.auction_id}</div>", unsafe_allow_html=True)

    for team, data in st.session_state.teams.items():
        st.markdown(
            f"<div class='team-head' style='background:{data['color']}; color:{data.get('text_color', '#ffffff')}; font-size:1.3rem;'>{team}</div>",
            unsafe_allow_html=True,
        )
        st.write("Remaining Purse:", data["purse"])
        st.dataframe(pd.DataFrame(data["players"]), use_container_width=True)

    def export():
        output = BytesIO()
        with pd.ExcelWriter(output) as writer:
            for team, data in st.session_state.teams.items():
                pd.DataFrame(data["players"]).to_excel(writer, sheet_name=team[:30])
        return output.getvalue()

    st.download_button("Download Results", export(), "auction.xlsx")

    if st.button("Back to Home"):
        # reset runtime state but keep auth
        keep = {"authenticated", "admin_username"}
        for k in list(st.session_state.keys()):
            if k not in keep:
                del st.session_state[k]
        st.rerun()
