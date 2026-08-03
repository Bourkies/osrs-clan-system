#!/usr/bin/env python3
"""
standalone_scripts/pb_inside_joke_report.py

Standalone PB Broadcast Report & "Inside Joke" Analyzer.
Analyzes Personal Best broadcasts from the clan database around target PB times
(such as 1:11.x / 119 ticks and 1:10.80 precise timing edge cases).

Safe Read-Only Database Access.
"""

import sys
import os
import re
import sqlite3
from pathlib import Path
try:
    import pandas as pd
except ImportError:
    print("[ERROR] Missing required dependency 'pandas'.")
    print("Standalone scripts do not add new requirements to system requirements.txt.")
    print("Please install pandas in your dev environment: pip install pandas")
    sys.exit(1)


# Force UTF-8 output encoding for Windows consoles if needed
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ==============================================================================
# CONFIGURATION OPTIONS (Modify these variables to customize your report)
# ==============================================================================
TARGET_BOSS = "Mad Angel"        # Boss / Task_Name filter (e.g. "Araxxor", "Hespori", or None for all)
TARGET_TIME_STR = "1:11" # Target PB time (e.g. "1:11.4", "1:11", "11:10")
LABEL_FORMAT = "truncated"    # Chart/Table Label Style: "exact_decimal" (1:11.4), "truncated" (1:11 (119t)), "rounded" (1:11 (119t))
WINDOW_TICKS = 6          # +/- tick window around target time to display on chart
USE_ENRICHED_DB = True    # True to use enriched_data.db (maps RSNs to Discord IDs & Main names)
SHOW_PLOT = True          # True to display interactive matplotlib chart window if available
# ==============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHARED_DATA_DIR = PROJECT_ROOT / "shared_data" / "databases"

def parse_pb_time(time_str: str, target_time_str: str = "1:11.4"):
    """
    Parses an OSRS PB time string into total seconds, nearest tick, and precision details.
    Examples:
      '1:10.80' -> 70.80s -> 118 ticks (precise=True)
      '1:11.40' -> 71.40s -> 119 ticks (precise=True)
      '1:11'    -> Non-precise string (In OSRS 1:11 covers 118t [70.8s] & 119t [71.4s])
    """
    if not time_str or not isinstance(time_str, str):
        return None

    time_str = time_str.strip()
    is_precise = "." in time_str

    parts = time_str.split(":")
    try:
        if len(parts) == 3:  # H:MM:SS(.ss)
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            seconds = h * 3600 + m * 60 + s
        elif len(parts) == 2:  # MM:SS(.ss)
            m, s = float(parts[0]), float(parts[1])
            seconds = m * 60 + s
        elif len(parts) == 1:  # SS(.ss)
            seconds = float(parts[0])
        else:
            return None
    except ValueError:
        return None

    # OSRS tick = 0.6s
    # SPECIAL CASE: Non-precise "1:11" (71.0s)
    # In OSRS, 118t = 70.8s (rounds UP to 1:11) and 119t = 71.4s (rounds DOWN to 1:11).
    # If targeting 1:11.x / 1:11.4 / 119t, non-precise "1:11" represents the 1:11 joke hit (119t).
    if not is_precise and time_str == "1:11":
        tick = 119  # Map non-precise 1:11 to the 119t (1:11.x) joke target tick!
    else:
        tick = int(round(seconds / 0.6))

    return {
        "raw_str": time_str,
        "seconds": seconds,
        "tick": tick,
        "is_precise": is_precise,
    }

def format_tick_time(tick: int, style: str = "exact_decimal") -> str:
    """
    Formats a tick count into string representation based on the requested style:
      - 'exact_decimal': Exact 1-decimal OSRS time (e.g. '1:10.8', '1:11.4')
      - 'truncated': Truncated whole seconds (e.g. '1:10', '1:11')
      - 'rounded': Rounded whole seconds (e.g. '1:11', '1:12')
    """
    total_seconds = tick * 0.6
    minutes = int(total_seconds // 60)
    rem_seconds = total_seconds % 60

    if style == "truncated":
        trunc_sec = int(rem_seconds)
        return f"{minutes}:{trunc_sec:02d}" if minutes > 0 else f"{trunc_sec:02d}s"
    elif style == "rounded":
        round_sec = int(round(rem_seconds))
        return f"{minutes}:{round_sec:02d}" if minutes > 0 else f"{round_sec:02d}s"
    else:  # default 'exact_decimal'
        if minutes > 0:
            return f"{minutes}:{rem_seconds:04.1f}"
        else:
            return f"{rem_seconds:04.1f}s"

def get_db_connection(use_enriched: bool = True):
    """Opens a safe read-only SQLite connection."""
    db_name = "enriched_data.db" if use_enriched else "parsed_data.db"
    db_path = SHARED_DATA_DIR / db_name

    if not db_path.exists():
        fallback_path = SHARED_DATA_DIR / "parsed_data.db"
        if fallback_path.exists():
            print(f"[!] Warning: {db_path.name} not found. Falling back to {fallback_path.name}")
            db_path = fallback_path
        else:
            raise FileNotFoundError(f"Database file not found at {db_path}")

    # Connect in read-only mode via URI
    uri_path = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri_path, uri=True)
    return conn

