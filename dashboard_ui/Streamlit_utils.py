# dashboard/Streamlit_utils.py
# Utility functions for the Streamlit dashboard.

import streamlit as st
import random
import pandas as pd
import altair as alt
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from pathlib import Path
import os
import toml
import html

# --- Theme Configuration ---
# Centralized UI colors to maintain consistency across custom HTML components.
UI_THEME = {
    "backgroundColor": "#050A10",
    "secondaryBackgroundColor": "#01153E",
    "primary": "#C89100",              
    "primary_border": "rgba(200, 145, 0, 0.3)",
    "primary_border_strong": "rgba(200, 145, 0, 0.4)",
    "primary_scrollbar": "rgba(200, 145, 0, 0.5)",
    "primary_hover": "rgba(200, 145, 0, 0.8)",
    "primary_highlight": "rgba(200, 145, 0, 0.15)",
    "secondary_accent": "#A4E0DC",     
    "text_main": "#FFFFFF",
    "text_dim": "#888888",
    "text_table": "#FAFAFA",
    "card_bg": "linear-gradient(145deg, #0A111A 0%, #050A10 100%)",
    "table_header_bg": "linear-gradient(180deg, #01153E 0%, #050A10 100%)",
    "shadow_sm": "0 4px 6px rgba(0,0,0,0.3)",
    "shadow_md": "0 8px 16px rgba(0,0,0,0.5)",
    "column_min_width": "420px"
}

PODIUM_RANKS = {
    0: { # Gold
        'bg': 'linear-gradient(145deg, #2E250D 0%, #161205 100%)', 'border': '#C89100', 'text': '#FDF5E6', 'shadow': '0 8px 16px rgba(200, 145, 0, 0.2)'
    },
    1: { # Silver
        'bg': 'linear-gradient(145deg, #232528 0%, #111214 100%)', 'border': '#C0C0C0', 'text': '#FDFDFD', 'shadow': '0 8px 16px rgba(192, 192, 192, 0.15)'
    },
    2: { # Bronze
        'bg': 'linear-gradient(145deg, #2E1B0D 0%, #170D06 100%)', 'border': '#CD7F32', 'text': '#FDF0E6', 'shadow': '0 8px 16px rgba(205, 127, 50, 0.15)'
    },
    'default': { # 4th and below
        'bg': 'linear-gradient(145deg, #262730 0%, #1A1B20 100%)', 'border': '#4A4A55', 'text': '#E0E0E0', 'shadow': '0 4px 8px rgba(0, 0, 0, 0.3)'
    }
}

# --- Global UI Injection ---
def inject_custom_css():
    """
    Injects global custom CSS to enforce UI theme rules across all pages.
    This prevents columns from squishing on small screens by forcing them to wrap.
    """
    st.markdown(f"""
    <style>
        /* Force the horizontal block (st.columns container) to wrap */
        [data-testid="stHorizontalBlock"] {{
            flex-wrap: wrap !important;
            row-gap: 1rem; /* Add gap for when they wrap to the next row */
        }}
        /* Target both legacy and modern Streamlit column IDs. Use min(100%, width) so it doesn't break on tiny mobile screens. */
        [data-testid="column"], [data-testid="stColumn"] {{
            min-width: calc(min(100%, {UI_THEME["column_min_width"]})) !important;
        }}
        /* Reduce the excessive default horizontal padding from Streamlit's wide layout */
        .block-container, [data-testid="block-container"] {{
            padding-left: 3.5rem !important;
            padding-right: 3.5rem !important;
        }}
        @media (max-width: 1200px) {{
            .block-container, [data-testid="block-container"] {{
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }}
        }}
        /* Make unselected pills pop against the sidebar background */
        [data-testid="stPills"] button[data-baseweb="button"]:not([aria-pressed="true"]) {{
            background-color: rgba(255, 255, 255, 0.08) !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
        }}
        /* Ensure the selected pill uses the rich gold with highly readable dark text */
        [data-testid="stPills"] button[data-baseweb="button"][aria-pressed="true"] {{
            color: {UI_THEME["backgroundColor"]} !important;
        }}
        /* Apply card styling to Streamlit charts to match the Event Feed */
        [data-testid="stVegaLiteChart"] {{
            background: {UI_THEME["card_bg"]} !important;
            border: 1px solid {UI_THEME["primary_border"]} !important;
            border-radius: 8px !important;
            box-shadow: {UI_THEME["shadow_sm"]} !important;
            box-sizing: border-box !important;
            max-width: 100% !important;
        }}
        /* Prevent the inner chart elements from overflowing the padded container */
        [data-testid="stVegaLiteChart"] > div,
        [data-testid="stVegaLiteChart"] iframe,
        [data-testid="stVegaLiteChart"] canvas {{
            max-width: 100% !important;
        }}
    </style>
    """, unsafe_allow_html=True)

