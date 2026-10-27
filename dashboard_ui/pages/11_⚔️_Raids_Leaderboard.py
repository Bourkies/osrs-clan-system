# dashboard/pages/11_⚔️_Raids_Leaderboard.py

import streamlit as st
import pandas as pd
import Streamlit_utils
import random
import os
import re
import html
import base64
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- Page Setup & Styling ---
st.set_page_config(page_title="Raids Leaderboard", page_icon="⚔️", layout="wide")
Streamlit_utils.inject_custom_css()

# --- Assets & Paths ---
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "shared_config" / "assets"
CUSTOM_ICON_DIR = ASSETS_DIR / "custom_icons"

# --- Raid Item Definitions ---
COX_ITEMS = [
    "Twisted bow", "Elder maul", "Kodai insignia", "Dragon claws",
    "Ancestral hat", "Ancestral robe top", "Ancestral robe bottom",
    "Dinh's bulwark", "Dexterous prayer scroll", "Arcane prayer scroll",
    "Dragon hunter crossbow", "Twisted buckler", "Olmlet"
]

TOB_ITEMS = [
    "Scythe of vitur (uncharged)", "Scythe of vitur", "Ghrazi rapier",
    "Sanguinesti staff (uncharged)", "Sanguinesti staff", "Justiciar faceguard",
    "Justiciar chestguard", "Justiciar legguards", "Avernic defender hilt", "Lil' zik"
]

TOA_ITEMS = [
    "Tumeken's shadow (uncharged)", "Tumeken's shadow", "Masori mask", "Masori body",
    "Masori chaps", "Osmumten's fang", "Lightbearer", "Elidinis' ward",
    "Tumeken's guardian"
]

TFA_ITEMS = [
    "Archivist's folio", "Archivist's folio (inert)", "Horn of Bran",
    "Zorya's tome", "Zorya's tome (uncharged)", "Rondache",
    "Ascension crossbows", "Obligator", "Orion"
]

CABBAGE_ITEMS = ["Cabbage", "Cabbage (very valuable)"]

# Normalized display names
ITEM_NORMALIZATION = {
    "archivist's folio (inert)": "Archivist's folio",
    "zorya's tome (uncharged)": "Zorya's tome",
    "scythe of vitur (uncharged)": "Scythe of vitur",
    "sanguinesti staff (uncharged)": "Sanguinesti staff",
    "tumeken's shadow (uncharged)": "Tumeken's shadow",
    "cabbage (very valuable)": "Cabbage",
}

# --- Helper Functions ---

def load_texts():
    """Loads text snippets from dashboard_texts.toml."""
    return Streamlit_utils.load_dashboard_texts()

def clean_item_name(name: str) -> str:
    """Cleans suffixes like '(very valuable)', strips leading quantities, and normalizes variants."""
    if not isinstance(name, str):
        return ""
    # Strip (very valuable)
    cleaned = re.sub(r'\s*\(very valuable\)', '', name, flags=re.IGNORECASE).strip()
    # Strip leading quantity if present (e.g. '1 x Cabbage' -> 'Cabbage')
    cleaned = re.sub(r'^\d{1,3}(?:,\d{3})*\s*x\s*', '', cleaned).strip()
    return ITEM_NORMALIZATION.get(cleaned.lower(), cleaned)

def get_raid_category(item_name: str) -> str | None:
    """Categorizes an item into its respective raid."""
    cleaned = clean_item_name(item_name).lower()
    if cleaned == "cabbage":
        return "Cabbage"
    for item in TFA_ITEMS:
        if clean_item_name(item).lower() == cleaned:
            return "The Fractured Archive"
    for item in TOA_ITEMS:
        if clean_item_name(item).lower() == cleaned:
            return "Tombs of Amascut"
    for item in TOB_ITEMS:
        if clean_item_name(item).lower() == cleaned:
            return "Theatre of Blood"
    for item in COX_ITEMS:
        if clean_item_name(item).lower() == cleaned:
            return "Chambers of Xeric"
    return None

def get_safe_filename(item_name: str) -> str:
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '', item_name.replace(' ', '_'))
    return safe_name + ".webp"

@st.cache_data
def get_image_as_base64(file_path: str):
    p = Path(file_path)
    if not p.exists():
        return None
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode()

