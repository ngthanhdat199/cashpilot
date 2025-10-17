import os
import unicodedata
import re
import gspread
import time
import re
from google.oauth2.service_account import Credentials
from src.track_py.utils.logger import logger
from src.track_py.config import config
from src.track_py.utils.timezone import get_current_time
from src.track_py.config import config, BASE_DIR, PROJECT_ROOT
from src.track_py.utils.logger import logger
from src.track_py.const import FOOD_KEYWORDS, DATING_KEYWORDS, TRANSPORT_KEYWORDS, RENT_KEYWORD, LONG_INVEST_KEYWORDS, SUPPORT_PARENT_KEYWORDS, OPPORTUNITY_INVEST_KEYWORDS, FREELANCE_CELL, SALARY_CELL, EXPECTED_HEADERS, TOTAL_EXPENSE_CELL

# Google Sheets setup
try:
    scope = config["google_sheets"]["scopes"]
    # credentials_path = os.path.join(BASE_DIR, config["google_sheets"]["credentials_file"])
    credentials_path = os.path.join(PROJECT_ROOT, config["google_sheets"]["credentials_file"])
    creds = Credentials.from_service_account_file(credentials_path, scopes=scope)
    client = gspread.authorize(creds)
    # Open the specific Google Sheet by ID from the URL
    spreadsheet = client.open_by_key(config["google_sheets"]["spreadsheet_id"])
    logger.info(f"Google Sheets connected successfully using credentials from {credentials_path}")
except Exception as e:
    logger.error(f"Failed to connect to Google Sheets: {e}")
    print("⚠️  Please make sure you have:")
    print(f"1. Created {config['google_sheets']['credentials_file']} file in {PROJECT_ROOT}")
    print(f"2. Shared the Google Sheet (ID: {config['google_sheets']['spreadsheet_id']}) with your service account email")
    print("3. The sheet has the correct permissions")
    exit(1)

# Helper functions for parsing and formatting
def parse_amount(value):
    """
    Convert an amount from int/float/str into a float (VND).
    Handles commas, dots, '₫', 'VND', etc.
    Returns 0 if parsing fails.
    """
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        # Remove everything except digits
        cleaned = re.sub(r"[^\d]", "", value)
        if cleaned.isdigit():
            return float(cleaned)

    logger.warning(f"Invalid amount format '{value}' in today summary")
    return 0.0

def format_expense(r, index=None):
    time_str = r.get("Time", "") or "—"
    amount_str = f"{parse_amount(r.get('VND', 0)):,.0f} VND"
    note_str = r.get("Note", "") or ""
    note_norm = normalize_text(note_str)

    if "xang" in note_norm:
        note_icon = "⛽"
    elif any(k in note_norm for k in ["an", "lunch", "com", "pho", "bun", "mien"]):
        note_icon = "🍽️"
    elif any(k in note_norm for k in ["cafe", "coffee", "ca phe", "caphe"]):
        note_icon = "☕"
    else:
        note_icon = "📝"

    prefix = f"{index}. " if index is not None else ""
    return f"{prefix}⏰ {time_str} | 💰 {amount_str} | {note_icon} {note_str}"

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = str(s).replace("\xa0", " ")        # NBSP → space
    s = unicodedata.normalize("NFD", s)    # decompose accents
    # drop combining marks
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    # map Vietnamese đ/Đ to d/D for ASCII-ish search
    s = s.replace("đ", "d").replace("Đ", "D")
    # collapse whitespace and lowercase
    s = " ".join(s.split()).lower()
    return s

def normalize_date(date_str: str) -> str:
    """
    Normalize a date like '4/9' or '4/10' into '04/09' or '04/10'.
    Keeps only day/month (no year).
    """
    try:
        day, month = date_str.split("/")
        return f"{day.zfill(2)}/{month.zfill(2)}"
    except ValueError:
        return date_str.strip()

