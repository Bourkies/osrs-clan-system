# dashboard_ui/pages/7_👑_Clan_Highscores.py
# Displays the #1 Clan Record Holders for all OSRS Bosses, Raids, Skills, and Activities.

import streamlit as st
import pandas as pd
import html
import os
import base64
from pathlib import Path

import Streamlit_utils

# --- Page Configuration ---
st.set_page_config(page_title="Clan Highscores", page_icon="👑", layout="wide")
Streamlit_utils.inject_custom_css()
UI_THEME = Streamlit_utils.UI_THEME

# --- Paths ---
CURRENT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = CURRENT_DIR.parent.parent / "shared_config" / "assets"
METRIC_ICONS_DIR = ASSETS_DIR / "metric_icons"
CONTENT_ART_DIR = ASSETS_DIR / "content_art" / "card"


@st.cache_data
def get_image_base64(file_path_str: str) -> str | None:
    """Reads a local image file and returns its base64 encoded data URI."""
    if not file_path_str or not os.path.exists(file_path_str):
        return None
    try:
        with open(file_path_str, "rb") as f:
            data = f.read()
        return f"data:image/webp;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception:
        return None


def format_score(score: float | int, score_type: str, level: int | None = None) -> str:
    """Formats numeric scores into clean, readable OSRS values."""
    if score is None:
        return "0"
    
    if score_type == "experience":
        lvl_str = f" (Lvl {int(level)})" if level is not None else ""
        if score >= 100_000_000:
            return f"{score / 1_000_000:.1f}M XP{lvl_str}"
        elif score >= 1_000_000:
            return f"{score / 1_000_000:.2f}M XP{lvl_str}"
        else:
            return f"{int(score):,} XP{lvl_str}"
    elif score_type == "hours":
        return f"{float(score):,.1f} Hours"
    elif score_type == "kills":
        return f"{int(score):,} KC"
    else:
        return f"{int(score):,}"


