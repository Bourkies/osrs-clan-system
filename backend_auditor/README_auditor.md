# OSRS Clan Management - The Auditor

This folder contains the files for the Python script, "The Auditor," which acts as the backend automation worker. It is designed to be deployed as a Docker container, running on a schedule (e.g., daily) to sync data from external APIs and audit the clan roster for discrepancies.

## Files

### Current Responsibilities
- `run_auditor.py`: The orchestrator and main entry point. Parses arguments and calls the individual modules in sequence.
- `db_manager.py`: The single source of interaction with the Google Sheets API. Utilizes Smart JIT (Just-In-Time) Indexing for completely concurrency-safe database writes.
- `backup_manager.py`: Connects to `db_manager` to export Google Sheets to CSVs, managing a Grandfather-Father-Son daily retention policy.
- `webhook_manager.py`: Formats and dispatches Discord embeds, respecting rate limits.
- `constants.py`: Centralized file for Enums (like System Flags) to prevent magic string usage.
- `file_utils.py`: Safe atomic file writing utilities to bypass host-level file lock crashes.
- `wom_client.py`: Handles Wise Old Man API requests, rate limits, and local caching in the `data/` directory.
- `discord_sync.py`: Fetches roles and members from Discord, discovering new members and updating volatile Discord data.
- `wom_sync.py`: Uses `wom_client.py` to fetch accounts, updating RSNs, game ranks, and clan statuses.
- `sqlite_manager.py`: Local database manager for tracking raw JSON snapshots and a normalized history of player name changes.
- `audit_logic.py`: An extensible, Object-Oriented rules engine (`BaseAudit`) that cross-references synced data to flag discrepancies, manages `System Flags`, and formats Discord webhook reports.
- `dashboard_exporter.py`: Generates a complete JSON roster export (including IDs, flags, and name-change history) for the ETL Dashboard. Uses atomic writes to prevent database locking.
- `CLI Tools`: Several setup scripts (e.g., `account_linker.py`, `rank_matcher.py`, `audit_resolver.py`) designed to help administrators rapidly sort untracked data.

*(Note: State data, logs, and configurations have been abstracted to the root `shared_data` and `shared_secrets` folders.)*


## Setup Instructions

### 1. Google Cloud Service Account Setup

The Auditor needs a Google Cloud Service Account to securely access and modify the Google Sheet without needing a human user's login.

1.  **Create a Google Cloud Project:** Go to the Google Cloud Console and create a new project.
2.  **Enable APIs:** In your new project, go to the "APIs & Services" dashboard and enable the **Google Drive API** and the **Google Sheets API**.
3.  **Create Service Account:**
    -   Go to "IAM & Admin" > "Service Accounts".
    -   Click "Create Service Account".
    -   Give it a name (e.g., "osrs-clan-auditor") and a description.
    -   Grant it the `Editor` role for now to ensure it has permissions.
4.  **Generate JSON Key:**
    -   After creating the account, find it in the list, click the three-dot menu under "Actions", and select "Manage keys".
    -   Click "Add Key" > "Create new key".
    -   Choose **JSON** as the key type and click "Create".
    -   A `.json` file will be downloaded. **This file is secret and sensitive.** Rename it to `credentials.json` and place it in the root `shared_secrets/` directory.

### 2. Share the Google Sheet

1.  Open the `credentials.json` file and find the `client_email` address (it will look something like `...gserviceaccount.com`).
2.  Open your master Google Sheet.
3.  Click the "Share" button in the top right.
4.  Paste the service account's email address into the sharing dialog and give it **Editor** access. Click "Send".

### 3. Discord Bot Setup

1.  Go to the Discord Developer Portal.
2.  Create a "New Application" and go to the "Bot" tab.
3.  **Crucial:** Scroll down to "Privileged Gateway Intents" and enable **Server Members Intent** and **Message Content Intent**.
4.  Reset and copy the **Bot Token**.
5.  Use the OAuth2 URL Generator to invite the bot to your server (it only needs "View Channels" and "Read Roles" permissions).

### 4. Local Development Setup (Without Docker)

