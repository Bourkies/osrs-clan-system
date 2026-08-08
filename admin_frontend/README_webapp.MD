# OSRS Clan Management - Admin Frontend

This directory contains the files for the Google Apps Script-based Web Application, which acts as the management UI for clan administrators.

Authentication and authorization are powered by **Discord OAuth** and **Discord Server Role verification** (e.g. `@moderator`). Clan admins authenticate with their Discord accounts, and the Web App verifies their server roles directly via the Discord API. This completely eliminates the need to grant human admins Editor access to the raw Google Sheet.

---

## Architecture & Security Model

- **100% Private Google Sheet**: The raw Google Sheet database is kept strictly private to the Sheet Owner and the Google Service Account (`shared_secrets/credentials.json`).
- **Web App Execution ("Execute as Me")**: The Web App executes under the owner's security context. All read/write operations pass through server-side validation in `Code.gs`.
- **Secret Isolation**: Sensitive API credentials (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_GUILD_ID`, `ADMIN_ACCESS_DISCORD_ROLES`, `DISCORD_REDIRECT_URI`) are stored in Apps Script **Script Properties** (`PropertiesService.getScriptProperties()`). They are never stored in the spreadsheet or exposed to client browsers.
- **Operational Clan Settings**: Non-sensitive settings (`Target Clan Name`, `Auth Version`) are stored in the `System_Config` spreadsheet tab.
- **7-Day Session Persistence**: Authenticated sessions persist securely in browser `localStorage` for up to 7 days.
- **Global Session Revocation**: Incrementing `Auth Version` in `System_Config` instantly revokes all active session tokens system-wide, forcing all users to re-authenticate against live Discord server roles.

---

## File Structure

- `Code.gs`: Server-side logic written in Google Apps Script. Manages OAuth code exchange, session token generation/validation, role verification, and spreadsheet operations.
- `Index.html`: Main HTML structure containing unauthenticated login card, logged-in header, DataTables view, and modal dialogs.
- `JavaScript.html`: Client-side JavaScript handling session token resolution, DataTables rendering, and server communication.
- `UserManager.html`: Client-side UI and logic for adding, editing, conflict-checking, and saving member roster profiles.
- `RanksManager.html`: Client-side UI and logic for configuring clan ranks, role rules, and in-game mappings.
- `WomLookup.html`: Wise Old Man API lookup integration for searching and linking player accounts.

---

## Complete Setup Instructions (From Scratch)

### 1. Create and Setup the Google Sheet Database
1. Create a new **Google Sheet**. Copy the Spreadsheet ID from the URL (the string between `/d/` and `/edit`).
2. Create six tabs named exactly:
   - `System_Schema`
   - `Reference_Data`
   - `System_Config`
   - `Discord_Roles`
   - `Database`
   - `Audit_Log`
3. Copy the column headers for each tab into Row 1 from the [system_architecture.md](file:///d:/Google%20drive/0E.Documents/04.Games/01.RS/002.Clan%20spread%20sheet%20main/osrs-clan-system/system_architecture.md) document.
4. In the `System_Config` tab, add the following rows:
   - `Target Clan Name` | `Your Clan Name`
   - `Auth Version` | `1`
5. **Permissions**: Keep the spreadsheet private. Do NOT give Editor access to human moderators. Share access only with your Google Service Account email (`shared_secrets/credentials.json`).

---

### 2. Create Discord Developer Application
1. Sign in to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, name it (e.g. `OSRS Clan Roster Manager`), and click **Create**.
3. Under **OAuth2** in the left sidebar:
   - Copy the **Client ID**.
   - Click **Reset Secret** to generate a **Client Secret** (copy and save this immediately).
4. Under **Redirects**, click **Add Redirect**:
   - Add your custom domain redirect (e.g. `https://admin.yourdomain.com`).
5. Click **Save Changes**.

---

### 3. Setup Google Apps Script Project
1. In your Google Sheet, open `Extensions` > `Apps Script`.
2. Replace/create the files in the editor with the matching contents from this folder:
   - `Code.gs`
   - `Index.html`
   - `JavaScript.html`
   - `UserManager.html`
   - `RanksManager.html`
   - `WomLookup.html`
3. Open `Code.gs` and update line 7 with your Spreadsheet ID:
   `const SPREADSHEET_ID = 'YOUR_ACTUAL_SPREADSHEET_ID';`

---

### 4. Configure Secure Script Properties (Secrets & Credentials)
1. In the Apps Script left sidebar, click the **Gear Icon (Project Settings)**.
2. Scroll down to **Script Properties** and click **Edit script properties** $\rightarrow$ **Add script property**.
3. Add the following entries:

| Property Name | Value | Description |
| :--- | :--- | :--- |
| `DISCORD_CLIENT_ID` | `123456789012345678` | Client ID from Discord Developer Portal. |
| `DISCORD_CLIENT_SECRET` | `your_client_secret_here` | Client Secret from Discord Developer Portal. |
| `DISCORD_GUILD_ID` | `987654321098765432` | Your Discord Server ID (Guild Snowflake). |
| `ADMIN_ACCESS_DISCORD_ROLES` | `112233445566778899` | Comma-separated Discord Role IDs authorized to access the Web App (e.g. `@moderator` ID). |
| `DISCORD_REDIRECT_URI` | `https://admin.yourdomain.com` | Custom domain redirect URL. |

4. Click **Save script properties**.

*Tip: Enable Developer Mode in Discord (Settings -> Advanced -> Developer Mode), then right-click your Server or Role and click "Copy ID".*

---

### 5. Deploy the Web Application
1. Click **Deploy** (top right) $\rightarrow$ **New deployment** (or **Manage deployments** $\rightarrow$ Edit).
2. For *Select type*, choose **Web app**.
3. Configure settings:
   - **Execute as**: **Me (your_email@gmail.com)**
   - **Who has access**: **Anyone**
4. Click **Deploy**. Authorize Google permissions if prompted.
5. Copy your **Web App URL** shown on the deployment success screen.

---

### 6. Setup Custom Domain Routing (Cloudflare Worker)
To map `https://admin.yourdomain.com` to your Apps Script Web App:

1. Log into your [Cloudflare Dashboard](https://dash.cloudflare.com/) and navigate to **Workers & Pages** $\rightarrow$ **Create Application** $\rightarrow$ **Create Worker** (or **Start with Hello World**).
2. Name your worker (e.g., `clan-admin-proxy`) and click **Deploy**.
3. Click **Edit Code** and paste the following container script:

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

    // Return a responsive full-window container container
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

4. Click **Save and Deploy**.
5. Bind your custom domain to the Worker:
   - On the Worker page, go to **Overview** or **Settings** $\rightarrow$ **Domains & Routes** $\rightarrow$ **+ Add** $\rightarrow$ **Custom Domain**.
   - Enter `admin.yourdomain.com` (e.g. `admin.auosrs-stats.com`). Cloudflare configures DNS and SSL automatically.

---

## Emergency Global Session Revocation

If a moderator leaves clan leadership or a security event occurs:
1. Open the `System_Config` tab in your Google Sheet.
2. Increment `Auth Version` (e.g. `1` $\rightarrow$ `2`).
3. **Effect**: Every active session token across all users becomes instantly invalid. All users will be forced to re-authenticate through Discord OAuth on their next interaction, re-verifying their live server roles.