def print_ascii_chart(df_chart):
    """Prints a clean ASCII bar chart in the terminal for non-GUI / SSH sessions."""
    print("\n" + "="*70)
    print(" [CHART] PB TIME STEP DISTRIBUTION (ASCII CHART)")
    print("="*70)
    max_count = df_chart["count"].max() if not df_chart.empty else 1
    chart_width = 40

    for _, row in df_chart.iterrows():
        count = row["count"]
        time_lbl = row["time_label"]
        bar_len = int((count / max_count) * chart_width) if max_count > 0 else 0
        bar = "#" * bar_len
        marker = " [TARGET]" if row.get("has_target") else ""
        print(f" {time_lbl:>7s} | {bar:<40s} {count:3d}{marker}")
    print("="*70)


def main():
    print("="*70)
    print(" [REPORT] OSRS CLAN SYSTEM - STANDALONE PB INSIDE JOKE REPORT")
    print("="*70)

    # 1. Connect to Database
    try:
        conn = get_db_connection(USE_ENRICHED_DB)
    except Exception as e:
        print(f"[ERROR] Error connecting to database: {e}")
        sys.exit(1)

    # 2. Query PB Broadcasts
    query = """
    SELECT 
        raw_log_id,
        Timestamp,
        Username,
        Task_Name,
        PB_Time,
        Discord_ID,
        Discord_Name
    FROM clan_broadcasts 
    WHERE PB_Time IS NOT NULL AND PB_Time != ''
    """
    if TARGET_BOSS:
        query += f" AND LOWER(Task_Name) LIKE '%{TARGET_BOSS.lower()}%'"

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print(f"[!] No PB broadcasts found matching query (Boss filter: {TARGET_BOSS}).")
        sys.exit(0)

    print(f"[*] Loaded {len(df)} total PB broadcasts from database.")

    # 3. Parse Times & Ticks
    parsed_records = []
    for idx, row in df.iterrows():
        parsed = parse_pb_time(row["PB_Time"], TARGET_TIME_STR)
        if parsed:
            player_name = row["Discord_Name"] if (pd.notna(row["Discord_Name"]) and row["Discord_Name"]) else row["Username"]
            parsed_records.append({
                "raw_log_id": row["raw_log_id"],
                "Timestamp": row["Timestamp"],
                "Username": row["Username"],
                "Player": player_name,
                "Task_Name": row["Task_Name"],
                "PB_Time": row["PB_Time"],
                "seconds": parsed["seconds"],
                "tick": parsed["tick"],
                "is_precise": parsed["is_precise"]
            })

    df_parsed = pd.DataFrame(parsed_records)

    # 4. Analyze Target Time
    target_parsed = parse_pb_time(TARGET_TIME_STR)
    if not target_parsed:
        print(f"[ERROR] Invalid TARGET_TIME_STR: '{TARGET_TIME_STR}'. Expected format like '1:11'.")
        sys.exit(1)

    target_tick = target_parsed["tick"]
    target_sec = target_parsed["seconds"]

    print(f"[*] Target String: '{TARGET_TIME_STR}' ({target_sec:.1f}s -> ~{target_tick} ticks)")
    print(f"[*] Window: +-{WINDOW_TICKS} ticks ({format_tick_time(target_tick - WINDOW_TICKS, LABEL_FORMAT)} to {format_tick_time(target_tick + WINDOW_TICKS, LABEL_FORMAT)})")

    # Filter records within tick window
    min_tick = target_tick - WINDOW_TICKS
    max_tick = target_tick + WINDOW_TICKS
    df_window = df_parsed[(df_parsed["tick"] >= min_tick) & (df_parsed["tick"] <= max_tick)].copy()

    # Discrete tick steps dataframe
    all_steps = list(range(min_tick, max_tick + 1))
    step_counts = df_window.groupby("tick").size().to_dict()
    df_steps = pd.DataFrame({
        "tick": all_steps,
        "count": [step_counts.get(t, 0) for t in all_steps],
        "time_label": [format_tick_time(t, LABEL_FORMAT) for t in all_steps]
    })

    # Group df_chart by time_label (combines counts for truncated/rounded modes)
    grouped = []
    seen = {}
    for idx, row in df_steps.iterrows():
        lbl = row["time_label"]
        if lbl not in seen:
            item = {
                "time_label": lbl,
                "count": row["count"],
                "has_target": (row["tick"] == target_tick),
                "has_118": (row["tick"] == 118),
            }
            seen[lbl] = item
            grouped.append(item)
        else:
            seen[lbl]["count"] += row["count"]
            if row["tick"] == target_tick:
                seen[lbl]["has_target"] = True
            if row["tick"] == 118:
                seen[lbl]["has_118"] = True
    df_chart = pd.DataFrame(grouped)

    # 5. Highlight Categories
    # A) Exact Joke Hits (Match base pattern e.g. "1:11" in PB_Time)
    base_joke_str = TARGET_TIME_STR.split(".")[0]
    exact_joke_hits = df_parsed[df_parsed["PB_Time"].str.contains(base_joke_str, na=False, regex=False)]

    # B) Precise Time Non-Rounders (1:10.80 / 118 ticks with precise timing ON)
    # 118 ticks = 70.8s. Precise timing outputs '1:10.80', missing '1:11' because of sub-second toggle!
    precise_misses = df_parsed[
        (df_parsed["tick"] == 118) & 
        (df_parsed["is_precise"]) & 
        (~df_parsed["PB_Time"].str.contains(base_joke_str, na=False, regex=False))
    ]

    # C) Tick Offsets Breakdown (-2t, -1t, Exact Target, +1t, +2t)
    offsets_def = [
        (-2, "-2 Ticks (Fast)"),
        (-1, "-1 Tick (Fast)"),
        (0, "Exact Target Tick"),
        (1, "+1 Tick (Slow)"),
        (2, "+2 Ticks (Slow)"),
    ]

    # 6. Print Markdown Console Summary
    print("\n" + "="*70)
    print(" [SUMMARY] REPORT RESULTS")
    print("="*70)

    print(f"\n### Exact Joke String Hits ('{base_joke_str}') ({len(exact_joke_hits)} total):")
    if not exact_joke_hits.empty:
        for _, r in exact_joke_hits.iterrows():
            print(f" - **{r['Player']}** ({r['Username']}) | {r['Task_Name']} | `{r['PB_Time']}` ({r['tick']}t) | {r['Timestamp']}")
    else:
        print(" - None found.")

    print(f"\n### Precise Timing Edge Cases (`1:10.80` / 118t - Missed '{base_joke_str}' due to decimals) ({len(precise_misses)} total):")
    if not precise_misses.empty:
        for _, r in precise_misses.iterrows():
            print(f" - **{r['Player']}** ({r['Username']}) | {r['Task_Name']} | `{r['PB_Time']}` (118t) | {r['Timestamp']}")
    else:
        print(" - None found.")

    print("\n### Near-Miss Breakdown by Tick Steps:")
    for offset, label in offsets_def:
        tick_val = target_tick + offset
        time_str_val = format_tick_time(tick_val, LABEL_FORMAT)
        sub_df = df_parsed[df_parsed["tick"] == tick_val]
        print(f"\n* **{label}** [{tick_val}t / {time_str_val}] ({len(sub_df)} entries):")

        if not sub_df.empty:
            for _, r in sub_df.head(10).iterrows():
                print(f"   * {r['Player']} - {r['Task_Name']} (`{r['PB_Time']}`)")
            if len(sub_df) > 10:
                print(f"   ... and {len(sub_df) - 10} more.")
        else:
            print("   * None")

    # Print ASCII chart to terminal
    print_ascii_chart(df_chart)

    # 7. Matplotlib Interactive Plot (if enabled & GUI available)
    if SHOW_PLOT:
        try:
            import matplotlib.pyplot as plt
            
            fig, ax = plt.subplots(figsize=(10, 6))
            
            colors = []
            for _, r in df_chart.iterrows():
                if r.get("has_target"):
                    colors.append("#2ecc71")  # Green for Target
                else:
                    colors.append("#3498db")  # Blue for all others

            bars = ax.bar(df_chart["time_label"], df_chart["count"], color=colors, edgecolor="black", width=0.6)
            
            if LABEL_FORMAT == "truncated":
                x_axis_label = "PB Broadcast Time (Truncated Seconds)"
            elif LABEL_FORMAT == "rounded":
                x_axis_label = "PB Broadcast Time (Rounded Seconds)"
            else:
                x_axis_label = "PB Broadcast Time (Exact OSRS Decimal Ticks)"

            ax.set_xlabel(x_axis_label, fontsize=12, fontweight="bold")
            ax.set_ylabel("Number of PB Broadcasts", fontsize=12, fontweight="bold")
            boss_lbl = f" - {TARGET_BOSS}" if TARGET_BOSS else " (All Bosses)"
            ax.set_title(f"OSRS Clan Personal Best Distribution Around '{TARGET_TIME_STR}'{boss_lbl}", fontsize=14, fontweight="bold")
            ax.grid(axis="y", linestyle="--", alpha=0.7)


            # Value labels on top of bars
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.annotate(f'{int(height)}',
                                xy=(bar.get_x() + bar.get_width() / 2, height),
                                xytext=(0, 3),  # 3 points vertical offset
                                textcoords="offset points",
                                ha='center', va='bottom', fontweight='bold')

            plt.tight_layout()
            print("\n[+] Displaying interactive plot window. Close window to finish script.")
            plt.show()

        except Exception as e:
            print(f"\n[!] Note: Could not display interactive GUI plot window ({e}). Terminal ASCII chart printed above.")

if __name__ == "__main__":
    main()
