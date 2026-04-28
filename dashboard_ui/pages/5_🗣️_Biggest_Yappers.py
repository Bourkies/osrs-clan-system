# dashboard/pages/5_🗣️_Biggest_Yappers.py

import streamlit as st
import pandas as pd
import Streamlit_utils as su
import toml
from pathlib import Path

current_script_directory = Path(__file__).resolve().parent

st.set_page_config(page_title="Biggest Yappers", page_icon="🗣️", layout="wide")
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
    title="🗣️ The Biggest Yappers",
    description="Who's the chattiest in the clan? This page tracks who's saying the important things."
)

texts = load_texts()
dashboard_config = su.load_dashboard_config()
# Load data for all yapper categories
df_menaces = su.load_table("menaces_111_summary")
df_gzers = su.load_table("big_gzers_summary")
df_cya_hick = su.load_table("cya_hick_crew_summary")

if df_menaces.empty and df_gzers.empty and df_cya_hick.empty:
    st.warning("No chat count data could be loaded. The ETL pipeline may not have run yet.")
else:
    period_suffix, selected_period_label = su.sidebar_summary_time_filter(dashboard_config, key="yappers_time_period")
    
    page_texts = texts.get('yappers', {})

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<h2 style='text-align: center;'>111 Voters!</h2>", unsafe_allow_html=True)
        su.display_leaderboard_podium(
            df=df_menaces,
            player_col="Username",
            count_col=f'Count_{period_suffix}',
            podium_messages=page_texts.get('top_yapper_messages', {}),
            podium_size=3,
            player_col_header="Player",
            count_col_header="Count"
        )

    with col2:
        st.markdown("<h2 style='text-align: center;'>The Big GZers!</h2>", unsafe_allow_html=True)
        su.display_leaderboard_podium(
            df=df_gzers,
            player_col="Username",
            count_col=f'Count_{period_suffix}',
            podium_messages=page_texts.get('top_gzer_messages', {}),
            podium_size=3,
            player_col_header="Player",
            count_col_header="Count"
        )

    st.markdown("---")
    st.markdown("<h2 style='text-align: center;'>'Cya Hick'</h2>", unsafe_allow_html=True)
    
    # For the 'cya hick' crew, we can create a simple message list if it's not in the TOML
    cya_hick_messages = [
        "👋 **{player}** is the biggest hick, saying it **{count}** times.",
        "🤠 G'day, hick! **{player}** leads the crew with **{count}** mentions.",
        "🌾 **{player}** is keeping it country with **{count}** 'cya hick' messages."
    ]

    su.display_leaderboard_podium(
        df=df_cya_hick,
        player_col="Username",
        count_col=f'Count_{period_suffix}',
        podium_messages=cya_hick_messages,
        podium_size=3,
        player_col_header="Player",
        count_col_header="Count"
    )
