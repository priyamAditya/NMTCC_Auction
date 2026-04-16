import streamlit as st
import pandas as pd
import time
from io import BytesIO

# ---------------- PAGE CONFIG ----------------
st.set_page_config(
    page_title="NMTCC Auction",
    layout="wide"
)

# ---------------- PREMIUM CSS ----------------
st.markdown("""
<style>
.main {
    background: linear-gradient(135deg,#0B0F1A,#111827);
}
.player-card {
    padding:30px;
    border-radius:25px;
    background: linear-gradient(135deg,#1E293B,#334155);
    text-align:center;
    color:white;
    box-shadow:0 10px 30px rgba(0,0,0,0.5);
}
.big-font {
    font-size:28px;
    font-weight:bold;
    color:#FFD700;
}
</style>
""", unsafe_allow_html=True)

# ---------------- SESSION STATE ----------------
defaults = {
    "auction_started": False,
    "teams": {},
    "current_player_index": 0,
    "sold_players": [],
    "history": [],
    "bid": 5
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ---------------- TITLE ----------------
st.markdown(
    "<h1 style='text-align:center;color:#FFD700;'>🏏 NMTCC AUCTION LEAGUE</h1>",
    unsafe_allow_html=True
)

# ---------------- SETUP SCREEN ----------------
if not st.session_state.auction_started:

    st.header("Auction Setup")

    num_teams = st.number_input(
        "Enter Number of Teams",
        min_value=2,
        max_value=20,
        value=2
    )

    teams = {}

    for i in range(num_teams):

        st.subheader(f"Team {i+1}")

        col1, col2, col3 = st.columns(3)

        with col1:
            team_name = st.text_input("Team Name", key=f"team_{i}")

        with col2:
            captain = st.text_input("Captain", key=f"captain_{i}")

        with col3:
            logo = st.file_uploader(
                "Upload Logo",
                type=['png', 'jpg'],
                key=f"logo_{i}"
            )

        if team_name:
            teams[team_name] = {
                "captain": captain,
                "logo": logo,
                "players": [],
                "purse": 0
            }

    uploaded_file = st.file_uploader(
        "Upload Player Excel",
        type=['xlsx']
    )

    players_per_team = st.number_input(
        "Players Per Team",
        min_value=1,
        value=11
    )

    purse = st.number_input(
        "Auction Purse",
        min_value=10,
        value=100
    )

    if st.button("🚀 START AUCTION"):

        if uploaded_file is None:
            st.error("Please upload Excel file.")
            st.stop()

        df = pd.read_excel(uploaded_file)

        # Normalize columns
        df.columns = (
            df.columns
            .str.strip()
            .str.lower()
            .str.replace(" ", "_")
        )

        required_columns = ["player_name", "set", "base_price"]

        missing_cols = [
            col for col in required_columns if col not in df.columns
        ]

        if missing_cols:
            st.error(f"Missing Columns: {missing_cols}")
            st.stop()

        for team in teams:
            teams[team]["purse"] = purse

        st.session_state.teams = teams
        st.session_state.players_df = df
        st.session_state.players_per_team = players_per_team
        st.session_state.auction_started = True
        st.session_state.bid = 5

        st.rerun()

# ---------------- AUCTION SCREEN ----------------
else:

    df = st.session_state.players_df

    selected_set = st.selectbox(
        "Choose Player Set",
        df["set"].unique()
    )

    filtered_players = df[df["set"] == selected_set].reset_index(drop=True)

    if st.session_state.current_player_index >= len(filtered_players):
        st.success("All Players in this Set Auctioned!")
        st.stop()

    player = filtered_players.iloc[
        st.session_state.current_player_index
    ]

    # TIMER
    st.markdown("### ⏳ Auction Timer")

    timer_placeholder = st.empty()

    for i in range(5, 0, -1):
        timer_placeholder.markdown(f"## {i} sec")
        time.sleep(0.1)

    # PLAYER CARD
    st.markdown(f"""
    <div class='player-card'>
        <h2>{player['player_name']}</h2>
        <h4>Set: {player['set']}</h4>
        <h3>Base Price: ₹{player['base_price']}</h3>
    </div>
    """, unsafe_allow_html=True)

    # BID DISPLAY
    st.markdown(
        f"<div class='big-font'>Current Bid: ₹{st.session_state.bid}</div>",
        unsafe_allow_html=True
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("➕ Increase Bid"):
            if st.session_state.bid < 15:
                st.session_state.bid += 2
            else:
                st.session_state.bid += 5
            st.rerun()

    with col2:
        if st.button("➖ Decrease Bid"):
            if st.session_state.bid > 5:
                if st.session_state.bid <= 15:
                    st.session_state.bid -= 2
                else:
                    st.session_state.bid -= 5
            st.rerun()

    with col3:
        if st.button("🔄 Reset Bid"):
            st.session_state.bid = int(player["base_price"])
            st.rerun()

    winning_team = st.selectbox(
        "Winning Team",
        list(st.session_state.teams.keys())
    )

    col4, col5, col6 = st.columns(3)

    # SELL PLAYER
    with col4:
        if st.button("🔨 SELL PLAYER"):

            team = st.session_state.teams[winning_team]

            if team["purse"] < st.session_state.bid:
                st.error("Insufficient Purse")

            else:
                team["players"].append(player["player_name"])
                team["purse"] -= st.session_state.bid

                sale = {
                    "Player": player["player_name"],
                    "Team": winning_team,
                    "Price": st.session_state.bid
                }

                st.session_state.sold_players.append(sale)
                st.session_state.history.append(sale)

                st.session_state.current_player_index += 1
                st.session_state.bid = 5

                st.success("🔨 SOLD!")
                st.balloons()

                st.rerun()

    # UNSOLD
    with col5:
        if st.button("❌ UNSOLD"):
            st.session_state.current_player_index += 1
            st.rerun()

    # UNDO
    with col6:
        if st.button("↩ UNDO LAST SALE"):

            if st.session_state.history:

                last = st.session_state.history.pop()

                st.session_state.teams[last["Team"]]["players"].remove(
                    last["Player"]
                )

                st.session_state.teams[last["Team"]]["purse"] += last["Price"]

                st.session_state.sold_players.pop()

                st.session_state.current_player_index -= 1

                st.rerun()

    # SIDEBAR DASHBOARD
    st.sidebar.title("🏆 Team Dashboard")

    for team, details in st.session_state.teams.items():

        st.sidebar.markdown(f"""
        ### {team}
        Captain: {details['captain']}

        Purse Left: ₹{details['purse']}

        Squad: {len(details['players'])}/{st.session_state.players_per_team}
        """)

    # SOLD PLAYERS TABLE
    st.divider()
    st.header("Sold Players")

    sold_df = pd.DataFrame(st.session_state.sold_players)

    st.dataframe(sold_df)

    # DOWNLOAD SOLD PLAYERS
    def convert_df(df):
        output = BytesIO()

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)

        return output.getvalue()

    st.download_button(
        "📥 Download Auction Results",
        convert_df(sold_df),
        "auction_results.xlsx"
    )

    # DOWNLOAD POST AUCTION TEAMS
    st.divider()
    st.header("Post Auction Team Sheets")

    def generate_team_excel():

        output = BytesIO()

        with pd.ExcelWriter(output, engine='openpyxl') as writer:

            for team, details in st.session_state.teams.items():

                team_df = pd.DataFrame({
                    "Captain": [details["captain"]] * len(details["players"]),
                    "Players": details["players"],
                    "Remaining Purse": [details["purse"]] * len(details["players"])
                })

                team_df.to_excel(
                    writer,
                    sheet_name=team[:31],
                    index=False
                )

        return output.getvalue()

    st.download_button(
        "📥 Download Post Auction Teams",
        generate_team_excel(),
        "NMTCC_Post_Auction_Teams.xlsx"
    )
