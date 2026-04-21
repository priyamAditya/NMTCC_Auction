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

    # RTM FLOW
    "rtm_stage": None,
    "rtm_player": None,
    "rtm_price": 0,
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
    st.markdown("<h3 style='text-align:center;'>Flamingo cup Season 1 - Part 2</h3>", unsafe_allow_html=True)

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
# RTM CONFIG
# =========================================================
elif st.session_state.page == "rtm":

    st.title("RTM Setup")

    count = st.number_input("RTMs per Team", 0, 5, 2)

    if st.button("Proceed"):
        st.session_state.rtm_count = count
        st.session_state.rtm_remaining = {
            t: count for t in st.session_state.teams
        }
        st.session_state.page = "auction"
        st.rerun()


# =========================================================
# AUCTION
# =========================================================
elif st.session_state.page == "auction":

    # SHOW RTM BALANCE
    if st.session_state.rtm_enabled:
        st.subheader("RTM Remaining")
        for t, v in st.session_state.rtm_remaining.items():
            st.write(f"{t}: {v}")

    # GET PLAYER
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

    st.subheader(player["player_name"])
    st.write("Base Price:", player["base_price"])

    last_team = "NA"
    if st.session_state.rtm_enabled:
        last_team = st.selectbox("Previous Team", ["NA"] + list(st.session_state.teams.keys()))

    st.write("Current Bid:", st.session_state.bid)

    bid_team = st.selectbox("Bidding Team", list(st.session_state.teams.keys()))

    if st.button("Increase Bid"):
        st.session_state.bid += 2 if st.session_state.bid < 15 else 5
        st.session_state.current_bid_team = bid_team
        st.rerun()


    # =====================================================
    # SELL BUTTON (UPDATED)
    # =====================================================
    if st.button("Sell Player"):

        final_team = st.session_state.current_bid_team
        price = st.session_state.bid

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


    # =====================================================
    # RTM FLOW (UPDATED)
    # =====================================================
    if st.session_state.rtm_stage == "ask":

        st.warning(f"{st.session_state.rtm_old_team} can use RTM")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Use RTM"):
                st.session_state.rtm_stage = "decision"
                st.rerun()

        with col2:
            if st.button("Skip RTM"):

                new_team = st.session_state.rtm_new_team
                player = st.session_state.rtm_player
                price = st.session_state.rtm_price

                st.session_state.teams[new_team]["players"].append({
                    "player": player["player_name"],
                    "base": player["base_price"],
                    "sold": price
                })

                st.session_state.teams[new_team]["purse"] -= price

                st.session_state.rtm_stage = None
                st.session_state.set_index[current_set] += 1
                st.session_state.bid = 5

                st.rerun()


    elif st.session_state.rtm_stage == "decision":

        st.warning(f"{st.session_state.rtm_new_team}, do you want to retain the player?")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Accept (Keep Player)"):

                new_team = st.session_state.rtm_new_team
                player = st.session_state.rtm_player
                price = st.session_state.rtm_price

                st.session_state.teams[new_team]["players"].append({
                    "player": player["player_name"],
                    "base": player["base_price"],
                    "sold": price
                })

                st.session_state.teams[new_team]["purse"] -= price

                st.session_state.rtm_stage = None
                st.session_state.set_index[current_set] += 1
                st.session_state.bid = 5

                st.rerun()

        with col2:
            if st.button("Reject (Give to RTM Team)"):

                old_team = st.session_state.rtm_old_team
                player = st.session_state.rtm_player
                price = st.session_state.rtm_price

                st.session_state.teams[old_team]["players"].append({
                    "player": player["player_name"],
                    "base": player["base_price"],
                    "sold": price
                })

                st.session_state.teams[old_team]["purse"] -= price
                st.session_state.rtm_remaining[old_team] -= 1

                st.session_state.rtm_stage = None
                st.session_state.set_index[current_set] += 1
                st.session_state.bid = 5

                st.rerun()


    # =====================================================
    # UNSOLD
    # =====================================================
    if st.button("Unsold"):
        st.session_state.unsold.append(player)
        st.session_state.set_index[current_set] += 1
        st.rerun()


    # =====================================================
    # TEAM TABLES
    # =====================================================
    st.divider()

    cols = st.columns(len(st.session_state.teams))

    for i, (team, data) in enumerate(st.session_state.teams.items()):
        with cols[i]:
            st.subheader(team)
            st.write("Purse:", data["purse"])
            st.dataframe(pd.DataFrame(data["players"]))


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

    st.download_button("Download Results", export(), "auction.xlsx")

    if st.button("Restart"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
