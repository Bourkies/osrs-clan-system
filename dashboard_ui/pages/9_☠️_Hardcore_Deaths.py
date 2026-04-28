# dashboard/pages/9_☠️_Hardcore_Deaths.py

import streamlit as st
import pandas as pd
import random
import Streamlit_utils
import toml
from pathlib import Path
import html
import base64

# --- Page Configuration ---
st.set_page_config(page_title="Hardcore Deaths", page_icon="☠️", layout="wide")

# --- CONFIGURATION ---
# Set the filename of the background image. Place it in 'shared_config/assets/Page_backgrounds/'.
BACKGROUND_IMAGE_FILENAME = "1080px-Graveyard_of_Shadows.png"

# -- Tombstone Style & Layout Configuration --
TOMBSTONE_MIN_WIDTH_PX = 300
TOMBSTONE_MAX_WIDTH_PX = 340
TOMBSTONE_HEIGHT_PX = 290
TOMBSTONE_BORDER_WIDTH_PX = 3 # Increased border width
TOMBSTONE_TAPER_ANGLE_DEG = -15 # How much the tombstone leans back to give a 3D feel.

# -- Tombstone Color Configuration (CSS format) --
TOMBSTONE_TEXT_COLOR = "#c4c4c4"
# Solo (Normal) Death
SOLO_DEATH_BG_COLOR = "linear-gradient(180deg, rgba(58, 62, 70, 0.95) 0%, rgba(30, 32, 36, 0.95) 100%)"
SOLO_DEATH_BORDER_COLOR = "#5a5e65"
# Group Life Lost
GROUP_LIFE_LOST_BG_COLOR = "linear-gradient(180deg, rgba(68, 48, 50, 0.95) 0%, rgba(38, 26, 27, 0.95) 100%)"
GROUP_LIFE_LOST_BORDER_COLOR = "#7a5a5a"
# Group Status Lost (Last Life)
GROUP_STATUS_LOST_BG_COLOR = "linear-gradient(180deg, rgba(58, 70, 92, 0.95) 0%, rgba(30, 38, 50, 0.95) 100%)" # More desaturated blue
GROUP_STATUS_LOST_BORDER_COLOR = "#7a8c99" # Greyish-blue border

# -- Grid Layout Configuration --
GRID_GAP_REM = 1.5 # Gap between cards.

# -- Randomization Limits --
RANDOM_ROTATION_DEG = 3      # Max rotation (reduced to prevent overlap).
RANDOM_OFFSET_Y_PX = 15         # Max vertical offset.
RANDOM_OFFSET_X_PX = 15         # Max horizontal offset.


# --- Functions ---

@st.cache_data
def get_image_as_base64(file_path):
    """Reads a local image file and returns its base64 encoded string."""
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return None
            
        if not file_path.is_file():
            return None
            
        with open(file_path, "rb") as f:
            data = f.read()
            
        if len(data) == 0:
            return None
            
        return base64.b64encode(data).decode()
        
    except Exception as e:
        return None

def set_page_background(image_filename):
    """Sets the background of the page to the specified image."""
    if not image_filename:
        return

    # Try multiple possible paths
    current_script_directory = Path(__file__).resolve().parent
    possible_paths = [
        current_script_directory.parent.parent / "shared_config" / "assets" / "Page_backgrounds" / image_filename,
        current_script_directory.parent.parent / "shared_config" / "images" / image_filename,
    ]
    
    image_path = None
    for path in possible_paths:
        if path.exists():
            image_path = path
            break
    
    if not image_path:
        return False

    base64_image = get_image_as_base64(image_path)
    
    if base64_image:
        # Try multiple CSS selectors for better compatibility
        background_style = f"""
        <style>
        /* Multiple selectors to ensure compatibility */
        [data-testid="stApp"] > .main {{
            background-image: url("data:image/png;base64,{base64_image}");
            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        .stApp > .main {{
            background-image: url("data:image/png;base64,{base64_image}");
            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        .stApp {{
            background-image: url("data:image/png;base64,{base64_image}");
            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        /* Fallback for older Streamlit versions */
        .main .block-container {{
            background-image: url("data:image/png;base64,{base64_image}");
            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        </style>
        """
        st.markdown(background_style, unsafe_allow_html=True)
        return True
    else:
        return False


# --- Apply Background and Custom CSS ---
set_page_background(BACKGROUND_IMAGE_FILENAME)