def normalize_time(time_str: str) -> str:
    """
    Normalize time formats:
    - '10h'       -> '10:00:00'
    - '01h'       -> '01:00:00'
    - '10h30'     -> '10:30:00'
    - '10h5'      -> '10:05:00'
    - '10h30s45'  -> '10:30:45'
    - '10:05'     -> '10:05:00'
    - '10:05:30'  -> '10:05:30' (unchanged)
    """
    time_str = time_str.strip().lower().replace(" ", "")
    
    if "h" in time_str:
        # Split by 'h' first
        h_parts = time_str.split("h")
        hour = h_parts[0].zfill(2) if h_parts[0] else "00"
        
        # Check if there's minute/second part after 'h'
        if len(h_parts) > 1 and h_parts[1]:
            remaining = h_parts[1]
            
            # Check if there's 's' for seconds
            if "s" in remaining:
                s_parts = remaining.split("s")
                minute = s_parts[0].zfill(2) if s_parts[0] else "00"
                second = s_parts[1].zfill(2) if len(s_parts) > 1 and s_parts[1] else "00"
            else:
                minute = remaining.zfill(2)
                second = "00"
        else:
            minute = "00"
            second = "00"
        
        return f"{hour}:{minute}:{second}"
    
    # Already colon format - add seconds if missing
    if time_str.count(":") == 1:
        return f"{time_str}:00"
    
    return time_str

def has_keyword(note: str, keywords: list[str]) -> bool:
    """
    Check if a note contains any of the specified keywords.
    
    This function performs case-insensitive keyword matching with different strategies:
    - For multi-word keywords (containing spaces): searches for exact substring match
    - For single-word keywords: searches for exact word match in tokenized text
    
    Args:
        note (str): The text to search for keywords
        keywords (list[str]): List of keywords to search for in the note
        
    Returns:
        bool: True if any keyword is found in the note, False otherwise
        
    Note:
        The function tokenizes the note using regex pattern r"[^\\s]+" which splits
        on whitespace. Single-word keywords must match complete tokens to avoid
        partial word matches (e.g., "cat" won't match "category").
    """
    note = note.lower()
    tokens = re.findall(r"[^\s]+", note)

    for k in keywords:
        k = k.lower()
        if " " in k:  # multi-word keyword
            if k in note:
                return True
        else:  # single-word keyword
            if k in tokens:
                return True
    return False

def safe_int(value):
    """Convert a value to int safely, removing non-digit characters"""
    if not value:
        return 0
    text = str(value).strip()
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() else 0

def convert_values_to_records(all_values):
    """Convert raw sheet values to record format (list of dicts)"""
    if not all_values or len(all_values) < 2:  # Need at least header + 1 data row
        return []
    
    records = []
    for row in all_values[1:]:  # Skip header
        if len(row) >= 4:  # Ensure we have all columns
            records.append({
                "Date": row[0] if len(row) > 0 else "",
                "Time": row[1] if len(row) > 1 else "",
                "VND": row[2] if len(row) > 2 else 0,
                "Note": row[3] if len(row) > 3 else ""
            })
    return records


def get_monthly_sheet_if_exists(target_month):
    """Get month's sheet if it exists, return None if it doesn't exist"""
    try:
        sheet_name = target_month
        logger.debug(f"Checking if sheet exists: {sheet_name}")
        
        # Try to get existing sheet
        try:
            current_sheet = spreadsheet.worksheet(sheet_name)
            logger.debug(f"Found existing sheet: {sheet_name}")
            return current_sheet
        except gspread.WorksheetNotFound:
            logger.debug(f"Sheet {sheet_name} not found")
            return None
        except Exception as worksheet_error:
            logger.error(f"Error accessing worksheet {sheet_name}: {worksheet_error}", exc_info=True)
            return None
                
    except Exception as e:
        logger.error(f"Error in get_monthly_sheet_if_exists: {e}", exc_info=True)
        return None

