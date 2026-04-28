@echo off
REM This script runs the Streamlit Dashboard for the OSRS Clan Reporter.

echo Launching Dashboard...
echo Your web browser should open automatically.
echo Press Ctrl+C in this window to stop the server.
echo.

REM Execute the Streamlit app located in the src folder
streamlit run Home.py

pause