# Apply tombstone CSS
st.markdown(f"""
<style>
    .tombstone-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax({TOMBSTONE_MIN_WIDTH_PX}px, 1fr));
        gap: {GRID_GAP_REM}rem;
        padding-top: 1rem;
        padding-bottom: 2rem;
    }}
    .tombstone {{
        background: {SOLO_DEATH_BG_COLOR};
        border: {TOMBSTONE_BORDER_WIDTH_PX}px solid {SOLO_DEATH_BORDER_COLOR};
        border-bottom: {TOMBSTONE_BORDER_WIDTH_PX}px solid #111;
        border-radius: 50px 50px 8px 8px;
        padding: 1.8rem 1.2rem 1.2rem 1.2rem;
        text-align: center;
        height: {TOMBSTONE_HEIGHT_PX}px;
        min-width: {TOMBSTONE_MIN_WIDTH_PX}px;
        max-width: {TOMBSTONE_MAX_WIDTH_PX}px;
        box-shadow: inset 0 0 20px rgba(0,0,0,0.8), 0 12px 15px rgba(0,0,0,0.6);
        position: relative;
        color: {TOMBSTONE_TEXT_COLOR};
        transition: transform 0.3s ease-in-out, box-shadow 0.3s ease-in-out;
        backdrop-filter: blur(3px);
        /* Apply individual perspective so lower stones don't distort weirdly */
        transform: perspective(1000px) rotateX({TOMBSTONE_TAPER_ANGLE_DEG}deg) rotateZ(var(--rot-z)) translate(var(--off-x), var(--off-y));
        transform-style: preserve-3d;
    }}
    .tombstone:hover {{
        z-index: 10;
        box-shadow: inset 0 0 15px rgba(0,0,0,0.6), 0 20px 25px rgba(0,0,0,0.8);
        transform: perspective(1000px) rotateX(0deg) scale(1.05) translate(var(--off-x), calc(var(--off-y) - 10px));
    }}
    .tombstone::after {{
        content: '';
        position: absolute;
        bottom: -{TOMBSTONE_BORDER_WIDTH_PX}px;
        left: -10px;
        right: -10px;
        height: 15px;
        background: linear-gradient(90deg, #1a1a1a 0%, #2a2a2a 50%, #1a1a1a 100%);
        border-radius: 4px;
        z-index: -1;
        box-shadow: 0 4px 8px rgba(0,0,0,0.7);
    }}
    .tombstone.tombstone-group-life {{
        background: {GROUP_LIFE_LOST_BG_COLOR};
        border-color: {GROUP_LIFE_LOST_BORDER_COLOR};
    }}
    .tombstone.tombstone-group-status-lost {{
        background: {GROUP_STATUS_LOST_BG_COLOR};
        border-color: {GROUP_STATUS_LOST_BORDER_COLOR};
    }}
    .tombstone h4 {{
        font-size: 1.3em;
        font-weight: 800;
        color: #e2e2e2;
        margin-top: 0;
        margin-bottom: 0.5rem;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
        letter-spacing: 1px;
    }}
    .tombstone .rip {{
        font-family: 'Times New Roman', Courier, serif;
        font-size: 2.8em;
        font-weight: bold;
        color: rgba(0, 0, 0, 0.6);
        margin: 0.5rem 0;
        text-shadow: -1px -1px 1px rgba(0,0,0,0.8), 1px 1px 1px rgba(255,255,255,0.15);
        letter-spacing: 2px;
    }}
    .tombstone .death-message {{
        font-size: 0.95em;
        font-style: italic;
        flex-grow: 1;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.7);
    }}
    .tombstone .death-date {{
        font-size: 0.9em;
        color: #888;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.7);
    }}
    .tombstone-content {{
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 100%;
    }}
    .shake-anim {{
        animation: shake 0.82s cubic-bezier(.36,.07,.19,.97) both;
    }}
    @keyframes shake {{
      10%, 90% {{ transform: translate3d(-1px, 0, 0); }}
      20%, 80% {{ transform: translate3d(2px, 0, 0); }}
      30%, 50%, 70% {{ transform: translate3d(-4px, 0, 0); }}
      40%, 60% {{ transform: translate3d(4px, 0, 0); }}
    }}

    /* --- Mobile Responsiveness --- */
    @media (max-width: 768px) {{
        .tombstone {{
            transform: rotateZ(var(--rot-z)) translate(var(--off-x), var(--off-y)) !important; 
        }}
        .tombstone:hover {{
            transform: scale(1.05) translate(var(--off-x), calc(var(--off-y) - 5px)) !important;
        }}
    }}
</style>
""", unsafe_allow_html=True)


# --- Data Loading ---

@st.cache_data(ttl=300)
def load_texts():
    """Loads text snippets from the TOML file."""
    try:
        # Try multiple paths for the TOML file too
        current_script_directory = Path(__file__).resolve().parent
        possible_toml_paths = [
            current_script_directory.parent / 'dashboard_texts.toml',
            current_script_directory / 'dashboard_texts.toml',
            Path('.') / 'dashboard_texts.toml',
        ]
        
        for toml_path in possible_toml_paths:
            if toml_path.exists():
                return toml.load(toml_path)
                
        return {}
    except Exception as e:
        return {}

