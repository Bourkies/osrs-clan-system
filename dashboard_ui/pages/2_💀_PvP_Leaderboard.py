# dashboard/pages/2_💀_PvP_Leaderboard.py

import streamlit as st
import pandas as pd
import Streamlit_utils
import random
import toml
from datetime import datetime, timezone
from pathlib import Path
import html

current_script_directory = Path(__file__).resolve().parent

st.set_page_config(page_title="PvP Leaderboard", page_icon="💀", layout="wide")
Streamlit_utils.inject_custom_css()


@st.cache_data(ttl=300)
def load_texts():
    """Loads text snippets from the TOML file."""
    try:
        return toml.load(current_script_directory.parent / 'dashboard_texts.toml')
    except Exception as e:
        st.error(f"Failed to load dashboard_texts.toml: {e}")
        return {}

Streamlit_utils.display_page_header(
    title="💀 PvP Leaderboard",
    description="Who are the hunters and who are the hunted? This page tracks all PvP action."
)

texts = load_texts()
page_texts = texts.get('pvp_leaderboard', {})

# --- Load Data ---
df_kills = Streamlit_utils.load_table("pvp_kills_detail_all_time")
df_deaths = Streamlit_utils.load_table("pvp_deaths_detail_all_time")
df_meta = Streamlit_utils.load_table("run_metadata")
run_time = pd.to_datetime(df_meta['last_updated_utc'].iloc[0], utc=True) if not df_meta.empty else datetime.now(timezone.utc)

# --- UI: Time Filters ---
min_date_kills = df_kills['Timestamp'].min() if not df_kills.empty else pd.Timestamp.max.replace(tzinfo=timezone.utc)
min_date_deaths = df_deaths['Timestamp'].min() if not df_deaths.empty else pd.Timestamp.max.replace(tzinfo=timezone.utc)
min_date = min(min_date_kills, min_date_deaths) if not (df_kills.empty and df_deaths.empty) else None

start_date, end_date = Streamlit_utils.sidebar_time_filter(run_time, min_date)

# --- Filter Data ---
df_kills_filtered = pd.DataFrame()
if not df_kills.empty:
    df_kills_filtered = df_kills[(df_kills['Timestamp'] >= start_date) & (df_kills['Timestamp'] <= end_date)].copy()
    
df_deaths_filtered = pd.DataFrame()
if not df_deaths.empty:
    df_deaths_filtered = df_deaths[(df_deaths['Timestamp'] >= start_date) & (df_deaths['Timestamp'] <= end_date)].copy()

# --- High-Level Metrics ---
summary_l_col, summary_r_col = st.columns([1, 1], gap="large")

with summary_l_col:
    # Kills Ribbon
    total_kill_value = df_kills_filtered['Item_Value'].sum() if not df_kills_filtered.empty else 0
    total_kills = len(df_kills_filtered)
    Streamlit_utils.display_summary_ribbon(
        metric1_label="⚔️ Total Kills",
        metric1_value=f"{total_kills:,}",
        metric2_label="💰 PK Loot Value",
        metric2_value=Streamlit_utils.format_gp(total_kill_value),
        list_title="🏆 Biggest PKs This Period",
        top_df=df_kills_filtered,
        player_col='Username',
        val_col='Item_Value',
        item_col='Opponent', 
        is_gp=True,
        limit=3
    )

with summary_r_col:
    # Deaths Ribbon
    total_death_value = df_deaths_filtered['Item_Value'].sum() if not df_deaths_filtered.empty else 0
    total_deaths = len(df_deaths_filtered)
    Streamlit_utils.display_summary_ribbon(
        metric1_label="🪦 Total Deaths",
        metric1_value=f"{total_deaths:,}",
        metric2_label="💸 Total Lost",
        metric2_value=Streamlit_utils.format_gp(total_death_value),
        list_title="💔 Biggest Losses This Period",
        top_df=df_deaths_filtered,
        player_col='Username',
        val_col='Item_Value',
        item_col='Opponent', 
        is_gp=True,
        limit=3
    )

st.markdown("---")

# --- Leaderboards ---
l_col, r_col = st.columns([1, 1], gap="large")

with l_col:
    st.subheader("⚔️ Top PKers")
    if not df_kills_filtered.empty:
        df_kill_leaderboard = df_kills_filtered.groupby('Username').agg(
            Count=('Item_Value', 'count'),
            Total_Value=('Item_Value', 'sum')
        ).reset_index().sort_values('Total_Value', ascending=False)
        
        Streamlit_utils.display_leaderboard_podium(
            df=df_kill_leaderboard,
            player_col='Username',
            count_col='Total_Value',
            secondary_count_col='Count',
            podium_messages=page_texts.get('most_valuable_pker_messages', {}),
            podium_size=3,
            player_col_header="Player",
            count_col_header="Total PK'd",
            show_header_count=False,
            format_count_as_gp=True
        )
    else:
        st.info("No kills to display for this period.")

with r_col:
    st.subheader("🪦 Top Donors")
    if not df_deaths_filtered.empty:
        df_death_leaderboard = df_deaths_filtered.groupby('Username').agg(
            Count=('Item_Value', 'count'),
            Total_Value=('Item_Value', 'sum')
        ).reset_index().sort_values('Total_Value', ascending=False)
        
        Streamlit_utils.display_leaderboard_podium(
            df=df_death_leaderboard,
            player_col='Username',
            count_col='Total_Value',
            secondary_count_col='Count',
            podium_messages=page_texts.get('most_valuable_donor_messages', {}),
            podium_size=3,
            player_col_header="Player",
            count_col_header="Total Lost",
            show_header_count=False,
            format_count_as_gp=True
        )
    else:
        st.info("No deaths to display for this period.")

st.markdown("---")

# --- Event Feeds ---
feed_l_col, feed_r_col = st.columns([1, 1], gap="large")
with feed_l_col:
    st.subheader("📜 Recent Kills Feed")
    Streamlit_utils.display_event_feed(
        df_kills_filtered.sort_values(by='Timestamp', ascending=False) if not df_kills_filtered.empty else df_kills_filtered,
        run_time=run_time,
        player_col='Username',
        item_col='Opponent',
        val_col='Item_Value',
        date_col='Timestamp',
        limit=100,
        height="500px"
    )
    
with feed_r_col:
    st.subheader("📜 Recent Deaths Feed")
    Streamlit_utils.display_event_feed(
        df_deaths_filtered.sort_values(by='Timestamp', ascending=False) if not df_deaths_filtered.empty else df_deaths_filtered,
        run_time=run_time,
        player_col='Username',
        item_col='Opponent',
        val_col='Item_Value',
        date_col='Timestamp',
        limit=100,
        height="500px"
    )

st.markdown("---")

# --- Dynamic Charts ---
chart_l_col, chart_r_col = st.columns([1, 1], gap="large")

with chart_l_col:
    if not df_kills_filtered.empty:
        Streamlit_utils.display_dynamic_timeseries(
            df=df_kills_filtered, 
            date_col='Timestamp', 
            value_col='Item_Value', 
            start_date=start_date, 
            end_date=end_date, 
            title="PK Wealth Generated", 
            is_gp=True
        )
        
with chart_r_col:
    if not df_deaths_filtered.empty:
        Streamlit_utils.display_dynamic_timeseries(
            df=df_deaths_filtered, 
            date_col='Timestamp', 
            value_col='Item_Value', 
            start_date=start_date, 
            end_date=end_date, 
            title="Wealth Lost to Wilderness", 
            is_gp=True
        )