def get_or_create_monthly_sheet(target_month=None):
    """Get month's sheet or create a new one for target month"""
    try:
        if target_month:
            # Use provided target month
            sheet_name = target_month
        else:
            # Use current month
            now = get_current_time()
            # now = get_current_time() + datetime.timedelta(days=63)
            sheet_name = now.strftime("%m/%Y")  # Format: MM/YYYY
        
        logger.info(f"Getting or creating sheet: {sheet_name}")
        
        # Try to get existing sheet
        try:
            current_sheet = spreadsheet.worksheet(sheet_name)
            logger.info(f"Using existing sheet: {sheet_name}")
            return current_sheet
        except gspread.WorksheetNotFound:
            logger.info(f"Sheet {sheet_name} not found, creating new one")
            
            try:
                # Try to copy from template sheet
                try:
                    template_sheet = spreadsheet.worksheet(config["settings"]["template_sheet_name"])
                    logger.info(f"Found template sheet: {config['settings']['template_sheet_name']}")
                    
                    # Create new sheet by duplicating the template
                    new_sheet = template_sheet.duplicate(new_sheet_name=sheet_name)
                    logger.info(f"Duplicated template sheet to create: {sheet_name}")
                    
                    # Clear only the data rows, keep headers and formatting
                    # Get all values to identify where data starts (after headers)
                    # try:
                    #     all_values = new_sheet.get_all_values()
                        
                    #     if len(all_values) > 1:  # If there's more than just headers
                    #         # Clear data from row 2 onwards (keep row 1 as headers)
                    #         range_to_clear = f"A2:Z{len(all_values)}"
                    #         new_sheet.batch_clear([range_to_clear])
                    #         logger.info(f"Cleared data rows from new sheet: {range_to_clear}")
                    # except Exception as clear_error:
                    #     logger.warning(f"Could not clear template data: {clear_error}")

                    salary_income = new_sheet.acell(SALARY_CELL).value
                    if not salary_income or salary_income.strip() == "":
                        salary_income = config["income"]["salary"]
                        new_sheet.update_acell(SALARY_CELL, salary_income)

                    freelance_income = new_sheet.acell(FREELANCE_CELL).value
                    if not freelance_income or freelance_income.strip() == "":
                        freelance_income = config["income"]["freelance"]
                        new_sheet.update_acell(FREELANCE_CELL, freelance_income)

                    logger.info(f"Created new sheet from template: {sheet_name}")
                    return new_sheet
                    
                except gspread.WorksheetNotFound:
                    logger.warning(f"Template sheet '{config['settings']['template_sheet_name']}' not found, creating basic sheet")
                    # Create a basic sheet if template doesn't exist
                    new_sheet = spreadsheet.add_worksheet(title=sheet_name, rows="100", cols="10")
                    
                    # Add basic headers
                    headers = ["Date", "Time", "VND", "Note"]
                    new_sheet.append_row(headers)
                    
                    logger.info(f"Created basic sheet: {sheet_name}")
                    return new_sheet
                except Exception as template_error:
                    logger.error(f"Error copying from template: {template_error}", exc_info=True)
                    raise
                    
            except Exception as create_error:
                logger.error(f"Error creating sheet {sheet_name}: {create_error}", exc_info=True)
                # Fallback to first available sheet
                logger.warning("Falling back to default sheet")
                return spreadsheet.sheet1
        except Exception as worksheet_error:
            logger.error(f"Error accessing worksheet {sheet_name}: {worksheet_error}", exc_info=True)
            raise
                
    except Exception as e:
        logger.error(f"Error in get_or_create_monthly_sheet: {e}", exc_info=True)
        # Fallback to default sheet
        logger.warning("Falling back to default sheet due to error")
        try:
            return spreadsheet.sheet1
        except Exception as fallback_error:
            logger.error(f"Even fallback to sheet1 failed: {fallback_error}", exc_info=True)
            raise

def get_gas_total(month):
    """Helper to get total gas expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)
        
        gas_expenses = []
        total = 0
        
        for r in records:
            note = r.get("Note", "").lower()
            if has_keyword(note, TRANSPORT_KEYWORDS):
                amount = r.get("VND", 0)
                if amount:
                    gas_expenses.append(r)
                    total += parse_amount(amount)
        
        return gas_expenses, total
    except Exception as e:
        logger.error(f"Error getting gas total for {month}: {e}", exc_info=True)
        return [], 0

# helper for food totals
def get_food_total(month):
    """Helper to get total food expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)
        
        food_expenses = []
        total = 0
        
        for r in records:
            note = r.get("Note", "").lower()
            if has_keyword(note, FOOD_KEYWORDS):
                amount = r.get("VND", 0)
                if amount:
                    food_expenses.append(r)
                    total += parse_amount(amount)
        
        return food_expenses, total
    except Exception as e:
        logger.error(f"Error getting food total for {month}: {e}", exc_info=True)
        return [], 0
    
# helper for dating totals
def get_dating_total(month):
    """Helper to get total date expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        date_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if has_keyword(note, DATING_KEYWORDS):
                    amount = r.get("VND", 0)
                    if amount:
                        date_expenses.append(r)
                        total += parse_amount(amount)
        
        return date_expenses, total
    except Exception as e:
        logger.error(f"Error getting dating total for {month}: {e}", exc_info=True)
        return [], 0
    
# helper for rent totals
def get_rent_total(month):
    """Helper to get total rent expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        rent_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if RENT_KEYWORD in note:
                    amount = r.get("VND", 0)
                    if amount:
                        rent_expenses.append(r)
                        total += parse_amount(amount)
        
        return rent_expenses, total
    except Exception as e:
        logger.error(f"Error getting rent total for {month}: {e}", exc_info=True)
        return [], 0
    
