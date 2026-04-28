# OSRS Clan Management - Dashboard UI

This folder contains the public-facing Streamlit application for the clan. It serves as a read-only portal for clan members to view stats, leaderboards, and recent drops, effectively bridging the data from the backend admin tools to the community.

## Features
* **Lightweight:** Powered by Streamlit for rapid web prototyping and deployment.
* **Separation of Concerns:** Does not connect to Discord, WOM, or the Google Sheets API directly. All data processing is strictly handled by the `etl_pipeline` prior to viewing.
* **Zero Downtime Updates:** Uses a "Blue/Green" database strategy.

## Blue/Green Database Reads

Because the ETL pipeline processes thousands of records into SQLite, those database files must be temporarily locked by the operating system during writes. If the Streamlit dashboard attempts to read the database at the exact moment the ETL is writing, it will crash.

To prevent this, the Dashboard UI uses a Blue/Green read strategy. The ETL will always write to an alternate `.db` file (e.g. `_alt.db`). Once the ETL is completely finished, it instantly swaps a pointer/flag in the configuration, causing this Streamlit app to seamlessly read from the newly updated database without dropping any user connections.

## Deployment

This application is managed and spun up via the root `docker-compose.yml`. Please ensure the host volumes (specifically `shared_data` and `shared_config`) are properly configured before running `docker-compose up`.