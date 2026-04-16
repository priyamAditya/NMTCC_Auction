import streamlit as st
import pandas as pd
import time
from io import BytesIO

st.set_page_config(
    page_title="NMTCC Auction",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------- PREMIUM CSS ----------------
st.markdown("""
<style>
body {
    background-color: #0B0F1A;
}
.main {
    background: linear-gradient(135deg,#0B0F1A,#111827);
}
.card {
    padding:20px;
    border-radius:20px;
    background: rgba(255,255,255,0.08);
    backdrop-filter: blur(12px);
    box-shadow:0 8px 32px rgba(0,0,0,0.4);
    margin-bottom:15px;
}
.big-font {
    font-size:28px;
    font-weight:bold;
    color:#FFD700;
}
.player-card {
    padding:30px;
    border-radius:25px;
    background: linear-gradient(135deg,#1E293B,#334155);
    text-align:center;
    color:white;
    box-shadow:0 10px 30px rgba(0,0,0,0.5);
}
</style>
""", unsafe_allow_html=True)

# ---------------- SESSION ----------------
defaults = {
    "auction_started": False,
    "teams": {},
    "current_player_index": 0,
    "sold_players": [],
    "bid": 5,
    "history": []
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ---------------- TITLE ----------------
st.markdown(
    "<h1 style='text-align:center;color:#FFD700;'>🏏 NMTCC AUCTION LEAGUE</h1>",
    unsafe_allow_html=True
)

# ---------------- SETUP ----------------
if not st.session_state.auction_started:

    st.markdown("## Auction Setup")

    num_teams = st.number_input("Enter Number of Teams", 2, 20)

    teams = {}

    for i in range(num_teams):

        st.markdown(f"### Team {i+1}")

        col1, col2, col3 = st.columns(3)

        with col1:
            name = st.text_input("Team Name", key=f"name{i}")

        with col2:
            captain = st.text_input("Captain", key=f"captain{i}")

        with col3:
            logo = st.file_uploader("Upload Logo", type=['png','jpg'], key=f"logo{i}")

        if name:
            teams[name] = {
                "captain": captain,
                "logo": logo,
                "players": [],
                "purse": 0
            }

    uploaded_file = st.file_uploader("Upload Player Excel", type=['xlsx'])

    players_per_team = st.number_input("Players Per Team", 1)

    purse = st.number_input("Auction Purse", 10)

  if st.button("🚀 START AUCTION"):

    if uploaded_file is None:
        st.error("Please upload an Excel file.")

    else:
        df = pd.read_excel(uploaded_file)

        # Normalize column names
        df.columns = (
            df.columns
            .str.strip()
            .str.lower()
            .str.replace(" ", "_")
        )

        st.write("Detected Columns:", df.columns.tolist())

        required_columns = ["player_name", "set", "base_price"]

        missing_cols = [col for col in required_columns if col not in df.columns]

        if missing_cols:
            st.error(f"Missing required columns: {missing_cols}")
            st.stop()

        for team in teams:
            teams[team]["purse"] = purse

        st.session_state.teams = teams
        st.session_state.players_df = df
        st.session_state.players_per_team = players_per_team
        st.session_state.auction_started = True

        st.rerun()

# ---------------- AUCTION ----------------
else:

    df = st.session_state.players_df

    selected_set = st.selectbox(
        "Choose Player Set",
        df["Set"].unique()
    )

    filtered = df[df["Set"] == selected_set].reset_index(drop=True)

    if st.session_state.current_player_index >= len(filtered):
        st.success("Set Completed!")
        st.stop()

    player = filtered.iloc[st.session_state.current_player_index]

    # TIMER
    st.markdown("### ⏳ Auction Timer")

    timer_placeholder = st.empty()

    for i in range(10,0,-1):
        timer_placeholder.markdown(f"## {i} sec")
        time.sleep(0.1)

    # PLAYER CARD
    st.markdown(f"""
    <div class='player-card'>
        <h2>{player['Player Name']}</h2>
        <h4>Set: {player['Set']}</h4>
        <h3>Base Price: ₹{player['Base Price']}</h3>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # BID LOGIC
    bid = st.session_state.bid

    st.markdown(f"<div class='big-font'>Current Bid: ₹{bid}</div>", unsafe_allow_html=True)

    col1,col2,col3 = st.columns(3)

    with col1:
        if st.button("➕ Increase Bid"):
            if bid < 15:
                st.session_state.bid += 2
            else:
                st.session_state.bid += 5
            st.rerun()

    with col2:
        if st.button("➖ Decrease Bid"):
            if bid > 5:
                if bid <= 15:
                    st.session_state.bid -= 2
                else:
                    st.session_state.bid -= 5
            st.rerun()

    with col3:
        if st.button("🔄 Reset Bid"):
            st.session_state.bid = player["Base Price"]
            st.rerun()

    winning_team = st.selectbox("Winning Team", list(st.session_state.teams.keys()))

    col4,col5,col6 = st.columns(3)

    # SELL PLAYER
    with col4:
        if st.button("🔨 SELL PLAYER"):

            team = st.session_state.teams[winning_team]

            if team["purse"] >= st.session_state.bid:

                team["players"].append(player["Player Name"])
                team["purse"] -= st.session_state.bid

                sale = {
                    "Player": player["Player Name"],
                    "Team": winning_team,
                    "Price": st.session_state.bid
                }

                st.session_state.sold_players.append(sale)
                st.session_state.history.append(sale)

                st.success("🔨 SOLD!")

                st.balloons()

                st.session_state.current_player_index += 1
                st.session_state.bid = 5

                st.rerun()

            else:
                st.error("Insufficient Purse")

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

                st.session_state.teams[last["Team"]]["players"].remove(last["Player"])
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

    # SOLD PLAYERS
    st.divider()

    st.markdown("## Auction Results")

    sold_df = pd.DataFrame(st.session_state.sold_players)

    st.dataframe(sold_df)

    # EXPORT EXCEL
    def convert_df(df):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer,index=False)
        return output.getvalue()

    excel = convert_df(sold_df)

    st.download_button(
        "📥 Download Results Excel",
        excel,
        "auction_results.xlsx"
    )
    st.divider()
st.markdown("## 📋 Post Auction Team Sheets")

team_data = []

for team, details in st.session_state.teams.items():

    for player in details["players"]:
        team_data.append({
            "Team Name": team,
            "Captain": details["captain"],
            "Player": player,
            "Remaining Purse": details["purse"]
        })

team_df = pd.DataFrame(team_data)


def convert_team_df(df):
    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Post Auction Teams")

    return output.getvalue()


team_excel = convert_team_df(team_df)

st.download_button(
    label="📥 Download Post Auction Teams",
    data=team_excel,
    file_name="post_auction_teams.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
