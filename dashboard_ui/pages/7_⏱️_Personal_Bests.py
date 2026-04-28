# dashboard/pages/7_⏱️_Personal_Bests.py

import streamlit as st
import pandas as pd
import random
import Streamlit_utils
import toml
from pathlib import Path
import json
import html

# --- Page Configuration ---
st.set_page_config(page_title="Personal Bests", page_icon="⏱️", layout="wide")
Streamlit_utils.inject_custom_css()


# --- Functions ---
@st.cache_data(ttl=300)
def load_texts():
    """Loads text snippets from the TOML file."""
    try:
        # Adjust the path to correctly locate dashboard_texts.toml in the parent directory
        current_script_directory = Path(__file__).resolve().parent
        return toml.load(current_script_directory.parent / 'dashboard_texts.toml')
    except Exception as e:
        st.error(f"Failed to load dashboard_texts.toml: {e}")
        return {}

def display_hall_of_fame(df_pbs, texts):
    """Calculates and displays the players with the most records from the provided dataframe."""
    st.header("🏆 Biggest Sweats")
    page_texts = texts.get('personal_bests', {})
    
    df_holder_counts = create_record_holder_table(df_pbs)
    
    if df_holder_counts.empty:
        st.info("No records found to determine the biggest sweats.")
        return
        
    Streamlit_utils.display_leaderboard_podium(
        df=df_holder_counts,
        player_col="Record Holder",
        count_col="Records Held",
        podium_messages=page_texts.get('sweatiest_players_messages', {}),
        podium_size=3,
        player_col_header="Player",
        count_col_header="Records Held"
    )

def create_record_holder_table(df_pbs):
    """Creates a DataFrame of all record holders and their total record count from the provided dataframe."""
    if df_pbs.empty or 'Holder' not in df_pbs.columns:
        return pd.DataFrame()
        
    all_holders = df_pbs['Holder'].dropna().str.split(',').explode().str.strip()
    # MODIFICATION: Filter out empty strings so they are not counted as a record holder.
    all_holders = all_holders[all_holders != '']
    
    holder_counts = all_holders.value_counts().reset_index()
    holder_counts.columns = ['Record Holder', 'Records Held']
    return holder_counts.sort_values(by='Records Held', ascending=False)

def display_pb_card(task, holder, time, date, label="Time"):
    """Returns the HTML for a single Personal Best record card."""
    
    unclaimed = time in ["0:00", "0", "0.0", ""] or not holder
    card_class = "pb-card-unclaimed" if unclaimed else "pb-card"
    
    safe_count = ""
    
    if unclaimed:
        holder_html = '<div class="holder-unclaimed">👤 Unclaimed</div>'
    else:
        # Split comma-separated string into a list
        players = [p.strip() for p in str(holder).split(',') if p.strip()]
        
        safe_count = f"{len(players)} Holders" if len(players) != 1 else "1 Holder"
        
        # Partition into two balanced rows based on string length to ensure equal widths
        row1, row2 = [], []
        len1, len2 = 0, 0
        for p in players:
            if len1 <= len2:
                row1.append(p)
                len1 += len(p)
            else:
                row2.append(p)
                len2 += len(p)
                
        def make_pills(row):
            return "".join([f'<span class="holder-pill">{html.escape(p)}</span>' for p in row])

        if len(players) == 1:
            pill_html = f'<span class="holder-pill-single">{html.escape(players[0])}</span>'
            holder_html = f'<div class="holder-container-col"><div class="holder-track-flex">{pill_html}</div></div>'
        elif len(players) <= 2:
            pill_html = make_pills(players)
            holder_html = f'<div class="holder-container-col"><div class="holder-track-flex">{pill_html}</div></div>'
        elif len(players) <= 4:
            r1_html = make_pills(row1)
            r2_html = make_pills(row2)
            holder_html = (
                f'<div class="holder-container-col">'
                f'<div class="holder-track-flex">{r1_html}</div>'
                f'<div class="holder-track-flex">{r2_html}</div>'
                f'</div>'
            )
        else:
            r1_html = make_pills(row1)
            r2_html = make_pills(row2)
            
            # Combine rows into a single block to ensure identical scrolling speed
            def make_block(aria_hidden=False):
                aria = ' aria-hidden="true"' if aria_hidden else ''
                return (
                    f'<div class="marquee-block"{aria}>'
                    f'<div class="holder-track-flex">{r1_html}</div>'
                    f'<div class="holder-track-flex">{r2_html}</div>'
                    f'</div>'
                )
            
            holder_html = (
                f'<div class="holder-container-marquee">'
                f'<div class="marquee-row" style="animation-duration: 20s;">{make_block()}{make_block(True)}</div>'
                f'</div>'
            )

    # Format date string
    date_display = ""
    if pd.notna(date):
        try:
            date_display = f"📅 {pd.to_datetime(date).strftime('%d %b %Y')}"
        except (ValueError, TypeError):
            date_display = "" # Keep it blank if date is invalid

    # Escape content to prevent HTML injection or rendering errors
    safe_task = html.escape(task)
    safe_time = html.escape(time.strip() if isinstance(time, str) else str(time))
    safe_label = html.escape(str(label))

    # Return the HTML string as a single block to avoid introducing whitespace/indentation
    # issues that can confuse Streamlit's HTML renderer.
    return (
        f'<div class="{card_class}">'
        f'<h4>{safe_task}</h4>'
        f'<div class="time-container">'
        f'<div class="metric-label count-label">{safe_count}</div>'
        f'<div class="time">{safe_time}</div>'
        f'<div class="metric-label">{safe_label}</div>'
        f'</div>'
        f'{holder_html}'
        f'<div class="date">{date_display}</div>'
        f'</div>'
    )