def display_column_ruler():
    """
    Displays a temporary 3-column ruler that updates dynamically with the screen size.
    Useful for finding the perfect minimum column width.
    """
    st.markdown("### 📏 Temporary Column Ruler")
    st.info(f"Current Universal Minimum Width is set to: **{UI_THEME['column_min_width']}**")
    
    cols = st.columns(3)
    for i, col in enumerate(cols):
        with col:
            # Using an iframe component ensures it exactly fits the Streamlit column width
            st.iframe(f"""
                <div id="ruler" style="
                    background: linear-gradient(90deg, #C89100 0%, #A4E0DC 100%); 
                    color: #050A10; 
                    padding: 10px; 
                    text-align: center; 
                    font-weight: bold; 
                    border-radius: 8px; 
                    font-family: Arial, sans-serif; 
                    box-sizing: border-box; 
                    width: 100%;
                    height: 100%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
                ">
                    Loading Col {i+1}...
                </div>
                <script>
                    const ruler = document.getElementById('ruler');
                    const updateWidth = () => {{ ruler.innerHTML = 'Col {i+1} Width:<br><span style="font-size: 1.2em;">' + window.innerWidth + 'px</span>'; }};
                    window.addEventListener('resize', updateWidth);
                    updateWidth(); // Initial call
                </script>
            """, height=75)
    st.markdown("---")

# --- Helper to find the latest database file ---
def get_latest_db_path() -> Path | None:
    """
    Identifies the most recently modified database file from two possible paths.
    The ETL process alternates writing to two separate database files to prevent
    downtime. This function checks which one was updated last.
    """
        # Try OS environment variables first (Docker), then fallback to absolute monorepo paths (Local Dev)
    current_dir = Path(__file__).resolve().parent
    default_path_1 = current_dir.parent / "shared_data" / "databases" / "optimised_data.db"
    default_path_2 = current_dir.parent / "shared_data" / "databases" / "optimised_data_alt.db"

    db_path_1_str = os.environ.get("LOCAL_DB_PATH_1") or str(default_path_1)
    db_path_2_str = os.environ.get("LOCAL_DB_PATH_2") or str(default_path_2)

    paths_to_check = []
    if db_path_1_str:
        paths_to_check.append(Path(db_path_1_str))
    if db_path_2_str:
        paths_to_check.append(Path(db_path_2_str))

    latest_file = None
    latest_mtime = -1

    for path in paths_to_check:
        if path.exists():
            mtime = path.stat().st_mtime
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_file = path
    
    return latest_file

# --- Function to track local database file changes ---
@st.cache_data(ttl=10)
def get_local_db_state():
    """
    Gets the modification time and size of the most recent local database file.
    This acts as a cache key. When the file is replaced by the ETL,
    this function's output will change. This change is detected by Streamlit,
    triggering a cache invalidation for any data-loading functions that call this.
    This ensures that the Streamlit app always displays the latest data after an ETL run.
    """
    try:
        latest_db_path = get_latest_db_path()
        if latest_db_path:
            # Return a tuple of modification time and size to be robust.
            # This unique signature represents the file's current state.
            return (latest_db_path.stat().st_mtime, latest_db_path.stat().st_size)
    except (FileNotFoundError, Exception):
        # If file is temporarily unavailable during ETL write, return None.
        return None
    return None

# --- Connection Management ---

def init_connection():
    """
    Initializes a new, non-cached connection to the local SQLite database.
    This is intentionally not cached with @st.cache_resource to prevent a
    persistent file lock, which would block the ETL process from replacing the database file.
    A new connection engine is created for each query and then disposed of.
    """
    try:
        local_db_path = get_latest_db_path()

        if not local_db_path:
            st.error("No database file found. Please ensure LOCAL_DB_PATH_1 and LOCAL_DB_PATH_2 environment variables are set and at least one file exists.")
            return None

        if not local_db_path.exists():
            st.error(f"Latest database file not found at the container path: {local_db_path}")
            return None

        # Return a new engine every time to avoid locking the file.
        return create_engine(f"sqlite:///{local_db_path.resolve()}")
    except Exception as e:
        st.error(f"Failed to initialize SQLite connection: {e}")
        return None

