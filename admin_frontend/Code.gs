/**
 * @file Code.gs
 * @description Backend logic for the OSRS Clan Management Web App with Discord OAuth authentication.
 */

// --- CONFIGURATION ---
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID'; // Replace with your Google Sheet ID
const DATABASE_TAB_NAME = 'Database';
const AUDIT_LOG_TAB_NAME = 'Audit_Log';
const SYSTEM_SCHEMA_TAB_NAME = 'System_Schema';
const REFERENCE_DATA_TAB_NAME = 'Reference_Data';
const SYSTEM_CONFIG_TAB_NAME = 'System_Config';
const DISCORD_ROLES_TAB_NAME = 'Discord_Roles';
const WOM_USER_AGENT = 'OSRS Clan Management Tool - Contact Discord: YourDiscordName';

const SESSION_LIFESPAN_MS = 7 * 24 * 60 * 60 * 1000; // 7 days in milliseconds

/**
 * Entry point for serving the web app. Handles Discord OAuth redirects & initial render.
 * @param {object} e HTTP Event object from Google Apps Script.
 */
function doGet(e) {
  const params = (e && e.parameter) ? e.parameter : {};
  const loginUrl = getDiscordOAuthLoginUrl();

  // 1. Handle Logout request
  if (params.logout && params.token) {
    invalidateSession(params.token);
    const template = HtmlService.createTemplateFromFile('Index');
    template.sessionToken = '';
    template.discordUser = null;
    template.loginUrl = loginUrl;
    template.authError = 'Logged out successfully.';
    return template.evaluate()
      .setTitle('OSRS Clan Management - Login')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  // 2. Handle Discord OAuth Code Callback
  if (params.code) {
    try {
      const oauthResult = handleDiscordOAuthCallback(params.code);
      if (oauthResult.success) {
        const template = HtmlService.createTemplateFromFile('Index');
        template.sessionToken = oauthResult.sessionToken;
        template.discordUser = oauthResult.discordUser;
        template.loginUrl = loginUrl;
        template.authError = '';
        return template.evaluate()
          .setTitle('OSRS Clan Management')
          .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
      } else {
        return renderAuthErrorPage(oauthResult.message);
      }
    } catch (err) {
      return renderAuthErrorPage('Authentication Exception: ' + err.message);
    }
  }

  // 3. Default Render (Unauthenticated Shell or App Shell)
  const template = HtmlService.createTemplateFromFile('Index');
  template.sessionToken = '';
  template.discordUser = null;
  template.loginUrl = loginUrl;
  template.authError = '';
  return template.evaluate()
    .setTitle('OSRS Clan Management')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * Includes the content of another file in the HTML template.
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

/**
 * Renders a styled Access Denied / Auth Error page.
 */
function renderAuthErrorPage(errorMessage) {
  const loginUrl = getDiscordOAuthLoginUrl();
  const html = `
    <!DOCTYPE html>
    <html>
      <head>
        <base target="_top">
        <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
        <title>Access Denied - OSRS Clan Management</title>
      </head>
      <body class="bg-light d-flex align-items-center justify-content-center" style="height: 100vh;">
        <div class="card shadow-sm border-danger" style="max-width: 480px; width: 100%;">
          <div class="card-header bg-danger text-white text-center">
            <h4 class="mb-0">Access Denied</h4>
          </div>
          <div class="card-body text-center p-4">
            <p class="text-danger font-weight-bold mb-3">${escapeHtml(errorMessage)}</p>
            <p class="text-muted small">You must be logged into Discord and hold an authorized Moderator/Admin role in the server to access this management dashboard.</p>
            <hr>
            <a href="${loginUrl}" target="_top" class="btn btn-primary btn-block">Try Logging In Again with Discord</a>
          </div>
        </div>
      </body>
    </html>
  `;
  return HtmlService.createHtmlOutput(html)
    .setTitle('Access Denied - OSRS Clan Management')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * Generates the Discord OAuth Authorization URL for the client.
 */
function getDiscordOAuthLoginUrl() {
  const clientId = PropertiesService.getScriptProperties().getProperty('DISCORD_CLIENT_ID') || getSystemConfigValue('Discord Client ID') || '';
  let redirectUri = PropertiesService.getScriptProperties().getProperty('DISCORD_REDIRECT_URI') || getSystemConfigValue('Discord Redirect URI') || '';
  
  if (!redirectUri) {
    redirectUri = ScriptApp.getService().getUrl();
  }

  const scope = encodeURIComponent('identify guilds.members.read');
  return `https://discord.com/api/v10/oauth2/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=code&scope=${scope}`;
}

/**
 * Handles the OAuth code exchange with Discord and validates user roles.
 */
function handleDiscordOAuthCallback(code) {
  const clientId = PropertiesService.getScriptProperties().getProperty('DISCORD_CLIENT_ID') || getSystemConfigValue('Discord Client ID') || '';
  const clientSecret = PropertiesService.getScriptProperties().getProperty('DISCORD_CLIENT_SECRET') || getSystemConfigValue('Discord Client Secret') || '';
  let redirectUri = PropertiesService.getScriptProperties().getProperty('DISCORD_REDIRECT_URI') || getSystemConfigValue('Discord Redirect URI') || '';
  
  if (!redirectUri) {
    redirectUri = ScriptApp.getService().getUrl();
  }

  if (!clientId || !clientSecret) {
    return { success: false, message: 'OAuth Error: DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET is missing from Apps Script Properties (or System_Config).' };
  }

  // 1. Token Exchange
  const tokenPayload = {
    client_id: clientId,
    client_secret: clientSecret,
    grant_type: 'authorization_code',
    code: code,
    redirect_uri: redirectUri
  };

  const tokenResponse = UrlFetchApp.fetch('https://discord.com/api/v10/oauth2/token', {
    method: 'post',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    payload: Object.keys(tokenPayload).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(tokenPayload[k])).join('&'),
    muteHttpExceptions: true
  });

  if (tokenResponse.getResponseCode() !== 200) {
    return { success: false, message: `Discord Token Error (${tokenResponse.getResponseCode()}): ${tokenResponse.getContentText()}` };
  }

  const tokenData = JSON.parse(tokenResponse.getContentText());
  const accessToken = tokenData.access_token;

  // 2. Fetch User Profile (@me)
  const userResponse = UrlFetchApp.fetch('https://discord.com/api/v10/users/@me', {
    headers: { Authorization: `Bearer ${accessToken}` },
    muteHttpExceptions: true
  });

  if (userResponse.getResponseCode() !== 200) {
    return { success: false, message: 'Failed to fetch Discord user profile.' };
  }

  const discordUser = JSON.parse(userResponse.getContentText());
  const discordId = discordUser.id;
  const discordName = discordUser.global_name || discordUser.username || discordId;

  // 3. Fetch Guild Member Roles
  const guildId = PropertiesService.getScriptProperties().getProperty('DISCORD_GUILD_ID') || getSystemConfigValue('Discord Guild ID') || '';
  const allowedRolesStr = PropertiesService.getScriptProperties().getProperty('ADMIN_ACCESS_DISCORD_ROLES') || getSystemConfigValue('Admin Access Discord Roles') || '';
  const allowedRoleIds = allowedRolesStr.split(',').map(r => r.trim()).filter(Boolean);

  if (allowedRoleIds.length === 0) {
    return { success: false, message: 'Security Configuration Error: Admin Access Discord Roles is missing from Script Properties (or System_Config).' };
  }

  let userRoles = [];
  if (guildId) {
    const memberUrl = `https://discord.com/api/v10/users/@me/guilds/${guildId}/member`;
    const memberResponse = UrlFetchApp.fetch(memberUrl, {
      headers: { Authorization: `Bearer ${accessToken}` },
      muteHttpExceptions: true
    });

    if (memberResponse.getResponseCode() === 200) {
      const memberData = JSON.parse(memberResponse.getContentText());
      userRoles = memberData.roles || [];
    } else {
      return { success: false, message: `Could not verify membership in Discord Guild (${guildId}). Are you in the Discord server?` };
    }
  }

  // 4. Verify Role Authorization
  const hasAuthorizedRole = userRoles.some(roleId => allowedRoleIds.includes(roleId));
  if (!hasAuthorizedRole) {
    logToAudit('Web App Security', `Access Denied - ${discordName} (${discordId}): Attempted login without required Moderator role.`);
    return { success: false, message: `Account '${discordName}' does not hold the required Moderator/Admin role in the Discord server.` };
  }

  // 5. Create Session Token (7-Day Lifespan)
  const sessionToken = Utilities.getUuid();
  const authVersion = getSystemConfigValue('Auth Version') || '1';
  const expiresAt = Date.now() + SESSION_LIFESPAN_MS;

  const sessionObj = {
    token: sessionToken,
    discordId: discordId,
    discordName: discordName,
    authVersion: String(authVersion),
    expiresAt: expiresAt
  };

  PropertiesService.getScriptProperties().setProperty('SESSION_' + sessionToken, JSON.stringify(sessionObj));
  logToAudit('Web App Security', `Login Success - ${discordName} (${discordId}): Authenticated via Discord OAuth.`);

  return {
    success: true,
    sessionToken: sessionToken,
    discordUser: { id: discordId, name: discordName }
  };
}

/**
 * Validates incoming session tokens against expiration, existence, and global Auth Version.
 * @param {string} sessionToken The session token provided by the client.
 * @returns {object} The validated session object.
 * @throws {Error} Throws error if token is invalid, expired, or revoked.
 */
function verifySession(sessionToken) {
  if (!sessionToken) {
    throw new Error('UNAUTHORIZED: Missing session token. Please log in with Discord.');
  }

  const props = PropertiesService.getScriptProperties();
  const sessionStr = props.getProperty('SESSION_' + sessionToken);
  
  if (!sessionStr) {
    throw new Error('UNAUTHORIZED: Invalid or expired session. Please log in with Discord.');
  }

  const session = JSON.parse(sessionStr);

  // Check 7-Day Expiry
  if (Date.now() > session.expiresAt) {
    props.deleteProperty('SESSION_' + sessionToken);
    throw new Error('UNAUTHORIZED: Session expired (7-day limit reached). Please log in with Discord.');
  }

  // Check Global Auth Version (Session Revocation Check)
  const currentAuthVersion = getSystemConfigValue('Auth Version') || '1';
  if (String(session.authVersion) !== String(currentAuthVersion)) {
    props.deleteProperty('SESSION_' + sessionToken);
    throw new Error('UNAUTHORIZED: All sessions have been revoked by an Administrator. Please log in again.');
  }

  return session;
}

/**
 * Invalidates a specific session token.
 */
function invalidateSession(sessionToken) {
  if (sessionToken) {
    PropertiesService.getScriptProperties().deleteProperty('SESSION_' + sessionToken);
  }
}

/**
 * Helper to get active Spreadsheet instance or open by ID.
 */
function getSpreadsheetInstance(optionalSs) {
  return optionalSs || SpreadsheetApp.openById(SPREADSHEET_ID);
}

/**
 * Computes SHA-256 base64 hash of data object/array for optimistic locking.
 */
function computeDataHash(dataObj) {
  if (!dataObj) return '';
  const str = typeof dataObj === 'string' ? dataObj : JSON.stringify(dataObj);
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, str, Utilities.Charset.UTF_8);
  return Utilities.base64Encode(digest);
}

/**
 * Fetches a single setting value from the System_Config tab.
 */
function getSystemConfigValue(settingName, optionalSs) {
  try {
    const ss = getSpreadsheetInstance(optionalSs);
    const sheet = ss.getSheetByName(SYSTEM_CONFIG_TAB_NAME);
    if (!sheet) return '';
    const data = sheet.getDataRange().getDisplayValues();
    if (data.length <= 1) return '';

    const headers = data[0].map(h => h.toString().trim());
    const nameCol = headers.indexOf('Setting Name');
    const valCol = headers.indexOf('Value');
    if (nameCol === -1 || valCol === -1) return '';

    for (let i = 1; i < data.length; i++) {
      if (data[i][nameCol] && data[i][nameCol].toString().trim() === settingName) {
        return data[i][valCol].toString().trim();
      }
    }
  } catch (e) {
    return '';
  }
  return '';
}

/**
 * Validates session and fetches initial application data payload in a single optimized pass.
 */
function getInitialPayload(sessionToken) {
  const session = verifySession(sessionToken);
  const ss = getSpreadsheetInstance();
  
  const refData = getFullReferenceData(ss);
  const users = getAllUsers(sessionToken, ss);

  return {
    targetClanName: getTargetClanName(ss),
    roleMap: getDiscordRolesMap(ss),
    users: users,
    ranks: getClanRanksFromRefData(refData),
    referenceData: refData,
    ranksHash: computeDataHash(refData),
    currentUser: { id: session.discordId, name: session.discordName },
    loginUrl: getDiscordOAuthLoginUrl()
  };
}

/**
 * Validates session and fetches login URL for unauthenticated clients.
 */
function getPublicLoginInfo() {
  return {
    loginUrl: getDiscordOAuthLoginUrl(),
    targetClanName: getTargetClanName()
  };
}

/**
 * Exposes target clan name.
 */
function getTargetClanName(optionalSs) {
  return getSystemConfigValue('Target Clan Name', optionalSs) || 'Unknown Clan';
}

/**
 * Finds user row by Discord ID (Session Protected).
 */
function findUserByDiscordId(sessionToken, discordId, optionalSs) {
  verifySession(sessionToken);
  const ss = getSpreadsheetInstance(optionalSs);
  const sheet = ss.getSheetByName(DATABASE_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues();
  const headers = data[0];
  const discordIdCol = headers.indexOf('Discord ID');

  if (discordIdCol === -1) {
    throw new Error(`'Discord ID' column not found in '${DATABASE_TAB_NAME}' tab.`);
  }

  const searchId = discordId.toString().trim().replace(/^'/, '');

  for (let i = 1; i < data.length; i++) {
    if (data[i][discordIdCol].toString().trim().replace(/^'/, '') === searchId) {
      const user = {};
      headers.forEach((header, index) => {
        user[header] = data[i][index];
      });
      return { 
        user: user, 
        row: i + 1,
        hash: computeDataHash(user)
      };
    }
  }
  return null;
}

/**
 * Fetches Discord roles map.
 */
function getDiscordRolesMap(optionalSs) {
  const ss = getSpreadsheetInstance(optionalSs);
  const sheet = ss.getSheetByName(DISCORD_ROLES_TAB_NAME);
  if (!sheet) return {};
  const data = sheet.getDataRange().getDisplayValues();
  const roleMap = {};
  if (data.length > 1) {
    for (let i = 1; i < data.length; i++) {
      let id = data[i][0].toString().trim();
      if (id.startsWith("'")) id = id.substring(1);
      roleMap[id] = data[i][1].toString().trim();
    }
  }
  return roleMap;
}

/**
 * Fetches all user records (Session Protected).
 */
function getAllUsers(sessionToken, optionalSs) {
  verifySession(sessionToken);
  const ss = getSpreadsheetInstance(optionalSs);
  const sheet = ss.getSheetByName(DATABASE_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues();
  if (data.length <= 1) return [];

  const headers = data[0];
  const users = [];

  for (let i = 1; i < data.length; i++) {
    let user = {};
    headers.forEach((header, index) => {
      user[header] = data[i][index];
    });
    users.push(user);
  }
  return users;
}

/**
 * Extracts clan ranks list from Reference Data.
 */
function getClanRanksFromRefData(refData) {
  if (!refData || refData.length === 0) return [];
  const ranks = [];
  refData.forEach(item => {
    const rank = item['Clan Rank'] ? item['Clan Rank'].toString().trim() : '';
    if (rank && !ranks.includes(rank)) ranks.push(rank);
  });
  return ranks;
}

/**
 * Fetches clan ranks.
 */
function getClanRanks(optionalSs) {
  const refData = getFullReferenceData(optionalSs);
  return getClanRanksFromRefData(refData);
}

/**
 * Fetches system schema.
 */
function getSystemSchema(optionalSs) {
  const ss = getSpreadsheetInstance(optionalSs);
  const sheet = ss.getSheetByName(SYSTEM_SCHEMA_TAB_NAME);
  if (!sheet) return [];
  const data = sheet.getDataRange().getValues();
  if (data.length <= 1) return [];

  const headers = data[0];
  const schema = [];
  for (let i = 1; i < data.length; i++) {
    let rule = {};
    headers.forEach((header, index) => {
      rule[header] = data[i][index];
    });
    schema.push(rule);
  }
  return schema;
}

/**
 * Validates form data against schema.
 */
function validateFormData(formData, schema) {
  for (let i = 0; i < schema.length; i++) {
    const rule = schema[i];
    const dbHeader = rule['Column Header (Database)'];
    const isRequired = rule['Required'] === true || rule['Required'].toString().toUpperCase() === 'TRUE';

    if (isRequired) {
      const value = formData[dbHeader];
      if (value === undefined || value === null || value.toString().trim() === '') {
        return { valid: false, message: `Missing required field: ${dbHeader}` };
      }
    }
  }
  return { valid: true };
}

/**
 * Creates or updates user record (Session Protected) with optional hash verification.
 */
function createOrUpdateUser(sessionToken, formData, expectedHash) {
  const session = verifySession(sessionToken);
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(15000);
    if (!formData || !formData['Discord ID']) {
      return { success: false, message: 'Validation Error: Discord ID is missing from the payload.' };
    }

    const ss = getSpreadsheetInstance();
    const sheet = ss.getSheetByName(DATABASE_TAB_NAME);
    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];

    const existingUser = findUserByDiscordId(sessionToken, formData['Discord ID'], ss);

    // Optimistic Concurrency Check
    if (existingUser && expectedHash && existingUser.hash !== expectedHash) {
      return {
        success: false,
        conflict: true,
        message: 'Data Conflict Detected: Another administrator has updated this profile since you opened it.',
        latestUserResult: existingUser
      };
    }

    const volatileHeaders = ['Discord Name', 'RSNs', 'Account Clan', 'Game Ranks', 'Discord Ranks', 'Join Date', 'System Flags'];

    let proposedData = {};
    headers.forEach(header => {
      let val;
      if (existingUser && volatileHeaders.includes(header)) {
        val = existingUser.user[header];
      } else {
        val = formData.hasOwnProperty(header) ? formData[header] : (existingUser ? existingUser.user[header] : '');
      }
      if (header === 'Discord ID' && val !== '' && !val.toString().startsWith("'")) val = "'" + val.toString().trim();
      proposedData[header] = val;
    });

    const schema = getSystemSchema(ss);
    const validation = validateFormData(proposedData, schema);

    if (!validation.valid) {
      return { success: false, message: 'Validation Error: ' + validation.message };
    }

    let rowData = headers.map(header => proposedData[header]);
    const discordId = formData['Discord ID'].toString().replace(/^'/, '');
    const dName = (existingUser && existingUser.user['Discord Name']) ? existingUser.user['Discord Name'] : 'Unknown';
    const auditUserString = `${session.discordName} (${session.discordId})`;

    if (existingUser) {
      let updates = 0;
      headers.forEach((header, index) => {
        if (!volatileHeaders.includes(header) && proposedData[header] !== undefined) {
          if (String(proposedData[header]) !== String(existingUser.user[header])) {
            sheet.getRange(existingUser.row, index + 1).setValue(proposedData[header]);
            updates++;
          }
        }
      });
      logToAudit('Web App', `Manual Update - ${dName} (${discordId}): Updated ${updates} fields.`, auditUserString);
      const updatedUserRes = findUserByDiscordId(sessionToken, discordId, ss);
      return { 
        success: true, 
        message: `User ${discordId} updated successfully.`,
        user: updatedUserRes ? updatedUserRes.user : proposedData,
        hash: updatedUserRes ? updatedUserRes.hash : computeDataHash(proposedData)
      };
    } else {
      sheet.appendRow(rowData);
      logToAudit('Web App', `Manual Create - Unknown (${discordId}): Added new member to database.`, auditUserString);
      const updatedUserRes = findUserByDiscordId(sessionToken, discordId, ss);
      return { 
        success: true, 
        message: `User ${discordId} created successfully.`,
        user: updatedUserRes ? updatedUserRes.user : proposedData,
        hash: updatedUserRes ? updatedUserRes.hash : computeDataHash(proposedData)
      };
    }
  } catch (e) {
    logToAudit('Web App', `System Error - System (N/A): ${e.message}`, `${session.discordName} (${session.discordId})`);
    return { success: false, message: `An error occurred: ${e.message}` };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Fetches full reference data.
 */
function getFullReferenceData(optionalSs) {
  const ss = getSpreadsheetInstance(optionalSs);
  const sheet = ss.getSheetByName(REFERENCE_DATA_TAB_NAME);
  if (!sheet) return [];
  const data = sheet.getDataRange().getDisplayValues();
  if (data.length <= 1) return [];

  const headers = data[0];
  const ranks = [];

  for (let i = 1; i < data.length; i++) {
    let rank = {};
    headers.forEach((h, index) => {
      let val = data[i][index];
      if (['Required Discord Roles', 'Allowed Discord Roles', 'Excluded Discord Roles'].includes(h)) val = val.toString().replace(/^'/, '');
      rank[h] = val;
    });
    ranks.push(rank);
  }
  return ranks;
}

/**
 * Saves reference data (Session Protected) with expected hash optimistic locking check.
 */
function saveReferenceData(sessionToken, ranks, expectedHash) {
  const session = verifySession(sessionToken);
  const auditUserString = `${session.discordName} (${session.discordId})`;
  const lock = LockService.getScriptLock();

  try {
    lock.waitLock(15000);
    const ss = getSpreadsheetInstance();

    if (expectedHash) {
      const currentRanks = getFullReferenceData(ss);
      const currentHash = computeDataHash(currentRanks);
      if (currentHash !== expectedHash) {
        return {
          success: false,
          conflict: true,
          message: 'Data Conflict: Clan Rank rules were updated by another administrator while you were editing.'
        };
      }
    }

    const sheet = ss.getSheetByName(REFERENCE_DATA_TAB_NAME);
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();

    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, lastCol).clearContent();
    }

    if (ranks && ranks.length > 0) {
      const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
      const rows = ranks.map(rank => {
        return headers.map(header => {
          let val = rank[header] !== undefined ? rank[header] : '';
          if (['Required Discord Roles', 'Allowed Discord Roles', 'Excluded Discord Roles'].includes(header) && val !== '' && !val.toString().includes(',') && !val.toString().startsWith("'")) {
            val = "'" + val;
          }
          return val;
        });
      });
      sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
    }

    const newRefData = getFullReferenceData(ss);
    const newHash = computeDataHash(newRefData);

    logToAudit('Web App', `System Action - Updated Clan Rank Mappings via Web UI.`, auditUserString);
    return { success: true, hash: newHash };
  } catch (e) {
    logToAudit('Web App', `System Error - Error saving ranks - ${e.message}`, auditUserString);
    return { success: false, message: e.message };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Queries Wise Old Man API (Session Protected) with exact match prioritization.
 */
function searchWomPlayer(sessionToken, username) {
  verifySession(sessionToken);
  try {
    const options = {
      muteHttpExceptions: true,
      headers: { 'User-Agent': WOM_USER_AGENT }
    };

    let player = null;
    let exactMatch = false;

    // 1. Try exact player lookup endpoint first
    const exactUrl = `https://api.wiseoldman.net/v2/players/username/${encodeURIComponent(username)}`;
    const exactRes = UrlFetchApp.fetch(exactUrl, options);

    if (exactRes.getResponseCode() === 200) {
      player = JSON.parse(exactRes.getContentText());
      exactMatch = true;
    } else {
      // 2. Fallback to search endpoint with limit=10
      const searchUrl = `https://api.wiseoldman.net/v2/players/search?username=${encodeURIComponent(username)}&limit=10`;
      const searchRes = UrlFetchApp.fetch(searchUrl, options);

      if (searchRes.getResponseCode() === 200) {
        const searchData = JSON.parse(searchRes.getContentText());
        if (searchData && searchData.length > 0) {
          const normQuery = username.toLowerCase().replace(/_/g, ' ').trim();
          const found = searchData.find(p => {
            const pUser = (p.username || '').toLowerCase().replace(/_/g, ' ').trim();
            const pDisp = (p.displayName || '').toLowerCase().replace(/_/g, ' ').trim();
            return pUser === normQuery || pDisp === normQuery;
          });

          if (found) {
            player = found;
            exactMatch = true;
          } else {
            player = searchData[0];
            exactMatch = false;
          }
        }
      }
    }

    if (player) {
      const membershipsUrl = `https://api.wiseoldman.net/v2/players/${encodeURIComponent(player.username)}/groups`;
      const membershipsRes = UrlFetchApp.fetch(membershipsUrl, options);
      let clanString = 'Not in WOM Group';
      let rankString = 'None';

      if (membershipsRes.getResponseCode() === 200) {
        const memberships = JSON.parse(membershipsRes.getContentText());
        if (memberships && memberships.length > 0) {
          clanString = memberships.map(m => m.group ? m.group.name : 'Unknown').join(', ');
          rankString = memberships.map(m => m.role ? m.role : 'Unknown').join(', ');
        }
      }

      return {
        success: true,
        womId: player.id,
        displayName: player.displayName,
        clan: clanString,
        rank: rankString,
        exactMatch: exactMatch
      };
    } else {
      return { success: false, message: 'Player not found on Wise Old Man.' };
    }
  } catch (e) {
    return { success: false, message: e.message };
  }
}

/**
 * Logs event to Audit_Log with standard Discord User identifier.
 */
function logToAudit(source, logEntry, userOverride) {
  const auditSheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(AUDIT_LOG_TAB_NAME);
  if (!auditSheet) return;
  const timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const user = userOverride || 'System (N/A)';
  auditSheet.appendRow([timestamp, source, user, logEntry]);
}

/**
 * Escapes HTML characters for security.
 */
function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}