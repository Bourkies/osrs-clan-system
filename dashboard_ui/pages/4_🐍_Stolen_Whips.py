# dashboard/pages/4_🐍_Stolen_Whips.py

import streamlit as st
import pandas as pd
import Streamlit_utils
import random
import toml
from datetime import datetime, timezone
from pathlib import Path
import html

current_script_directory = Path(__file__).resolve().parent

st.set_page_config(page_title="Stolen Whips", page_icon="🐍", layout="wide")
Streamlit_utils.inject_custom_css()

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
texts = load_texts()
dashboard_config = Streamlit_utils.load_dashboard_config()
df_whips = Streamlit_utils.load_table("stolen_whips_summary")

page_texts = texts.get('stolen_whips', {})
whip_queen = page_texts.get('whip_queen', 'Abby Queen')

Streamlit_utils.display_page_header(
    title="🐍 Stolen Whips Leaderboard",
    description=f"All whips belong to <span style='color: {Streamlit_utils.UI_THEME['primary']}; font-weight: bold;'>{html.escape(whip_queen)}</span>. This page tracks all whips stolen by other clan members."
)

if df_whips.empty:
    st.warning("No whip data could be loaded. The ETL pipeline may not have run yet.")
else:
    period_suffix, selected_period_label = Streamlit_utils.sidebar_summary_time_filter(dashboard_config, key="whips_time_period")
    count_col = f'Count_{period_suffix}'
    value_col = f'Value_{period_suffix}'

    if count_col in df_whips.columns:
        # Queen stats
        queen_stats = df_whips[df_whips['Username'] == whip_queen]
        queen_period = int(queen_stats[count_col].sum()) if not queen_stats.empty else 0
        queen_all_time = int(queen_stats['Count_All_Time'].sum()) if not queen_stats.empty else 0

        # Thieves stats
        thieves_df_all = df_whips[df_whips['Username'] != whip_queen]
        stolen_period = int(thieves_df_all[count_col].sum()) if not thieves_df_all.empty else 0
        stolen_all_time = int(thieves_df_all['Count_All_Time'].sum()) if not thieves_df_all.empty else 0

        # Filter thieves for the current period
        thieves_df_period = thieves_df_all[thieves_df_all[count_col] > 0].copy()
        
        ui_theme = Streamlit_utils.UI_THEME

        # --- The Queen's Special Banner ---
        queen_banner_html = f"""
        <div style="background: {ui_theme['card_bg']}; 
                    border: 2px solid {ui_theme['primary']}; 
                    border-radius: 12px; 
                    padding: 2rem; 
                    margin-bottom: 2rem; 
                    box-shadow: 0 0 20px {ui_theme['primary_highlight']};
                    text-align: center;">
            <h2 style="color: {ui_theme['primary']}; margin-top: 0; margin-bottom: 1rem; font-size: 2.2rem; letter-spacing: 1px;">👑 The {whip_queen}'s Hoard</h2>
            <p style="font-size: 1.2rem; color: {ui_theme['text_table']}; line-height: 1.6; margin: 0;">
                The Queen has rightfully claimed <span style="color: {ui_theme['primary']}; font-weight: bold; font-size: 1.5rem;">{queen_period:,}</span> whips this period 
                <span style="color: {ui_theme['text_dim']}; font-size: 1rem;">({queen_all_time:,} all-time)</span>.<br><br>
                However, the sticky-fingered clan rats have stolen <span style="color: {ui_theme['secondary_accent']}; font-weight: bold; font-size: 1.5rem;">{stolen_period:,}</span> whips 
                <span style="color: {ui_theme['text_dim']}; font-size: 1rem;">({stolen_all_time:,} all-time)</span> right from under her nose!
            </p>
        </div>
        """
        st.markdown(queen_banner_html, unsafe_allow_html=True)

        st.subheader("🕵️‍♂️ The Thieves")
        if thieves_df_period.empty:
            st.success("No whips have been stolen in this period. All is right with the world.", icon="😇")
        else:
            Streamlit_utils.display_leaderboard_podium(
                df=thieves_df_period,
                player_col='Username',
                count_col=count_col,
                podium_messages=page_texts.get('top_thief_messages', {}),
                podium_size=3,
                player_col_header="Thief",
                count_col_header="Whips Stolen"
            )
    else:
        st.info("No whip data available for this period.")