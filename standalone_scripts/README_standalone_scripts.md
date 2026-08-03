# Standalone Scripts (`standalone_scripts/`)

This directory contains standalone, self-contained Python scripts designed for custom reporting, one-off analytics, and specialized clan tools.

Scripts in this directory operate independently from the main daily automation pipeline while safely consuming project configuration and database assets.

---

## 📜 Rules & Authoring Guidelines

All scripts added to or maintained within this directory must adhere strictly to the following constraints:

1. **Development Environment Execution**:
   * Scripts are intended and expected to be executed in a **development environment** (`dev` environment) rather than inside automated production pipelines or scheduled daily tasks.

2. **Strict Read-Only Database Connections**:
   * Scripts **must only make read-only connections** to SQLite databases (e.g. using `mode=ro` SQLite URI parameters like `file:<path>?mode=ro`) or static project data sources.
   * Writing to database files, modifying schemas, or risking database locks on live system data is prohibited.

3. **No New Project Dependencies**:
   * **Do NOT add new dependencies** to `requirements.txt` or system package manifests for standalone scripts.
   * If a script requires third-party packages beyond standard project requirements (e.g., specialized visualization or analysis libraries like `matplotlib`), the script **must include a runtime check for the dependency** (e.g. `try...except ImportError`).
   * If the dependency is missing, the script must handle it gracefully (e.g., fall back to standard text/ASCII output or fail with a clear, helpful message instructing how to run in dev) without breaking execution or requiring the dependency in `requirements.txt`.

---

## 🔒 Safety & Read-Only Access

* **Read-Only Database Connections**: All scripts in this directory connect to SQLite databases in `mode=ro` (read-only) mode to prevent database locks, schema corruption, or accidental modification of production data.
* **No Side Effects**: Executing scripts in this folder will not alter system state, modify Google Sheets, or overwrite pipeline outputs unless explicitly stated.

---

## 🛠 Available Scripts

### `pb_inside_joke_report.py`
A report analyzer for clan personal best (PB) broadcasts. It identifies PB distribution around specific target times (such as `1:11` / 119 ticks), plots discrete step charts, and highlights "near miss" precise timing edge cases (e.g. `1:10.80`).

#### **Execution**:
```bash
python standalone_scripts/pb_inside_joke_report.py
```

#### **Customization**:
Open `pb_inside_joke_report.py` and adjust the configuration block at the top of the file:
```python
TARGET_BOSS = None        # Set boss name (e.g., "Araxxor", "The Hueycoatl") or None for all bosses
TARGET_TIME_STR = "1:11"  # Target PB time pattern (e.g. "1:11", "11:10")
WINDOW_TICKS = 6          # +/- tick window around target time
USE_ENRICHED_DB = True    # Resolve RSNs to static Discord IDs / primary member names
SHOW_PLOT = True          # Attempt interactive popup chart window
```

---

## 🖥 Environment & Headless SSH Compatibility

Scripts handle both local desktop environments (with GUI support for interactive plots) and remote SSH / server runs gracefully:
* If a GUI display is available, an interactive plot window will open.
* If running over an SSH session or headless environment where plot display fails, scripts fall back to a clean terminal ASCII table/histogram without crashing.
