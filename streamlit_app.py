import random
import urllib.parse
import uuid
from datetime import date, datetime, time
from io import BytesIO

import pandas as pd
import streamlit as st

from auth import check_admin, create_admin, has_any_admin
from db import (
    add_auction_players,
    add_auction_team,
    create_auction,
    create_master_team,
    get_master_team_by_name,
    init_schema,
    list_auctions,
    list_master_teams,
    record_sale,
    update_auction_status,
)
from sync_queue import enqueue, stats as sync_stats

st.set_page_config(page_title="NMTCC Auction", layout="wide", page_icon="🏏")

# Global styles
st.markdown(
    """
    <style>
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
@st.cache_data(ttl=30, show_spinner=False)
def cached_master_teams():
    return list_master_teams()


@st.cache_data(ttl=15, show_spinner=False)
def cached_recent_auctions():
    return list_auctions()


def invalidate_master_teams_cache():
    cached_master_teams.clear()


def invalidate_auctions_cache():
    cached_recent_auctions.clear()


# ---------------- Sync queue status (sidebar) ----------------
def render_sync_sidebar():
    s = sync_stats()
    with st.sidebar:
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
        if st.button("Refresh status", key="refresh_sync"):
            st.rerun()


render_sync_sidebar()


# ---------------- SESSION STATE ----------------
defaults = {
    "authenticated": False,
    "admin_username": None,
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
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================================================
# AUTH GATE
# =========================================================
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
                        st.session_state.authenticated = True
                        st.session_state.admin_username = u
                        st.rerun()
                    else:
                        st.error("Invalid username or password")


if not st.session_state.authenticated:
    render_auth()
    st.stop()


# Header with logout
top_l, top_r = st.columns([6, 1])
with top_r:
    if st.button("Log out"):
        st.session_state.authenticated = False
        st.session_state.admin_username = None
        st.rerun()


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

        st.markdown("&nbsp;", unsafe_allow_html=True)

        with st.expander("📋 Past Auctions", expanded=False):
            auctions = cached_recent_auctions()
            if not auctions:
                st.caption("No past auctions yet.")
            else:
                for a in auctions:
                    dt = a["auction_datetime"].strftime("%Y-%m-%d %H:%M")
                    name = a["name"] or "(unnamed)"
                    st.markdown(
                        f"**{name}** — {dt} · status: `{a['status']}` "
                        f"<br><span class='auction-id'>ID: {a['id']}</span>",
                        unsafe_allow_html=True,
                    )
                    st.divider()


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

    st.divider()

    # --- Players Upload ---
    st.subheader("2 · Players")
    uploaded = st.file_uploader(
        "Upload Players Excel (columns: player_name, set, base_price)",
        type=["xlsx"],
    )
    df_preview = None
    if uploaded is not None:
        try:
            df_preview = pd.read_excel(uploaded)
            df_preview.columns = df_preview.columns.str.strip().str.lower().str.replace(" ", "_")
            required = {"player_name", "set", "base_price"}
            missing = required - set(df_preview.columns)
            if missing:
                st.error(f"Missing columns: {', '.join(missing)}")
                df_preview = None
            else:
                st.success(f"Loaded {len(df_preview)} players across {df_preview['set'].nunique()} sets")
                st.dataframe(df_preview, use_container_width=True, height=200)
        except Exception as e:
            st.error(f"Could not parse Excel: {e}")
            df_preview = None

    st.divider()

    # --- Teams ---
    st.subheader("3 · Teams Participating")
    st.caption("Max 15 teams. Each team name must be unique. Colours are saved for reuse.")

    master_teams = cached_master_teams()
    master_names = [t["name"] for t in master_teams]
    selected_names = [t["name"] for t in st.session_state.setup_selected_teams]

    t1, t2 = st.columns([3, 2])
    with t1:
        to_add = st.selectbox(
            "Add saved team",
            options=[n for n in master_names if n not in selected_names],
            index=None,
            placeholder="Select a saved team...",
            key="add_saved_team",
        )
        if st.button("➕ Add saved team", disabled=to_add is None):
            if len(st.session_state.setup_selected_teams) >= 15:
                st.error("Maximum 15 teams reached")
            else:
                team = next(t for t in master_teams if t["name"] == to_add)
                st.session_state.setup_selected_teams.append(
                    {
                        "id": team["id"],
                        "name": team["name"],
                        "captain": team["captain"],
                        "color": team["color"],
                        "text_color": team.get("text_color") or "#ffffff",
                    }
                )
                st.rerun()

    with t2:
        with st.popover("➕ Add new team"):
            # Plain widgets (not inside a form) so the preview updates live
            new_name = st.text_input("Team Name", key="new_team_name")
            new_captain = st.text_input("Captain", key="new_team_captain")
            c_bg, c_fg = st.columns(2)
            with c_bg:
                new_color = st.color_picker("Background", value="#3b82f6", key="new_team_bg")
            with c_fg:
                new_text_color = st.color_picker("Text Colour", value="#ffffff", key="new_team_fg")

            preview_label = (new_name.strip() or "Team") + " · " + (new_captain.strip() or "Captain")
            st.markdown(
                f"<div style='padding:0.5rem 1rem; border-radius:999px; display:inline-block; "
                f"background:{new_color}; color:{new_text_color}; font-weight:600; margin:0.4rem 0;'>"
                f"{preview_label}</div>",
                unsafe_allow_html=True,
            )

            if st.button("Save & Add", key="new_team_save"):
                nn = new_name.strip()
                if not nn:
                    st.error("Team name required")
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
                            nn, new_captain.strip(), new_color, new_text_color
                        )
                        invalidate_master_teams_cache()
                        st.session_state.setup_selected_teams.append(
                            {
                                "id": team_id,
                                "name": nn,
                                "captain": new_captain.strip(),
                                "color": new_color,
                                "text_color": new_text_color,
                            }
                        )
                        # clear the form fields for the next entry
                        for k in ("new_team_name", "new_team_captain"):
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

    # --- Validate & Start ---
    nav_l, nav_r = st.columns([1, 1])
    with nav_l:
        if st.button("← Back to Home"):
            st.session_state.page = "home"
            st.rerun()
    with nav_r:
        if st.button("🚀 Start Auction", type="primary", use_container_width=True):
            errors = []
            if uploaded is None or df_preview is None:
                errors.append("Upload a valid players Excel file")
            if len(st.session_state.setup_selected_teams) < 2:
                errors.append("Add at least 2 teams")
            if len(st.session_state.setup_selected_teams) > 15:
                errors.append("Maximum 15 teams")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                dt = datetime.combine(auction_date, auction_time)
                auction_id = str(uuid.uuid4())

                # Async: UI proceeds immediately; daemon thread syncs to Postgres.
                enqueue(
                    create_auction,
                    auction_id=auction_id,
                    name=auction_name.strip() or None,
                    auction_datetime=dt,
                    players_per_team=int(players_per_team),
                    purse=int(purse),
                    rtm_enabled=bool(rtm_enabled),
                    rtm_count=int(rtm_count) if rtm_enabled else 0,
                )

                teams_state = {}
                for t in st.session_state.setup_selected_teams:
                    enqueue(
                        add_auction_team,
                        auction_id,
                        t["id"],
                        int(purse),
                        int(rtm_count) if rtm_enabled else 0,
                    )
                    teams_state[t["name"]] = {
                        "team_id": t["id"],
                        "captain": t["captain"],
                        "color": t["color"],
                        "text_color": t.get("text_color") or "#ffffff",
                        "purse": int(purse),
                        "players": [],
                        "rtm_remaining": int(rtm_count) if rtm_enabled else 0,
                    }

                player_rows = [
                    (str(r["player_name"]), str(r["set"]), r["base_price"])
                    for r in df_preview.to_dict("records")
                ]
                enqueue(add_auction_players, auction_id, player_rows)
                invalidate_auctions_cache()

                # hydrate session state for auction flow
                st.session_state.auction_id = auction_id
                st.session_state.teams = teams_state
                st.session_state.players_df = df_preview
                st.session_state.players_per_team = int(players_per_team)
                st.session_state.purse = int(purse)
                st.session_state.rtm_enabled = bool(rtm_enabled)
                st.session_state.rtm_count = int(rtm_count) if rtm_enabled else 0
                st.session_state.bid = 5

                set_order = list(df_preview["set"].unique())
                st.session_state.set_order = set_order
                st.session_state.current_set_idx = 0
                for s in set_order:
                    players = df_preview[df_preview["set"] == s].to_dict("records")
                    random.shuffle(players)
                    st.session_state.set_players[s] = players
                    st.session_state.set_index[s] = 0

                st.session_state.page = "auction"
                st.rerun()


# =========================================================
# AUCTION
# =========================================================
elif st.session_state.page == "auction":
    # Purse badge at top, prominent
    aid = st.session_state.auction_id
    st.markdown(
        f"""
        <div class='purse-badge'>
          <div class='label'>Auction Purse</div>
          <div class='value'>{st.session_state.purse}</div>
        </div>
        <div style='text-align:center;' class='auction-id'>Auction ID: {aid}</div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.rtm_enabled:
        st.subheader("RTM Remaining")
        rtm_cols = st.columns(len(st.session_state.teams))
        for i, (team, data) in enumerate(st.session_state.teams.items()):
            with rtm_cols[i]:
                count = data["rtm_remaining"]
                count_color = "#22c55e" if count > 0 else "#ef4444"
                st.markdown(
                    f"<div class='team-head' style='background:{data['color']}; color:{data.get('text_color', '#ffffff')};'>{team}</div>"
                    f"<h2 style='color:{count_color}'>{count}</h2>",
                    unsafe_allow_html=True,
                )

    # Walk to next player
    while st.session_state.current_set_idx < len(st.session_state.set_order):
        current_set = st.session_state.set_order[st.session_state.current_set_idx]
        idx = st.session_state.set_index[current_set]
        if idx < len(st.session_state.set_players[current_set]):
            player = st.session_state.set_players[current_set][idx]
            break
        else:
            st.session_state.current_set_idx += 1
    else:
        enqueue(update_auction_status, st.session_state.auction_id, "completed")
        invalidate_auctions_cache()
        st.session_state.page = "trade"
        st.rerun()

    st.subheader(player["player_name"])
    st.write("Set:", current_set, " | Base Price:", player["base_price"])

    last_team = "NA"
    if st.session_state.rtm_enabled:
        last_team = st.selectbox("Previous Team", ["NA"] + list(st.session_state.teams.keys()))

    st.write("Current Bid:", st.session_state.bid)

    valid_teams = [
        t for t, d in st.session_state.teams.items() if d["purse"] >= st.session_state.bid
    ]
    if not valid_teams:
        st.error("No team can afford this player. Reduce bid.")
        st.stop()

    bid_team = st.selectbox("Bidding Team", valid_teams)
    st.session_state.current_bid_team = bid_team

    if st.button("Increase Bid"):
        st.session_state.bid += 2 if st.session_state.bid < 15 else 5
        st.rerun()

    if st.button("Sell Player", type="primary"):
        final_team = st.session_state.current_bid_team
        price = st.session_state.bid

        if st.session_state.teams[final_team]["purse"] < price:
            st.error(f"{final_team} does not have enough purse!")
        else:
            if st.session_state.rtm_enabled and last_team != "NA":
                if st.session_state.teams[last_team]["rtm_remaining"] > 0:
                    st.session_state.rtm_stage = "ask"
                    st.session_state.rtm_player = player
                    st.session_state.rtm_price = price
                    st.session_state.rtm_new_team = final_team
                    st.session_state.rtm_old_team = last_team
                    st.rerun()

            # NORMAL SALE
            td = st.session_state.teams[final_team]
            td["players"].append(
                {"player": player["player_name"], "base": player["base_price"], "sold": price}
            )
            td["purse"] -= price
            enqueue(
                record_sale,
                st.session_state.auction_id,
                player["player_name"],
                td["team_id"],
                price,
                is_rtm=False,
            )
            st.session_state.set_index[current_set] += 1
            st.session_state.bid = 5
            st.rerun()

    # RTM FLOW
    if st.session_state.rtm_stage == "ask":
        st.warning(f"{st.session_state.rtm_old_team} can use RTM")
        if st.button("Use RTM"):
            st.session_state.rtm_stage = "counter"
            st.rerun()
        if st.button("Skip RTM"):
            new_team = st.session_state.rtm_new_team
            price = st.session_state.rtm_price
            td = st.session_state.teams[new_team]
            td["players"].append(
                {
                    "player": st.session_state.rtm_player["player_name"],
                    "base": st.session_state.rtm_player["base_price"],
                    "sold": price,
                }
            )
            td["purse"] -= price
            enqueue(
                record_sale,
                st.session_state.auction_id,
                st.session_state.rtm_player["player_name"],
                td["team_id"],
                price,
                is_rtm=False,
            )
            st.session_state.rtm_stage = None
            st.session_state.set_index[current_set] += 1
            st.session_state.bid = 5
            st.rerun()

    elif st.session_state.rtm_stage == "counter":
        new_price = st.number_input("Enter RTM Price", min_value=st.session_state.rtm_price)
        if st.button("Submit Price"):
            st.session_state.rtm_counter_price = new_price
            st.session_state.rtm_stage = "decision"
            st.rerun()

    elif st.session_state.rtm_stage == "decision":
        if st.button("Accept"):
            team = st.session_state.rtm_new_team
            price = st.session_state.rtm_counter_price
            td = st.session_state.teams[team]
            if td["purse"] < price:
                st.error(f"{team} cannot afford this RTM price!")
            else:
                td["players"].append(
                    {
                        "player": st.session_state.rtm_player["player_name"],
                        "base": st.session_state.rtm_player["base_price"],
                        "sold": price,
                    }
                )
                td["purse"] -= price
                enqueue(
                    record_sale,
                    st.session_state.auction_id,
                    st.session_state.rtm_player["player_name"],
                    td["team_id"],
                    price,
                    is_rtm=False,
                )
                st.session_state.rtm_stage = None
                st.session_state.set_index[current_set] += 1
                st.session_state.bid = 5
                st.rerun()
        if st.button("Reject"):
            team = st.session_state.rtm_old_team
            price = st.session_state.rtm_counter_price
            td = st.session_state.teams[team]
            if td["purse"] < price:
                st.error(f"{team} cannot afford RTM!")
            else:
                td["players"].append(
                    {
                        "player": st.session_state.rtm_player["player_name"],
                        "base": st.session_state.rtm_player["base_price"],
                        "sold": price,
                    }
                )
                td["purse"] -= price
                td["rtm_remaining"] -= 1
                enqueue(
                    record_sale,
                    st.session_state.auction_id,
                    st.session_state.rtm_player["player_name"],
                    td["team_id"],
                    price,
                    is_rtm=True,
                )
                st.session_state.rtm_stage = None
                st.session_state.set_index[current_set] += 1
                st.session_state.bid = 5
                st.rerun()

    st.divider()
    cols = st.columns(len(st.session_state.teams))
    for i, (team, data) in enumerate(st.session_state.teams.items()):
        with cols[i]:
            st.markdown(
                f"<div class='team-head' style='background:{data['color']}; color:{data.get('text_color', '#ffffff')};'>{team}</div>",
                unsafe_allow_html=True,
            )
            st.write("Purse:", data["purse"])
            st.dataframe(pd.DataFrame(data["players"]), use_container_width=True)


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

    if st.button("Execute Trade"):
        team1 = st.session_state.teams[t1]["players"]
        team2 = st.session_state.teams[t2]["players"]
        player1 = next(p for p in team1 if p["player"] == p1)
        player2 = next(p for p in team2 if p["player"] == p2)
        team1.remove(player1)
        team2.remove(player2)
        team1.append(player2)
        team2.append(player1)
        st.success("Trade Completed")

    if st.button("Finish Trade"):
        st.session_state.page = "summary"
        st.rerun()


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
