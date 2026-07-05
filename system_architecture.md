# **OSRS Clan Management System \- Architecture & Data Flow**

## **1. Project Overview**

This system is designed to track Old School RuneScape (OSRS) clan members, log their multiple in-game accounts (alts), and audit their in-game and Discord ranks for discrepancies.  
Because OSRS display names (RSNs) and Discord usernames change frequently, this system relies exclusively on static IDs (Discord Snowflakes and Wise Old Man IDs) as the core identifiers.  
To prioritize ease of use for non-technical clan leadership while maintaining data integrity, the system uses a **Google Sheet as a serverless database**, a **Google Web App as a safe frontend UI**, and a **Python script (The Auditor) as a daily tracking and auditing worker**.
A downstream **ETL Pipeline** and **Streamlit Dashboard** provide a public-facing UI for regular clan members to view stats and activities without having access to the raw admin database.

## **2. Core System Components**

### **A. The Database (Google Sheets)**

Acts as the Single Source of Truth (SSOT). It provides a familiar, readable format for clan leadership but is protected from accidental human error.

* **Access Control:** **Admins** must be granted Editor access to the raw spreadsheet. To protect the data from human error, all tabs are protected using Google Sheets' "Show a warning when editing this range" feature. This funnels Admins to use the Web App UI for all modifications while retaining full accountability via Google's native Version History.

### **B. The Frontend UI (Google Web App / HTML & JS)**

A serverless web dashboard hosted via Google Apps Script.

* **Purpose:** Allows clan **Admins** to add new members, link alt accounts, and set ranks without ever touching the raw spreadsheet. Both the Web App and the Auditor adhere to the rules defined in the System_Schema tab to ensure data integrity.  
* **Validation:** Enforces data formatting before anything is written to the database.

### **C. The Auditor (Python Script)**

The Auditor is a lightweight Python script scheduled to run daily (e.g., via a cron job in a Docker container).

* **Purpose:** Reads the database, queries the Wise Old Man (WOM) and Discord APIs, updates volatile data (like display names and clan memberships), and audits the roster for discrepancies, logging all findings.

### **D. The ETL Pipeline (Data Transformation)**

* **Purpose:** Runs on a schedule in Docker to ingest raw data from Discord webhooks (using the Clan Chat Webhook plugin) and a JSON roster export provided by the Auditor. It normalizes this data into local SQLite databases.
* **Pipeline Sequence:**
  1. **Ingest Webhooks:** Pulls raw JSON from Discord.
  2. **Fetch Item Prices:** Syncs historical pricing from the OSRS Wiki.
  3. **Parse Engine:** Extracts actionable metrics via Regex and assigns dynamic prices.
  4. **Roster Enrichment:** Maps raw in-game names to static Discord IDs using the Auditor's JSON export, handling alt accounts, historical names, and clan leaver grace periods.
  5. **Transform Data:** Aggregates the enriched data into fast, public-facing leaderboard tables.
  6. **Discord PB Poster:** Optionally pings members dynamically when their static ID achieves a new personal best.


### **E. The Dashboard UI (Streamlit Frontend)**

* **Purpose:** A lightweight, public-facing web interface for clan members. It provides read-only access to leaderboards, drop logs, and member statistics by querying the SQLite databases built by the ETL pipeline.


## **3. Database Architecture (The Workbook)**

The Google Sheet is divided into six strictly purposed tabs:

### **System_Schema**

**Immutable Tab Name:** `System_Schema`  
The master dictionary. Both the Web App and the Auditor read this tab first to understand the database rules dynamically.

