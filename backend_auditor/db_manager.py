import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
import time
import functools
import requests
from loguru import logger
from constants import SystemFlag, SHARED_SECRETS_DIR

def retry_connection(max_retries=3, delay=5):
    """Decorator to retry Google Sheets API calls if the connection drops during long idle periods."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.RequestException, ConnectionError, ConnectionResetError) as e:
                    retries += 1
                    if retries > max_retries:
                        logger.error(f"Max retries reached in {func.__name__}. Failing.")
                        raise
                    logger.warning(f"Connection dropped in {func.__name__} ({e.__class__.__name__}). Retrying in {delay}s ({retries}/{max_retries})...")
                    time.sleep(delay)
        return wrapper
    return decorator

class DBManager:
    def __init__(self, spreadsheet_id, creds_file=None):
        if creds_file is None:
            creds_file = SHARED_SECRETS_DIR / 'credentials.json'
        self.scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(creds)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)
        self._sheets = {}

    @retry_connection()
    def get_sheet(self, sheet_name):
        if sheet_name not in self._sheets:
            self._sheets[sheet_name] = self.spreadsheet.worksheet(sheet_name)
        return self._sheets[sheet_name]

    @retry_connection()
    def get_all_records(self, sheet_name):
        return self.get_sheet(sheet_name).get_all_records()

    @retry_connection()
    def get_headers(self, sheet_name):
        return self.get_sheet(sheet_name).row_values(1)

    @retry_connection()
    def get_col_values(self, sheet_name, col_num):
        return self.get_sheet(sheet_name).col_values(col_num)

    def find_row_by_id(self, sheet_name, target_id, id_col=1):
        """JIT Indexing: Fetches the latest column data to safely find the row number (1-based index)."""
        col_values = self.get_col_values(sheet_name, id_col)
        target_id_str = str(target_id).replace("'", "").strip()
        for idx, val in enumerate(col_values):
            if str(val).replace("'", "").strip() == target_id_str:
                return idx + 1
        return None

    def _sanitize_value(self, value):
        """Ensures values are correctly formatted strings before writing to Google Sheets."""
        if isinstance(value, list):
            clean_list = [str(v).strip() for v in value if str(v).strip()]
            return ", ".join(clean_list)
        elif value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def update_flags(current_flags_str, add_flags=None, remove_flags=None, clear_all=False):
        """Safely parses and modifies the System Flags comma-separated string."""
        if clear_all:
            return SystemFlag.OK.value
        
        flags = {f.strip() for f in current_flags_str.split(',') if f.strip() and f.strip() != SystemFlag.OK.value}
        
        if add_flags:
            for f in add_flags: flags.add(f.strip())
        if remove_flags:
            for f in remove_flags: flags.discard(f.strip())
                
        return ", ".join(sorted(list(flags))) if flags else SystemFlag.OK.value

    def batch_update_by_id(self, sheet_name, id_column_name, updates):
        """
        Smart JIT Batching: Takes a list of dicts, finds the absolute latest row for each ID, 
        resolves the column letters automatically, and pushes the batch safely.
        Format: [{'id': '123456789', 'col_name': 'RSNs', 'value': 'New RSN'}, ...]
        """
        if not updates:
            return

        headers = self.get_headers(sheet_name)
        if id_column_name not in headers:
            logger.error(f"Column '{id_column_name}' not found in {sheet_name}")
            return
            
        id_col_idx = headers.index(id_column_name) + 1
        
        # 1 API Call to fetch the absolute latest order of the IDs
        current_ids = self.get_col_values(sheet_name, id_col_idx)
        id_to_row = {str(val).replace("'", "").strip(): idx + 1 for idx, val in enumerate(current_ids)}
        
        batch_payload = []
        for update in updates:
            target_id = str(update['id']).replace("'", "").strip()
            row_num = id_to_row.get(target_id)
            
            if row_num and update['col_name'] in headers:
                col_idx = headers.index(update['col_name']) + 1
                range_a1 = rowcol_to_a1(row_num, col_idx)
                batch_payload.append({'range': range_a1, 'values': [[self._sanitize_value(update['value'])]]})
            else:
                logger.warning(f"JIT Update Failed for ID {target_id}: Row or Column '{update['col_name']}' not found.")
                
        if batch_payload:
            self.batch_update(sheet_name, batch_payload)

    @retry_connection()
    def batch_update(self, sheet_name, updates):
        if updates:
            self.get_sheet(sheet_name).batch_update(updates, value_input_option='RAW')

    @retry_connection()
    def append_rows(self, sheet_name, rows):
        if rows:
            sanitized_rows = [[self._sanitize_value(val) for val in row] for row in rows]
            self.get_sheet(sheet_name).append_rows(sanitized_rows, value_input_option='RAW')
            
    @retry_connection()
    def update_cell(self, sheet_name, range_name, value):
        clean_value = self._sanitize_value(value)
        self.get_sheet(sheet_name).update(values=[[clean_value]], range_name=range_name, value_input_option='RAW')

    @retry_connection()
    def clear_and_rewrite(self, sheet_name, headers, rows):
        sheet = self.get_sheet(sheet_name)
        sheet.clear()
        sheet.append_row(headers)
        if rows:
            sanitized_rows = [[self._sanitize_value(val) for val in row] for row in rows]
            sheet.append_rows(sanitized_rows, value_input_option='RAW')

    @retry_connection()
    def append_audit_logs(self, logs):
        if not logs:
            return
        timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        rows_to_append = [[timestamp, 'The Auditor', 'auditor_bot', msg] for msg in logs]
        self.get_sheet('Audit_Log').append_rows(rows_to_append, value_input_option='RAW')
        for msg in logs:
            logger.info(f"Spreadsheet Audit Logged: {msg}")

    @retry_connection()
    def trim_audit_logs(self, keep_last=2000):
        """Trims the Audit_Log tab to keep only the most recent N records."""
        try:
            sheet = self.get_sheet('Audit_Log')
            total_rows = len(sheet.get_all_values())
            
            # keep_last + 1 to account for the header row
            if total_rows > keep_last + 1:
                rows_to_delete = total_rows - (keep_last + 1)
                # Delete from row 2 (row 1 is header) up to the necessary offset
                sheet.delete_rows(2, 2 + rows_to_delete - 1)
                logger.success(f"Trimmed {rows_to_delete} old records from Audit_Log tab.")
        except Exception as e:
            logger.error(f"Failed to trim Audit Logs: {e}")
