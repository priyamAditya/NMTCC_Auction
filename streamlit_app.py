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
    "bid": 5,
    "set_order": [],
    "set_players": {},
    "set_index": {},
    "current_set_idx": 0,
    "rtm_enabled": False,
    "rtm_remaining": {},
    "current_bid_team": None,

    # RTM
    "rtm_stage": None,
    "rtm_player": None,
    "rtm_price": 0,
    "rtm_counter_price": 0,
    "rtm_new_team": None,
    "rtm_old_team": None,

    # FIX
    "sell_triggered": False
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

    if st.button("Start Auction"):
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
            teams[name] = {"players": [], "purse": 100}

    uploaded = st.file_uploader("Upload Excel", type=["xlsx"])

    rtm = st.radio("RTM?", ["No", "Yes"])

    if st.button("Next"):

        df = pd.read_excel(uploaded)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

        st.session_state.teams = teams
        st.session_state.players_df = df

        st.session_state.set_order = list(df["set"].unique())
        st.session_state.current_set_idx = 0

        for s in st.session_state.set_order:
            players = df[df["set"] == s].to_dict("records")
            random.shuffle(players)
            st.session_state.set_players[s] = players
            st.session_state.set_index[s] = 0

        if rtm == "Yes":
            st.session_state.rtm_enabled = True
            st.session_state.rtm_remaining = {t: 2 for t in teams}

        st.session_state.page = "auction"
        st.rerun()


# =========================================================
# AUCTION
# =========================================================
elif st.session_state.page == "auction":

    left, right = st.columns([2, 1])

    # ---------------- LEFT ----------------
    with left:

        # PLAYER
        while True:
            if st.session_state.current_set_idx >= len(st.session_state.set_order):
                st.session_state.page = "summary"
                st.rerun()

            current_set = st.session_state.set_order[st.session_state.current_set_idx]
            idx = st.session_state.set_index[current_set]

            if idx < len(st.session_state.set_players[current_set]):
                player = st.session_state.set_players[current_set][idx]
                break
            else:
                st.session_state.current_set_idx += 1

        st.markdown(f"<h1 style='text-align:center;color:#38bdf8'>{player['player_name']}</h1>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        col1.markdown(f"<h2>Base Price<br>{player['base_price']}</h2>", unsafe_allow_html=True)
        col2.markdown(f"<h2>Current Bid<br>{st.session_state.bid}</h2>", unsafe_allow_html=True)

        last_team = st.selectbox("Previous Team", ["NA"] + list(st.session_state.teams.keys()))

        # VALID TEAMS
        valid_teams = [
            t for t in st.session_state.teams
            if st.session_state.teams[t]["purse"] >= st.session_state.bid
        ]

        if not valid_teams:
            st.warning("No team can afford this player. Reduce bid.")
        else:
            bid_team = st.selectbox("Bidding Team", valid_teams)
            st.session_state.current_bid_team = bid_team

        colA, colB = st.columns(2)

        if colA.button("Increase Bid"):
            st.session_state.bid += 2 if st.session_state.bid < 15 else 5
            st.rerun()

        if colB.button("Sell Player"):
            st.session_state.sell_triggered = True

        # ================= SELL PROCESS =================
        if st.session_state.sell_triggered:

            st.session_state.sell_triggered = False

            final_team = st.session_state.current_bid_team
            price = st.session_state.bid

            if st.session_state.teams[final_team]["purse"] < price:
                st.error(f"{final_team} does not have enough purse!")

            else:
                # RTM
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

    # ---------------- RIGHT ----------------
    with right:

        st.markdown("## Teams")

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