| Column Header (Database) | Code Key | Data Type | Required | Notes / Auditor Action |
| :---- | :---- | :---- | :---- | :---- |
| Discord ID | discord_id | string | **TRUE** | 18-digit Snowflake. Primary Key. |
| Discord Name | discord_name | string | FALSE | Overwritten by Auditor daily. |
| User Notes | user_notes | string | FALSE | Manually entered via Web UI. General notes or fixed alias for the member. |
| Clan Rank | clan_rank | string | FALSE | The user's actual assigned rank. Auditor compares in-game & Discord ranks against this for errors. |
| Clan Rank Date | clan_rank_date | date | FALSE | Date the clan rank was assigned. |
| WOM IDs | wom_ids | list | FALSE | Manually entered via Web UI. Comma-separated (e.g., 3123231, 234243) |
| RSNs | rsns | list | FALSE | Overwritten by Auditor daily. Comma-separated (e.g., Billy, FE Billy) |
| Account Notes | account_notes | list | FALSE | Manually entered via Web UI. Comma-separated notes (e.g., Main, PK Build). |
| Account Clan | account_clan | list | FALSE | Fetched from WOM API daily by Auditor. Comma-separated clan names (uses 'Unknown' if none). |
| Game Ranks | game_ranks | list | FALSE | Fetched from WOM API daily. Comma-separated in-game ranks. Compared by Auditor against Clan Rank. |
| Discord Ranks | discord_ranks | list | FALSE | Fetched from Discord API by Auditor. Comma-separated list of static Role IDs. Web UI translates to readable names. |
| Join Date | join_date | date | FALSE | Fetched from Discord API and set once by Auditor if empty. |
| System Flags | system_flags | list | FALSE | Comma-separated alerts generated by Auditor (e.g., 'Not in Discord'). |
| Admin Flags | admin_flags | list | FALSE | Comma-separated admin tags (e.g., 'Banned') or acknowledged system flags. |
| Rank History | rank_history | kv_list | FALSE | Appended by Web App on rank change: [Rank]:[YYYY-MM-DD] |
| Name History | name_history | string | FALSE | Overwritten by Auditor. Nested JSON string mapping WOM IDs to arrays of name changes. |

### **Reference_Data**

**Immutable Tab Name:** `Reference_Data`  
Holds the clan variables so they do not need to be hardcoded into the Python/JS code. This allows leadership to adjust rank mappings without touching the code.

| Column Header | Code Key | Data Type | Notes |
| :--- | :--- | :--- | :--- |
| Clan Rank | clan_rank | string | The official clan rank name (e.g., Corporal, General). Primary Key for this table. |
| Required Discord Roles | required_discord_roles | list | Discord Role Snowflakes the user MUST have (e.g., 123456789). |
| Allowed Discord Roles | allowed_discord_roles | list | Optional Role Snowflakes the user is allowed to hold (e.g., Event Staff). |
| Excluded Discord Roles | excluded_discord_roles | list | Role Snowflakes that will immediately flag the user if held. |
| Main In-Game Rank | main_in_game_rank | string | The primary in-game rank the user must hold on at least one account. |
| Allowed Alt Ranks | allowed_alt_ranks | list | Permitted in-game ranks for any additional linked accounts (e.g., Smiley). |
| Max Clan Accounts | max_clan_accounts | integer | The maximum number of accounts this member is allowed to have in the WOM clan. |
| Max Inactive Days | max_inactive_days | integer | Number of days without activity before the user is flagged as inactive. |
| Notes / Description | notes | string | Edited via Web UI. Description of the rank or its purpose. |

**Copy-Pasteable Headers for Google Sheets:**

| Clan Rank | Required Discord Roles | Allowed Discord Roles | Excluded Discord Roles | Main In-Game Rank | Allowed Alt Ranks | Max Clan Accounts | Max Inactive Days | Notes / Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| | | | | | | |

*(Example Row - Transposed for readability)*
* **Clan Rank:** Corporal
* **Required Discord Roles:** 1029384756, 5647382910
* **Allowed Discord Roles:** 8888888888
* **Excluded Discord Roles:** 9999999999
* **Main In-Game Rank:** Corporal
* **Allowed Alt Ranks:** Smiley
* **Max Clan Accounts:** 1
* **Max Inactive Days:** 90
* **Notes / Description:** Standard member rank, granted after trial period.

### **System_Config**

**Immutable Tab Name:** `System_Config`  
A key-value store for global settings used by both the Web App and The Auditor.

| Column Header | Code Key | Data Type | Notes |
| :--- | :--- | :--- | :--- |
| Setting Name | setting_name | string | The exact name of the setting. Primary Key. |
| Value | value | string | The configured value. |
| Description | description | string | Human-readable explanation of what the setting does. |

**Copy-Pasteable table for Google Sheets:**

*(note: Ensure settings are updated and clan name is set correctly before deployment)*
| Setting Name | Value | Description |
| :--- | :--- | :--- |
| Target Clan Name | ENTER_CLAN_NAME_HERE | The exact WOM Group Name to filter in-game ranks against and check clan departures. do not include quations eg: clan name |

### **Discord_Roles**

**Immutable Tab Name:** `Discord_Roles`
Managed entirely by The Auditor to track historical and current Discord Roles without hardcoding volatile names.

| Column Header | Code Key | Data Type | Notes |
| :--- | :--- | :--- | :--- |
| Role ID | role_id | string | 18-digit Snowflake. Primary Key. |
| Role Name | role_name | string | The human-readable name of the role. |
| Status | status | string | 'OK' or 'Not Found'. Updated by the Auditor. |

**Copy-Pasteable Headers for Google Sheets:**

