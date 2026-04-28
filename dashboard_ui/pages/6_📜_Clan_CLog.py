# dashboard/pages/6_📜_Clan_CLog.py

import streamlit as st
import pandas as pd
import Streamlit_utils
import json
import html
import os
import base64
import re
import urllib.parse

st.set_page_config(page_title="Clan Collection Log", page_icon="📜", layout="wide")
Streamlit_utils.inject_custom_css()

# --- Define paths to assets ---
# The only file you now need from the osrsreboxed-db is 'items-complete.json'
# https://github.com/0xNeffarion/osrsreboxed-db/blob/master/osrsreboxed/docs/items-complete.json
from pathlib import Path
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "shared_config" / "assets"
CUSTOM_ICON_DIR = ASSETS_DIR / "custom_icons"
# Path to the local item data file that includes base64 icons
ITEM_DATA_PATH = ASSETS_DIR / "items-complete.json"

# --- Helper function to load all item data from a single local file ---
@st.cache_data
def load_item_data(path):
    """
    Loads item data from a local JSON file, creating two mappings:
    1. A mapping from lowercase item name to its base64 icon data URI.
    2. A mapping from lowercase item name to its wiki URL.
    This function prioritizes items where 'noted' is false.
    """
    if not os.path.exists(path):
        st.error(f"Fatal Error: The item data file was not found at {path}")
        return {}, {}
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Use an intermediate dictionary to handle noted/un-noted priority.
    processed_items = {}
    for item_id, item_details in data.items():
        name = item_details.get('name')
        if not name:
            continue
        
        name_lower = name.lower()
        is_noted = item_details.get('noted', True)

        # We want to store the item if it's the first one we've seen with this name,
        # or if it's the un-noted version, which takes priority.
        if name_lower not in processed_items or not is_noted:
            processed_items[name_lower] = {
                'icon': item_details.get('icon'),
                'wiki_url': item_details.get('wiki_url')
            }

    # Create the final maps from the processed data.
    name_to_icon_map = {
        name: f"data:image/png;base64,{details['icon']}"
        for name, details in processed_items.items()
        if details.get('icon')
    }
    name_to_wiki_url_map = {
        name: details['wiki_url']
        for name, details in processed_items.items()
        if details.get('wiki_url')
    }
    
    return name_to_icon_map, name_to_wiki_url_map