def get_item_icon_html(item_name: str, size: int = 36) -> str:
    """Builds an HTML icon element for a given item name."""
    cleaned = clean_item_name(item_name)
    safe_name = get_safe_filename(cleaned)
    icon_file = CUSTOM_ICON_DIR / safe_name
    
    icon_src = None
    if icon_file.exists():
        b64 = get_image_as_base64(str(icon_file))
        if b64:
            icon_src = f"data:image/webp;base64,{b64}"
            
    wiki_url = f"https://oldschool.runescape.wiki/w/{urllib.parse.quote(cleaned.replace(' ', '_'))}"
    
    if icon_src:
        return f'<a href="{html.escape(wiki_url)}" target="_blank" rel="noopener noreferrer"><img src="{icon_src}" style="width: {size}px; height: {size}px; object-fit: contain; vertical-align: middle;"></a>'
    else:
        # Fallback emoji badge
        emoji = "🥬" if cleaned.lower() == "cabbage" else "✨"
        return f'<a href="{html.escape(wiki_url)}" target="_blank" rel="noopener noreferrer" style="font-size: 1.5rem; text-decoration: none;">{emoji}</a>'

# --- Load Data ---
texts = load_texts()
dashboard_config = Streamlit_utils.load_dashboard_config()
df_meta = Streamlit_utils.load_table("run_metadata")
run_time = pd.to_datetime(df_meta['last_updated_utc'].iloc[0], utc=True) if not df_meta.empty else datetime.now(timezone.utc)

# 1. Attempt to load the new dedicated raids detailed report
df_raw = Streamlit_utils.load_table("raids_drops_detail_all_time")

# Fallback if ETL hasn't run the new table yet
if df_raw.empty:
    df_raw = Streamlit_utils.load_table("valuable_drops_detail_all_time")

# Also load cabbage summary if available
df_cabbage_summary = Streamlit_utils.load_table("cabbage_patch_summary")

Streamlit_utils.display_page_header(
    title="⚔️ Raids & Incursions Leaderboard",
    description="Track purples, uniques, and Brassica Prime cabbage blessings across all raids."
)

if df_raw.empty and df_cabbage_summary.empty:
    st.warning("No raid drop data available yet. Please run or rebuild the ETL pipeline.")
    st.stop()

# --- Process & Prepare Data ---
df_data = df_raw.copy() if not df_raw.empty else pd.DataFrame()

if not df_data.empty:
    # Retain active clan members only if Is_Retained column exists
    if 'Is_Retained' in df_data.columns:
        df_data = df_data[df_data['Is_Retained'] == True].copy()
        
    # Ensure Timestamp is datetime
    df_data['Timestamp'] = pd.to_datetime(df_data['Timestamp'], utc=True)
    
    # Normalize Item Names
    df_data['Clean_Item_Name'] = df_data['Item_Name'].apply(clean_item_name)
    df_data['Raid'] = df_data['Clean_Item_Name'].apply(get_raid_category)
    
    # Filter to only known raid items or cabbages
    df_data = df_data[df_data['Raid'].notnull()].copy()
    
    # --- Deduplication Engine ---
    # Sort and remove duplicates where the same player received the same item within 120 seconds
    df_data = df_data.sort_values(by=['Username', 'Clean_Item_Name', 'Timestamp']).reset_index(drop=True)
    
    # Compute time difference between consecutive records for the same player & item
    same_player = df_data['Username'] == df_data['Username'].shift(1)
    same_item = df_data['Clean_Item_Name'] == df_data['Clean_Item_Name'].shift(1)
    time_diff = (df_data['Timestamp'] - df_data['Timestamp'].shift(1)).dt.total_seconds().abs()
    
    is_duplicate = same_player & same_item & (time_diff <= 120)
    df_data = df_data[~is_duplicate].copy()
    
    # Sort back by Timestamp descending for displays
    df_data = df_data.sort_values(by='Timestamp', ascending=False).reset_index(drop=True)

# --- Sidebar Time Filter ---
min_date = df_data['Timestamp'].min() if not df_data.empty else (run_time - timedelta(days=365))
start_date, end_date = Streamlit_utils.sidebar_time_filter(run_time, min_date)

# Apply Time Filter
mask = (df_data['Timestamp'] >= start_date) & (df_data['Timestamp'] <= end_date) if not df_data.empty else pd.Series([], dtype=bool)
df_filtered = df_data[mask].copy() if not df_data.empty else pd.DataFrame()

