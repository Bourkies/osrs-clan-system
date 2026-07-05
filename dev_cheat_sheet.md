# OSRS Clan System - Developer Cheat Sheet

This document contains quick copy-paste commands for managing the Docker containers and manually triggering individual scripts in both Dev and Prod environments.

## 🐳 Docker Management
*If on the live Ubuntu server, ensure you are in the project folder first:*
`cd ~/ai-server/osrs-clan-system`

*Run these from the root directory (`osrs-clan-system/`)*

**Start the ecosystem (in the background):**
`docker compose up -d --build`

**Stop the ecosystem:**
`docker compose down`

**View real-time logs for a specific container:**
`docker compose logs -f backend_auditor`
`docker compose logs -f etl_pipeline`
`docker compose logs -f dashboard_ui`

---

## 🚀 Deployment & Updates
*Run these commands on your live server to pull the latest code and seamlessly restart the ecosystem with zero data loss.*

**Pull the latest code from the repository:**
`git pull`

**Rebuild and restart the containers in the background:**
`docker compose up -d --build`

---

## �️ Backend Auditor Commands
*The Auditor runs autonomously on a cron schedule, but you can safely trigger it manually via Docker.*

**Standard Run:**
`docker compose exec backend_auditor python backend_auditor/run_auditor.py`

**Specialized Runs (Using Flags):**
Force clear and refresh the Wise Old Man cache:
`docker compose exec backend_auditor python backend_auditor/run_auditor.py --force-wom`

Run full sync and audit, but DO NOT post to the Discord webhook:
`docker compose exec backend_auditor python backend_auditor/run_auditor.py --no-webhook`

Sync Discord and WOM to the database, but skip audits completely:
`docker compose exec backend_auditor python backend_auditor/run_auditor.py --sync-only`

**CLI Admin Tools:**
Run the Account Linker (Fuzzy match unlinked accounts):
`docker compose exec backend_auditor python backend_auditor/account_linker.py`

Run the Rank Matcher (Bulk-assign missing clan ranks):
`docker compose exec backend_auditor python backend_auditor/rank_matcher.py`

Run the Audit Resolver (Interactively resolve warning flags):
`docker compose exec backend_auditor python backend_auditor/audit_resolver.py`

---

## ⚙️ ETL Pipeline Commands
*The ETL pipeline runs autonomously, but individual steps can be executed manually for debugging or backfilling.*

**Run the Full Pipeline (Safely handled via Smart Lock):**
`docker compose exec etl_pipeline python etl_pipeline/src/run_etl.py`

**Run Individual ETL Steps:**
1. Fetch data from Discord (Uses time_settings in config.toml):
`docker compose exec etl_pipeline python etl_pipeline/src/1_fetch_data.py`

2. Fetch dynamic item prices from the OSRS Wiki API:
`docker compose exec etl_pipeline python etl_pipeline/src/2_fetch_item_prices.py`

3. Parse raw chat/broadcasts into normalized tables:
`docker compose exec etl_pipeline python etl_pipeline/src/3_parse_engine.py`

4. Run the Roster Enricher (Link Discord IDs to RSNs via Auditor JSON):
`docker compose exec etl_pipeline python etl_pipeline/src/4_enrich_roster.py`

5. Transform data into the dashboard-optimized SQLite databases (Blue/Green):
`docker compose exec etl_pipeline python etl_pipeline/src/5_transform_data.py`

6. Update the Personal Bests (PBs) Discord channel:
`docker compose exec etl_pipeline python etl_pipeline/src/6_post_pbs_to_discord.py`

---

## 💻 Local Development (Non-Docker)
If you are developing locally without Docker, make sure your Python Virtual Environment (`venv`) is activated.

### Setting the Environment to Dev ("Baking it in")
The system determines if it is in Dev or Prod by looking for the `ENV_NAME` environment variable (defaulting to `prod` if not found). 
To avoid typing this every time you run a command in your VSCode terminal, open your **local** `shared_secrets/.env` file and add: `ENV_NAME=dev`

Because `shared_secrets/` is explicitly ignored by Git and never copied to your live server, your live server will safely default to `prod`, while your local machine will automatically isolate state files!

### Running Backend Auditor Locally
**Windows (PowerShell):**
Enable the env: `.\venv\Scripts\Activate.ps1`

**Standard Run:**
`python backend_auditor/run_auditor.py`

**Specialized Runs:**
`python backend_auditor/run_auditor.py --force-wom`
`python backend_auditor/run_auditor.py --no-webhook`
`python backend_auditor/run_auditor.py --sync-only`

**CLI Admin Tools:**
`python backend_auditor/account_linker.py`
`python backend_auditor/rank_matcher.py` Note: 2-y-n
`python backend_auditor/audit_resolver.py`


### Running ETL Pipeline Locally
**Run the Full Pipeline:**
`python etl_pipeline/src/run_etl.py`

**Run Individual ETL Steps:**
`python etl_pipeline/src/1_fetch_data.py`
`python etl_pipeline/src/2_fetch_item_prices.py`
`python etl_pipeline/src/3_parse_engine.py`
`python etl_pipeline/src/4_enrich_roster.py`
`python etl_pipeline/src/5_transform_data.py`
`python etl_pipeline/src/6_post_pbs_to_discord.py`

**Start the Streamlit Server:**
`streamlit run dashboard_ui/Home.py`
