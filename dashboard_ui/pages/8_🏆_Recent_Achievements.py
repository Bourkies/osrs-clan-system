# dashboard/pages/8_🏆_Recent_Achievements.py

import streamlit as st
import pandas as pd
import random
import Streamlit_utils
import toml
from pathlib import Path
import html
import re
from datetime import datetime, timezone

current_script_directory = Path(__file__).resolve().parent

st.set_page_config(page_title="Recent Achievements", page_icon="🏆", layout="wide")

@st.cache_data(ttl=300)
def load_texts():
    """Loads text snippets from the TOML file."""
    try:
        return toml.load(current_script_directory.parent / 'dashboard_texts.toml')
    except Exception as e:
        st.error(f"Failed to load dashboard_texts.toml: {e}")
        return {}

def get_achievement_message(row, texts):
    """Gets the formatted message for an achievement and applies custom colors."""
    ui_theme = Streamlit_utils.UI_THEME
    broadcast_type = str(row.get('Broadcast_Type', ''))
    page_texts = texts.get('recent_achievements', {})
    
    # 1. Extract base values
    raw_player = html.escape(str(row.get('Username', 'Someone')))
    
    ts = row.get('Timestamp')
    raw_date = pd.to_datetime(ts).strftime('%d %b %Y') if pd.notna(ts) else "Unknown Date"
    
    new_level_val = row.get('New_Level')
    raw_level = str(int(new_level_val)) if pd.notna(new_level_val) else "0"
    
    raw_skill = html.escape(str(row.get('Skill', 'Unknown')))
    raw_task = html.escape(str(row.get('Task_Name', 'Unknown')))
    raw_tier = html.escape(str(row.get('Tier', 'Unknown')))
    raw_pet = html.escape(str(row.get('Pet_Name', 'Unknown')))
    raw_content = html.escape(str(row.get('Content', 'something noteworthy!')))

    # 2. Wrap the values in specific theme colors
    fmt_player = f'<strong style="color: {ui_theme["primary"]}; font-weight: bold; font-size: 1.05em;">{raw_player}</strong>'
    fmt_date = f'<span style="color: {ui_theme["text_dim"]};">{raw_date}</span>'
    
    def highlight(text):
        return f'<strong style="color: {ui_theme["secondary_accent"]};">{text}</strong>'
        
    format_args = {
        'player': fmt_player,
        'date': fmt_date,
        'level': highlight(raw_level),
        'skill': highlight(raw_skill),
        'task': highlight(raw_task),
        'diary': highlight(raw_task),
        'quest_name': highlight(raw_task),
        'tier': highlight(raw_tier),
        'pet_name': highlight(raw_pet)
    }

    message_map = {
        'Maxed Skill (99)': 'maxed_skill_messages',
        'Level Up': 'level_up_messages',
        'Combat Task': 'combat_task_messages',
        'Diary': 'diary_messages',
        'Combat Achievement Tier': 'ca_tier_messages',
        'Pet': 'pet_messages',
        'Quest': 'quest_messages'
    }
    
    # 3. Default fallback message using the raw content
    html_message = f"🏆 On {fmt_date}, {fmt_player} achieved: {highlight(raw_content)}"

    # 4. Construct the final message
    if broadcast_type == 'Maxed Combat':
        html_message = f"🏆 On {fmt_date}, {fmt_player} achieved the highest combat level of {highlight('126')}!"
    elif broadcast_type in message_map:
        msg_key = message_map[broadcast_type]
        messages = page_texts.get(msg_key, [])
        if messages:
            # Strip the markdown ** bolding from the TOML template since we inject HTML directly now
            template = random.choice(messages).replace('**', '')
            html_message = template.format(**format_args)
            
    return html_message

# --- Main Page ---
Streamlit_utils.display_page_header(
    title="🏆 Recent Achievements",
    description="A live feed of the latest and greatest accomplishments from across the clan."
)

df_achievements = Streamlit_utils.load_table("recent_achievements")
texts = load_texts()

if df_achievements.empty:
    st.warning("No recent achievements could be loaded. The ETL pipeline may not have run yet.")
else:
    limit = st.sidebar.slider(
        "Number of achievements to show:",
        min_value=10,
        max_value=200,
        value=50,
        step=10
    )
    
    st.markdown("---")
    
    df_to_display = df_achievements.sort_values(by='Timestamp', ascending=False).head(limit)
    
    color_map = {
        "Maxed Skill (99)": "#FFD700",
        "Maxed Combat": "#FFD700",
        "Pet": "#DDA0DD",
        "Level Up": "#4682B4",
        "Combat Task": "#DC143C",
        "Combat Achievement Tier": "#DC143C",
        "Diary": "#8B4513",
        "Quest": "#8B4513"
    }
    
    if not df_to_display.empty:
        ui_theme = Streamlit_utils.UI_THEME
        now_utc = datetime.now(timezone.utc)
        
        # Centered container with max-width to replace st.columns, giving cards a better minimum width
        feed_html = '<div style="max-width: 850px; min-width: 350px; margin: 0 auto; height: 750px; overflow-y: auto; padding-right: 15px; padding-left: 15px;">'
        
        for _, row in df_to_display.iterrows():
            broadcast_type = html.escape(str(row.get('Broadcast_Type', 'Achievement')))
            message = get_achievement_message(row, texts)
            
            event_time = row.get('Timestamp')
            time_ago = "Unknown"
            if pd.notna(event_time):
                delta = now_utc - event_time
                total_seconds = int(delta.total_seconds())
                if total_seconds < 0: time_ago = "Just now"
                elif total_seconds >= 86400: time_ago = f"{total_seconds // 86400}d ago"
                elif total_seconds >= 3600: time_ago = f"{total_seconds // 3600}h ago"
                else: time_ago = f"{max(1, total_seconds // 60)}m ago"
                
            accent_color = color_map.get(broadcast_type, ui_theme.get("secondary_accent", "#A4E0DC"))
            
            feed_html += (
                f'<div style="background: {ui_theme["card_bg"]}; border: 1px solid {accent_color}; border-radius: 8px; padding: 15px; margin-bottom: 16px; box-shadow: {ui_theme["shadow_md"]};">'
                f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px;">'
                f'<span style="color: {accent_color}; font-weight: bold; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px;">{broadcast_type}</span>'
                f'<span style="color: {ui_theme["text_dim"]}; font-size: 0.85em; font-weight: 500;">{time_ago}</span>'
                f'</div>'
                f'<div style="color: {ui_theme["text_main"]}; font-size: 1.05em; line-height: 1.5;">'
                f'{message}'
                f'</div>'
                f'</div>'
            )
            
        feed_html += '</div>'
        
        st.markdown(feed_html, unsafe_allow_html=True)
    else:
        st.info("No achievements to display with the current settings.")
