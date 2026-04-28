# OSRS Clan Management - Admin Frontend

This folder contains the files for the Google Apps Script-based Web App, which acts as the frontend UI for clan administrators.

## Files

- `Code.gs`: The backend server-side logic written in Google Apps Script. It handles serving the HTML, processing form submissions, and interacting with the Google Sheet.
- `Index.html`: The main HTML file that defines the structure of the web form.
- `JavaScript.html`: The client-side JavaScript code that handles UI dynamics, form validation, and communication with the `Code.gs` backend.
- `RanksManager.html`: Client-side UI and logic for the "Manage Ranks" modal.
- `WomLookup.html`: The client-side JavaScript for handling Wise Old Man (WOM) player lookups and UI interactions when linking accounts.

## Setup Instructions

1.  **Create a new Google Sheet:** This will be your database.
2.  **Create and Setup Tabs:** 
    - Create six tabs named exactly: `System_Schema`, `Reference_Data`, `System_Config`, `Discord_Roles`, `Database`, and `Audit_Log`.
    - Copy the respective column headers into row 1 for each tab from the `system_architecture.md` document.
3.  **Lock the Sheets (Data Protection):**
    - Right-click each tab at the bottom (or use `Data` > `Protect sheets and ranges`) and select **Protect sheet**.
    - Select **Show a warning when editing this range**.
    - *Note: Admins need Editor access to the sheet so the Web App can execute under their Google account. The warning prevents accidental manual edits, forcing them to use the Web App UI safely.*
4.  **Copy the Sheet ID:** The ID is the long string of characters in the URL (e.g., `.../d/THIS_IS_THE_ID/edit...`).
5.  **Open Apps Script:** In your Google Sheet, go to `Extensions` > `Apps Script`.
6.  **Replace Spreadsheet ID:** In `Code.gs`, replace the placeholder `YOUR_SPREADSHEET_ID` with the ID you copied.
7.  **Copy Files:**
    -   Copy the contents of `Code.gs` from this folder and paste it into the `Code.gs` file in your Apps Script editor.
    -   Create a new HTML file in the editor (`File` > `New` > `HTML file`) and name it `Index`. Copy the contents of `Index.html` into it.
    -   Create another new HTML file and name it `JavaScript`. Copy the contents of `JavaScript.html` into it.
    -   Create another new HTML file and name it `RanksManager`. Copy the contents of `RanksManager.html` into it.
    -   Create another new HTML file and name it `WomLookup`. Copy the contents of `WomLookup.html` into it.
8.  **Initial Deployment:**
    -   Click the `Deploy` button in the top right.
    -   Select `New deployment`.
    -   For `Select type`, choose the gear icon and select `Web app`.
    -   Under **Execute as**, select **User accessing the web app**.
    -   In the `Who has access` dropdown, select **Anyone with a Google account**. 
    -   *Security Note: This is safe! Because the app executes as the user, Google strictly enforces the spreadsheet's sharing permissions. If an unauthorized person opens the URL, the script will be denied access to the spreadsheet and crash. Only users explicitly granted Editor access to the underlying Google Sheet can successfully use the Web App.*
    -   Click `Deploy`.
9.  **Authorize Permissions (The "Unverified App" Warning):** 
    -   The first time you (or any Admin) open the Web App, Google will show a "Google hasn't verified this app" warning. This is 100% normal for custom, internal scripts.
    -   To proceed, click **Advanced**, then click **Go to [Your Project Name] (unsafe)**, and click **Allow**. Each Admin will only have to do this once.
10. **Get URL:** After deployment, you will be given a Web App URL. This is the link your Admins will use to access the management UI.