@st.cache_data(ttl=300)
def load_hc_deaths():
    """Loads all Hardcore death events from the persistent graveyard report."""
    try:
        # Load the new, persistent detailed report for all-time hardcore deaths
        df_deaths = Streamlit_utils.load_table("hc_graveyard_detail_all_time")
        if df_deaths.empty:
            return pd.DataFrame()
        
        # Ensure the 'New_Group_Lives' column exists for the tombstone logic
        if 'New_Group_Lives' not in df_deaths.columns:
            df_deaths['New_Group_Lives'] = None
        else:
            # Standardize missing values for easier processing
            df_deaths['New_Group_Lives'] = df_deaths['New_Group_Lives'].replace({"": None, pd.NA: None})

        # The detailed report is already sorted by timestamp descending in the ETL
        # but we can sort again just to be safe.
        df_deaths.sort_values(by='Timestamp', ascending=False, inplace=True)
        return df_deaths
    except Exception as e:
        st.error(f"Could not load the Hardcore Graveyard report. It may not have been generated yet. Error: {e}")
        return pd.DataFrame()

# --- Formatting Functions ---

def get_death_details(row, texts):
    """Determines the death type and message from a row."""
    page_texts = texts.get('hardcore_deaths', {})
    player = row.get('Username', 'A brave warrior')
    date = pd.to_datetime(row.get('Timestamp')).strftime('%d %b %Y')
    group_lives = row.get('New_Group_Lives')

    base_class = "tombstone"
    is_status_lost = False
    if pd.isna(group_lives):
        modifier_class = ""
        messages = page_texts.get('solo_death_messages', [])
        if not messages:
            messages = ["{player} thought they were invincible. They were wrong."]
        message_template = random.choice(messages)
    elif str(group_lives).startswith('0/'):
        modifier_class = "tombstone-group-status-lost"
        is_status_lost = True
        messages = page_texts.get('group_status_lost_messages', [])
        if not messages:
            messages = ["{player} took the team down with them. Team status: DEAD."]
        message_template = random.choice(messages)
    else:
        modifier_class = "tombstone-group-life"
        messages = page_texts.get('group_life_lost_messages', [])
        if not messages:
            messages = ["{player} cost the team a life. Lives remaining: {lives}"]
        message_template = random.choice(messages)
        
    full_class = f"{base_class} {modifier_class}".strip()
    
    message = message_template.format(player=player, date=date, lives=group_lives)
    message_html = message.replace(player, f'<strong>{player}</strong>', 1)
    
    return player, date, message_html, full_class, is_status_lost

def display_tombstone(player, date, message, style_class, inline_vars, is_status_lost):
    """Returns the HTML for a single tombstone card with random transformations."""
    safe_player = html.escape(player)
    inner_class = "tombstone-content shake-anim" if is_status_lost else "tombstone-content"
    
    return (
        f'<div class="{style_class}" style="{inline_vars}">'
        f'<div class="{inner_class}">'
        f'<h4>{safe_player}</h4>'
        f'<div class="rip">R.I.P.</div>'
        f'<div class="death-message">{message}</div>'
        f'<div class="death-date">Fallen: {date}</div>'
        f'</div>'
        f'</div>'
    )

# --- Main Page ---

Streamlit_utils.display_page_header(
    title="☠️ The Graveyard",
    description="A tribute to those who dared to risk it all and failed spectacularly. A wall of shame for the fallen. Press F to pay respects."
)

texts = load_texts()
df_deaths = load_hc_deaths()

if df_deaths.empty:
    st.success("🎉 The graveyard is empty! No one has died recently. The clan is safe... for now.")
else:
    df_to_display = df_deaths

    tombstone_cards = []
    for _, row in df_to_display.iterrows():
        player, date, message, style_class, is_status_lost = get_death_details(row, texts)
        
        rotation = random.uniform(-RANDOM_ROTATION_DEG, RANDOM_ROTATION_DEG)
        y_offset = random.uniform(-RANDOM_OFFSET_Y_PX, RANDOM_OFFSET_Y_PX)
        x_offset = random.uniform(-RANDOM_OFFSET_X_PX, RANDOM_OFFSET_X_PX)
        
        inline_vars = f"--rot-z: {rotation:.2f}deg; --off-y: {y_offset:.2f}px; --off-x: {x_offset:.2f}px;"
        
        tombstone_cards.append(display_tombstone(player, date, message, style_class, inline_vars, is_status_lost))

    tombstones_html = "".join(tombstone_cards)
    st.markdown(f'<div class="tombstone-grid">{tombstones_html}</div>', unsafe_allow_html=True)