@st.cache_data(ttl=300)
def load_table(table_name: str) -> pd.DataFrame:
    """
    Loads an entire pre-aggregated table from the local SQLite database.
    This function's cache is automatically invalidated
    when the database file is updated by the ETL process.
    """
    # By calling this function, we make st.cache_data aware of the db file's state.
    # When the file changes, the output of get_local_db_state() changes, and
    # Streamlit automatically invalidates the cache for this function.
    get_local_db_state()
    
    conn = init_connection()
    if conn is None: 
        st.error("Database connection is not available.")
        return pd.DataFrame()

    try:
        # Using the connection object directly ensures it's properly closed
        # after the read operation, further helping to prevent file locks.
        with conn.connect() as connection:
            df = pd.read_sql_table(table_name, connection)

        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce', utc=True)
        return df
    except Exception as e:
        if "no such table" in str(e).lower():
            st.warning(f"Table '{table_name}' not found. The ETL might not have run for it yet.")
        else:
            st.error(f"Error loading table '{table_name}': {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def get_last_updated_timestamp() -> datetime:
    """Fetches the last ETL run timestamp from the metadata table."""
    df_meta = load_table('run_metadata')
    if not df_meta.empty and 'last_updated_utc' in df_meta.columns:
        # Handle potential empty dataframe after an ETL run before data is populated
        if df_meta['last_updated_utc'].iloc[0] is not None:
            return pd.to_datetime(df_meta['last_updated_utc'].iloc[0], utc=True)
    return None

@st.cache_data(ttl=300)
def load_dashboard_config() -> dict:
    """
    Loads the dashboard configuration table.
    """
    df = load_table('dashboard_config')
    if df.empty:
        return {}
    return pd.Series(df.value.values, index=df.key).to_dict()

def get_time_period_options(dashboard_config: dict) -> dict:
    """
    Generates the list of time period options for the sidebar, using
    the static labels generated by the ETL process.
    """
    today_label = dashboard_config.get('label_today', 'Today')
    last_7_label = dashboard_config.get('label_last_7_days', 'Last 7 Days')
    last_30_label = dashboard_config.get('label_last_30_days', 'Last 30 Days')
    this_year_label = dashboard_config.get('label_this_year', 'This Year')

    options = {
        "All Time": "All_Time",
        this_year_label: "This_Year",
        last_30_label: "Last_30_Days",
        last_7_label: "Last_7_Days",
        today_label: "Today"
    }
    return options

def display_leaderboard_podium(
    df: pd.DataFrame,
    player_col: str,
    count_col: str,
    *,
    podium_messages: dict | list = None,
    podium_size: int = 3,
    player_col_header: str = "Player",
    count_col_header: str = "Count",
    show_header_count: bool = True,
    format_count_as_gp: bool = False,
    secondary_count_col: str = None
):
    """
    Displays a leaderboard with a "podium" for top players and a table for the rest.

    Args:
        df (pd.DataFrame): The dataframe containing leaderboard data.
        player_col (str): The name of the column with player names.
        count_col (str): The name of the column with the count/score.
        podium_messages (dict | list, optional): A dict containing rank lists (e.g., {'rank_1': ['msg']}) OR a flat list of strings.
                                                 Should contain {player} and {count} or {value}. Defaults to None.
        podium_size (int, optional): Number of players to show on the podium. Defaults to 3.
        player_col_header (str, optional): Display name for the player column in the table. Defaults to "Player".
        count_col_header (str, optional): Display name for the count column in the table. Defaults to "Count".
        show_header_count (bool, optional): If False, hides the count from the header badge. Defaults to True.
        format_count_as_gp (bool, optional): If True, formats the count as a GP string. Defaults to False.
        secondary_count_col (str, optional): If provided, replaces {count} with this column's value instead of count_col. Defaults to None.
    """
    if df.empty or count_col not in df.columns:
        st.info("No data available for this leaderboard.")
        return

    df_filtered = df[df[count_col] > 0].sort_values(by=count_col, ascending=False).reset_index(drop=True)

    if df_filtered.empty:
        st.info("No qualifying players for this period.")
        return

    # --- Podium Display (Top N players) ---
    podium_df = df_filtered.head(podium_size)
    font_sizes = [28, 24, 20]  # Font sizes for 1st, 2nd, 3rd
    widths = ["100%", "95%", "90%"] # Relative widths to maintain pyramid on narrow screens
    max_widths = ["800px", "700px", "600px"] # Wider widths for 1st, 2nd, 3rd to create pyramid
    emojis = ["🥇", "🥈", "🥉"]

    # Create a local copy of flat lists so we don't mutate the cached TOML data
    local_flat_messages = podium_messages.copy() if isinstance(podium_messages, list) else []

    # Pre-calculate cross-rank references (e.g., {rank_1}) with appropriate colors
    cross_rank_players = {}
    for rank_idx in range(podium_size):
        if rank_idx < len(podium_df):
            p_safe = str(podium_df.iloc[rank_idx][player_col]).replace('<', '&lt;').replace('>', '&gt;')
            p_color = PODIUM_RANKS.get(rank_idx, PODIUM_RANKS['default'])['border']
            cross_rank_players[f"{{rank_{rank_idx+1}}}"] = f"<span style='color: {p_color}; font-weight: bold;'>{p_safe}</span>"
        else:
            cross_rank_players[f"{{rank_{rank_idx+1}}}"] = "<span style='color: #888888; font-style: italic;'>Nobody</span>"

    for i, row in podium_df.iterrows():
        player_safe = str(row[player_col]).replace('<', '&lt;').replace('>', '&gt;')
        count = row[count_col]
        
        if format_count_as_gp:
            count_str = format_gp(count)
        else:
            count_str = f"{int(count):,}" if pd.notna(count) else "0"
            
        secondary_str = count_str
        if secondary_count_col and secondary_count_col in df.columns:
            sec_val = row[secondary_count_col]
            secondary_str = f"{int(sec_val):,}" if pd.notna(sec_val) else "0"
            
        emoji = emojis[i] if i < len(emojis) else "🔹"
        font_size = font_sizes[i] if i < len(font_sizes) else font_sizes[-1]
        width_val = widths[i] if i < len(widths) else widths[-1]
        max_width = max_widths[i] if i < len(max_widths) else max_widths[-1]
        colors = PODIUM_RANKS.get(i, PODIUM_RANKS['default'])

        # Player and rank header
        if show_header_count:
            header_html = f"""<span style="font-size: {font_size}px; font-weight: bold; letter-spacing: 1px;">{emoji} {player_safe} - {count_str}</span>"""
        else:
            header_html = f"""<span style="font-size: {font_size}px; font-weight: bold; letter-spacing: 1px;">{emoji} {player_safe}</span>"""

        # Custom message text
        message_text_html = ""
        if podium_messages:
            msg_template = None
            if isinstance(podium_messages, dict):
                rank_key = f"rank_{i+1}"
                msgs_for_rank = podium_messages.get(rank_key, [])
                if msgs_for_rank:
                    msg_template = random.choice(msgs_for_rank)
            elif isinstance(podium_messages, list) and local_flat_messages:
                msg_template = random.choice(local_flat_messages)
                local_flat_messages.remove(msg_template)
                
            if msg_template:
                clean_template = msg_template.replace('**', '')
                message_text = clean_template.replace("{player}", f"<span style='color: {colors['border']}; font-weight: bold;'>{player_safe}</span>") \
                                             .replace("{value}", f"<span style='color: {colors['border']}; font-weight: bold;'>{count_str}</span>") \
                                             .replace("{count}", f"<span style='color: {colors['border']}; font-weight: bold;'>{secondary_str}</span>")
                                         
            # Apply cross-rank replacements
            for rank_tag, rank_html in cross_rank_players.items():
                message_text = message_text.replace(rank_tag, rank_html)
                
                message_text_html = f"""<hr style="border-top: 1px solid rgba(255,255,255,0.1); margin: 12px 0;">
                                        <div style="text-align: center; font-size: 0.95em; font-style: italic;">{message_text}</div>"""

        # Combine into a single HTML block
        st.markdown(f"""
        <div style="width: {width_val}; max-width: {max_width}; margin: 0 auto 20px auto; text-align: center; background: {colors['bg']}; border: 2px solid {colors['border']}; color: {colors['text']}; padding: 15px 20px; border-radius: 12px; box-shadow: {colors['shadow']};">
            {header_html}
            {message_text_html}
        </div>
        """, unsafe_allow_html=True)

    # --- Table Display (for the rest) ---
    if len(df_filtered) > podium_size:
        df_table = df_filtered.copy()
        df_table.insert(0, 'Rank', range(1, len(df_table) + 1))
        
        table_html = (
            '<style>\n'
            '.podium-table-wrapper { display: flex; justify-content: center; width: 100%; margin-top: 10px; margin-bottom: 20px; }\n'
            f'.podium-table-scroll {{ box-sizing: border-box; width: 85%; max-width: 550px; max-height: 420px; overflow-y: auto; border-radius: 12px; border: 1px solid {UI_THEME["primary_border"]}; background: {UI_THEME["card_bg"]}; box-shadow: {UI_THEME["shadow_md"]}; }}\n'
            '.podium-table-scroll::-webkit-scrollbar { width: 6px; }\n'
            '.podium-table-scroll::-webkit-scrollbar-track { background: rgba(0, 0, 0, 0.1); }\n'
            f'.podium-table-scroll::-webkit-scrollbar-thumb {{ background: {UI_THEME["primary_scrollbar"]}; border-radius: 3px; }}\n'
            f'.podium-table-scroll::-webkit-scrollbar-thumb:hover {{ background: {UI_THEME["primary_hover"]}; }}\n'
            f'.podium-table {{ width: 100%; border-collapse: collapse; color: {UI_THEME["text_table"]}; font-size: 0.95em; }}\n'
            '.podium-table th, .podium-table td { padding: 12px 15px; text-align: left; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }\n'
            f'.podium-table th {{ position: sticky; top: 0; background: {UI_THEME["table_header_bg"]}; color: {UI_THEME["primary"]}; font-weight: bold; text-transform: uppercase; font-size: 0.85em; letter-spacing: 1px; z-index: 1; border-bottom: 2px solid {UI_THEME["primary_border_strong"]}; }}\n'
            '.podium-table tr:last-child td { border-bottom: none; }\n'
            f'.podium-table tr:hover {{ background-color: {UI_THEME["primary_highlight"]}; }}\n'
            f'.rank-col {{ width: 10%; min-width: 60px; text-align: center !important; font-weight: bold; color: {UI_THEME["primary"]}; }}\n'
            '.player-col { width: 70%; font-weight: 500; letter-spacing: 0.5px; }\n'
            f'.count-col {{ width: 20%; min-width: 80px; text-align: right !important; font-weight: bold; color: {UI_THEME["secondary_accent"]}; }}\n'
            '</style>\n'
            '<div class="podium-table-wrapper">\n'
            '<div class="podium-table-scroll">\n'
            '<table class="podium-table">\n'
            '<thead>\n'
            f'<tr><th class="rank-col">Rank</th><th class="player-col">{player_col_header}</th><th class="count-col">{count_col_header}</th></tr>\n'
            '</thead>\n'
            '<tbody>\n'
        )
        
        for _, row in df_table.iterrows():
            player_safe = str(row[player_col]).replace('<', '&lt;').replace('>', '&gt;')
            rank = int(row['Rank'])
            count = row[count_col]
            
            if format_count_as_gp:
                table_count_str = format_gp(count)
            else:
                table_count_str = f"{int(count):,}" if pd.notna(count) else "0"
            
            table_html += f'<tr><td class="rank-col">#{rank}</td><td class="player-col">{player_safe}</td><td class="count-col">{table_count_str}</td></tr>\n'
            
        table_html += '</tbody>\n</table>\n</div>\n</div>'
        
        st.markdown(table_html, unsafe_allow_html=True)

def format_gp(value):
    """
    Formats a numeric value into a human-readable GP string mirroring OSRS thresholds.

    """
    if pd.isna(value) or value is None:
        return "0 gp"
        
    try:
        val = float(value)
    except (ValueError, TypeError):
        return "0 gp"

    abs_val = abs(val)
    if abs_val >= 10_000_000_000:
        return f"{int(val / 1_000_000_000)}b gp"
    elif abs_val >= 10_000_000:
        return f"{int(val / 1_000_000)}m gp"
    elif abs_val >= 10_000:
        return f"{int(val / 1_000)}k gp"
    else:
        return f"{int(val):,} gp"

def make_metric_card(title: str, value: str) -> str:
    """Generates a styled HTML card for a single metric."""
    return f"""
    <div style="background: {UI_THEME['card_bg']}; border: 1px solid {UI_THEME['primary_border']}; border-radius: 8px; padding: 15px; margin-bottom: 0.5rem; box-shadow: {UI_THEME['shadow_sm']}; height: 100%; display: flex; flex-direction: column; justify-content: center;">
        <div style="color: {UI_THEME['text_dim']}; font-size: 0.9em; font-weight: bold; text-transform: uppercase; margin-bottom: 5px;">{title}</div>
        <div style="color: {UI_THEME['primary']}; font-size: 1.8em; font-weight: bold;">{value}</div>
    </div>
    """

def display_summary_ribbon(metric1_label: str, metric1_value: str,
                           metric2_label: str, metric2_value: str,
                           list_title: str, top_df: pd.DataFrame,
                           player_col: str, val_col: str,
                           item_col: str = None, is_gp: bool = False,
                           limit: int = 3):
    """
    Displays a responsive 3-column summary ribbon.
    Left and Middle columns are single metric cards.
    Right column is a compact Top N list.
    """
    m1, m2, m3 = st.columns([1, 1, 1.5])
    
    with m1:
        st.markdown(make_metric_card(metric1_label, metric1_value), unsafe_allow_html=True)
    with m2:
        st.markdown(make_metric_card(metric2_label, metric2_value), unsafe_allow_html=True)
    with m3:
        list_items = ""
        if not top_df.empty:
            top_n = top_df.nlargest(limit, val_col)
            emojis = ["🥇", "🥈", "🥉"]
            for i, row in enumerate(top_n.itertuples()):
                player_name = html.escape(str(getattr(row, player_col)))
                raw_val = getattr(row, val_col)
                
                if is_gp:
                    val_str = format_gp(raw_val)
                else:
                    try:
                        val_str = f"{int(float(raw_val)):,}"
                    except (ValueError, TypeError):
                        val_str = html.escape(str(raw_val))
                        
                emoji = emojis[i] if i < len(emojis) else "🔹"
                
                item_span = ""
                if item_col:
                    item_name = html.escape(str(getattr(row, item_col)))
                    item_span = f"<span style='color: {UI_THEME['text_main']};'>{item_name}</span> "
                    
                list_items += f"<div style='margin-bottom: 8px; font-size: 0.95em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'>{emoji} {item_span}<span style='color: {UI_THEME['secondary_accent']}; font-weight: bold;'>{val_str}</span> <span style='color: {UI_THEME['text_dim']}; font-size: 0.85em; margin: 0 4px;'>by</span> <span style='color: {UI_THEME['primary']}; font-weight: bold;'>{player_name}</span></div>"
        else:
            list_items = f"<div style='color: {UI_THEME['text_dim']};'>No data recorded for this period.</div>"
            
        st.markdown(f"""<div style="background: {UI_THEME['card_bg']}; border: 1px solid {UI_THEME['primary_border']}; border-radius: 8px; padding: 15px; margin-bottom: 0.5rem; box-shadow: {UI_THEME['shadow_sm']}; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="color: {UI_THEME['text_dim']}; font-size: 0.9em; font-weight: bold; text-transform: uppercase; margin-bottom: 10px;">{list_title}</div>{list_items}</div>""", unsafe_allow_html=True)

def display_page_header(title: str, description: str):
    """
    Displays a styled hero banner for the top of dashboard pages, 
    replacing standard st.title() and st.markdown() descriptions.
    """
    safe_title = html.escape(title)
    
    header_html = f"""
    <div style="background: {UI_THEME['secondaryBackgroundColor']}; 
                border: 1px solid {UI_THEME['primary_border']}; 
                border-radius: 8px; 
                padding: 1.5rem; 
                margin-bottom: 2rem; 
                box-shadow: {UI_THEME['shadow_md']};">
        <h1 style="margin: 0 0 0.5rem 0; padding: 0; color: {UI_THEME['text_main']}; font-size: 2.2rem; font-weight: bold; letter-spacing: 0.5px;">{safe_title}</h1>
        <p style="margin: 0; color: {UI_THEME['text_dim']}; font-size: 1.1rem; line-height: 1.4;">{description}</p>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

def get_chart_data_for_period(df_timeseries, selected_period_label, dashboard_config, period_options_map, run_time, value_to_chart='Value'):
    """
    Filters the timeseries data for the selected period and prepares it for charting.
    Can chart 'Value' or 'Count'.
    """
    period_suffix = period_options_map.get(selected_period_label)
    cumulative_col = 'Cumulative_Value' if value_to_chart == 'Value' else 'Cumulative_Count'

    start_date, end_date, target_freq = None, None, None

    if period_suffix == 'Today':
        target_freq = '6H'
        start_date = run_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = run_time
    elif period_suffix == 'Last_7_Days':
        target_freq = 'D'
        start_date = (run_time - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = run_time
    elif period_suffix == 'Last_30_Days':
        target_freq = 'D'
        start_date = (run_time - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = run_time
    elif period_suffix == 'This_Year':
        target_freq = 'W'
        start_date = run_time.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = run_time
    else: # All-Time
        target_freq = 'W'

    if not target_freq: return pd.DataFrame()

    # Attempt to filter by the ideal frequency, but fall back if it's not available.
    # This handles cases where e.g. '6H' data is desired but only 'D' data exists.
    available_frequencies = df_timeseries['Frequency'].unique()
    
    if target_freq not in available_frequencies:
        if target_freq == '6H' and 'D' in available_frequencies:
            target_freq = 'D' # Fallback from 6-hourly to daily

    df_filtered_by_freq = df_timeseries[df_timeseries['Frequency'] == target_freq].copy()    
    if df_filtered_by_freq.empty:
        return pd.DataFrame()
        
    df_filtered_by_freq['Date'] = pd.to_datetime(df_filtered_by_freq['Date'], utc=True)
    df_filtered_by_freq.sort_values('Date', inplace=True)

    if period_suffix == 'All_Time':
        df_all_time = df_filtered_by_freq.copy()
        df_all_time['Value'] = df_all_time[cumulative_col]
        
        if not df_all_time.empty:
            first_date = df_all_time.iloc[0]['Date']
            zero_date = first_date - timedelta(days=7)
            zero_row = pd.DataFrame([{'Date': zero_date, 'Value': 0}])
            return pd.concat([zero_row, df_all_time[['Date', 'Value']]], ignore_index=True)
        return df_all_time

    df_before_period = df_filtered_by_freq[df_filtered_by_freq['Date'] < start_date]
    start_value = df_before_period.iloc[-1][cumulative_col] if not df_before_period.empty else 0
    
    # For most periods, the end_date is an inclusive boundary (e.g., run_time for Custom_Days/YTD,
    # or a manufactured point at the start of the next period for Prev_Week/Prev_Month).
    # We use '<=' to ensure this last point is included in the chart data.
    
    df_in_period = df_filtered_by_freq[(df_filtered_by_freq['Date'] >= start_date) & (df_filtered_by_freq['Date'] <= end_date)].copy()
    
    df_in_period['Value'] = df_in_period[cumulative_col] - start_value
    
    zero_row = pd.DataFrame([{'Date': start_date, 'Value': 0}])
    
    return pd.concat([zero_row, df_in_period[['Date', 'Value']]], ignore_index=True)

def display_event_feed(
    df: pd.DataFrame,
    run_time: datetime,
    player_col: str = 'Username',
    item_col: str = 'Item_Name',
    val_col: str = 'Item_Value',
    date_col: str = 'Timestamp',
    limit: int = 150,
    height: str = "600px"
):
    """Displays a scrollable HTML event feed of recent activities."""
    if df.empty:
        st.info("No recent events.")
        return

    now_utc = datetime.now(timezone.utc)
    feed_html = f'<div style="height: {height}; overflow-y: auto; padding-right: 10px;">'
    for _, row in df.head(limit).iterrows():
        # Escape HTML characters to prevent rendering breaks
        player = str(row.get(player_col, 'Unknown')).replace('<', '&lt;').replace('>', '&gt;')
        item = str(row.get(item_col, 'Unknown')).replace('<', '&lt;').replace('>', '&gt;')
        val_raw = row.get(val_col, 0)
        
        if pd.api.types.is_numeric_dtype(type(val_raw)) or isinstance(val_raw, (int, float)):
            val_str = format_gp(val_raw)
        else:
            val_str = str(val_raw).replace('<', '&lt;').replace('>', '&gt;')
            
        event_time = row.get(date_col)
        time_ago = "Unknown"
        if pd.notna(event_time):
            delta = now_utc - event_time
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0: time_ago = "Just now"
            elif total_seconds >= 86400: time_ago = f"{total_seconds // 86400}d ago"
            elif total_seconds >= 3600: time_ago = f"{total_seconds // 3600}h ago"
            else: time_ago = f"{max(1, total_seconds // 60)}m ago"
            
        feed_html += (
            f'<div style="background: {UI_THEME["card_bg"]}; border: 1px solid {UI_THEME["primary_border"]}; border-radius: 8px; padding: 12px; margin-bottom: 12px; box-shadow: {UI_THEME["shadow_sm"]};">'
            f'<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">'
            f'<span style="color: {UI_THEME["primary"]}; font-weight: bold; font-size: 0.95em;">{player}</span>'
            f'<span style="color: {UI_THEME["text_dim"]}; font-size: 0.75em;">{time_ago}</span>'
            f'</div>'
            f'<div style="display: flex; justify-content: space-between;">'
            f'<span style="color: {UI_THEME["text_main"]}; font-size: 0.85em;">{item}</span>'
            f'<span style="color: {UI_THEME["secondary_accent"]}; font-weight: bold; font-size: 0.85em;">{val_str}</span>'
            f'</div>'
            f'</div>'
        )
    feed_html += "</div>"
    st.markdown(feed_html, unsafe_allow_html=True)

def sidebar_time_filter(run_time: datetime, min_date: datetime = None) -> tuple[datetime, datetime]:
    """
    Displays a standardized time period selector in the sidebar using pills and a date picker.
    Returns the selected start and end dates as timezone-aware datetimes.
    """
    st.sidebar.markdown("### 📅 Time Period")
    
    time_preset = st.sidebar.pills(
        "Quick Select",
        options=["Today", "Last 7 Days", "Last 30 Days", "This Year", "All Time"],
        default="Last 30 Days",
        label_visibility="collapsed"
    )
    
    end_date = run_time
    if time_preset == "Today":
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_preset == "Last 7 Days":
        start_date = end_date - timedelta(days=7)
    elif time_preset == "Last 30 Days":
        start_date = end_date - timedelta(days=30)
    elif time_preset == "This Year":
        start_date = end_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else: # All Time
        start_date = min_date if min_date else (end_date - timedelta(days=365))
        
    custom_dates = st.sidebar.date_input(
        "Custom Range",
        value=(start_date.date(), end_date.date()),
        max_value=end_date.date()
    )
    if len(custom_dates) == 2:
        start_date = pd.to_datetime(custom_dates[0]).replace(tzinfo=timezone.utc)
        # Make the end date inclusive of the entire day
        end_date = pd.to_datetime(custom_dates[1]).replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)
        
    st.sidebar.markdown("---")
    return start_date, end_date

def sidebar_summary_time_filter(dashboard_config: dict, key: str = "summary_time_period") -> tuple[str, str]:
    """
    Displays a standardized time period selector in the sidebar using pills for pre-aggregated summary tables.
    Returns the selected period suffix (e.g., 'YTD', 'All_Time') and the display label.
    """
    period_options_map = get_time_period_options(dashboard_config)
    st.sidebar.markdown("### 📅 Time Period")
    
    ordered_suffixes = ['Today', 'Last_7_Days', 'Last_30_Days', 'This_Year', 'All_Time']
    suffix_to_label_map = {v: k for k, v in period_options_map.items()}
    ordered_labels = [suffix_to_label_map[suffix] for suffix in ordered_suffixes if suffix in suffix_to_label_map]

    default_label = suffix_to_label_map.get('Last_30_Days', ordered_labels[-1])

    selected_period_label = st.sidebar.pills(
        "Quick Select", 
        options=ordered_labels,
        default=default_label,
        key=key, 
        label_visibility="collapsed"
    )
    if not selected_period_label:
        selected_period_label = default_label
        
    period_suffix = period_options_map.get(selected_period_label)
    
    st.sidebar.markdown("---")
    return period_suffix, selected_period_label

def display_dynamic_timeseries(df: pd.DataFrame, date_col: str, value_col: str, start_date: datetime, end_date: datetime, title: str, is_gp: bool = False):
    """
    Generates and displays a styled timeseries line chart using Altair.
    Ensures the timeline starts exactly at start_date from 0, and scales values for readability.
    """
    # Dynamically select resolution based on the time range selected
    delta_days = (end_date - start_date).days
    if delta_days <= 2:
        freq = 'h' # Hourly for "Today"
        offset = pd.Timedelta(minutes=59, seconds=59)
    elif delta_days <= 14:
        freq = '6h' # 6-Hourly for "Last 7 Days"
        offset = pd.Timedelta(hours=5, minutes=59, seconds=59)
    else:
        freq = 'D' # Daily for everything else
        offset = pd.Timedelta(hours=23, minutes=59, seconds=59)
        
    start_dt = pd.to_datetime(start_date).floor(freq)
    end_dt = pd.to_datetime(end_date).ceil(freq)
    idx = pd.date_range(start_dt, end_dt, freq=freq)
    
    if df.empty:
        cumulative_sums = pd.DataFrame({'Date': idx + offset, 'Value': 0})
        zero_row = pd.DataFrame([{'Date': start_dt, 'Value': 0}])
        cumulative_sums = pd.concat([zero_row, cumulative_sums], ignore_index=True)
        y_label = 'Value'
    else:
        df_chart = df[[date_col, value_col]].copy()
        df_chart['Date'] = pd.to_datetime(df_chart[date_col]).dt.floor(freq)
        
        grouped_sums = df_chart.groupby('Date')[value_col].sum()
        grouped_sums = grouped_sums.reindex(idx, fill_value=0)
        
        cumulative_sums = grouped_sums.cumsum().reset_index()
        cumulative_sums.columns = ['Date', 'Value']
        
        # Shift the aggregated points to the very end of their respective periods
        cumulative_sums['Date'] = cumulative_sums['Date'] + offset
        
        # Anchor the chart to exactly 0 at the start of the time period (00:00:00)
        zero_row = pd.DataFrame([{'Date': start_dt, 'Value': 0}])
        cumulative_sums = pd.concat([zero_row, cumulative_sums], ignore_index=True)
        
    y_label = 'Value'
    if is_gp:
        max_val = cumulative_sums['Value'].max()
        if max_val >= 10_000_000_000:
            cumulative_sums['Value'] = cumulative_sums['Value'] / 1_000_000_000
            y_label = 'GP (Billions)'
        elif max_val >= 10_000_000:
            cumulative_sums['Value'] = cumulative_sums['Value'] / 1_000_000
            y_label = 'GP (Millions)'
        else:
            y_label = 'GP'
    
    cumulative_sums.rename(columns={'Value': y_label}, inplace=True)
    
    # Plot using Altair to cleanly embed the title and style the axes
    chart = alt.Chart(cumulative_sums).mark_line(
        color=UI_THEME['primary'],
        strokeWidth=3,
        interpolate='monotone' # This mathematically smooths the line to remove sharp jagged edges!
    ).encode(
        x=alt.X('Date:T', title='', axis=alt.Axis(
            grid=False, 
            labelColor=UI_THEME['text_dim'], 
            tickColor=UI_THEME['primary_border'],
            domainColor=UI_THEME['primary_border'],
            labelAngle=-45,
            labelOverlap=True
        )),
        y=alt.Y(f'{y_label}:Q', title=y_label, axis=alt.Axis(
            gridColor='rgba(255,255,255,0.05)', 
            labelColor=UI_THEME['text_dim'], 
            titleColor=UI_THEME['secondary_accent'], 
            domainColor='transparent', 
            tickColor='transparent',
            tickCount=5
        )),
        tooltip=[
            alt.Tooltip('Date:T', title='Date', format='%d %b %Y %H:%M'), 
            alt.Tooltip(f'{y_label}:Q', title=y_label, format=',.1f' if is_gp else ',.0f')
        ]
    ).properties(
        title=alt.TitleParams(
            text=title,
            color=UI_THEME['primary'],
            fontSize=20,
            fontWeight='bold',
            anchor='middle',
            offset=20
        ),
        height=350
    ).configure_view(strokeWidth=0).configure(background='transparent', padding={"left": 15, "top": 25, "right": 25, "bottom": 15})
    
    st.altair_chart(chart, theme=None, width="stretch")