# Separate Purples from Cabbages
df_purples = df_filtered[df_filtered['Raid'] != "Cabbage"].copy() if not df_filtered.empty else pd.DataFrame()
df_cabbages = df_filtered[df_filtered['Raid'] == "Cabbage"].copy() if not df_filtered.empty else pd.DataFrame()

# All-time sets
df_purples_all = df_data[df_data['Raid'] != "Cabbage"].copy() if not df_data.empty else pd.DataFrame()
df_cabbages_all = df_data[df_data['Raid'] == "Cabbage"].copy() if not df_data.empty else pd.DataFrame()

# --- Page Tabs ---
tab_raids, tab_cabbage = st.tabs([
    "🏆 Raids Leaderboard",
    "🥬 The Cabbage Patch"
])

ui_theme = Streamlit_utils.UI_THEME

# =========================================================================
# TAB 1: RAIDS LEADERBOARD (ALL RAIDS)
# =========================================================================
with tab_raids:
    st.subheader("🏆 Clan Raids Highscores")
    
    # Raid filter pills
    raid_options = ["All Raids", "Chambers of Xeric", "Theatre of Blood", "Tombs of Amascut", "The Fractured Archive"]
    selected_raid = st.radio("Filter by Raid:", raid_options, horizontal=True, index=0)
    
    # Filter by selected raid
    if selected_raid == "All Raids":
        df_view = df_purples.copy()
    else:
        df_view = df_purples[df_purples['Raid'] == selected_raid].copy()
        
    # High-level Metrics Ribbon
    total_purples = len(df_view)
    unique_raiders = df_view['Username'].nunique() if not df_view.empty else 0
    top_drop = df_view['Clean_Item_Name'].mode().iloc[0] if not df_view.empty else "N/A"
    
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Purples / Uniques", f"{total_purples:,}")
    c2.metric("👥 Lucky Raiders", f"{unique_raiders:,}")
    c3.metric("🎯 Most Common Drop", f"{top_drop}")
    
    st.markdown("---")
    
    l_col, r_col = st.columns([1.3, 1], gap="large")
    
    with l_col:
        st.subheader(f"🥇 Top Raiders — {selected_raid}")
        if df_view.empty:
            st.info("No raid purples found for the selected period and raid filter.")
        else:
            # Build Leaderboard
            df_leaderboard = df_view.groupby('Username').agg(
                Total_Drops=('Clean_Item_Name', 'count'),
                Last_Seen=('Timestamp', 'max'),
                Favorite_Drop=('Clean_Item_Name', lambda x: x.mode().iloc[0] if not x.empty else 'N/A')
            ).reset_index().sort_values('Total_Drops', ascending=False)
            
            # Display Podium
            raids_texts = texts.get('raids_leaderboard', {})
            podium_msgs = raids_texts.get('top_raider_messages', {})
            
            Streamlit_utils.display_leaderboard_podium(
                df=df_leaderboard,
                player_col='Username',
                count_col='Total_Drops',
                podium_messages=podium_msgs if podium_msgs else None,
                podium_size=3,
                player_col_header="Raider",
                count_col_header="Purples"
            )
            
            with st.expander("📋 View Full Standings Table"):
                df_display = df_leaderboard.copy()
                df_display['Last Drop'] = df_display['Last_Seen'].dt.strftime('%Y-%m-%d')
                df_display = df_display[['Username', 'Total_Drops', 'Favorite_Drop', 'Last Drop']]
                df_display.columns = ['Raider', 'Purples', 'Most Common Drop', 'Last Drop Date']
                st.dataframe(df_display, use_container_width=True, hide_index=True)
            
    with r_col:
        st.subheader("📜 Recent Raid Purples")
        if df_view.empty:
            st.info("No drops to display in feed.")
        else:
            Streamlit_utils.display_event_feed(
                df_view,
                run_time=run_time,
                player_col='Username',
                item_col='Clean_Item_Name',
                val_col='Item_Value' if 'Item_Value' in df_view.columns else None,
                date_col='Timestamp',
                limit=150,
                height="800px"
            )