For testing and running the script locally, it is highly recommended to use a Python virtual environment to keep dependencies isolated.

1.  Make sure you have Python 3 installed.
2.  **Create a Virtual Environment:**
    Open your terminal in the `backend_auditor` directory and run:
    ```bash
    python -m venv venv
    ```
3.  **Activate the Virtual Environment:**
    *   **VS Code:** Press `Ctrl+Shift+P` (or `Cmd+Shift+P`), search for `Python: Select Interpreter`, and select the one showing `('venv': venv)`. Open a *new* terminal in VS Code, and it should activate automatically (you will see `(venv)` at the start of your prompt).
        *   if you dont se the (venv) then use `cd backend_auditor` then `.venv\Scripts\Activate.ps1`
    *   **Windows (Manual):** `venv\Scripts\activate`
    *   **Mac/Linux (Manual):** `source venv/bin/activate`
4.  **Install the required libraries:** 
    Make sure `(venv)` is visible in your terminal prompt, then run:
    `pip install -r requirements.txt`
5.  **Update Configuration:** Copy `.env.example` to the root `shared_secrets/` folder and rename it `.env`. Fill in the values.


6.  **Run the script:**
    *   Standard run: `python run_auditor.py`
    *   Ignore WOM cache: `python run_auditor.py --force-wom`
    *   Run audits silently (no Discord ping): `python run_auditor.py --no-webhook`
    *   Sync APIs silently (skip audits completely): `python run_auditor.py --sync-only`

## Setup & Onboarding Tools

If you are setting up the database for the first time, or resolving daily warnings, you can use the built-in CLI tools locally:

1.  **The Account Linker (`python account_linker.py`)**
    *   *Requirement:* You must run `run_auditor.py` at least once so it caches WOM IDs.
    *   *Usage:* Runs a fuzzy-search against your database's Discord users and known RSNs, helping you quickly link missing Wise Old Man accounts to the correct Discord member.

2.  **The Rank Matcher (`python rank_matcher.py`)**
    *   *Requirement:* Ensure your `Reference_Data` tab is filled out with your clan's Discord Role IDs and In-Game Rank names.
    *   *Usage:* Loops through all members missing a Clan Rank, suggesting the most logical rank based on their existing Discord roles or in-game rank, allowing you to bulk-assign missing ranks safely.

3.  **The Audit Resolver (`python audit_resolver.py`)**
    *   *Requirement:* Run a silent audit (which you can do via the tool's startup prompt) so system flags are updated in Google Sheets.
    *   *Usage:* Interactive menu that loops through categories of warning flags (Missing from In-Game Clan, Returning Members, Rank Mismatch, Left Discord, Multiple Clans, Missing RSNs) allowing you to skip/enter sections and resolve issues by applying appropriate Ignore or On Leave flags.

4.  **The Dashboard Exporter (`dashboard_exporter.py`)**
    *   *Usage:* Runs automatically at the end of the daily audit. It exports a JSON file bridging the Auditor with the `etl_pipeline`. No manual execution is typically required.

## Common Edge Cases & Troubleshooting

### The "Unknown" Alt Account (WOM Name Change Merges)
Occasionally, you may see an `Unknown` account appear in a member's `RSNs` list alongside their actual name. This happens due to a delay in tracking name changes on the Wise Old Man (WOM) API:
1. A player changes their name (e.g., `OldName` -> `NewName`) but it isn't immediately registered on WOM.
2. They join the clan as `NewName`. WOM doesn't know their history, so it creates a brand new WOM ID for `NewName`.
3. Later, the automated system or a user explicitly submits a name change request on WOM. WOM realizes `OldName` is actually `NewName`, and updates the *original* WOM ID with the new name.
4. The *second* WOM ID is now orphaned. Because it no longer has a valid OSRS name attached, WOM returns it as `Unknown`.

**Resolution:** The `account_linker.py` script will usually catch the correct, original WOM ID and suggest linking it. Once linked, you can safely delete the orphaned/ghost WOM ID from the member's `WOM IDs` cell in the Google Sheet via the Web App.