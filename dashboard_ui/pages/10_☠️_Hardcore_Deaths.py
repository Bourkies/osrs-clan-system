# dashboard/pages/10_☠️_Hardcore_Deaths.py

import streamlit as st
import pandas as pd
import random
import Streamlit_utils
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pathlib import Path
import html
import base64
import os


# --- Page Configuration ---
st.set_page_config(page_title="Hardcore Deaths", page_icon="☠️", layout="wide")

# --- CONFIGURATION ---
# Set the filename of the background image. Place it in 'shared_config/assets/Page_backgrounds/'.
BACKGROUND_IMAGE_FILENAME = "1080px-Graveyard_of_Shadows.png"

# Toggle: Set to True to require '?admin=true' in URL to display Death's Domain.
# If False, Death's Domain will be visible at the bottom of the page for all viewers (collapsed by default).
REQUIRE_ADMIN_PARAM_FOR_DEATHS_DOMAIN = False

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
        word-wrap: break-word;
        overflow-wrap: break-word;
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

    /* --- Option C: Custom Lore Seal & Links Tray --- */
    .tombstone-seal {{
        position: absolute;
        top: 14px;
        left: 18px;
        font-size: 1.15rem;
        line-height: 1;
        cursor: help;
        z-index: 12;
        transition: transform 0.2s ease, filter 0.2s ease;
        filter: drop-shadow(0 2px 4px rgba(0,0,0,0.8));
        user-select: none;
    }}
    .tombstone-seal:hover {{
        transform: scale(1.25) rotate(-8deg);
        filter: drop-shadow(0 0 6px rgba(234, 179, 8, 0.8));
    }}
    .tombstone-links-tray {{
        position: absolute;
        top: 12px;
        right: 18px;
        display: flex;
        gap: 6px;
        z-index: 15;
    }}
    .tombstone-link-btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        background: rgba(18, 21, 30, 0.88);
        border: 1px solid rgba(255, 255, 255, 0.25);
        border-radius: 6px;
        font-size: 0.85rem;
        line-height: 1;
        text-decoration: none !important;
        cursor: pointer;
        box-shadow: 0 2px 5px rgba(0,0,0,0.6);
        transition: transform 0.15s ease, background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .tombstone-link-btn:hover {{
        transform: scale(1.2);
        background: rgba(30, 41, 59, 0.98);
        border-color: #60a5fa;
        box-shadow: 0 0 8px rgba(96, 165, 250, 0.6);
    }}
    /* Custom gravestones subtle distinction */
    .tombstone.tombstone-custom h4 {{
        color: #fef08a; /* Gilded engraved name */
        text-shadow: 0 0 10px rgba(234, 179, 8, 0.3), 2px 2px 4px rgba(0,0,0,0.9);
    }}
    .tombstone.tombstone-custom .death-message {{
        color: #f1f5f9;
    }}

    /* --- Mobile & Narrow Screen Responsiveness --- */
    @media (max-width: 900px) {{
        /* Stack columns vertically inside Death's Domain on tablet & mobile */
        [data-testid="stExpander"] [data-testid="column"] {{
            min-width: 100% !important;
            flex: 1 1 100% !important;
            margin-bottom: 1.5rem !important;
        }}
    }}

    @media (max-width: 768px) {{
        .tombstone {{
            transform: rotateZ(var(--rot-z)) translate(var(--off-x), var(--off-y)) !important;
            min-width: 280px !important;
            max-width: 340px !important;
            width: 100% !important;
        }}
        .tombstone:hover {{
            transform: scale(1.05) translate(var(--off-x), calc(var(--off-y) - 5px)) !important;
        }}
        [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
            padding: 1rem 0.75rem !important;
        }}
    }}

    /* --- Death's Domain / Admin Expander Solid Theme --- */
    [data-testid="stExpander"] {{
        background: #151821 !important;
        border: 2px solid #3c4252 !important;
        border-radius: 10px !important;
        box-shadow: 0 16px 36px rgba(0, 0, 0, 0.9) !important;
        margin-bottom: 2rem !important;
    }}
    [data-testid="stExpander"] > details {{
        background: #151821 !important;
        border-radius: 8px !important;
    }}
    [data-testid="stExpander"] > details > summary {{
        background: linear-gradient(90deg, #1f2330 0%, #171a24 100%) !important;
        color: #e2e8f0 !important;
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        border-radius: 8px 8px 0 0 !important;
        border-bottom: 1px solid #2d3342 !important;
        padding: 0.85rem 1.25rem !important;
    }}
    [data-testid="stExpander"] > details > summary:hover {{
        color: #60a5fa !important;
    }}
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
        background: #12141c !important;
        border-radius: 0 0 8px 8px !important;
        padding: 1.5rem !important;
        color: #cbd5e1 !important;
    }}
    [data-testid="stExpander"] [data-testid="stMetric"] {{
        background: #1b1e2a !important;
        border: 1px solid #2e3444 !important;
        border-radius: 8px !important;
        padding: 0.75rem 1rem !important;
    }}
    [data-testid="stExpander"] [data-testid="stMetricLabel"] {{
        color: #94a3b8 !important;
    }}
    [data-testid="stExpander"] [data-testid="stMetricValue"] {{
        color: #f1f5f9 !important;
    }}
