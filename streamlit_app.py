import streamlit as st
import pandas as pd
from io import BytesIO
import pickle
import os

# ---------------- CONFIG ----------------
SAVE_FILE = "auction_state.pkl"

st.set_page_config(page_title="NMTCC Auction", layout="wide")


# ---------------- SAVE / LOAD FUNCTIONS ----------------
def save_state():
    with open(SAVE_FILE, "wb") as f:
        pickle.dump(dict(st.session_state), f)


def load_state():
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "rb") as f:
            saved_data = pickle.load(f)

        for key, value in saved_data.items():
            st.session_state[key] = value


# LOAD PREVIOUS SESSION ON START
if "loaded" not in st.session_state:
    load_state()
    st.session_state.loaded = True


# ---------------- DEFAULTS ----------------
defaults = {
    "page": "setup",
    "teams": {},
    "players_df": None,
    "players_per_team": 11,
    "bid": 5,
    "current_player_index": {},
    "sold_players": [],
    "unsold_players": [],
    "unsold_round": False
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ---------------- TITLE ----------------
st.title("🏏 NMTCC Auction")


# =====================================================
# SETUP PAGE
# =====================================================
if st.session_state.page == "setup":

    num_teams = st.number_input("Number of Teams", 2, 20, 2)

    teams = {}

    for i in range(num_teams):

        col1, col2 = st.columns(2)

        with col1:
            team_name = st.text_input("Team Name", key=f"team_{i}")

        with col2:
            captain = st.text_input("Captain", key=f"captain_{i}")

        if team_name:
            teams[team_name] = {
                "captain": captain,
                "players": [],
                "purse": 100
            }

    uploaded_file = st.file_uploader("Upload Player Excel", type=["xlsx"])

    players_per_team = st.number_input("Players Per Team", 1, 30, 11)

    purse = st.number_input("Auction Purse", 10, 1000, 100)

    if st.button("Start Auction"):

        df = pd.read_excel(uploaded_file)

        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace(" ", "_")
        )

        for team in teams:
            teams[team]["purse"] = purse

        st.session_state.teams = teams
        st.session_state.players_df = df
        st.session_state.players_per_team = players_per_team
        st.session_state.current_player_index = {
            set_name: 0 for set_name in df["set"].unique()
        }

        st.session_state.page = "auction"

        save_state()
        st.rerun()


# =====================================================
# AUCTION PAGE
# =====================================================
elif st.session_state.page == "auction":

    df = st.session_state.players_df

    available_sets = []

    for set_name in df["set"].unique():

        filtered = df[df["set"] == set_name]

        if st.session_state.current_player_index[set_name] < len(filtered):
            available_sets.append(set_name)

    if not available_sets and st.session_state.unsold_players:
        st.session_state.unsold_round = True

    if not available_sets and not st.session_state.unsold_players:
        st.session_state.page = "summary"
        save_state()
        st.rerun()

    if st.session_state.unsold_round:

        player = pd.DataFrame(st.session_state.unsold_players).iloc[0]

    else:

        selected_set = st.selectbox("Choose Set", available_sets)

        filtered_players = df[df["set"] == selected_set].reset_index(drop=True)

        idx = st.session_state.current_player_index[selected_set]

        player = filtered_players.iloc[idx]

    st.subheader(player["player_name"])
    st.write("Base Price:", player["base_price"])

    st.write("Current Bid:", st.session_state.bid)

    if st.button("Increase Bid"):
        st.session_state.bid += 2 if st.session_state.bid < 15 else 5
        save_state()
        st.rerun()

    winning_team = st.selectbox("Winning Team", list(st.session_state.teams.keys()))

    if st.button("Sell"):

        st.session_state.teams[winning_team]["players"].append(player["player_name"])
        st.session_state.teams[winning_team]["purse"] -= st.session_state.bid

        if st.session_state.unsold_round:
            st.session_state.unsold_players.pop(0)
        else:
            st.session_state.current_player_index[selected_set] += 1

        st.session_state.bid = 5

        save_state()
        st.rerun()

    if st.button("Unsold"):

        if not st.session_state.unsold_round:
            st.session_state.unsold_players.append(player.to_dict())
            st.session_state.current_player_index[selected_set] += 1
        else:
            st.session_state.unsold_players.pop(0)

        save_state()
        st.rerun()


# =====================================================
# SUMMARY PAGE
# =====================================================
elif st.session_state.page == "summary":

    st.success("Auction Completed!")

    # ---------------- TEAM WISE TABLES ----------------
    for team, details in st.session_state.teams.items():

        st.subheader(team)

        team_df = pd.DataFrame({
            "Captain": [details["captain"]] * len(details["players"]),
            "Players Bought": details["players"],
            "Remaining Purse": [details["purse"]] * len(details["players"])
        })

        st.dataframe(team_df)

    # ---------------- MULTI SHEET EXCEL ----------------
    def generate_excel():

        output = BytesIO()

        with pd.ExcelWriter(output, engine="openpyxl") as writer:

            for team, details in st.session_state.teams.items():

                team_df = pd.DataFrame({
                    "Captain": [details["captain"]] * len(details["players"]),
                    "Players Bought": details["players"],
                    "Remaining Purse": [details["purse"]] * len(details["players"])
                })

                team_df.to_excel(
                    writer,
                    sheet_name=team[:31],
                    index=False
                )

        return output.getvalue()

    st.download_button(
        "📥 Download Team Wise Auction Results",
        generate_excel(),
        "Team_Wise_Auction_Results.xlsx"
    )

    # ---------------- RESET ----------------
    if st.button("Restart Auction"):

        if os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)

        for key in list(st.session_state.keys()):
            del st.session_state[key]

        st.rerun()