# helper for other totals
def get_other_total(month):
    """Helper to get total other expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        other_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if not (
                    has_keyword(note, FOOD_KEYWORDS) or 
                    has_keyword(note, DATING_KEYWORDS) or
                    has_keyword(note, TRANSPORT_KEYWORDS) or
                    has_keyword(note, LONG_INVEST_KEYWORDS) or 
                    has_keyword(note, OPPORTUNITY_INVEST_KEYWORDS) or
                    has_keyword(note, SUPPORT_PARENT_KEYWORDS)  or
                    has_keyword(note, RENT_KEYWORD)
                ):
                    amount = r.get("VND", 0)
                    if amount:
                        other_expenses.append(r)
                        total += parse_amount(amount)
        
        return other_expenses, total
    except Exception as e:
        logger.error(f"Error getting other total for {month}: {e}", exc_info=True)
        return [], 0

# helper for investment totals
def get_long_investment_total(month):
    """Helper to get total investment expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if has_keyword(note, LONG_INVEST_KEYWORDS):
                    amount = r.get("VND", 0)
                    if amount:
                        invest_expenses.append(r)
                        total += parse_amount(amount)
        
        return invest_expenses, total
    except Exception as e:
        logger.error(f"Error getting investment total for {month}: {e}", exc_info=True)
        return [], 0

def get_opportunity_investment_total(month):
    """Helper to get total opportunity investment expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if has_keyword(note, OPPORTUNITY_INVEST_KEYWORDS):
                    amount = r.get("VND", 0)
                    if amount:
                        invest_expenses.append(r)
                        total += parse_amount(amount)
        
        return invest_expenses, total
    except Exception as e:
        logger.error(f"Error getting opportunity investment total for {month}: {e}", exc_info=True)
        return [], 0
    
def get_investment_total(month):
    """Helper to get total investment expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if has_keyword(note, OPPORTUNITY_INVEST_KEYWORDS) or has_keyword(note, LONG_INVEST_KEYWORDS):
                    amount = r.get("VND", 0)
                    if amount:
                        invest_expenses.append(r)
                        total += parse_amount(amount)
        
        return invest_expenses, total
    except Exception as e:
        logger.error(f"Error getting opportunity investment total for {month}: {e}", exc_info=True)
        return [], 0