</style>
""", unsafe_allow_html=True)


# --- Data Loading & Persistence ---

def get_custom_deaths_file_path() -> Path:
    """Finds the path to hardcore_deaths.toml, or the location to save it."""
    shared_config_env = os.environ.get("SHARED_CONFIG_DIR")
    if shared_config_env:
        return Path(shared_config_env) / "hardcore_deaths.toml"
        
    current_script_directory = Path(__file__).resolve().parent
    possible_paths = [
        current_script_directory.parent.parent / "shared_config" / "hardcore_deaths.toml",
        Path("/app/shared_config/hardcore_deaths.toml"),
        Path("shared_config/hardcore_deaths.toml")
    ]
    for p in possible_paths:
        if p.exists():
            return p
    return current_script_directory.parent.parent / "shared_config" / "hardcore_deaths.toml"

@st.cache_data(ttl=60)
def load_custom_deaths() -> dict:
    """
    Loads custom death overrides from hardcore_deaths.toml.
    Returns a dict mapping raw_log_id (int) -> death entry dict.
    """
    file_path = get_custom_deaths_file_path()
    if not file_path.exists():
        # Fall back to example file if main does not exist
        example_path = file_path.parent / "hardcore_deaths.example.toml"
        if example_path.exists():
            file_path = example_path
        else:
            return {}
            
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
        deaths_list = data.get("deaths", [])
        mapping = {}
        for entry in deaths_list:
            if "id" in entry:
                try:
                    mapping[int(entry["id"])] = entry
                except (ValueError, TypeError):
                    pass
        return mapping
    except Exception as e:
        st.warning(f"Could not load custom deaths from {file_path.name}: {e}")
        return {}

def load_texts():
    """Loads text snippets from dashboard_texts.toml."""
    return Streamlit_utils.load_dashboard_texts()

@st.cache_data(ttl=300)
def load_hc_deaths():
    """Loads all Hardcore death events from the persistent graveyard report."""
    try:
        df_deaths = Streamlit_utils.load_table("hc_graveyard_detail_all_time")
        if df_deaths.empty:
            return pd.DataFrame()
        
        if 'New_Group_Lives' not in df_deaths.columns:
            df_deaths['New_Group_Lives'] = None
        else:
            df_deaths['New_Group_Lives'] = df_deaths['New_Group_Lives'].replace({"": None, pd.NA: None})

        df_deaths = df_deaths.sort_values(by='Timestamp', ascending=False)
        return df_deaths
    except Exception as e:
        st.error(f"Could not load the Hardcore Graveyard report. Error: {e}")
        return pd.DataFrame()

# --- Formatting Functions ---

def parse_links(entry: dict) -> list:
    """
    Parses 'link' (string) or 'links' (list/string) from a custom death entry.
    Returns a list of dicts: [{'url': str, 'icon': str, 'title': str}, ...]
    """
    if not entry:
        return []
    raw = entry.get("links") or entry.get("link")
    if not raw:
        return []
    
    urls = []
    if isinstance(raw, list):
        urls = [str(u).strip() for u in raw if str(u).strip()]
    elif isinstance(raw, str):
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        
    parsed = []
    for url in urls:
        low = url.lower()
        if "twitch.tv" in low:
            icon = "🎬"
            title = "Watch Twitch Clip"
        elif "youtube.com" in low or "youtu.be" in low:
            icon = "▶️"
            title = "Watch YouTube Video"
        elif "discord.com" in low or "discord.gg" in low:
            icon = "💬"
            title = "View Discord Clip / Message"
        elif any(ext in low for ext in [".png", ".jpg", ".jpeg", ".webp", "gyazo.com", "imgur.com"]):
            icon = "📸"
            title = "View Screenshot"
        else:
            icon = "🔗"
            title = "View Proof / Related Link"
            
        parsed.append({"url": url, "icon": icon, "title": title})
        
    return parsed

def get_death_details(row, texts, custom_deaths=None):
    """Determines the death type, message, and links from a row, checking for custom overrides first."""
    if custom_deaths is None:
        custom_deaths = {}
        
    page_texts = texts.get('hardcore_deaths', {})
    player = row.get('Username', 'A brave warrior')
    date = pd.to_datetime(row.get('Timestamp')).strftime('%d %b %Y')
    group_lives = row.get('New_Group_Lives')
    raw_id = row.get('raw_log_id')

    base_class = "tombstone"
    is_status_lost = False
    
    if pd.isna(group_lives):
        modifier_class = ""
        default_messages = page_texts.get('solo_death_messages', [])
        if not default_messages:
            default_messages = ["{player} thought they were invincible. They were wrong."]
    elif str(group_lives).startswith('0/'):
        modifier_class = "tombstone-group-status-lost"
        is_status_lost = True
        default_messages = page_texts.get('group_status_lost_messages', [])
        if not default_messages:
            default_messages = ["{player} took the team down with them. Team status: DEAD."]
    else:
        modifier_class = "tombstone-group-life"
        default_messages = page_texts.get('group_life_lost_messages', [])
        if not default_messages:
            default_messages = ["{player} cost the team a life. Lives remaining: {lives}"]
        
    full_class = f"{base_class} {modifier_class}".strip()
    
    # Check for custom override by raw_log_id
    is_custom = False
    links_list = []
    if raw_id is not None and int(raw_id) in custom_deaths:
        entry = custom_deaths[int(raw_id)]
        message_template = entry.get('message', '')
        is_custom = True
        links_list = parse_links(entry)
    else:
        message_template = random.choice(default_messages)
        
    try:
        message = message_template.format(
            player=player,
            username=player,
            date=date,
            lives=group_lives if pd.notna(group_lives) else "Solo"
        )
    except (KeyError, IndexError, ValueError):
        message = message_template
        
    message_html = message.replace(player, f'<strong>{player}</strong>', 1)
    
    return player, date, message_html, full_class, is_status_lost, is_custom, links_list

def display_tombstone(player, date, message, style_class, inline_vars, is_status_lost, is_custom=False, links=None):
    """Returns the HTML for a single tombstone card with transformations, Option C seal, and link tray."""
    safe_player = html.escape(player)
    inner_class = "tombstone-content shake-anim" if is_status_lost else "tombstone-content"
    custom_class = " tombstone-custom" if is_custom else ""
    full_card_class = f"{style_class}{custom_class}"
    
    seal_html = ""
    if is_custom:
        seal_html = '<span class="tombstone-seal" title="Inscribed Clan Lore (Custom Epitaph)">📜</span>'
        
    links_html = ""
    if links:
        link_items = []
        for l in links:
            safe_url = html.escape(l.get("url", "#"))
            safe_title = html.escape(l.get("title", "Link"))
            icon = l.get("icon", "🔗")
            link_items.append(
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="tombstone-link-btn" title="{safe_title}">{icon}</a>'
            )
        links_html = f'<div class="tombstone-links-tray">{"".join(link_items)}</div>'
    
    return (
        f'<div class="{full_card_class}" style="{inline_vars}">'
        f'{seal_html}'
        f'{links_html}'
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
custom_deaths = load_custom_deaths()

# --- Tombstone Grid Rendering ---

if df_deaths.empty:
    st.success("🎉 The graveyard is empty! No one has died recently. The clan is safe... for now.")
else:
    df_to_display = df_deaths

    tombstone_cards = []
    for _, row in df_to_display.iterrows():
        player, date, message, style_class, is_status_lost, is_custom, links_list = get_death_details(row, texts, custom_deaths)
        
        rotation = random.uniform(-RANDOM_ROTATION_DEG, RANDOM_ROTATION_DEG)
        y_offset = random.uniform(-RANDOM_OFFSET_Y_PX, RANDOM_OFFSET_Y_PX)
        x_offset = random.uniform(-RANDOM_OFFSET_X_PX, RANDOM_OFFSET_X_PX)
        
        inline_vars = f"--rot-z: {rotation:.2f}deg; --off-y: {y_offset:.2f}px; --off-x: {x_offset:.2f}px;"
        
        tombstone_cards.append(
            display_tombstone(
                player=player,
                date=date,
                message=message,
                style_class=style_class,
                inline_vars=inline_vars,
                is_status_lost=is_status_lost,
                is_custom=is_custom,
                links=links_list
            )
        )

    tombstones_html = "".join(tombstone_cards)
    st.markdown(f'<div class="tombstone-grid">{tombstones_html}</div>', unsafe_allow_html=True)

# --- Death's Domain (Epitaph Inscription & Admin Inspector) at Bottom of Page ---
has_admin_flag = str(st.query_params.get("admin", "")).lower() in ["true", "1", "yes"]
show_deaths_domain = (not REQUIRE_ADMIN_PARAM_FOR_DEATHS_DOMAIN) or has_admin_flag

if show_deaths_domain and not df_deaths.empty:
    st.divider()
    title_suffix = " (Admin Mode)" if has_admin_flag else " — Gravestone Inscriptions"
    with st.expander(f"⏳ Death's Domain{title_suffix}", expanded=False):
        st.markdown("Inspect death events claimed by Death, craft custom epitaphs, and preview them live.")
        
        # Tags reference guide inside Death's Domain
        st.markdown("""
        <div style="background: #191c26; border: 1px solid #2e3444; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1.25rem;">
            <div style="font-weight: bold; color: #f1f5f9; margin-bottom: 0.5rem; font-size: 0.95rem;">📜 Available Placeholder Tags:</div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.75rem;">
                <div style="color: #cbd5e1; font-size: 0.88rem;"><code style="color: #60a5fa; font-weight: bold;">{player}</code> / <code style="color: #60a5fa; font-weight: bold;">{username}</code>: Player's RSN (auto-bolded, max 12 chars)</div>
                <div style="color: #cbd5e1; font-size: 0.88rem;"><code style="color: #60a5fa; font-weight: bold;">{date}</code>: Fallen date (e.g. <em>28 Aug 2026</em>, 11 chars)</div>
                <div style="color: #cbd5e1; font-size: 0.88rem;"><code style="color: #60a5fa; font-weight: bold;">{lives}</code>: Group lives left (e.g. <em>1/4</em> or <em>Solo</em>, 4 chars)</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Summary counts
        total_deaths = len(df_deaths)
        custom_count = sum(1 for rid in df_deaths['raw_log_id'] if int(rid) in custom_deaths)
        generic_count = total_deaths - custom_count
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Fallen", total_deaths)
        m2.metric("Custom Overrides Active", custom_count)
        m3.metric("Generic Banter", generic_count)
        
        st.divider()
        
        # Build options for selector
        death_options = {}
        for _, r in df_deaths.iterrows():
            r_id = int(r['raw_log_id'])
            r_user = str(r['Username'])
            r_date = pd.to_datetime(r['Timestamp']).strftime('%d %b %Y, %H:%M')
            has_cust = r_id in custom_deaths
            status_tag = "🟢 Custom" if has_cust else "🎲 Random"
            is_group = bool(pd.notna(r.get('New_Group_Lives')))
            lives_tag = f"[{r['New_Group_Lives']}]" if is_group else "[Solo]"
            label = f"#{r_id} — {r_user} ({r_date}) {lives_tag} — {status_tag}"
            death_options[label] = r
            
        selected_label = st.selectbox("Select Death Event to Inspect / Override:", list(death_options.keys()))
        selected_row = death_options[selected_label]
        sel_id = int(selected_row['raw_log_id'])
        sel_user = str(selected_row['Username'])
        sel_date = pd.to_datetime(selected_row['Timestamp']).strftime('%d %b %Y')
        sel_lives = selected_row.get('New_Group_Lives')
        sel_content = str(selected_row.get('Content', 'No broadcast content found'))
        
        st.caption(f"**In-Game Broadcast:** `{sel_content}` | **Timestamp (UTC):** `{selected_row['Timestamp']}`")
        
        # Current message in custom_deaths or default
        existing_custom_msg = str(custom_deaths.get(sel_id, {}).get("message", ""))
        existing_custom_entry = custom_deaths.get(sel_id, {})
        existing_raw_links = existing_custom_entry.get("links") or existing_custom_entry.get("link", "")
        if isinstance(existing_raw_links, list):
            init_links_val = ", ".join(str(l) for l in existing_raw_links)
        else:
            init_links_val = str(existing_raw_links or "")
        
        custom_input_val = st.text_area(
            "Custom Epitaph / Story",
            value=existing_custom_msg,
            placeholder=f"e.g. Too hardcore for an anti-dragon shield, {{player}} got cooked to Elvarg.",
            help="Available tags: {player} or {username}, {date}, {lives}.",
            key=f"custom_input_{sel_id}"
        )
        custom_input: str = str(custom_input_val or "").strip()
        
        # Smart Character Count Calculation (directly under epitaph box):
        MAX_CHARS = 150
        def calc_rendered_len(text: str, user: str) -> int:
            u_len = max(len(user), 12) if user else 12
            t = text.replace("{player}", "X" * u_len)
            t = t.replace("{username}", "X" * u_len)
            t = t.replace("{date}", "X" * 11)
            t = t.replace("{lives}", "X" * 4)
            return len(t)
            
        rendered_len = calc_rendered_len(custom_input, sel_user)
        remaining = MAX_CHARS - rendered_len
        
        if custom_input:
            if remaining >= 0:
                st.caption(f"📏 Estimated rendered length: **{rendered_len} / {MAX_CHARS}** characters ({remaining} characters remaining)")
            else:
                st.warning(f"⚠️ Message exceeds recommended tombstone space by **{abs(remaining)}** characters ({rendered_len} / {MAX_CHARS}). It may cut off on the stone.")
        else:
            st.caption(f"📏 Maximum recommended rendered length: **{MAX_CHARS}** characters.")
        
        links_input_val = st.text_input(
            "Proof / Clip Links (Optional — comma-separated for multiple)",
            value=init_links_val,
            placeholder="e.g. https://clips.twitch.tv/..., https://imgur.com/...",
            help="Supported: Twitch clips (🎬), YouTube (▶️), Discord (💬), Screenshots (📸), and web links (🔗). Separate multiple URLs with commas.",
            key=f"links_input_{sel_id}"
        )
        links_input: str = str(links_input_val or "").strip()
        
        # Determine tombstone styling for preview
        is_sel_status_lost = False
        if pd.isna(sel_lives):
            sel_class = "tombstone"
        elif str(sel_lives).startswith('0/'):
            sel_class = "tombstone tombstone-group-status-lost"
            is_sel_status_lost = True
        else:
            sel_class = "tombstone tombstone-group-life"
            
        preview_text = custom_input if custom_input else f"<em>(Preview: Enter an epitaph above)</em>"
        try:
            preview_formatted = preview_text.format(
                player=sel_user,
                username=sel_user,
                date=sel_date,
                lives=sel_lives if pd.notna(sel_lives) else "Solo"
            )
        except Exception:
            preview_formatted = preview_text
        preview_html = preview_formatted.replace(sel_user, f'<strong>{sel_user}</strong>', 1)
        
        # Parse links for live preview
        preview_links = parse_links({"links": links_input}) if links_input else []
        is_preview_custom = bool(custom_input or links_input)
        
        # Row 1: Live Tombstone Preview (Full Width Row)
        st.markdown("##### 🪦 Live Tombstone Preview")
        preview_card = display_tombstone(
            player=sel_user,
            date=sel_date,
            message=preview_html,
            style_class=sel_class,
            inline_vars="--rot-z: 0deg; --off-y: 0px; --off-x: 0px; margin: 0 auto;",
            is_status_lost=is_sel_status_lost,
            is_custom=is_preview_custom,
            links=preview_links
        )
        st.markdown(f'<div style="display:flex; justify-content:center; padding: 1.25rem 0;">{preview_card}</div>', unsafe_allow_html=True)
        
        # Row 2: TOML Configuration (Full Width Row)
        st.markdown("##### 📋 TOML Configuration")
        st.caption("Copy this snippet and paste it into `shared_config/hardcore_deaths.toml` (or share it with a clan admin to inscribe):")
        safe_msg = custom_input.replace('"', '\\"')
        
        # Build TOML lines
        toml_lines = [
            "[[deaths]]",
            f"id = {sel_id}",
            f'username = "{sel_user}"',
            f'message = "{safe_msg}"'
        ]
        
        cleaned_urls = [u.strip() for u in links_input.split(",") if u.strip()]
        if len(cleaned_urls) == 1:
            safe_url = cleaned_urls[0].replace('"', '\\"')
            toml_lines.append(f'link = "{safe_url}"')
        elif len(cleaned_urls) > 1:
            formatted_items = []
            for u in cleaned_urls:
                esc_u = u.replace('"', '\\"')
                formatted_items.append(f'  "{esc_u}"')
            formatted_urls = ",\n".join(formatted_items)
            toml_lines.append(f'links = [\n{formatted_urls}\n]')
            
        toml_snippet = "\n".join(toml_lines)
        st.code(toml_snippet, language="toml", wrap_lines=True)

        st.divider()