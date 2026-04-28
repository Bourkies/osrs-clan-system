# dashboard/pages/1_💰_Valuable_Drops.py

import streamlit as st
import pandas as pd
import toml
import random
from pathlib import Path
import Streamlit_utils
from datetime import datetime, timedelta, timezone
import html

current_script_directory = Path(__file__).resolve().parent

st.set_page_config(page_title="Valuable Drops", page_icon="💰", layout="wide")
Streamlit_utils.inject_custom_css()

@st.cache_data(ttl=300)
def load_texts():
    """Loads text snippets from the TOML file."""
    try:
        texts_path = current_script_directory.parent / 'dashboard_texts.toml'
        return toml.load(texts_path)
    except Exception as e:
        st.error(f"Failed to load dashboard_texts.toml: {e}")
        return {}

Streamlit_utils.display_page_header(
    title="💰 Valuable Drops",
    description="This page shows leaderboards and trends for valuable drops received by clan members."
)

# --- Load Data ---
df_detail = Streamlit_utils.load_table("valuable_drops_detail_all_time")
df_meta = Streamlit_utils.load_table("run_metadata")
run_time = pd.to_datetime(df_meta['last_updated_utc'].iloc[0], utc=True) if not df_meta.empty else datetime.now(timezone.utc)

if df_detail.empty:
    st.warning("No valuable drop data available. The ETL pipeline may not have run yet.")
    st.stop()

# --- UI: Time Filters ---
min_date = df_detail['Timestamp'].min() if not df_detail.empty else None
start_date, end_date = Streamlit_utils.sidebar_time_filter(run_time, min_date)

# --- Filter Data ---
mask = (df_detail['Timestamp'] >= start_date) & (df_detail['Timestamp'] <= end_date)
df_filtered = df_detail[mask].copy()

st.markdown("---")

# --- High-Level Metrics ---
total_value = df_filtered['Item_Value'].sum() if not df_filtered.empty else 0
total_drops = len(df_filtered)

Streamlit_utils.display_summary_ribbon(
    metric1_label="📦 Total Drops",
    metric1_value=f"{total_drops:,}",
    metric2_label="💰 Total Value",
    metric2_value=Streamlit_utils.format_gp(total_value),
    list_title="🏆 Top Drops This Period",
    top_df=df_filtered,
    player_col='Username',
    val_col='Item_Value',
    item_col='Item_Name',
    is_gp=True,
    limit=3
)

st.markdown("---")

texts = load_texts()
page_texts = texts.get('valuable_drops', {})
podium_msgs = page_texts.get('top_earner_messages', {})

# --- Leaderboard & Feed ---
l_col, r_col = st.columns([1.2, 1], gap="large")

with l_col:
    st.subheader("🏆 Top Earners")
    if not df_filtered.empty:
        df_leaderboard = df_filtered.groupby('Username').agg(
            Drops=('Item_Value', 'count'),
            Total_Value=('Item_Value', 'sum')
        ).reset_index().sort_values('Total_Value', ascending=False)
        
        Streamlit_utils.display_leaderboard_podium(
            df_leaderboard,
            player_col='Username',
            count_col='Total_Value',
            podium_messages=podium_msgs if podium_msgs else None,
            podium_size=3,
            player_col_header="Player",
            count_col_header="Total GP",
            show_header_count=False, # Values are displayed cleanly in the message now
            format_count_as_gp=True
        )
        
    else:
        st.info("No drops to display for this period.")

with r_col:
    st.subheader("📜 Event Feed")
    Streamlit_utils.display_event_feed(
        df_filtered,
        run_time=run_time,
        player_col='Username',
        item_col='Item_Name',
        val_col='Item_Value',
        date_col='Timestamp',
        limit=200,          # Increased item limit
        height="850px"      # Match the height of the podium
    )

st.markdown("---")

# --- Dynamic Chart ---
if not df_filtered.empty:
    Streamlit_utils.display_dynamic_timeseries(
        df=df_filtered, 
        date_col='Timestamp', 
        value_col='Item_Value', 
        start_date=start_date, 
        end_date=end_date, 
        title="Value Over Time", 
        is_gp=True
    )