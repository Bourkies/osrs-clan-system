/**
 * @file Code.gs
 * @description Backend logic for the OSRS Clan Management Web App.
 */

// --- CONFIGURATION ---
const SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID'; // Replace with your Google Sheet ID
const DATABASE_TAB_NAME = 'Database';
const AUDIT_LOG_TAB_NAME = 'Audit_Log';
const SYSTEM_SCHEMA_TAB_NAME = 'System_Schema';
const REFERENCE_DATA_TAB_NAME = 'Reference_Data';
const SYSTEM_CONFIG_TAB_NAME = 'System_Config';
const DISCORD_ROLES_TAB_NAME = 'Discord_Roles';
const WOM_USER_AGENT = 'OSRS Clan Management Tool - Contact Discord: YourDiscordName'; // Update with your Discord name

/**
 * Serves the main HTML page of the web app.
 * This is the entry point when a user visits the web app URL.
 */
function doGet() {
  return HtmlService.createTemplateFromFile('Index').evaluate()
    .setTitle('OSRS Clan Management')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.DEFAULT);
}

/**
 * Includes the content of another file in the HTML template.
 * Used to include JavaScript.html and CSS.html into Index.html.
 * @param {string} filename The name of the file to include.
 * @returns {string} The content of the file.
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

/**
 * Fetches all initial data required to load the dashboard in a single call.
 * @returns {object} An object containing the clan name, role map, users, and ranks.
 */
function getInitialPayload() {
  return {
    targetClanName: getTargetClanName(),
    roleMap: getDiscordRolesMap(),
    users: getAllUsers(),
    ranks: getClanRanks(),
    referenceData: getFullReferenceData()
  };
}

/**
 * Exposes the target clan name to the frontend for filtering.
 * @returns {string} The target clan name.
 */
function getTargetClanName() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SYSTEM_CONFIG_TAB_NAME);
  if (!sheet) return 'Unknown Clan';
  
  const data = sheet.getDataRange().getDisplayValues();
  if (data.length <= 1) return 'Unknown Clan';
  
  // Map and trim headers to prevent accidental space issues
  const headers = data[0].map(h => h.toString().trim());
  const nameCol = headers.indexOf('Setting Name');
  const valCol = headers.indexOf('Value');
  
  if (nameCol === -1 || valCol === -1) return 'Unknown Clan';
  
  for (let i = 1; i < data.length; i++) {
    if (data[i][nameCol] && data[i][nameCol].toString().trim() === 'Target Clan Name') {
      return data[i][valCol].toString().trim();
    }
  }
  return 'Unknown Clan';
}

/**
 * Finds a user's row in the database by their Discord ID.
 * @param {string} discordId The Discord ID to search for.
 * @returns {object|null} An object with the user's data and row number, or null if not found.
 */
function findUserByDiscordId(discordId) {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(DATABASE_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues(); // Use getDisplayValues to avoid large number rounding
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
      return { user: user, row: i + 1 };
    }
  }
  return null;
}

/**
 * Fetches the Discord Role map to translate IDs to Names in the UI.
 * @returns {object} A dictionary mapping Role IDs to Names.
 */
function getDiscordRolesMap() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(DISCORD_ROLES_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues();
  const roleMap = {};
  if (data.length > 1) {
    for(let i = 1; i < data.length; i++) {
      let id = data[i][0].toString().trim();
      if (id.startsWith("'")) id = id.substring(1); 
      roleMap[id] = data[i][1].toString().trim();
    }
  }
  return roleMap;
}

/**
 * Fetches all user records from the database to populate the frontend table.
 * @returns {Array<object>} An array of user objects.
 */
function getAllUsers() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(DATABASE_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues(); // getDisplayValues formats dates/numbers nicely
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
 * Fetches all available clan ranks from the Reference_Data tab.
 * @returns {Array<string>} An array of clan rank names.
 */
function getClanRanks() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(REFERENCE_DATA_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues(); // Use getDisplayValues for clean strings
  if (data.length <= 1) return [];
  
  const headers = data[0];
  const rankColIndex = headers.indexOf('Clan Rank');
  if (rankColIndex === -1) return [];
  
  const ranks = [];
  for (let i = 1; i < data.length; i++) {
    const rank = data[i][rankColIndex].toString().trim();
    if (rank && !ranks.includes(rank)) ranks.push(rank);
  }
  return ranks;
}

/**
 * Fetches the system schema to be used for validation.
 * @returns {Array<object>} An array of schema rules.
 */
function getSystemSchema() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SYSTEM_SCHEMA_TAB_NAME);
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
 * Validates incoming form data against the rules defined in the System Schema.
 * @param {object} formData The complete proposed user data row.
 * @param {Array<object>} schema The system schema rules.
 * @returns {object} An object containing a 'valid' boolean and optional 'message'.
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
 * Creates or updates a user's record in the database.
 * @param {object} formData The user data submitted from the web app form.
 * @returns {object} A success or error message.
 */
