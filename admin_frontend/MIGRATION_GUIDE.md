# Admin Frontend - Discord OAuth Migration Guide

This step-by-step guide explains how to transition your **OSRS Clan Management Admin Frontend** from Google Account spreadsheet permissions to **Discord OAuth** with custom domain routing (`clan_spreadsheet.yourdomain.com`), 7-day session persistence, and instant global session revocation.

---

## 📋 Table of Contents
1. [Overview & Security Architecture](#1-overview--security-architecture)
2. [Step 1: Create Discord Developer Application](#step-1-create-discord-developer-application)
3. [Step 2: Update Apps Script Code & Configure Script Properties](#step-2-update-apps-script-code--configure-script-properties)
4. [Step 3: Setup Custom Domain via Cloudflare Worker](#step-3-setup-custom-domain-via-cloudflare-worker)
5. [Step 4: Configure `System_Config` Tab in Google Sheets](#step-4-configure-system_config-tab-in-google-sheets)
6. [Step 5: Lock Down Spreadsheet & Verify](#step-5-lock-down-spreadsheet--verify)
7. [Session Management & Global Revocation](#session-management--global-revocation)

---

## 1. Overview & Security Architecture

To prevent sensitive API keys and secrets from being exposed inside Google Sheet cells, the architecture strictly separates **Operational Clan Variables** (stored in the Google Sheet) from **Application Secrets & OAuth Credentials** (stored in Apps Script `ScriptProperties`).

| Setting Category | Storage Location | Examples | Security Level |
| :--- | :--- | :--- | :--- |
| **OAuth Credentials & Secrets** | Apps Script **`ScriptProperties`** | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_GUILD_ID`, `ADMIN_ACCESS_DISCORD_ROLES`, `DISCORD_REDIRECT_URI` | **100% Private to Script Backend** (Hidden from Google Sheet & Client JS) |
| **Operational Clan Variables** | Google Sheet **`System_Config` Tab** | `Target Clan Name`, `Auth Version` | Visible to Sheet Owner & Service Account |

---

## Step 1: Create Discord Developer Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and sign in.
2. Click **New Application** in the top right. Name it (e.g., `OSRS Clan Roster Manager`) and click **Create**.
3. Under **OAuth2** in the left sidebar:
   - Copy your **Client ID** (save this for Step 2).
   - Click **Reset Secret** to generate a **Client Secret** (copy and save this immediately).
4. Scroll down to **Redirects** and click **Add Redirect**:
   - Add your custom domain redirect: `https://clan_spreadsheet.yourdomain.com`
5. Click **Save Changes** at the bottom of the page.

---

## Step 2: Update Apps Script Code & Configure Script Properties

> [!IMPORTANT]
> **URL Stability**: When updating an existing deployment using **Manage deployments** $\rightarrow$ **New version**, your Google Apps Script Web App URL **remains 100% identical**.

### A. Copy Code Files
1. In your Google Sheet, open `Extensions` > `Apps Script`.
2. Replace the files in your editor with the updated files from the `admin_frontend/` folder:
   - `Code.gs` *(Verify `SPREADSHEET_ID` on line 7)*
   - `Index.html`
   - `JavaScript.html`
   - `UserManager.html`
   - `RanksManager.html`
   - `WomLookup.html`

### B. Configure Secure Script Properties (Secrets & Credentials)
1. In the Apps Script left sidebar, click the **Gear Icon (Project Settings)**.
2. Scroll down to **Script Properties** and click **Edit script properties** $\rightarrow$ **Add script property**.
3. Add the following entries:

| Property Name | Value | Description |
| :--- | :--- | :--- |
| `DISCORD_CLIENT_ID` | `123456789012345678` | Client ID from Discord Developer Portal. |
| `DISCORD_CLIENT_SECRET` | `your_client_secret_here` | Client Secret from Discord Developer Portal. |
| `DISCORD_GUILD_ID` | `987654321098765432` | Your Discord Server ID (Guild Snowflake). |
| `ADMIN_ACCESS_DISCORD_ROLES` | `112233445566778899` | Comma-separated Discord Role IDs authorized to access the Web App (e.g. `@moderator` ID). |
| `DISCORD_REDIRECT_URI` | `https://clan_spreadsheet.yourdomain.com` | Custom domain redirect URL. |

4. Click **Save script properties**.

*Tip: To get your Discord Server ID or Role IDs in Discord, enable Developer Mode (Settings -> Advanced -> Developer Mode), then right-click your Server/Role and click "Copy ID".*

### C. Deploy Web App ("Execute as Me")
1. Click **Deploy** (top right) $\rightarrow$ **Manage deployments**.
2. Click the **Edit (Pencil icon)** on your active Web App deployment.
3. Update deployment settings:
   - **Version**: Select **New version**
   - **Execute as**: Change to **Me (your_email@gmail.com)**
   - **Who has access**: Change to **Anyone**
4. Click **Deploy**. Authorize access if prompted.
5. Copy your **Web App URL** shown on the deployment success screen. You will use this URL in Step 3.

---

## Step 3: Setup Custom Domain via Cloudflare Worker

To route `https://clan_spreadsheet.yourdomain.com` to your Google Apps Script Web App:

### Part A: Create the Worker Script
1. In the Cloudflare left sidebar (Account level), click **Workers & Pages** (or **Compute** $\rightarrow$ **Workers**).
2. Click **Create Application** $\rightarrow$ **Create Worker** (or **Start with Hello World**).
3. Name your worker (e.g. `clan-admin-proxy`) and click **Deploy**.
4. Click **Edit Code** and replace the script with:

```javascript
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const TARGET_GAS_URL = "https://script.google.com/macros/s/YOUR_APPS_SCRIPT_DEPLOYMENT_ID/exec";

    // Forward any incoming query parameters (such as ?code=... or ?logout=1)
    const targetUrl = new URL(TARGET_GAS_URL);
    url.searchParams.forEach((value, key) => {
      targetUrl.searchParams.set(key, value);
    });

    console.log("[Cloudflare Worker] Incoming Request:", url.toString());
    console.log("[Cloudflare Worker] Forwarding to Iframe Target:", targetUrl.toString());

    // Return a responsive full-window container.
    // This allows Google Apps Script to run natively on script.google.com without MIME type or domain-hop errors.
    const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OSRS Clan Management</title>
  <style>
    html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background-color: #f8f9fa; }
    iframe { width: 100%; height: 100%; border: none; display: block; }
  </style>
</head>
<body>
  <iframe id="app-iframe" src="${targetUrl.toString()}"></iframe>
  <script>
    console.log('[Cloudflare Worker Container] Loading iframe src:', "${targetUrl.toString()}");
  </script>
</body>
</html>`;

    return new Response(html, {
      headers: {
        "content-type": "text/html;charset=UTF-8",
        "cache-control": "no-cache"
      }
    });
  }
};
```
5. Click **Save and Deploy**.

### Part B: Route Custom Domain to Worker
- **Method 1 (Domains & Routes - Recommended)**: On your Worker page (`clan-admin-proxy`), go to **Overview** or **Settings** $\rightarrow$ **Domains & Routes** $\rightarrow$ Click **+ Add** $\rightarrow$ **Custom Domain** and enter `clan_spreadsheet.yourdomain.com`.
- **Method 2 (Workers Routes)**: Go to your domain (`yourdomain.com`) $\rightarrow$ **Workers Routes** $\rightarrow$ **Add Route**: `clan_spreadsheet.yourdomain.com/*` $\rightarrow$ Worker: `clan-admin-proxy`.

---

## Step 4: Configure `System_Config` Tab in Google Sheets

Open your master Google Sheet and navigate to the `System_Config` tab. Secrets are no longer stored here—only non-sensitive operational variables:

| Setting Name | Value | Description |
| :--- | :--- | :--- |
| `Target Clan Name` | `Your Clan Name` | WOM Group Name filter. |
| `Auth Version` | `1` | Incrementing this number instantly revokes all active 7-day user sessions. |

---

## Step 5: Lock Down Spreadsheet & Verify

1. **Lock Down the Google Sheet**:
   - Share settings on the Google Sheet: Remove Editor access for all human moderators/admins.
   - The sheet should now be shared **ONLY** with:
     - You (Owner)
     - The Google Service Account email (`shared_secrets/credentials.json`).
2. **Test Unauthorized Login**:
   - Open `https://clan_spreadsheet.yourdomain.com` in an Incognito Window.
   - Verify that **zero clan data is visible** and only a "Login with Discord" button appears.
3. **Test Non-Moderator Login**:
   - Click "Login with Discord" using a Discord account that does **NOT** hold the `@moderator` role.
   - Verify that the app displays an **Access Denied** error page.
4. **Test Moderator Login**:
   - Click "Login with Discord" using a Discord account that holds the `@moderator` role.
   - Verify successful login, display of roster data, and username shown in navbar.

---

## Session Management & Global Revocation

### 7-Day Session Persistence
Logged-in moderators remain authenticated for **7 days** across browser restarts using secure tokens stored in browser `localStorage`.

### Emergency Global Session Revocation
If a moderator leaves leadership or a security event occurs:
1. Open the `System_Config` tab in your Google Sheet.
2. Change `Auth Version` from `1` to `2` (or increment it).
3. **Effect**: Every existing session token across all users becomes instantly invalid. All users will be forced to log in again via Discord, re-verifying their live server roles.