| Role ID | Role Name | Status |
| :--- | :--- | :--- |
| | | |

### **Database (The Main Roster)**

**Immutable Tab Name:** `Database`  
The single-page, highly readable master roster that follows the System_Schema.

**Copy-Pasteable Headers for Google Sheets:**

| Discord ID | Discord Name | User Notes | Clan Rank | Clan Rank Date | WOM IDs | RSNs | Account Notes | Account Clan | Game Ranks | Discord Ranks | Join Date | System Flags | Admin Flags | Rank History | Name History |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| | | | | | | | | | | | | | | | |

*(Example Row - Transposed for readability)*

* **Discord ID:** 123456789012345678  
* **Discord Name:** zezima_gaming  
* **User Notes:** Original founder, also goes by Zez.
* **Clan Rank:** Corporal  
* **Clan Rank Date:** 2024-06-20  
* **WOM IDs:** 45892, 45893  
* **RSNs:** Zezima, Iron Zezima  
* **Account Notes:** Main, Iron Alt  
* **Account Clan:** MyClan, Unknown  
* **Game Ranks:** Corporal, Unknown  
* **Discord Ranks:** 1029384756, 5647382910  
* **Join Date:** 2024-01-15  
* **System Flags:** OK  
* **Admin Flags:** Banned, Rank Mismatch  
* **Rank History:** Recruit:2024-01-15, Corporal:2024-06-20
* **Name History:** {"45892":[{"old":"Zezima","new":"IronZez","date":"2025-08-14"}]}

### **Audit_Log**

**Immutable Tab Name:** `Audit_Log`  
A human-readable, append-only log for tracking all significant events and discrepancies. Both the Web App and The Auditor can write to this log. It is not designed to be read programmatically, but rather to provide a clear history of changes for Admins.

| Column Header | Notes |
| :--- | :--- |
| Timestamp | ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ). Automatically generated. |
| Source | The system component that generated the log (e.g., 'Web App', 'The Auditor'). |
| User | The Google account email of the Admin making the change, or the script identifier (e.g., 'The Auditor'). |
| Log Entry | A free-text description of the event. |

**Copy-Pasteable Headers for Google Sheets:**

| Timestamp | Source | User | Log Entry |
| :--- | :--- | :--- | :--- |
| | | | |

*(Example Entries)*
* `2026-03-18T11:45:00Z | Web App | admin_user@email.com | Manual Update - zezima_gaming (123456789012345678): Clan Rank manually set to 'Corporal'.`
* `2026-03-19T02:05:10Z | The Auditor | auditor_bot | Flag Added - zezima_gaming (123456789012345678): Flagged as 'Rank Mismatch' (Expected 'Corporal', found 'Recruit').`
* `2026-03-19T02:05:11Z | The Auditor | auditor_bot | Flag Added - IronZez (987654321098765432): Flagged as 'Not in WOM Clan' (Account 'Iron Zezima' is in clan 'Other Clan').`

## **4. Data Flow & Execution Rules**

### **The Web App Workflow (Frontend)**

**Function:** Provides a safe, validated interface for Admins to manage clan roster data without accessing the raw spreadsheet.

**Workflow:**
1. An **Admin** opens the Web App UI.
2. **Search/Create:** They query an existing member or create a new entry using a **Discord ID** (the primary key). The Web App enforces uniqueness, preventing duplicate rows for the same Discord ID.
3. **Data Entry & WOM Lookup:** They add alt accounts by searching a player's RSN via the built-in search tool. The Web App securely queries the Wise Old Man API to find and lock in the static **WOM ID**. The Web App sanitizes all inputs (stripping user-entered commas) and constructs the comma-separated strings programmatically to prevent formatting errors.
4. **Rank Management:** They manually set or update the **Clan Rank** and **Clan Rank Date** as needed.
5. **Background Formatting:** If a new Clan Rank is set, the Web App logic automatically appends the rank and date to the **Rank History** string.
6. **Commit & Log:** The Web App writes the updated row to the `Database` tab and appends a record of the change (e.g., "Updated Clan Rank to Corporal") to the `Audit_Log` tab.

### **The Auditor Workflow (Backend Automation)**

**Function:** A scheduled daily script that handles volatile data synchronization and logical evaluations to keep the database accurate and flag discrepancies.

