import streamlit as st
import pandas as pd
import random
from io import BytesIO

st.set_page_config(page_title="NMTCC Auction", layout="wide")

# ---------------- STATE ----------------
defaults = {
    "page": "home",
    "teams": {},
    "players_df": None,
    "players_per_team": 11,
    "purse": 100,
    "bid": 5,
    "set_order": [],
    "set_players": {},
    "set_index": {},
    "current_set_idx": 0,
    "unsold": [],
    "rtm_enabled": False,
    "rtm_count": 0,
    "rtm_remaining": {},
    "current_bid_team": None,
    "rtm_stage": None,
    "rtm_player": None,
    "rtm_price": 0,
    "rtm_counter_price": 0,
    "rtm_new_team": None,
    "rtm_old_team": None
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================================================
# HOME
# =========================================================
if st.session_state.page == "home":

    st.markdown("<h1 style='text-align:center;'>🏏 NMTCC AUCTION</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align:center;'>Flamingo Cup Season 1 - Part 2</h3>", unsafe_allow_html=True)

    if st.button("🚀 Start Auction"):
        st.session_state.page = "setup"
        st.rerun()


# =========================================================
# SETUP
# =========================================================
elif st.session_state.page == "setup":

    st.title("Auction Setup")

    num_teams = st.number_input("Number of Teams", 2, 10, 2)

    teams = {}

    for i in range(num_teams):
        col1, col2 = st.columns(2)
        name = col1.text_input("Team Name", key=f"name{i}")
        cap = col2.text_input("Captain", key=f"cap{i}")

        if name:
            teams[name] = {"captain": cap, "players": [], "purse": 0}

    uploaded = st.file_uploader("Upload Excel", type=["xlsx"])

    players_per_team = st.number_input("Players per Team", 1, 20, 11)
    purse = st.number_input("Auction Purse", 10, 500, 100)

    rtm = st.radio("RTM Option?", ["No", "Yes"])

    if st.button("Next"):

        if uploaded is None:
            st.error("Upload Excel file")
            st.stop()

        df = pd.read_excel(uploaded)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

        st.session_state.teams = teams
        st.session_state.players_df = df
        st.session_state.players_per_team = players_per_team
        st.session_state.purse = purse

        for t in teams:
            teams[t]["purse"] = purse

        st.session_state.set_order = list(df["set"].unique())
        st.session_state.current_set_idx = 0

        for s in st.session_state.set_order:
            players = df[df["set"] == s].to_dict("records")
            random.shuffle(players)
            st.session_state.set_players[s] = players
            st.session_state.set_index[s] = 0

        if rtm == "Yes":
            st.session_state.rtm_enabled = True
            st.session_state.page = "rtm"
        else:
            st.session_state.page = "auction"

        st.rerun()


# =========================================================
# RTM SETUP
# =========================================================
elif st.session_state.page == "rtm":

    st.title("RTM Setup")

    count = st.number_input("RTMs per Team", 0, 5, 2)

    if st.button("Proceed"):
        st.session_state.rtm_count = count
        st.session_state.rtm_remaining = {t: count for t in st.session_state.teams}
        st.session_state.page = "auction"
        st.rerun()

elif st.session_state.page == "auction":

    # ================= MAIN LAYOUT =================
    left, right = st.columns([2, 1])

    # =========================================================
    # LEFT SIDE → AUCTION PANEL
    # =========================================================
    with left:

        # RTM DISPLAY
        if st.session_state.rtm_enabled:
            st.markdown("### RTM Remaining")
            cols = st.columns(len(st.session_state.rtm_remaining))
            for i, (team, count) in enumerate(st.session_state.rtm_remaining.items()):
                with cols[i]:
                    color = "#22c55e" if count > 0 else "#ef4444"
                    st.markdown(f"""
                    <div style="background:#1e293b;padding:10px;border-radius:10px;text-align:center;">
                        <h5 style="color:white;">{team}</h5>
                        <h2 style="color:{color};margin:0;">{count}</h2>
                    </div>
                    """, unsafe_allow_html=True)

        # -------- GET PLAYER --------
        while st.session_state.current_set_idx < len(st.session_state.set_order):
            current_set = st.session_state.set_order[st.session_state.current_set_idx]
            idx = st.session_state.set_index[current_set]

            if idx < len(st.session_state.set_players[current_set]):
                player = st.session_state.set_players[current_set][idx]
                break
            else:
                st.session_state.current_set_idx += 1
        else:
            st.session_state.page = "trade"
            st.rerun()

        # ================= PLAYER DISPLAY =================
        st.markdown(f"""
        <div style="text-align:center; padding:20px;">
            <h1 style="color:#38bdf8; font-size:48px;">{player['player_name']}</h1>
        </div>
        """, unsafe_allow_html=True)

        # PRICE DISPLAY
        col1, col2 = st.columns(2)

        with col1:
            st.markdown(f"""
            <div style="text-align:center;">
                <p>Base Price</p>
                <h1 style="color:#22c55e;">{player['base_price']}</h1>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"""
            <div style="text-align:center;">
                <p>Current Bid</p>
                <h1 style="color:#facc15;">{st.session_state.bid}</h1>
            </div>
            """, unsafe_allow_html=True)

        # PREVIOUS TEAM
        last_team = "NA"
        if st.session_state.rtm_enabled:
            last_team = st.selectbox("Previous Team", ["NA"] + list(st.session_state.teams.keys()))

        # VALID TEAMS
        valid_teams = [
            t for t in st.session_state.teams
            if st.session_state.teams[t]["purse"] >= st.session_state.bid
        ]

        bid_team = st.selectbox("Bidding Team", valid_teams)
        st.session_state.current_bid_team = bid_team

        # BUTTONS
        colA, colB = st.columns(2)

        with colA:
            if st.button("⬆ Increase Bid"):
                st.session_state.bid += 2 if st.session_state.bid < 15 else 5
                st.rerun()

        with colB:
            if st.button("✅ Sell Player"):

                final_team = st.session_state.current_bid_team
                price = st.session_state.bid

                if st.session_state.teams[final_team]["purse"] < price:
                    st.error(f"{final_team} does not have enough purse!")
                else:
                    if st.session_state.rtm_enabled and last_team != "NA":
                        if st.session_state.rtm_remaining[last_team] > 0:
                            st.session_state.rtm_stage = "ask"
                            st.session_state.rtm_player = player
                            st.session_state.rtm_price = price
                            st.session_state.rtm_new_team = final_team
                            st.session_state.rtm_old_team = last_team
                            st.rerun()

                    # NORMAL SALE
                    st.session_state.teams[final_team]["players"].append({
                        "player": player["player_name"],
                        "base": player["base_price"],
                        "sold": price
                    })
                    st.session_state.teams[final_team]["purse"] -= price

                    st.session_state.set_index[current_set] += 1
                    st.session_state.bid = 5
                    st.rerun()

        # ================= RTM FLOW =================
        if st.session_state.rtm_stage == "ask":

            st.warning(f"{st.session_state.rtm_old_team} can use RTM")

            if st.button("Use RTM"):
                st.session_state.rtm_stage = "counter"
                st.rerun()

            if st.button("Skip RTM"):
                team = st.session_state.rtm_new_team
                price = st.session_state.rtm_price

                st.session_state.teams[team]["players"].append({
                    "player": st.session_state.rtm_player["player_name"],
                    "base": st.session_state.rtm_player["base_price"],
                    "sold": price
                })
                st.session_state.teams[team]["purse"] -= price

                st.session_state.rtm_stage = None
                st.session_state.set_index[current_set] += 1
                st.session_state.bid = 5
                st.rerun()

        elif st.session_state.rtm_stage == "counter":

            new_price = st.number_input("Enter RTM Price", min_value=st.session_state.rtm_price)

            if st.button("Submit RTM Price"):
                st.session_state.rtm_counter_price = new_price
                st.session_state.rtm_stage = "decision"
                st.rerun()

        elif st.session_state.rtm_stage == "decision":

            if st.button("Accept"):
                team = st.session_state.rtm_new_team
                price = st.session_state.rtm_counter_price

                if st.session_state.teams[team]["purse"] >= price:
                    st.session_state.teams[team]["players"].append({
                        "player": st.session_state.rtm_player["player_name"],
                        "base": st.session_state.rtm_player["base_price"],
                        "sold": price
                    })
                    st.session_state.teams[team]["purse"] -= price

                    st.session_state.rtm_stage = None
                    st.session_state.set_index[current_set] += 1
                    st.session_state.bid = 5
                    st.rerun()
                else:
                    st.error("Not enough purse!")

            if st.button("Reject"):
                team = st.session_state.rtm_old_team
                price = st.session_state.rtm_counter_price

                if st.session_state.teams[team]["purse"] >= price:
                    st.session_state.teams[team]["players"].append({
                        "player": st.session_state.rtm_player["player_name"],
                        "base": st.session_state.rtm_player["base_price"],
                        "sold": price
                    })
                    st.session_state.teams[team]["purse"] -= price
                    st.session_state.rtm_remaining[team] -= 1

                    st.session_state.rtm_stage = None
                    st.session_state.set_index[current_set] += 1
                    st.session_state.bid = 5
                    st.rerun()
                else:
                    st.error("Not enough purse!")

    # =========================================================
    # RIGHT SIDE → TEAM PANELS
    # =========================================================
    with right:

        st.markdown("## 🏏 Teams")

        for team, data in st.session_state.teams.items():
            st.markdown(f"### {team} (₹{data['purse']})")
            st.dataframe(pd.DataFrame(data["players"]), height=200)

# =========================================================
# SUMMARY
# =========================================================
elif st.session_state.page == "summary":

    st.title("Auction Summary")

    for team, data in st.session_state.teams.items():
        st.subheader(team)
        st.write("Remaining Purse:", data["purse"])
        st.dataframe(pd.DataFrame(data["players"]))

    def export():
        output = BytesIO()
        with pd.ExcelWriter(output) as writer:
            for team, data in st.session_state.teams.items():
                pd.DataFrame(data["players"]).to_excel(writer, sheet_name=team[:30])
        return output.getvalue()

    st.download_button("Download Excel", export(), "auction.xlsx")
