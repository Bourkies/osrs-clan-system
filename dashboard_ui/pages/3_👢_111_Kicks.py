# dashboard/pages/3_👢_111_Kicks.py

import streamlit as st
import pandas as pd
import Streamlit_utils as su
import toml
from pathlib import Path

current_script_directory = Path(__file__).resolve().parent

st.set_page_config(page_title="111 Kicks", page_icon="👢", layout="wide")
su.inject_custom_css()

# --- Helper Functions ---

@st.cache_data(ttl=300)
def load_texts():
    """Loads text snippets from the TOML file."""
    try:
        return toml.load(current_script_directory.parent / 'dashboard_texts.toml')
    except Exception as e:
        st.error(f"Failed to load dashboard_texts.toml: {e}")
        return {}

# --- Main Page Execution ---
su.display_page_header(
    title="👢 '111' Kicks Leaderboard",
    description="Who's getting the boot? This page tracks players who have been temporarily '111' kicked from the clan."
)

texts = load_texts()
dashboard_config = su.load_dashboard_config()
df_kicked = su.load_table("kicked_by_player_summary")
df_kickers = su.load_table("kicker_summary")

if df_kicked.empty and df_kickers.empty:
    st.warning("No kick data could be loaded. The ETL pipeline may not have run yet.")
else:
    period_suffix, selected_period_label = su.sidebar_summary_time_filter(dashboard_config, key="kicks_time_period")
    
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<h2 style='text-align: center;'>111 Kick's, Cya Hick</h2>", unsafe_allow_html=True)
        page_texts = texts.get('kicks', {})
        count_col_kicked = f'Count_{period_suffix}'

        su.display_leaderboard_podium(
            df=df_kicked,
            player_col="Username",
            count_col=count_col_kicked,
            podium_messages=page_texts.get('top_kicked_messages', {}),
            podium_size=3,
            player_col_header="Player",
            count_col_header="Times Kicked"
        )

    with col2:
        st.markdown("<h2 style='text-align: center;'>Admin Power Abuse</h2>", unsafe_allow_html=True)
        page_texts = texts.get('kicks', {})
        count_col_kickers = f'Count_{period_suffix}'

        su.display_leaderboard_podium(
            df=df_kickers,
            player_col="Action_By",
            count_col=count_col_kickers,
            podium_messages=page_texts.get('fastest_finger_messages', {}),
            podium_size=3,
            player_col_header="Admin",
            count_col_header="Players Kicked"
        )
