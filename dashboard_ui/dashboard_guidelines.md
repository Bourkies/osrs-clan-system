# AU OSRS Dashboard - UI & UX Guidelines

This document outlines the design philosophy, theme, and structural rules for building and maintaining pages within the AU OSRS Clan Dashboard. Always refer to these guidelines before creating a new page or refactoring an old one.

---

## 1. Core Identity & Tone
**"The Clan Tavern Noticeboard"**
*   **Audience:** Clan members checking in casually on their phones or second monitors.
*   **Tone:** Celebratory, cheeky, and engaging. We celebrate the massive RNG spoons and playfully mock the tragic PvP deaths.
*   **Data Philosophy (Progressive Disclosure):** Do not overwhelm the user with "Excel spreadsheet" walls of data. Give them the highlights immediately, and let them click to see the raw data if they are curious.

## 2. Themeing (OSRS Southern Cross)
The dashboard uses a custom Streamlit theme defined in `.streamlit/config.toml` that bridges the official AU/NZ Flag Navy with classic OSRS Interface Gold:
*   **Base (`backgroundColor`):** Deep Navy/Charcoal (`#050A10`). Represents the night sky/ocean and OSRS dark stone. Easy on the eyes.
*   **Sidebar (`secondaryBackgroundColor`):** Official AU/NZ Flag Blue (darkened to `#01153E`).
*   **Primary Accent (`primaryColor`):** Rich OSRS Interface Gold (`#C89100`). Used for buttons, borders, and primary highlights. Highly readable against white text.
*   **Text & Font:** Pure White (`#FFFFFF`) using `"sans serif"` (Arial) to closely mimic the clean OSRS UI font.

### The `UI_THEME` Single Source of Truth
Never hardcode hex colors or layout widths into individual page files. All custom HTML/CSS components must reference the `UI_THEME` dictionary located at the top of `Streamlit_utils.py`.
*   Use `UI_THEME['primary']` for gold accents.
*   Use `UI_THEME['secondary_accent']` for positive/value highlights (OSRS Magic Blue).
*   Use `UI_THEME['card_bg']` for container backgrounds.

Similarly, the minimum width for responsive columns is defined globally via `UI_THEME['column_min_width']` (e.g., `420px`). Do not manually adjust column breakpoint CSS on a per-page basis.

---

## 3. Standard Layout Formula
Every page on the dashboard should follow a consistent top-to-bottom visual hierarchy.

### A. The Hero Section
*   Big, bold title using `st.title()`.
*   Always include a relevant emoji in the title (e.g., `st.title("💰 Recent Loot")`).
*   **Time Filters:** Call `Streamlit_utils.sidebar_time_filter(run_time)` to generate a standardized Date Picker and Quick Select Pills in the sidebar. Do not build custom time UI on the main page.

### B. High-Level Summary (The TL;DR)
*   Use `st.columns()` and `st.metric()` to display 3 to 4 high-level stats at the very top. 
*   *Example:* For the Drops page, show "Total Value This Week", "Biggest Drop", and "Luckiest Player".

### C. The Hook (Visualizations first)
*   This is the core of the page. Use custom HTML/CSS components instead of raw dataframes.
*   **Leaderboards:** Use `Streamlit_utils.display_leaderboard_podium()`. It automatically formats top players visually and handles GP conversion if `format_count_as_gp=True`.
*   **Charts:** Use `Streamlit_utils.display_dynamic_timeseries()`. It generates beautiful, smoothed Altair charts that perfectly match the dashboard's CSS containers and color theme.
*   **Feeds:** Use `Streamlit_utils.display_event_feed()`. It replaces dense tables with scrollable, HTML-escaped card layouts and dynamic "Time Ago" formatting.

### D. The Details (Hidden by default)
*   If a page requires a massive raw data table (e.g., the full history of drops for the month), it **must** be placed inside an expander.
*   Use: `with st.expander("View Full Raw Data 📜"):`
*   Use `st.dataframe(use_container_width=True, hide_index=True)` to make the table span the screen nicely.

---

## 4. Coding Practices & Optimization

### Caching & The Blue/Green Database
Because the ETL pipeline overwrites the SQLite database, Streamlit needs to know when to drop its cache and fetch fresh data.
*   **Rule:** Any function that loads data from the database (e.g., `load_table()`) must be decorated with `@st.cache_data(ttl=300)`.
*   **Rule:** Data loading functions must call `get_local_db_state()` inside their execution. This ties the Streamlit cache to the physical file's modification time. If the ETL swaps the DB, Streamlit instantly refreshes.
*   **Rule:** Never use `@st.cache_resource` on the SQLite database connection itself, as this will place a persistent lock on the file and cause the background ETL pipeline to crash.

### UI Responsiveness
*   Always build layouts assuming they will be viewed on a mobile device.
*   When using `st.columns()`, be aware that Streamlit collapses them vertically on small screens. Ensure the stacking order makes logical sense.
*   **Global CSS:** You MUST call `Streamlit_utils.inject_custom_css()` immediately after `st.set_page_config()` on every page. This prevents columns from squishing, optimizes desktop padding, and styles the widgets.

### Emojis
Liberally (but tastefully) use emojis in headers, tabs, and expanders to break up the dark interface and add personality.

### Streamlit Deprecations & Modern Standards
*   **Layout Widths:** Do not use `use_container_width=True` (deprecated). Instead, explicitly use `width="stretch"` for full-width charts/buttons, or `width="content"`.
*   **HTML/JS Components:** Do not use `streamlit.components.v1`. Use `st.iframe()` or `st.markdown(..., unsafe_allow_html=True)` for rendering custom HTML/JS.
*   **Image Handling:** To prevent `MediaFileHandler: Missing file` cache errors on hot reloads, prefer converting local images to Base64 HTML strings rather than using `st.image("local/path.png")`.