# --- Main Page Logic ---
Streamlit_utils.display_page_header(
    title="⏱️ Personal Bests",
    description="This board shows the fastest records achieved by clan members. Got a missing record? Contact an admin to have it added!"
)

# --- Custom CSS for PB Cards ---
ui_theme = Streamlit_utils.UI_THEME

st.markdown(f"""
<style>
    /* Grid container for responsive card layout */
    .card-container {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
        gap: 1rem;
        padding-bottom: 1rem;
    }}
    .pb-card {{
        background: {ui_theme['card_bg']};
        border: 1px solid {ui_theme['primary_border_strong']};
        border-radius: 10px;
        padding: 1rem;
        box-shadow: {ui_theme['shadow_md']};
        transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
        height: 250px; 
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-width: 340px;
        max-width: 450px;
    }}
    .pb-card:hover {{
        transform: translateY(-5px);
        box-shadow: 0 12px 24px rgba(0,0,0,0.6);
        border-color: {ui_theme['primary']};
    }}
    .pb-card-unclaimed {{
        background: {ui_theme['backgroundColor']};
        border: 1px dashed {ui_theme['primary_border']};
        border-radius: 10px;
        padding: 1rem;
        opacity: 0.6;
        height: 250px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-width: 340px;
        max-width: 450px;
    }}
    .pb-card h4 {{
        margin: 0 0 0.5rem 0;
        font-size: 1.15em;
        color: {ui_theme['text_main']};
        font-weight: bold;
        text-align: center;
        flex-grow: 1;
        margin-bottom: -1.5rem;
    }}
    .pb-card .time-container {{
        display: grid;
        grid-template-columns: 1fr max-content 1fr;
        align-items: baseline;
        margin-bottom: 0.2rem;
    }}
    .pb-card .time {{
        font-size: 2em;
        font-weight: bold;
        color: {ui_theme['primary']};
        text-align: center;
    }}
    .pb-card-unclaimed .time {{
        color: {ui_theme['text_dim']};
    }}
    .pb-card .metric-label {{
        font-size: 0.85em;
        color: {ui_theme['secondary_accent']};
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-left: 0.6rem;
        text-align: left;
    }}
    .pb-card-unclaimed .metric-label {{
        color: {ui_theme['text_dim']};
    }}
    .pb-card .count-label {{
        text-align: right;
        margin-left: 0;
        margin-right: 0.6rem;
        color: {ui_theme['text_dim']};
        align-self: start;
        margin-top: 0.6rem;
    }}
    .pb-card .date {{
        font-size: 1.15em;
        color: {ui_theme['text_main']};
        text-align: center;
    }}
    .pb-card .holder-unclaimed {{
        font-size: 1.1em;
        color: {ui_theme['text_dim']};
        text-align: center;
        margin: 0.5rem 0;
    }}
    .pb-card .holder-container-col {{
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
        width: 100%;
        margin: 0.5rem 0;
        padding-bottom: 0.4rem;
        overflow-x: auto;
    }}
    /* Sleek custom horizontal scrollbar for static badge rows */
    .pb-card .holder-container-col::-webkit-scrollbar {{ height: 4px; }}
    .pb-card .holder-container-col::-webkit-scrollbar-track {{ background: rgba(0, 0, 0, 0.1); border-radius: 4px; }}
    .pb-card .holder-container-col::-webkit-scrollbar-thumb {{ background: {ui_theme['primary_scrollbar']}; border-radius: 4px; }}
    .pb-card .holder-container-col::-webkit-scrollbar-thumb:hover {{ background: {ui_theme['primary_hover']}; }}

    .pb-card .holder-track-flex {{
        display: flex;
        justify-content: center;
        align-items: center;
        flex-wrap: nowrap;
        gap: 0.4rem;
        width: max-content;
        min-width: 100%;
    }}
    .pb-card .holder-container-marquee {{
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
        width: 100%;
        overflow: hidden;
        margin: 0.5rem 0;
        padding-bottom: 0.4rem;
        mask-image: linear-gradient(to right, transparent, black 5%, black 95%, transparent);
        -webkit-mask-image: -webkit-linear-gradient(left, transparent, black 5%, black 95%, transparent);
    }}
    .pb-card .marquee-row {{
        display: flex;
        width: max-content;
        animation: pb-marquee linear infinite;
    }}
    .pb-card .marquee-row:hover {{
        animation-play-state: paused;
    }}
    .pb-card .marquee-block {{
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
        padding-right: 1.5rem; /* Gap before the duplicate starts */
        width: max-content;
    }}
    @keyframes pb-marquee {{
        0% {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}
    
    .pb-card .holder-pill-single {{
        background: linear-gradient(145deg, {ui_theme['primary_highlight']}, rgba(0, 0, 0, 0.4));
        border: 1px solid {ui_theme['primary_border_strong']};
        box-shadow: 0 4px 6px rgba(0,0,0,0.4);
        border-radius: 20px;
        padding: 0.4rem 1.2rem;
        font-size: 1.5em;
        color: {ui_theme['text_main']};
        white-space: nowrap;
        height: max-content;
        width: max-content;
    }}
    .pb-card .holder-pill {{
        background: linear-gradient(145deg, {ui_theme['primary_highlight']}, rgba(0, 0, 0, 0.4));
        border: 1px solid {ui_theme['primary_border_strong']};
        box-shadow: 0 2px 4px rgba(0,0,0,0.4);
        border-radius: 14px;
        padding: 0.25rem 0.75rem;
        font-size: 1.0em;
        color: {ui_theme['text_main']};
        white-space: nowrap;
        height: max-content;
        width: max-content;
    }}
    /* Style for the expander title */
    div[data-testid="stExpander"] summary p {{
        font-size: 1.5rem;
        font-weight: bold;
    }}
</style>
""", unsafe_allow_html=True)


