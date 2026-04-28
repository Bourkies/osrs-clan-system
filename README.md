# OSRS Clan Management System

A full-stack ecosystem designed to manage Old School RuneScape (OSRS) clan rosters, track player statistics, and provide a public-facing dashboard. While originally developed for a specific clan, the system is highly customizable—feel free to deploy it for your own setup or fork it to fit your community's needs! It integrates directly with Google Sheets, Discord APIs, and the Wise Old Man (WOM) API.

## System Overview

This monorepo consists of four primary components, designed to separate backend administrative tasks from public-facing data visualization.

1. **Admin Frontend (Google Apps Script):** A serverless web application that provides a safe interface for clan leaders to update ranks and link alt accounts into a master Google Sheet database without risking human error.
2. **Backend Auditor (Python):** A scheduled Python service that reads the Google Sheet, syncs external data (Discord user updates, WOM clan changes), audits for rank discrepancies, and generates roster exports.
3. **ETL Pipeline (Python):** A data extraction and transformation pipeline that ingests Discord webhook chat logs and the Auditor's JSON exports, processing them into optimized local SQLite databases.
4. **Dashboard UI (Streamlit):** A read-only, public-facing web dashboard where clan members can view leaderboards, recent drops, and personal statistics.

## Architecture & Docker Orchestration

The Backend Auditor, ETL Pipeline, and Dashboard UI are designed to run concurrently as isolated Docker containers orchestrated via `docker-compose`. 

To ensure data persistence and easy backups, all stateful data is mapped to host volumes located at the root of this project:

*   `shared_data/`: Contains SQLite databases, JSON exports, CSV backups, and system logs.
*   `shared_config/`: Contains non-sensitive configuration files (`.toml`) and image assets used by the UI.
*   `shared_secrets/`: Contains sensitive API keys, `.env` files, and Google Service Account credentials. **(Never committed to Git)**.

By keeping the data decoupled from the application logic, the entire system can be updated via `git pull` and container rebuilds without any risk of data loss.

## Getting Started

To deploy or configure specific parts of the system, please refer to the dedicated READMEs in their respective folders:

*   Admin Webapp Setup
*   Backend Auditor Setup
*   ETL Pipeline Setup
*   Dashboard UI Setup

### Core Blueprint

For a deep dive into the system's data schema, logic flows, and architecture rules, see the **System Architecture** document.

## Server Deployment & Updates

Because this system relies heavily on Docker and host-mapped volumes, deploying to a production Linux server is straightforward and completely free using Git.

### 1. Initial Server Setup
1. **Clone the Repository:** Log into your server and clone your repository.
   `git clone <your-repo-url> osrs-clan-system`
   `cd osrs-clan-system`

2. **Configure Secrets (Crucial):** Since Git explicitly ignores your secret files, you must manually create them on the server.
   * Inside the `shared_secrets/` directory, copy `.env.example` to `.env` and fill out your production variables (ensure `ENV_NAME=prod` is set).
   * Place your Google Service Account `credentials.json` directly into `shared_secrets/`.
   * Copy or create your `secrets.toml` inside `shared_secrets/`.
3. **Configure Shared Configs:** Copy any `.example.toml` files from `shared_config/` to their live counterparts (e.g., `config.example.toml` -> `config.toml`) and adjust settings as needed. This includes:
   * `config.toml`: Main configuration for the ETL pipeline.
   * `historical_collection_logs.toml`: Tracks initial clan collection log counts.
4. **Start the Ecosystem:** Run Docker Compose to build the images and spin up the containers in the background.
   `docker-compose up -d --build`


### 2. Updating the Live Server
When you make changes to the codebase locally and push them to your repository, updating the live server takes seconds and results in **zero data loss** (since your databases and caches are safely mapped to the host machine).
`git pull`
`docker-compose up -d --build`

Docker will automatically detect which containers had code changes, shut them down gracefully, rebuild the specific image, and spin them back up.

### 🔒 Securing the Dashboard with a Cloudflare Tunnel

To safely expose the Streamlit Dashboard to the public web without opening any firewall ports on your server (and to easily bypass CGNAT restrictions), this project uses a Cloudflare Tunnel.

**1. Create the Tunnel**
1. Log into your [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) dashboard.
2. Navigate to **Networks** -> **Tunnels** and click **Add a tunnel**.
3. Select **Cloudflared** as the connector type.
4. Name your tunnel (e.g., `osrs-clan-dashboard`) and click **Save tunnel**.
5. You will be shown installation commands. Look for the long string of characters starting with `ey...` in the provided command. This is your secret token. Copy it.

**2. Configure the Server Secrets**
1. Open your `shared_secrets/.env` file on your host machine.
2. Add the token you copied as a new variable. For example:
   `TUNNEL_TOKEN=eyYourExtremelyLongCloudflareTokenHere...`

**3. Route the Traffic**
1. Back in the Cloudflare Dashboard, click **Next** to move to the routing step.
2. Configure your **Public Hostname** (e.g., `clan.yourdomain.com`).
3. Under **Service**, configure the following settings:
   * **Type:** `HTTP`
   * **URL:** `osrs_dashboard_ui:8501`
4. Click **Save Tunnel**.

When you spin up the Docker ecosystem (`docker-compose up -d`), the `cloudflared` container will automatically read the token from your `.env` file, establish a secure outbound connection to Cloudflare, and proxy traffic seamlessly to your dashboard—completely isolating it from the public internet!

## External Assets Setup (Action Required)

To avoid storing copyrighted or heavy binary assets in this repository, you must manually download and place a few files into your `shared_config/assets/` folder before running the dashboard:

1. **`items-complete.json`:** Required for the Clan Collection Log icons. Download it from the osrsreboxed-db repository and place it at `shared_config/assets/items-complete.json`.
2. **Background Images:** For customized pages like the Hardcore Deaths page, place your background images (e.g., `1080px-Graveyard_of_Shadows.png`) in `shared_config/assets/Page_backgrounds/`.

## Attributions & Licensing

This project is licensed under the MIT License. See LICENSE for details.

**Assets & Data Sources:**
* Data and images related to Old School RuneScape are the property of Jagex Ltd. 
* Images and API endpoints used in this project are heavily sourced from the Old School RuneScape Wiki under the **CC BY-NC-SA 3.0** license.
* Item data and base64 icon strings are sourced from the excellent osrsreboxed-db project.

**Note on AI Generation:**
This project was created collaboratively with Google's Gemini. While the logic, architecture, and functionality have been guided and tested by a human developer, much of the boilerplate code and documentation was AI-generated.