# helper for support parent totals
def get_support_parent_total(month):
    """Helper to get total support parent expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        
        # Skip header row and convert to records-like format
        support_parent_expenses = []
        total = 0
        
        for row in all_values[1:]:  # Skip header
            if len(row) >= 4:  # Ensure we have all columns
                r = {
                    "Date": row[0] if len(row) > 0 else "",
                    "Time": row[1] if len(row) > 1 else "",
                    "VND": row[2] if len(row) > 2 else 0,
                    "Note": row[3] if len(row) > 3 else ""
                }
                note = r.get("Note", "").lower()
                if has_keyword(note, SUPPORT_PARENT_KEYWORDS):
                    amount = r.get("VND", 0)
                    if amount:
                        support_parent_expenses.append(r)
                        total += parse_amount(amount)
        
        return support_parent_expenses, total
    except Exception as e:
        logger.error(f"Error getting support parent total for {month}: {e}", exc_info=True)
        return [], 0
    
# helper for totals summary
def get_month_summary(records):
    """Helper to get total expenses summary for a given month"""
    totals = {
        "expenses": [],
        "total": 0,
        "food": 0,
        "dating": 0,
        "gas": 0,
        "rent": 0,
        "other": 0,
        "long_investment": 0,
        "opportunity_investment": 0,
        "essential": 0, # total of food + gas + rent + other
        "investment": 0,  # total of long_investment + opportunity_investment
        "support_parent": 0,
    }

    for r in records:
        note = r.get("Note", "").lower()
        amount = parse_amount(r.get("VND", 0))

        if amount == 0:
            continue        

        totals["expenses"].append(r)
        totals["total"] += amount

        if has_keyword(note, FOOD_KEYWORDS):
            totals["food"] += amount
            totals["essential"] += amount
        elif has_keyword(note, TRANSPORT_KEYWORDS):
            totals["gas"] += amount
            totals["essential"] += amount
        elif has_keyword(note, RENT_KEYWORD):
            totals["rent"] += amount
            totals["essential"] += amount
        elif has_keyword(note, DATING_KEYWORDS):
            totals["dating"] += amount
        elif has_keyword(note, LONG_INVEST_KEYWORDS):
            totals["long_investment"] += amount
            totals["investment"] += amount
        elif has_keyword(note, OPPORTUNITY_INVEST_KEYWORDS):
            totals["opportunity_investment"] += amount
            totals["investment"] += amount
        elif has_keyword(note, SUPPORT_PARENT_KEYWORDS):
            totals["support_parent"] += amount
        else:
            totals["other"] += amount
            totals["essential"] += amount

    return totals

# helper for get total income
def get_total_income(sheet):
    """Helper to get total income from salary and freelance"""
    try:
        salary = sheet.acell(SALARY_CELL).value
        freelance = sheet.acell(FREELANCE_CELL).value

        if not salary or salary.strip() == "":
            salary = config["income"]["salary"]
        if not freelance or freelance.strip() == "":
            freelance = config["income"]["freelance"]
        
        salary = safe_int(salary)
        freelance = safe_int(freelance)
        total_income = salary + freelance
        return total_income
    except Exception as e:
        logger.error(f"Error getting total income: {e}", exc_info=True)
        return 0, 0, 0
    
# Performance optimization: Cache for sheet data to reduce API calls
_sheet_cache = {}
_worksheet_cache = {}
_cache_timeout = 30  # Cache data for 30 seconds

def get_cached_worksheet(sheet_name, force_refresh=False):
    """Get cached worksheet object or fetch fresh if expired"""
    current_time = time.time()
    cache_key = f"worksheet_{sheet_name}"
    
    if not force_refresh and cache_key in _worksheet_cache:
        worksheet, timestamp = _worksheet_cache[cache_key]
        if current_time - timestamp < _cache_timeout:
            logger.debug(f"Using cached worksheet for {sheet_name}")
            return worksheet
    
    # Fetch fresh worksheet
    logger.debug(f"Fetching fresh worksheet for {sheet_name}")
    try:
        worksheet = get_or_create_monthly_sheet(sheet_name)
        _worksheet_cache[cache_key] = (worksheet, current_time)
        return worksheet
    except Exception as e:
        logger.error(f"Error fetching worksheet for {sheet_name}: {e}")
        # Return cached worksheet if available, even if expired
        if cache_key in _worksheet_cache:
            return _worksheet_cache[cache_key][0]
        raise

def get_cached_sheet_data(sheet_name, force_refresh=False):
    """Get cached sheet data or fetch fresh if expired"""
    current_time = time.time()
    cache_key = f"data_{sheet_name}"
    
    if not force_refresh and cache_key in _sheet_cache:
        data, timestamp = _sheet_cache[cache_key]
        if current_time - timestamp < _cache_timeout:
            logger.debug(f"Using cached data for sheet {sheet_name}")
            return data
    
    # Fetch fresh data
    logger.debug(f"Fetching fresh data for sheet {sheet_name}")
    try:
        sheet = get_cached_worksheet(sheet_name)
        # Use get_values instead of get_all_records for better performance
        all_values = sheet.get_values("A:D")
        _sheet_cache[cache_key] = (all_values, current_time)
        return all_values
    except Exception as e:
        logger.error(f"Error fetching sheet data for {sheet_name}: {e}")
        # Return cached data if available, even if expired
        if cache_key in _sheet_cache:
            return _sheet_cache[cache_key][0]
        raise

def invalidate_sheet_cache(sheet_name):
    """Invalidate cache for a specific sheet"""
    data_key = f"data_{sheet_name}"
    worksheet_key = f"worksheet_{sheet_name}"
    
    if data_key in _sheet_cache:
        del _sheet_cache[data_key]
        logger.debug(f"Invalidated data cache for sheet {sheet_name}")
    
    if worksheet_key in _worksheet_cache:
        del _worksheet_cache[worksheet_key]
        logger.debug(f"Invalidated worksheet cache for sheet {sheet_name}")

def get_monthly_expense(sheet_name):
    """Fetch total expense for a given month sheet"""
    total = 0.0
    try:
        # Try to get the sheet for this month (don't create if it doesn't exist)
        sheet = get_monthly_sheet_if_exists(sheet_name)
        if sheet:
            # Get value from cell G2 (total expenses cell)
            try:
                total_cell_value = sheet.acell(TOTAL_EXPENSE_CELL).value
                if total_cell_value:
                    # Parse the amount (remove currency symbols, commas, etc.)
                    total = parse_amount(total_cell_value)
            except Exception as cell_error:
                logger.warning(f"Could not read G2 from sheet {sheet_name}: {cell_error}")
    except Exception as sheet_error:
        logger.error(f"Error accessing sheet {sheet_name}: {sheet_error}")
    
    return total

# Convert markdown → HTML
def markdown_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text