df_pbs = Streamlit_utils.load_table("personal_bests_summary")
df_pb_detail = Streamlit_utils.load_table("personal_bests_detail_all_time")
df_meta = Streamlit_utils.load_table("run_metadata")
run_time = pd.to_datetime(df_meta['last_updated_utc'].iloc[0], utc=True) if not df_meta.empty else pd.Timestamp.now(tz='UTC')
dashboard_config = Streamlit_utils.load_dashboard_config()
texts = load_texts()

if df_pbs.empty:
    st.warning("No Personal Best data could be loaded. The ETL pipeline may not have run yet.")
else:
    # --- Sidebar Sorting Toggles ---
    st.sidebar.header("Display Options")
    default_group_sort = dashboard_config.get('pb_default_group_sort', 'config')
    sort_groups_alpha = st.sidebar.toggle("Sort Groups Alphabetically", value=(default_group_sort == 'alphabetical'))

    default_item_sort = dashboard_config.get('pb_default_item_sort', 'alphabetical')
    sort_items_alpha = st.sidebar.toggle("Sort Records Alphabetically", value=(default_item_sort == 'alphabetical'))

    # --- Get Group and Item Order from Config ---
    group_order = json.loads(dashboard_config.get('pb_group_order', '[]'))
    item_orders = json.loads(dashboard_config.get('pb_item_orders', '{}'))
    other_group_name = dashboard_config.get('pb_other_group_name', 'Miscellaneous PBs')
    if other_group_name not in group_order:
        group_order.append(other_group_name)

    # --- Determine Group Display Order ---
    if sort_groups_alpha:
        groups_to_display = sorted([g for g in group_order if g in df_pbs['Group'].unique()])
    else:
        groups_to_display = [g for g in group_order if g in df_pbs['Group'].unique()]
    
    display_hall_of_fame(df_pbs, texts)
    st.markdown("---")

    # --- Event Feeds ---
    feed_l_col, feed_r_col = st.columns([1, 1], gap="large")
    with feed_l_col:
        st.subheader("📜 Recent Personal PBs")
        if not df_pb_detail.empty:
            Streamlit_utils.display_event_feed(
                df_pb_detail.sort_values(by='Timestamp', ascending=False).head(50),
                run_time=run_time,
                player_col='Username',
                item_col='Task_Name',
                val_col='PB_Time',
                date_col='Timestamp',
                limit=50,
                height="400px"
            )
        else:
            st.info("No recent personal bests available. Check if the ETL pipeline has generated the data.")
            
    with feed_r_col:
        st.subheader("🏆 Newest Clan Records")
        df_pbs_recent = df_pbs.dropna(subset=['Date']).copy()
        if not df_pbs_recent.empty:
            df_pbs_recent = df_pbs_recent[df_pbs_recent['Date'] != ""]
            df_pbs_recent['Timestamp'] = pd.to_datetime(df_pbs_recent['Date'], utc=True, errors='coerce')
            df_pbs_recent = df_pbs_recent.dropna(subset=['Timestamp'])
            df_pbs_recent.sort_values(by='Timestamp', ascending=False, inplace=True)
            
            Streamlit_utils.display_event_feed(
                df_pbs_recent.head(50),
                run_time=run_time,
                player_col='Holder',
                item_col='Task',
                val_col='Time',
                date_col='Timestamp',
                limit=50,
                height="400px"
            )
        else:
            st.info("No recent clan records available.")

    st.markdown("---")
    
    # --- Display each group and its records ---
    for group_name in groups_to_display:
        # FIX: Use an expander for each group to prevent rendering issues
        with st.expander(group_name, expanded=True):
            df_group = df_pbs[df_pbs['Group'] == group_name].copy()
            
            # --- Sort items within the group based on toggle ---
            if not sort_items_alpha and group_name in item_orders:
                # Apply config order
                config_order = list(dict.fromkeys(item_orders.get(group_name, [])))
                tasks_in_df = df_group['Task'].unique()
                ordered_tasks = [task for task in config_order if task in tasks_in_df]
                other_tasks = sorted([task for task in tasks_in_df if task not in ordered_tasks])
                final_order = ordered_tasks + other_tasks
                
                if final_order:
                    df_group['Task'] = pd.Categorical(df_group['Task'], categories=final_order, ordered=True)
                    df_group.sort_values('Task', inplace=True)
            else:
                # Apply alphabetical order
                df_group.sort_values('Task', inplace=True)

            # --- Display records as cards in a responsive grid ---
            card_html_list = []
            for row in df_group.itertuples():
                # Fallback to Task if Display_Name doesn't exist in older DBs
                display_title = getattr(row, 'Display_Name', row.Task)
                label = getattr(row, 'Label', 'Time')
                card_html_list.append(display_pb_card(display_title, row.Holder, row.Time, row.Date, label))
            
            # Join all card HTML into one string and wrap in the grid container
            st.write(f'<div class="card-container">{"".join(card_html_list)}</div>', unsafe_allow_html=True)
