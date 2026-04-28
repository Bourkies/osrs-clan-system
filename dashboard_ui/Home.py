# dashboard/Home.py
# Main landing page for the Streamlit application.

import streamlit as st
import Streamlit_utils
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from streamlit_js_eval import streamlit_js_eval

current_script_directory = Path(__file__).resolve().parent
image_path = current_script_directory.parent / "shared_config" / "images" / "AU_OSRS_Flag.png"

# --- Page Configuration ---
st.set_page_config(
    page_title="AU OSRS Dashboard",
    page_icon="🇦🇺",
    layout="wide"
)

# --- Initialize session state for timezone if it doesn't exist ---
if 'user_timezone' not in st.session_state:
    st.session_state.user_timezone = None

# --- Main "Home" Page ---
st.title("🇦🇺 AU OSRS Clan Dashboard 🇦🇺")

st.sidebar.title("Dashboard Info")

# --- ADDED: Refresh Button ---
if st.sidebar.button("🔄 Clear Cache & Refresh Data"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# This runs only once per session to get the timezone.
if st.session_state.user_timezone is None:
    user_tz_str = streamlit_js_eval(js_expressions="Intl.DateTimeFormat().resolvedOptions().timeZone", key="tz_eval")
    if user_tz_str:
        # If we successfully got the timezone, store it and rerun the script
        st.session_state.user_timezone = user_tz_str
        st.rerun()

# Use the stored timezone for display
user_tz_str = st.session_state.user_timezone
last_updated_utc = Streamlit_utils.get_last_updated_timestamp()

if last_updated_utc:
    # Ensure the UTC timestamp is timezone-aware
    if last_updated_utc.tzinfo is None:
        last_updated_utc = last_updated_utc.replace(tzinfo=ZoneInfo("UTC"))
    
    # Format UTC time string first as a fallback
    last_updated_utc_str = last_updated_utc.strftime('%d %b %Y, %H:%M %Z')
    display_timestamp = f"**Last Updated (UTC):** {last_updated_utc_str}"

    # If we have the user's timezone, create a local time string and prepend it
    if user_tz_str:
        try:
            local_tz = ZoneInfo(user_tz_str)
            last_updated_local = last_updated_utc.astimezone(local_tz)
            last_updated_local_str = last_updated_local.strftime('%d %b %Y, %H:%M %Z')
            display_timestamp = (
                f"**Last Updated (Your Time):** {last_updated_local_str}\n\n"
                + display_timestamp
            )
        except ZoneInfoNotFoundError:
            # If the browser timezone isn't recognized, we just show UTC
            pass

    # Display the data source and timestamp string
    st.sidebar.info(f"{display_timestamp}", icon="💻")
else:
    # Fallback message if the timestamp can't be found
    st.sidebar.warning("Data Source: Local DB\n\nCould not read last updated time from `run_metadata` table.", icon="⚠️")

st.sidebar.markdown("---")

st.markdown("---")

# Use columns to center and constrain the image width
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
																
    st.image(str(image_path), width='stretch')


st.header("Welcome to the **AU OSRS** Clan Dashboard!")
st.markdown("""
This dashboard provides a live feed of our clan's latest achievements, valuable drops, personal bests, and more! 
Use the sidebar on the left to explore the different leaderboards and tracking pages.
""")

st.markdown("---")

st.header("Looking to join? 🇦🇺")
st.markdown("""
 We are a PvM and social clan focused on raiding, bossing, and having a good time with other Aussie players.


### What We Offer
- **💰 Billions in clan event prizes** (Bingos, competitions & more)
- **⚔️ Regular PvM events & raids**
- **🍻 Friendly, social community**
- **📈 Players of all experience levels welcome**

Whether you're learning raids or smashing end-game PvM, there's always people online to boss with.

### Requirements
- **1500+ Total Level**
- **Active player**
- **Preferably Australian timezone or New Zealand 🇦🇺**
            
### Apply on discord!
""")

st.header("Clan Links")
st.markdown("""
- **[🔗 Visit our Clan Website](https://www.auosrs.com.au/)**
- **[💬 Join our Discord Server](https://discord.gg/auosrs)**
""")

st.markdown("""
---         

---
*Data on this dashboard is refreshed every 15-20 minutes. To ensure your broadcasts are tracked, install the **Clan Chat Webhook** plugin as per the Discord pin in the `#chat-logs` channel.*

Contact the admin team for any issue or improvement ideas.
""")