def render_champion_card(row: pd.Series) -> str:
    """Generates a compact, un-indented HTML card to prevent markdown code-block rendering."""
    metric_key = str(row.get('metric_key', ''))
    display_name = html.escape(str(row.get('display_name', metric_key)))
    discord_name = html.escape(str(row.get('discord_name', 'Unknown')))
    rsn = html.escape(str(row.get('rsn', 'Unknown')))
    score = row.get('score', 0)
    score_type = str(row.get('score_type', 'score'))
    level = row.get('level')
    global_rank = row.get('global_rank')
    player_type = str(row.get('player_type', 'regular')).lower()
    
    formatted_score = format_score(score, score_type, level)

    # Resolve Assets (Base64)
    icon_file = METRIC_ICONS_DIR / f"{metric_key}_icon.webp"
    icon_uri = get_image_base64(str(icon_file))

    card_art_file = CONTENT_ART_DIR / f"{metric_key}_card.webp"
    card_art_uri = get_image_base64(str(card_art_file))

    if icon_uri:
        icon_html = f'<img src="{icon_uri}" style="width: 32px; height: 32px; image-rendering: pixelated; object-fit: contain;" />'
    else:
        icon_html = '<span style="font-size: 1.5rem;">👑</span>'

    if card_art_uri:
        bg_art_style = (
            f"background-image: linear-gradient(145deg, rgba(10, 17, 26, 0.94) 0%, rgba(5, 10, 16, 0.97) 100%), url('{card_art_uri}'); "
            f"background-position: right bottom; "
            f"background-repeat: no-repeat; "
            f"background-size: auto 85%;"
        )
    else:
        bg_art_style = f"background: {UI_THEME['card_bg']};"

    # Global Rank Pill
    rank_html = ""
    try:
        rank_val = int(global_rank)
        if rank_val > 0:
            rank_html = f'<span style="font-size: 0.72em; color: {UI_THEME["secondary_accent"]}; background: rgba(164, 224, 220, 0.1); border: 1px solid rgba(164, 224, 220, 0.25); border-radius: 10px; padding: 2px 7px; white-space: nowrap;">#{rank_val:,} Global</span>'
    except (ValueError, TypeError, OverflowError):
        pass

    # Account Type Pill (Ironman icons or label)
    type_badge = ""
    if player_type == "ironman":
        type_badge = " <span style='font-size: 0.75em; color: #C0C0C0;'>[Iron]</span>"
    elif player_type == "hardcore":
        type_badge = " <span style='font-size: 0.75em; color: #FF4444;'>[HCIM]</span>"
    elif player_type == "ultimate":
        type_badge = " <span style='font-size: 0.75em; color: #FFFFFF;'>[UIM]</span>"

    # Return as single unindented line to prevent CommonMark from treating 4+ spaces as a code block
    return (
        f'<div class="champion-card" style="{bg_art_style}">'
        f'<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.6rem;">'
        f'<div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">'
        f'<div class="champion-icon-container">{icon_html}</div>'
        f'<div style="font-size: 1.05em; font-weight: bold; color: {UI_THEME["text_main"]}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{display_name}">{display_name}</div>'
        f'</div>'
        f'{rank_html}'
        f'</div>'
        f'<div style="margin-top: 0.4rem; padding-top: 0.5rem; border-top: 1px solid rgba(200, 145, 0, 0.15);">'
        f'<div style="font-size: 1.15em; font-weight: bold; color: {UI_THEME["text_main"]}; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{discord_name}</div>'
        f'<div style="display: flex; align-items: center; justify-content: space-between; margin-top: 2px;">'
        f'<div class="rsn-badge" title="Character: {rsn}">👤 {rsn}{type_badge}</div>'
        f'<div style="font-size: 1.1em; font-weight: bold; color: {UI_THEME["primary"]}; text-shadow: 0 0 10px rgba(200, 145, 0, 0.3);">{formatted_score}</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )


# --- Custom Page CSS ---
st.markdown(f"""
<style>
    .champion-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 16px;
        margin-top: 12px;
        margin-bottom: 24px;
    }}
    .champion-card {{
        border: 1px solid {UI_THEME['primary_border']};
        border-radius: 10px;
        padding: 14px 16px;
        position: relative;
        overflow: hidden;
        transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        box-shadow: {UI_THEME['shadow_sm']};
        min-height: 128px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }}
    .champion-card:hover {{
        transform: translateY(-2px);
        border-color: {UI_THEME['primary']};
        box-shadow: 0 8px 18px rgba(200, 145, 0, 0.25);
    }}
    .champion-icon-container {{
        width: 38px;
        height: 38px;
        min-width: 38px;
        background: rgba(0, 0, 0, 0.4);
        border: 1px solid {UI_THEME['primary_border']};
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .rsn-badge {{
        background: rgba(200, 145, 0, 0.12);
        border: 1px solid rgba(200, 145, 0, 0.3);
        border-radius: 12px;
        padding: 2px 8px;
        font-size: 0.82em;
        color: {UI_THEME['text_main']};
        max-width: 60%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
</style>
""", unsafe_allow_html=True)


# --- Load Data ---
df_champions = Streamlit_utils.load_table("content_hiscores_summary")
df_stats = Streamlit_utils.load_table("clan_statistics_summary")

# --- Hero Header ---
Streamlit_utils.display_page_header(
    "👑 Clan Highscores & Content Records",
    "Highscores, and milestone achievements across all OSRS bosses, raids, skills, and minigames. "
    "Updated every Monday."
)

if df_champions.empty:
    st.info("⚠️ **Clan Highscores Not Yet Indexed**\n\nRun the Backend Auditor and ETL pipeline to sync clan records from Wise Old Man.")
else:
    # --- Top Section Header: Clan-Wide Totals ---
    st.markdown(
        f"""<div style="margin-bottom: 0.85rem;">
            <span style="font-size: 1.2em; font-weight: 700; color: {UI_THEME['primary']}; letter-spacing: 0.5px;">🏛️ Clan-Wide Milestones & Totals</span>
            <span style="font-size: 0.85em; color: {UI_THEME['text_dim']}; margin-left: 10px;">(Aggregated across the entire clan membership)</span>
        </div>""",
        unsafe_allow_html=True
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    
    # Extract stats from df_stats if available
    stats_dict = {}
    if not df_stats.empty and 'metric' in df_stats.columns:
        stats_dict = dict(zip(df_stats['metric'], df_stats['value']))

    # Find the player holding the most #1 crowns
    top_holder = "None"
    top_crowns = 0
    if 'discord_name' in df_champions.columns:
        holder_counts = df_champions['discord_name'].value_counts()
        if not holder_counts.empty:
            top_holder = holder_counts.index[0]
            top_crowns = int(holder_counts.iloc[0])

    with col1:
        st.markdown(Streamlit_utils.make_metric_card("⚔️ Maxed Combat (126)", f"{stats_dict.get('maxedCombatCount', 0):,} Members"), unsafe_allow_html=True)
    with col2:
        st.markdown(Streamlit_utils.make_metric_card("🏆 Max Total (2376)", f"{stats_dict.get('maxedTotalCount', 0):,} Members"), unsafe_allow_html=True)
    with col3:
        st.markdown(Streamlit_utils.make_metric_card("🌟 200M XP Skills", f"{stats_dict.get('maxed200msCount', 0):,} Achieved"), unsafe_allow_html=True)
    with col4:
        st.markdown(Streamlit_utils.make_metric_card("📊 Clan Avg Total", f"{stats_dict.get('averageTotalLevel', 0):,} Level"), unsafe_allow_html=True)
    with col5:
        st.markdown(Streamlit_utils.make_metric_card("🥇 Most #1 Highscores", f"{top_holder} ({top_crowns} #1s)"), unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)

    # --- Section Subheader: Content Highscores ---
    st.markdown(
        f"""<div style="margin-bottom: 0.75rem;">
            <span style="font-size: 1.2em; font-weight: 700; color: {UI_THEME['primary']}; letter-spacing: 0.5px;">👑 Content Highscores & Champions</span>
            <span style="font-size: 0.85em; color: {UI_THEME['text_dim']}; margin-left: 10px;">(Current #1 record holder at each piece of content)</span>
        </div>""",
        unsafe_allow_html=True
    )

    # --- Search & Filter Bar ---
    search_col, type_col = st.columns([3, 1])
    with search_col:
        search_query = st.text_input("🔍 Search Content or Player", placeholder="Search by boss, skill, or player name...").strip().lower()
    with type_col:
        type_options = ["All Types", "Regular", "Ironman", "Hardcore", "Ultimate"]
        selected_type = st.selectbox("Player Type", type_options, index=0)

    # Filter DataFrame
    df_filtered = df_champions.copy()
    if search_query:
        df_filtered = df_filtered[
            df_filtered['display_name'].str.lower().str.contains(search_query) |
            df_filtered['discord_name'].str.lower().str.contains(search_query) |
            df_filtered['rsn'].str.lower().str.contains(search_query)
        ]
    if selected_type != "All Types":
        df_filtered = df_filtered[df_filtered['player_type'].str.lower() == selected_type.lower()]

    # --- Dynamic Category Tabs ---
    CATEGORY_LABELS = {
        "bosses": "🐉 Bosses & Raids",
        "skills": "🛡️ Skills",
        "activities": "📜 Activities & Clues",
        "computed": "⚡ Efficiency (EHP & EHB)"
    }

    category_order = ["bosses", "skills", "activities", "computed"]
    available_cats = [c for c in category_order if c in df_filtered['category'].unique()]
    other_cats = [c for c in df_filtered['category'].unique() if c not in category_order]
    all_active_cats = available_cats + other_cats

    if not all_active_cats:
        st.warning("No records found matching your search filters.")
    else:
        tab_names = [f"{CATEGORY_LABELS.get(c, c.title())} ({len(df_filtered[df_filtered['category'] == c])})" for c in all_active_cats]
        tabs = st.tabs(tab_names)

        for tab, cat in zip(tabs, all_active_cats):
            with tab:
                df_cat = df_filtered[df_filtered['category'] == cat]
                if df_cat.empty:
                    st.info(f"No records match the current filters in {cat.title()}.")
                else:
                    cards_str = "".join(render_champion_card(row) for _, row in df_cat.iterrows())
                    st.markdown(f'<div class="champion-grid">{cards_str}</div>', unsafe_allow_html=True)