# --- Helper function to get image as base64 (for custom icons) ---
@st.cache_data
def get_image_as_base64(file_path):
    """Reads a local image file and returns its base64 encoded string."""
    if not os.path.exists(file_path):
        return None
    with open(file_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

# --- Custom CSS for the responsive card grid layout ---
ui_theme = Streamlit_utils.UI_THEME
st.markdown(f"""
<style>
    /*
     VVV CHANGE THE FONT SIZE AND STYLE OF THE EXPANDER TITLE HERE VVV
     Using 'data-testid' is a stable way to target Streamlit components.
    */
    div[data-testid="stExpander"] summary p {{
        font-size: 1.2rem; /* Example values: 1.2rem, 18px, 1.5em */
        font-weight: bold;
    }}
    /* ^^^ CHANGE THE FONT SIZE AND STYLE OF THE EXPANDER TITLE HERE ^^^ */

    .card-grid-container {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 10px;
    }}
    .item-card {{
        background: {ui_theme['card_bg']};
        border: 1px solid {ui_theme['primary_border']};
        border-radius: 7px;
        padding: 10px 42px 10px 10px;
        height: 110px;
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: flex-start;
        box-shadow: {ui_theme['shadow_sm']};
    }}
    .icon-container {{
        width: 42px;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 10px;
        flex-shrink: 0;
    }}
    .item-icon {{
        max-height: 32px;
        max-width: 32px;
    }}
    .text-container {{
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        justify-content: center;
        height: 100%;
        overflow: hidden;
    }}
    .item-name {{
        font-size: 0.9em;
        font-weight: bold;
        color: {ui_theme['text_main']};
        text-align: left;
    }}
    .item-count {{
        font-size: 1.1em;
        color: {ui_theme['primary']};
        font-weight: bold;
        text-align: left;
    }}
    /* VVV Custom styles for the search bar with a clear button VVV */
    .search-container {{
        position: relative;
        width: 100%;
    }}
    .search-container input {{
        padding-right: 2.5rem !important; /* Make space for the button */
    }}
    .clear-button {{
        position: absolute;
        right: 10px;
        top: 50%;
        transform: translateY(-50%);
        background: none;
        border: none;
        cursor: pointer;
        color: {ui_theme['text_dim']};
        font-size: 1.2rem;
    }}
    /* ^^^ End of search bar styles ^^^ */
</style>
""", unsafe_allow_html=True)

Streamlit_utils.display_page_header(
    title="📜 Clan Collection Log",
    description="A summary of all unique items collected by the clan."
)

# --- Data Loading ---
df_clog = Streamlit_utils.load_table("collection_log_summary")
dashboard_config = Streamlit_utils.load_dashboard_config()
# Load both the icon and wiki URL maps using our new function
item_icon_map, item_wiki_url_map = load_item_data(ITEM_DATA_PATH)


if df_clog.empty:
    st.warning("No collection log data could be loaded. The ETL pipeline may not have run yet.")
elif not item_icon_map:
    st.error("Could not load item data. Please ensure `items-complete.json` is in the `assets` folder.")
else:
    # --- Top-level controls (Search, Expand/Collapse) ---
    col1, col2, col3 = st.columns([2, 1, 1])

    if 'clog_search_query' not in st.session_state:
        st.session_state.clog_search_query = ""
        
    def clear_clog_search():
        st.session_state.clog_search_input = ""
        st.session_state.clog_search_query = ""

    with col1:
        # We use a custom component for the search bar to include a clear button
        search_query = st.text_input(
            "Search for items or groups:",
            value=st.session_state.clog_search_query,
            key="clog_search_input", # Use a different key for the input widget itself
            placeholder="E.g., 'Twisted bow' or 'All Pets'",
            label_visibility="collapsed" # Hide label, we use placeholder
        )
        st.session_state.clog_search_query = search_query

        # If there's text in the search bar, show the clear button using custom HTML
        if st.session_state.clog_search_query:
            st.button("❌", key="clear_search_clog", on_click=clear_clog_search)
    
    # Initialize expand/collapse state
    if 'clog_expanded_state' not in st.session_state:
        st.session_state.clog_expanded_state = True

    with col2:
        if st.button("Expand All", use_container_width=True):
            st.session_state.clog_expanded_state = True
            st.rerun()
    with col3:
        if st.button("Collapse All", use_container_width=True):
            st.session_state.clog_expanded_state = False
            st.rerun()
    st.markdown("---")

    # --- Data Filtering ---
    df_obtained = df_clog[df_clog['All_Time_Count'] > 0].copy()

    # Generate hidden datalist for the search bar autocomplete
    all_options = sorted(list(set(df_obtained['Item_Name'].unique().tolist() + df_obtained['Group'].unique().tolist())))
    options_html = "".join([f'<option value="{html.escape(opt)}">' for opt in all_options])
    options_html_escaped = options_html.replace("`", "\\`")

    st.iframe(
        f"""
        <script>
            const parentDoc = window.parent ? window.parent.document : document;
            let datalist = parentDoc.getElementById('clog_search_list');
            if (!datalist) {{
                datalist = parentDoc.createElement('datalist');
                datalist.id = 'clog_search_list';
                parentDoc.body.appendChild(datalist);
            }}
            datalist.innerHTML = `{options_html_escaped}`;
            
            const inputs = parentDoc.querySelectorAll('input');
            for (let i = 0; i < inputs.length; i++) {{
                if (inputs[i].placeholder && inputs[i].placeholder.includes('Twisted bow')) {{
                    inputs[i].setAttribute('list', 'clog_search_list');
                    inputs[i].setAttribute('autocomplete', 'off'); // Prevent browser history from blocking the datalist
                    break;
                }}
            }}
        </script>
        """,
        height=1,
        width=1
    )

    # Use the search query from session state
    if st.session_state.clog_search_query:
        search_lower = st.session_state.clog_search_query.lower()
        df_display_all = df_obtained[df_obtained['Item_Name'].str.lower().str.contains(search_lower) | df_obtained['Group'].str.lower().str.contains(search_lower)]
    else:
        df_display_all = df_obtained

    # --- Get Group and Item Order from Config ---
    group_order_from_config = json.loads(dashboard_config.get('clog_group_order', '[]'))
    item_orders = json.loads(dashboard_config.get('clog_item_orders', '{}'))
    other_group_name = dashboard_config.get('clog_other_group_name', 'Miscellaneous Drops')
    if other_group_name not in group_order_from_config:
        group_order_from_config.append(other_group_name)

    # --- Sidebar ---
    # The sidebar filters should be based on ALL obtained items, not the searched items.
    all_available_groups = sorted(df_obtained['Group'].unique())
    
    st.sidebar.header("Display Options")

    # Sorting Toggles
    default_group_sort = dashboard_config.get('clog_default_group_sort', 'config')
    sort_groups_alpha = st.sidebar.toggle("Sort Groups Alphabetically", value=(default_group_sort == 'alphabetical'))

    default_item_sort = dashboard_config.get('clog_default_item_sort', 'alphabetical')
    sort_items_alpha = st.sidebar.toggle("Sort Items Alphabetically", value=(default_item_sort == 'alphabetical'), key="clog_item_sort")

    st.sidebar.markdown("---")
    
    # Determine Group Display Order based on the toggle
    if sort_groups_alpha:
        groups_to_display_options = all_available_groups
    else:
        # Filter config order to only include groups that actually have data
        groups_to_display_options = [g for g in group_order_from_config if g in all_available_groups]

    # Filtering Section
    st.sidebar.header("Filter by Group")
    
    # Initialize the widget's session state if it doesn't exist
    if 'clog_group_selector' not in st.session_state:
        st.session_state.clog_group_selector = groups_to_display_options

    # Ensure the current selection only contains valid options to prevent Streamlit errors
    st.session_state.clog_group_selector = [g for g in st.session_state.clog_group_selector if g in groups_to_display_options]

    def select_all_groups():
        st.session_state.clog_group_selector = groups_to_display_options

    def deselect_all_groups():
        st.session_state.clog_group_selector = []

    # Select/Deselect All buttons
    col1, col2 = st.sidebar.columns(2)
    col1.button("Select All", use_container_width=True, key="clog_select_all", on_click=select_all_groups)
    col2.button("Deselect All", use_container_width=True, key="clog_deselect_all", on_click=deselect_all_groups)

    selected_groups = st.sidebar.multiselect(
        "Select groups to display:",
        options=groups_to_display_options,
        key="clog_group_selector"
    )


    # --- Main Page Display ---
    if not selected_groups:
        st.info("Please select one or more groups from the sidebar to view data.")
    else:
        df_filtered = df_display_all[df_display_all['Group'].isin(selected_groups)]

        if sort_groups_alpha:
             final_group_render_order = sorted(selected_groups)
        else:
             final_group_render_order = [g for g in group_order_from_config if g in selected_groups]

        for group_name in final_group_render_order:
            df_group = df_filtered[df_filtered['Group'] == group_name].copy()
            
            if df_group.empty:
                continue

            # Use an expander for each group. The title style is set in the CSS above.
            with st.expander(label=group_name, expanded=st.session_state.clog_expanded_state):
                
                # Sort items within the group based on toggle
                if not sort_items_alpha and group_name in item_orders:
                    item_order_list = item_orders.get(group_name, [])
                    df_group['Item_Name'] = pd.Categorical(df_group['Item_Name'], categories=item_order_list, ordered=True)
                    df_group.sort_values('Item_Name', inplace=True)
                else:
                    df_group.sort_values('Item_Name', inplace=True)
                
                # --- Card Display Logic ---
                items_in_group = df_group.to_dict('records')
                
                card_html_list = []
                for item in items_in_group:
                    safe_item_name = html.escape(item['Item_Name'])
                    item_name_lower = item['Item_Name'].lower().strip()
                    
                    # --- UPDATED ICON LOGIC ---
                    icon_html = ""
                    icon_src = ""
                    
                    # 1. Try to find the custom name-based icon first
                    custom_icon_filename = re.sub(r'[^a-zA-Z0-9_]', '', item['Item_Name'].replace(' ', '_')) + ".webp"
                    custom_icon_path = os.path.join(CUSTOM_ICON_DIR, custom_icon_filename)
                    
                    if os.path.exists(custom_icon_path):
                        icon_b64 = get_image_as_base64(custom_icon_path)
                        if icon_b64:
                            icon_src = f"data:image/webp;base64,{icon_b64}"
                    
                    # 2. If not found, fall back to the direct icon map from items-complete.json
                    if not icon_src:
                        icon_src = item_icon_map.get(item_name_lower)

                    # 3. Build the final icon HTML, adding a link if a wiki URL exists.
                    if icon_src:
                        icon_img_tag = f'<img src="{icon_src}" class="item-icon">'
                        wiki_url = item_wiki_url_map.get(item_name_lower)
                        
                        # Generate a default Wiki URL if not in the map
                        if not wiki_url:
                            safe_item_url = urllib.parse.quote(item['Item_Name'].replace(' ', '_'))
                            wiki_url = f"https://oldschool.runescape.wiki/w/{safe_item_url}"
                            
                        # Wrap the image in a clickable link
                        icon_html = f'<a href="{html.escape(wiki_url)}" target="_blank" rel="noopener noreferrer">{icon_img_tag}</a>'
                    # --- End Icon Logic ---
                    
                    icon_container_html = f'<div class="icon-container">{icon_html}</div>'

                    # --- Text Content ---
                    text_container_html = (
                        '<div class="text-container">'
                        f'<div class="item-name">{safe_item_name}</div>'
                        f'<div class="item-count">{item["All_Time_Count"]:,}</div>'
                        '</div>'
                    )

                    card_html = (
                        f'<div class="item-card">{icon_container_html}{text_container_html}</div>'
                    )
                    card_html_list.append(card_html)
                
                all_cards_html = "".join(card_html_list)
                grid_html = f'<div class="card-grid-container">{all_cards_html}</div>'
                
                st.markdown(grid_html, unsafe_allow_html=True)