function createOrUpdateUser(formData) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(15000); // Wait up to 15 seconds for any concurrent saves to finish
    if (!formData || !formData['Discord ID']) {
      return { success: false, message: 'Validation Error: Discord ID is missing from the payload.' };
    }

    const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(DATABASE_TAB_NAME);
    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    
    const existingUser = findUserByDiscordId(formData['Discord ID']);

    // Columns strictly managed by the Auditor shouldn't be overwritten by Web App form submissions
    const volatileHeaders = ['Discord Name', 'RSNs', 'Account Clan', 'Game Ranks', 'Discord Ranks', 'Join Date', 'System Flags'];

    // Build the complete proposed data object
    let proposedData = {};
    headers.forEach(header => {
      let val;
      if (existingUser && volatileHeaders.includes(header)) {
        val = existingUser.user[header];
      } else {
        val = formData.hasOwnProperty(header) ? formData[header] : (existingUser ? existingUser.user[header] : '');
      }
      // Prepend apostrophe to force Discord ID as plain text in the Google Sheet
      if (header === 'Discord ID' && val !== '' && !val.toString().startsWith("'")) val = "'" + val.toString().trim();
      proposedData[header] = val;
    });

    // Validate the proposed data against the System Schema
    const schema = getSystemSchema();
    const validation = validateFormData(proposedData, schema);
    
    if (!validation.valid) {
      return { success: false, message: 'Validation Error: ' + validation.message };
    }

    // Map the proposed data back to a flat array for insertion
    let rowData = headers.map(header => proposedData[header]);
    
    const discordId = formData['Discord ID'].toString().replace(/^'/, '');
    const dName = (existingUser && existingUser.user['Discord Name']) ? existingUser.user['Discord Name'] : 'Unknown';

    if (existingUser) {
      // Cell-Level Updates: Only write static fields that have changed to prevent overwriting the Auditor
      let updates = 0;
      headers.forEach((header, index) => {
        if (!volatileHeaders.includes(header) && proposedData[header] !== undefined) {
          if (String(proposedData[header]) !== String(existingUser.user[header])) {
            sheet.getRange(existingUser.row, index + 1).setValue(proposedData[header]);
            updates++;
          }
        }
      });
      logToAudit('Web App', `Manual Update - ${dName} (${discordId}): Updated ${updates} fields.`);
      return { success: true, message: `User ${discordId} updated successfully.` };
    } else {
      // Create new row
      sheet.appendRow(rowData);
      logToAudit('Web App', `Manual Create - Unknown (${discordId}): Added new member to database.`);
      return { success: true, message: `User ${discordId} created successfully.` };
    }
  } catch (e) {
    logToAudit('Web App', `System Error - System (N/A): ${e.message}`);
    return { success: false, message: `An error occurred: ${e.message}` };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Fetches all reference data for the ranks manager.
 * @returns {Array<object>} An array of rank objects.
 */
function getFullReferenceData() {
  const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(REFERENCE_DATA_TAB_NAME);
  const data = sheet.getDataRange().getDisplayValues();
  if (data.length <= 1) return [];
  
  const headers = data[0];
  const ranks = [];
  
  for (let i = 1; i < data.length; i++) {
    let rank = {};
    headers.forEach((h, index) => {
      let val = data[i][index];
      // Clean up any formatting apostrophes for the frontend
      if (['Required Discord Roles', 'Allowed Discord Roles', 'Excluded Discord Roles'].includes(h)) val = val.toString().replace(/^'/, '');
      rank[h] = val;
    });
    ranks.push(rank);
  }
  return ranks;
}

/**
 * Replaces the reference data with a new sorted list from the UI.
 * @param {Array<object>} ranks The complete array of rank objects.
 * @returns {object} Success or error response.
 */
function saveReferenceData(ranks) {
  try {
    const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(REFERENCE_DATA_TAB_NAME);
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    
    // Clear everything except headers
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, lastCol).clearContent();
    }
    
    if (ranks && ranks.length > 0) {
      const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
      const rows = ranks.map(rank => {
        return headers.map(header => {
          let val = rank[header] !== undefined ? rank[header] : '';
          // Ensure single Discord IDs don't get scientific notation
          if (['Required Discord Roles', 'Allowed Discord Roles', 'Excluded Discord Roles'].includes(header) && val !== '' && !val.toString().includes(',') && !val.toString().startsWith("'")) {
             val = "'" + val;
          }
          return val;
        });
      });
      sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);
    }
    
    logToAudit('Web App', `System Action - System (N/A): Updated Clan Rank Mappings via Web UI.`);
    return { success: true };
  } catch (e) {
    logToAudit('Web App', `System Error - System (N/A): Error saving ranks - ${e.message}`);
    return { success: false, message: e.message };
  }
}

/**
 * Queries the Wise Old Man API for a player's exact match and their clan.
 * @param {string} username The RSN to search.
 * @returns {object} Search result with WOM ID, Display Name, Clan, and Rank.
 */
function searchWomPlayer(username) {
  try {
    const options = {
      muteHttpExceptions: true,
      headers: {
        'User-Agent': WOM_USER_AGENT
      }
    };

    // 1. Search for the player to get the exact ID (handles capitalization/spacing)
    const searchUrl = `https://api.wiseoldman.net/v2/players/search?username=${encodeURIComponent(username)}&limit=1`;
    const searchRes = UrlFetchApp.fetch(searchUrl, options);
    
    if (searchRes.getResponseCode() === 200) {
      const data = JSON.parse(searchRes.getContentText());
      if (data && data.length > 0) {
        const player = data[0];
        
        // 2. Fetch their group memberships
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
          rank: rankString
        };
      } else {
        return { success: false, message: 'Player not found on Wise Old Man.' };
      }
    } else {
      return { success: false, message: `WOM API Error: ${searchRes.getResponseCode()}` };
    }
  } catch (e) {
    return { success: false, message: e.message };
  }
}

/**
 * Appends a log entry to the Audit_Log tab.
 * @param {string} source The source of the log ('Web App' or 'The Auditor').
 * @param {string} logEntry The detailed log message.
 */
function logToAudit(source, logEntry) {
  const auditSheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(AUDIT_LOG_TAB_NAME);
  const timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'); // Strip milliseconds for pure ISO 8601
  const user = Session.getActiveUser().getEmail();
  auditSheet.appendRow([timestamp, source, user, logEntry]);
}