# =========================================================================
# TAB 2: THE CABBAGE PATCH (BRASSICA PRIME TROLL LEADERBOARD)
# =========================================================================
with tab_cabbage:
    cabbage_texts = texts.get('cabbage_patch', {})
    
    cabbage_period_count = len(df_cabbages)
    cabbage_all_time_count = len(df_cabbages_all)
    
    # Cult of Brassica Banner
    cabbage_banner_html = f"""
    <div style="background: {ui_theme['card_bg']}; 
                border: 2px solid #2ecc71; 
                border-radius: 12px; 
                padding: 1.8rem; 
                margin-bottom: 2rem; 
                box-shadow: 0 0 20px rgba(46, 204, 113, 0.25);
                text-align: center;">
        <h2 style="color: #2ecc71; margin-top: 0; margin-bottom: 0.8rem; font-size: 2.2rem; letter-spacing: 1px;">
            🥬 The Cult of Brassica Prime
        </h2>
        <p style="font-size: 1.15rem; color: {ui_theme['text_table']}; line-height: 1.6; margin: 0;">
            The raid chest was opened, hearts were beating fast, the hype was real...<br>
            ...and out popped a crunchy, crispy <span style="color: #2ecc71; font-weight: bold; font-size: 1.3rem;">Cabbage (very valuable)</span>!<br>
            Clan members have been blessed with <span style="color: #2ecc71; font-weight: bold; font-size: 1.4rem;">{cabbage_period_count:,}</span> cabbages this period 
            <span style="color: {ui_theme['text_dim']}; font-size: 0.95rem;">({cabbage_all_time_count:,} all-time)</span>.
        </p>
    </div>
    """
    st.markdown(cabbage_banner_html, unsafe_allow_html=True)
    
    cab_l, cab_r = st.columns([1.3, 1], gap="large")
    
    with cab_l:
        st.subheader("🥇 Chief Cabbage Farmers (Hall of Shame)")
        
        # Build Cabbage Leaderboard
        if df_cabbages.empty and not df_cabbage_summary.empty:
            # Fallback to summary table if raw events in period are empty
            df_cabbage_lead = df_cabbage_summary.copy()
            count_col = 'Count_All_Time' if 'Count_All_Time' in df_cabbage_lead.columns else df_cabbage_lead.columns[1]
            df_cabbage_lead = df_cabbage_lead.sort_values(by=count_col, ascending=False)
            display_count_col = count_col
        elif not df_cabbages.empty:
            df_cabbage_lead = df_cabbages.groupby('Username').agg(
                Cabbages=('Clean_Item_Name', 'count'),
                Last_Cabbage=('Timestamp', 'max')
            ).reset_index().sort_values('Cabbages', ascending=False)
            display_count_col = 'Cabbages'
        else:
            df_cabbage_lead = pd.DataFrame()
            display_count_col = 'Cabbages'
            
        if df_cabbage_lead.empty:
            st.success("No clan members have been trolled with cabbages in this period. Brassica Prime sleeps.", icon="😇")
        else:
            cab_podium_msgs = cabbage_texts.get('top_cabbage_messages', {})
            
            Streamlit_utils.display_leaderboard_podium(
                df=df_cabbage_lead,
                player_col='Username',
                count_col=display_count_col,
                podium_messages=cab_podium_msgs if cab_podium_msgs else None,
                podium_size=3,
                player_col_header="Cabbage Victim",
                count_col_header="Cabbages"
            )
            
            with st.expander("📋 View Full Harvest Standings"):
                disp_cab = df_cabbage_lead.copy()
                if 'Last_Cabbage' in disp_cab.columns:
                    disp_cab['Last Harvest'] = disp_cab['Last_Cabbage'].dt.strftime('%Y-%m-%d %H:%M')
                    disp_cab = disp_cab[['Username', display_count_col, 'Last Harvest']]
                    disp_cab.columns = ['Player', 'Cabbages Pulled', 'Last Harvest Date']
                else:
                    disp_cab.columns = ['Player', 'Cabbages Pulled']
                st.dataframe(disp_cab, use_container_width=True, hide_index=True)
            
    with cab_r:
        st.subheader("📜 Live Cabbage Harvest Feed")
        if df_cabbages.empty:
            st.info("No cabbage drops recorded in this period.")
        else:
            Streamlit_utils.display_event_feed(
                df_cabbages,
                run_time=run_time,
                player_col='Username',
                item_col='Clean_Item_Name',
                date_col='Timestamp',
                limit=100,
                height="700px"
            )