**Workflow:**
1. **Fetch Setup:** The script reads the `System_Schema` to map database columns and reads `Reference_Data` to understand the current rank rules and Discord role mappings.
2. **Role Syncing:** It fetches the guild roles from the Discord API, updating the `Discord_Roles` tab (adding new roles as 'Active', marking missing ones as 'Deleted').
3. **Member Discovery:** It fetches the full member list from the Discord API. Any Discord user not already in the `Database` is automatically appended as a new row. If an existing database member is missing from the Discord fetch, a 'Not in Discord' flag is added to `System Flags` (unless it exists in `Admin Flags`).
4. **WOM Data Syncing:** For every user row, it parses the `WOM IDs`, queries the Wise Old Man API, and updates the `RSNs` and `Account Clan` columns.
   * **Name History Tracking:** As a background task, the Auditor saves the raw JSON of the group roster to a local SQLite database (`data/history.db`). It compares the current RSN against its local memory, and if a change is detected, fetches and stores the complete name change history for that specific player. The Auditor then serializes this history into a nested JSON string and syncs it to the `Name History` column in the Google Sheet. If it detects corrupted JSON in the sheet, it overwrites it with a fresh copy from the local database.
4. **Discord Data Syncing:** It queries the Discord API to update the `Discord Name` and `Discord Ranks` for existing members.
5. **Auditing & Logging:** It cross-references the newly synced data against the target truth values, logging discrepancies to the `Audit_Log` tab for human review. Specific checks include:
   * **Rank Mismatch:** Checks if the assigned `Discord Ranks` correctly reflect the manually set `Clan Rank` according to the `Reference_Data`.
   * **Not in WOM Clan:** Flags if any account in the `Account Clan` list is 'Unknown' or belongs to a different clan.

### **Data Handoff & Concurrency (Auditor -> ETL -> Dashboard)**

To safely pass data from the backend to the public-facing dashboard, the system uses specific handoff techniques:
1. **Atomic Auditor Export:** At the end of its daily run, the Auditor generates a JSON file (`roster_export.json`) representing the complete mapped roster (including system and admin flags). To prevent the ETL from reading a partially written file, the Auditor writes to a temporary file (`.tmp`) and uses an instantaneous OS-level rename to make the swap atomic.
2. **Smart Lock Ingestion:** The ETL pipeline reads this JSON file. To prevent manual runs of the ETL colliding with scheduled cron runs, the entry-point script uses a file-based "Smart Lock" (Wait -> Retry -> Timeout).
3. **Blue/Green SQLite Reads:** SQLite locks the entire database file during write operations. To prevent the Dashboard UI from crashing or lagging while the ETL is writing data, the ETL employs a Blue/Green deployment strategy, writing to an alternate "Green" database (`_alt.db`). Once finished, the Streamlit app swaps to the new DB instantly.
4. **Enriched Data Grouping:** To ensure that historical name changes and multi-account setups (alts) don't fracture a user's dashboard statistics, the ETL utilizes `4_enrich_roster.py` to map the volatile Game Names back to their static `Discord_ID` before standardizing the tables for the Dashboard.


## **5. Standard Flags Dictionary**

To avoid making assumptions, the system uses explicit state and error flags. Because flags are stored as comma-separated lists, a user can have multiple active flags (e.g., `User Not Found, Banned`).

### **Role Status Flags (`Discord_Roles` Tab)**
* **`OK`**: The role was found in the latest Discord API fetch and the name is up-to-date.
* **`Not Found`**: The role ID was not returned by the Discord API.

### **System Flags (`Database` Tab - Set by Auditor)**
* **`OK`**: The user was found in the Discord API and all data synced successfully without errors.
* **`Not in Discord`**: The Discord ID was not returned in the server member list.
* **`Rank Mismatch`**: The user's Discord roles do not match their assigned `Clan Rank`.
* **`In-Game Rank Mismatch`**: The user's synced in-game ranks do not align with their expected Main or Alt ranks.
* **`Not in WOM Clan`**: One or more of the user's `WOM IDs` is registered to a different clan.
* **`Banned in Clan`**: One or more of the user's `WOM IDs` is marked as banned in-game but is still occupying a slot in the WOM group roster.
* **`Multiple Clans`**: The user has at least one account in the target clan and at least one account in another clan.
* **`Archived`**: The user has no clan rank, no managed discord roles, and is not in the WOM clan. The Auditor will skip most API lookups for them to improve performance.

### **Admin Flags (`Database` Tab - Set via Web UI or CLI Resolver)**
* **`Banned`**: Used to blacklist a user. If a user with this flag rejoins the Discord server, the Auditor will append them, but the "Banned" flag will persist, alerting Admins in reports.
* **`On Leave`**: A standard flag for members on an approved hiatus.
* **Acknowledge System Flags**: Admins can type the exact name of a System Flag (e.g., `Rank Mismatch`) here to tell the Auditor to ignore the discrepancy. This can be done manually via the Web UI or interactively in bulk using the `audit_resolver.py` CLI tool.