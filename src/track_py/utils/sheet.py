import os
import gspread
import time
import re
import asyncio
import datetime
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials
from gspread.utils import a1_to_rowcol
from src.track_py.utils.logger import logger
from src.track_py.utils.timezone import get_current_time
from src.track_py.config import config, PROJECT_ROOT
from src.track_py.utils.logger import logger
import src.track_py.const as const
import src.track_py.utils.util as util
from src.track_py.utils.category import category_display
from src.track_py.utils.datetime import parse_date_time
from typing import TypedDict
from huggingface_hub import InferenceClient
from src.track_py.utils.util import markdown_to_html
from src.track_py.config import config, save_config
from collections import defaultdict


class Record(TypedDict):
    date: str
    time: str
    vnd: int
    note: str


# Performance optimization: Cache for sheet data to reduce API calls
_sheet_cache = {}
_worksheet_cache = {}
_cache_timeout = 300  # Cache timeout in seconds (5 minutes)
_today_cache_timeout = 60  # Shorter cache for today's data (1 minute)

# Google Sheets setup
try:
    scope = config["google_sheets"]["scopes"]
    credentials_path = os.path.join(
        PROJECT_ROOT, config["google_sheets"]["credentials_file"]
    )
    creds = Credentials.from_service_account_file(credentials_path, scopes=scope)
    client = gspread.authorize(creds)

    # Open the specific Google Sheet by ID from the URL
    spreadsheet = client.open_by_key(config["google_sheets"]["spreadsheet_id"])
    logger.info(
        f"Google Sheets connected successfully using credentials from {credentials_path}"
    )
except Exception as e:
    logger.error(f"Failed to connect to Google Sheets: {e}")
    print("⚠️  Please make sure you have:")
    print(
        f"1. Created {config['google_sheets']['credentials_file']} file in {PROJECT_ROOT}"
    )
    print(
        f"2. Shared the Google Sheet (ID: {config['google_sheets']['spreadsheet_id']}) with your service account email"
    )
    print("3. The sheet has the correct permissions")
    exit(1)


def parse_amount(value: int | float | str) -> int:
    """
    Convert an amount from int/float/str into a float (VND).
    Handles commas, dots, '₫', 'VND', etc.
    Returns 0 if parsing fails.
    """
    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        # Remove everything except digits
        cleaned = re.sub(r"[^\d]", "", value)
        if cleaned.isdigit():
            return int(cleaned)

    logger.warning(f"Invalid amount format '{value}' in today summary")
    return 0


def format_expense(r: Record, index=None):
    """Format an expense record into a readable string"""
    time_str = r["time"] or "—"
    amount_str = f"{parse_amount(r['vnd']):,.0f} VND"
    note_str = r["note"].lower() or ""

    if has_keyword(note_str, const.FOOD_KEYWORDS):
        note_icon = const.CATEGORY_ICONS["food"]
    elif has_keyword(note_str, const.TRANSPORT_KEYWORDS):
        note_icon = const.CATEGORY_ICONS["gas"]
    elif has_keyword(note_str, const.DATING_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.DATING]
    elif has_keyword(note_str, const.LONG_INVEST_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.LONG_INVEST]
    elif has_keyword(note_str, const.OPPORTUNITY_INVEST_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.OPPORTUNITY_INVEST]
    elif has_keyword(note_str, const.SUPPORT_PARENT_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.SUPPORT_PARENT]
    elif has_keyword(note_str, const.RENT_KEYWORD):
        note_icon = const.CATEGORY_ICONS[const.RENT]
    else:
        note_icon = "📝"

    prefix = f"{index}. " if index is not None else ""
    return f"{prefix}⏰ {time_str} | 💰 {amount_str} | {note_icon} {note_str}"


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
                second = (
                    s_parts[1].zfill(2) if len(s_parts) > 1 and s_parts[1] else "00"
                )
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


def safe_int(value: str) -> int:
    """Convert a string value to int safely, removing non-digit characters"""
    if not value:
        return 0

    text = str(value).strip()
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() else 0


def convert_values_to_records(all_values: list[list[str]]) -> list[Record]:
    """Convert raw sheet values to record format (list of dicts) with optimization"""
    if not all_values or len(all_values) < 2:  # Need at least header + 1 data row
        return []

    records = []
    for row in all_values[1:]:  # Skip header
        # Create record with proper error handling
        record = Record(
            {
                "date": (row[0] if len(row) > 0 else "").strip(),
                "time": (row[1] if len(row) > 1 else "").strip(),
                "vnd": row[2] if len(row) > 2 else 0,
                "note": (row[3] if len(row) > 3 else "").strip(),
            }
        )

        # Only add records that have at least a date or amount
        if record["date"] or record["vnd"]:
            records.append(record)

    return records


def get_monthly_sheet_if_exists(target_month: str) -> gspread.Worksheet | None:
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
            logger.error(
                f"Error accessing worksheet {sheet_name}: {worksheet_error}",
                exc_info=True,
            )
            return None

    except Exception as e:
        logger.error(f"Error in get_monthly_sheet_if_exists: {e}", exc_info=True)
        return None


def get_or_create_monthly_sheet(target_month=None) -> gspread.Worksheet:
    """Get month's sheet or create a new one for target month"""
    try:
        if target_month:
            # Use provided target month
            sheet_name = target_month
        else:
            # Use current month
            now = get_current_time()
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
                    template_sheet = spreadsheet.worksheet(
                        config["settings"]["template_sheet_name"]
                    )
                    logger.info(
                        f"Found template sheet: {config['settings']['template_sheet_name']}"
                    )

                    # Create new sheet by duplicating the template
                    new_sheet = template_sheet.duplicate(new_sheet_name=sheet_name)
                    logger.info(f"Duplicated template sheet to create: {sheet_name}")

                    try:
                        update_config_to_sheet(new_sheet)
                    except Exception as e:
                        logger.error(
                            f"Error updating config to new sheet {sheet_name}: {e}",
                            exc_info=True,
                        )

                    logger.info(f"Created new sheet from template: {sheet_name}")
                    return new_sheet

                except gspread.WorksheetNotFound:
                    logger.warning(
                        f"Template sheet '{config['settings']['template_sheet_name']}' not found, creating basic sheet"
                    )
                    # Create a basic sheet if template doesn't exist
                    new_sheet = spreadsheet.add_worksheet(
                        title=sheet_name, rows="100", cols="10"
                    )

                    # Add basic headers
                    headers = ["Date", "Time", "VND", "Note"]
                    new_sheet.append_row(headers)

                    logger.info(f"Created basic sheet: {sheet_name}")
                    return new_sheet
                except Exception as template_error:
                    logger.error(
                        f"Error copying from template: {template_error}", exc_info=True
                    )
                    raise

            except Exception as create_error:
                logger.error(
                    f"Error creating sheet {sheet_name}: {create_error}", exc_info=True
                )
                # Fallback to first available sheet
                logger.warning("Falling back to default sheet")
                return spreadsheet.sheet1
        except Exception as worksheet_error:
            logger.error(
                f"Error accessing worksheet {sheet_name}: {worksheet_error}",
                exc_info=True,
            )
            raise

    except Exception as e:
        logger.error(f"Error in get_or_create_monthly_sheet: {e}", exc_info=True)
        # Fallback to default sheet
        logger.warning("Falling back to default sheet due to error")
        try:
            return spreadsheet.sheet1
        except Exception as fallback_error:
            logger.error(
                f"Even fallback to sheet1 failed: {fallback_error}", exc_info=True
            )
            raise


def get_gas_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total gas expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        gas_expenses = []
        total = 0

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.TRANSPORT_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    gas_expenses.append(r)
                    total += parse_amount(amount)

        return gas_expenses, total
    except Exception as e:
        logger.error(f"Error getting gas total for {month}: {e}", exc_info=True)
        return [], 0


# helper for food totals
def get_food_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total food expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        food_expenses = []
        total = 0

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.FOOD_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    food_expenses.append(r)
                    total += parse_amount(amount)

        return food_expenses, total
    except Exception as e:
        logger.error(f"Error getting food total for {month}: {e}", exc_info=True)
        return [], 0


# helper for dating totals
def get_dating_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total date expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        date_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.DATING_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    date_expenses.append(r)
                    total += parse_amount(amount)

        return date_expenses, total
    except Exception as e:
        logger.error(f"Error getting dating total for {month}: {e}", exc_info=True)
        return [], 0


# helper for rent totals
def get_rent_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total rent expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        rent_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if const.RENT_KEYWORD in note:
                amount = r["vnd"]
                if amount:
                    rent_expenses.append(r)
                    total += parse_amount(amount)

        return rent_expenses, total
    except Exception as e:
        logger.error(f"Error getting rent total for {month}: {e}", exc_info=True)
        return [], 0


# helper for other totals
def get_other_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total other expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        other_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if not (
                has_keyword(note, const.FOOD_KEYWORDS)
                or has_keyword(note, const.DATING_KEYWORDS)
                or has_keyword(note, const.TRANSPORT_KEYWORDS)
                or has_keyword(note, const.LONG_INVEST_KEYWORDS)
                or has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS)
                or has_keyword(note, const.SUPPORT_PARENT_KEYWORDS)
                or has_keyword(note, const.RENT_KEYWORD)
            ):
                amount = r["vnd"]
                if amount:
                    other_expenses.append(r)
                    total += parse_amount(amount)

        return other_expenses, total
    except Exception as e:
        logger.error(f"Error getting other total for {month}: {e}", exc_info=True)
        return [], 0


# helper for investment totals
def get_long_investment_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total investment expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.LONG_INVEST_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    invest_expenses.append(r)
                    total += parse_amount(amount)

        return invest_expenses, total
    except Exception as e:
        logger.error(f"Error getting investment total for {month}: {e}", exc_info=True)
        return [], 0


def get_opportunity_investment_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total opportunity investment expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    invest_expenses.append(r)
                    total += parse_amount(amount)

        return invest_expenses, total
    except Exception as e:
        logger.error(
            f"Error getting opportunity investment total for {month}: {e}",
            exc_info=True,
        )
        return [], 0


def get_investment_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total investment expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS) or has_keyword(
                note, const.LONG_INVEST_KEYWORDS
            ):
                amount = r["vnd"]
                if amount:
                    invest_expenses.append(r)
                    total += parse_amount(amount)

        return invest_expenses, total
    except Exception as e:
        logger.error(
            f"Error getting opportunity investment total for {month}: {e}",
            exc_info=True,
        )
        return [], 0


# helper for support parent totals
def get_support_parent_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total support parent expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        support_parent_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = get_cached_sheet_data(month)
        records = convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if has_keyword(note, const.SUPPORT_PARENT_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    support_parent_expenses.append(r)
                    total += parse_amount(amount)

        return support_parent_expenses, total
    except Exception as e:
        logger.error(
            f"Error getting support parent total for {month}: {e}", exc_info=True
        )
        return [], 0


# helper for totals summary
def get_records_summary_by_cat(records: list[Record]) -> dict:
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
        "essential": 0,  # total of food + gas + rent + other
        "investment": 0,  # total of long_investment + opportunity_investment
        "support_parent": 0,
        "food_and_travel": 0,
    }

    for r in records:
        note = r["note"].lower()
        amount = parse_amount(r["vnd"])

        if amount == 0:
            continue

        totals["expenses"].append(r)
        totals["total"] += amount

        if has_keyword(note, const.FOOD_KEYWORDS):
            totals["food"] += amount
            totals["essential"] += amount
        elif has_keyword(note, const.TRANSPORT_KEYWORDS):
            totals["gas"] += amount
            totals["essential"] += amount
        elif has_keyword(note, const.RENT_KEYWORD):
            totals["rent"] += amount
            totals["essential"] += amount
        elif has_keyword(note, const.DATING_KEYWORDS):
            totals["dating"] += amount
        elif has_keyword(note, const.LONG_INVEST_KEYWORDS):
            totals["long_investment"] += amount
            totals["investment"] += amount
        elif has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS):
            totals["opportunity_investment"] += amount
            totals["investment"] += amount
        elif has_keyword(note, const.SUPPORT_PARENT_KEYWORDS):
            totals["support_parent"] += amount
        else:
            totals["other"] += amount
            totals["essential"] += amount

    # Calculate food_and_travel total
    totals["food_and_travel"] = totals["food"] + totals["gas"]

    return totals


# helper for get total income
def get_total_income(sheet: gspread.Worksheet) -> int:
    """Helper to get total income from salary and freelance"""
    try:
        salary = sheet.acell(const.SALARY_CELL).value
        freelance = sheet.acell(const.FREELANCE_CELL).value

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
        return 0


def get_cached_worksheet(
    sheet_name: str, force_refresh: bool = False
) -> gspread.Worksheet:
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


def get_cached_sheet_data(
    sheet_name: str, force_refresh: bool = False
) -> list[list[str]]:
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


def get_cached_today_data(
    sheet_name: str, today_str: str, force_refresh: bool = False
) -> list[list[str]]:
    """Get cached today's data with shorter cache timeout for better freshness"""
    current_time = time.time()
    cache_key = f"today_data_{sheet_name}_{today_str}"

    if not force_refresh and cache_key in _sheet_cache:
        data, timestamp = _sheet_cache[cache_key]
        if current_time - timestamp < _today_cache_timeout:
            logger.info(
                f"Using cached today data for {today_str} in sheet {sheet_name}"
            )
            return data

    # Fetch fresh data - try to get a smaller range first
    logger.info(f"Fetching fresh today data for {today_str} in sheet {sheet_name}")
    try:
        sheet = get_cached_worksheet(sheet_name)

        # First attempt: Try to get the sheet's actual used range to optimize further
        try:
            # Get the actual last row with data to avoid fetching empty rows
            all_values_meta = sheet.get_values(
                "A:A"
            )  # Just get column A to find last row
            if all_values_meta:
                last_row = len(all_values_meta)
                # Add some buffer but cap at reasonable limit
                fetch_range = f"A2:D{min(last_row + 10, 1000)}"
                logger.info(f"Optimizing fetch range to: {fetch_range}")
                logger.info(
                    f"Optimized fetch range: {fetch_range} (detected {last_row} rows)"
                )
                all_values = sheet.get_values(fetch_range)
                logger.info(f"Fetched {all_values} rows for today data")
            else:
                all_values = []
        except Exception as range_error:
            logger.debug(
                f"Range optimization failed, using default range: {range_error}"
            )
            # Fallback to fixed range
            all_values = sheet.get_values("A2:D1000")

        # Add header row for consistency with existing code
        if all_values:
            all_values.insert(0, ["Date", "Time", "VND", "Note"])
        else:
            all_values = [["Date", "Time", "VND", "Note"]]

        _sheet_cache[cache_key] = (all_values, current_time)
        return all_values
    except Exception as e:
        logger.error(f"Error fetching today's sheet data for {sheet_name}: {e}")
        # Fallback to full sheet data if range fetch fails
        try:
            return get_cached_sheet_data(sheet_name, force_refresh)
        except Exception as fallback_error:
            logger.error(f"Fallback fetch also failed: {fallback_error}")
            # Return cached data if available, even if expired
            if cache_key in _sheet_cache:
                return _sheet_cache[cache_key][0]
            raise


def invalidate_sheet_cache(sheet_name: str):
    """Invalidate cache for a specific sheet"""
    data_key = f"data_{sheet_name}"
    worksheet_key = f"worksheet_{sheet_name}"

    if data_key in _sheet_cache:
        del _sheet_cache[data_key]
        logger.debug(f"Invalidated data cache for sheet {sheet_name}")

    if worksheet_key in _worksheet_cache:
        del _worksheet_cache[worksheet_key]
        logger.debug(f"Invalidated worksheet cache for sheet {sheet_name}")

    # Also invalidate today's data cache for this sheet
    today_keys_to_remove = [
        key
        for key in _sheet_cache.keys()
        if key.startswith(f"today_data_{sheet_name}_")
    ]
    for key in today_keys_to_remove:
        del _sheet_cache[key]
        logger.debug(f"Invalidated today cache: {key}")


def get_monthly_expense(sheet_name: str) -> int:
    """Fetch total expense for a given month sheet"""
    total = 0
    try:
        # Try to get the sheet for this month (don't create if it doesn't exist)
        sheet = get_monthly_sheet_if_exists(sheet_name)
        if sheet:
            # Get value from cell G2 (total expenses cell)
            try:
                total_cell_value = sheet.acell(const.TOTAL_EXPENSE_CELL).value
                if total_cell_value:
                    # Parse the amount (remove currency symbols, commas, etc.)
                    total = parse_amount(total_cell_value)
            except Exception as cell_error:
                logger.warning(
                    f"Could not read G2 from sheet {sheet_name}: {cell_error}"
                )
    except Exception as sheet_error:
        logger.error(f"Error accessing sheet {sheet_name}: {sheet_error}")

    return total


# helper for month response
def get_month_response(
    records: list[Record], sheet: gspread.Worksheet, time_with_offset: datetime.datetime
) -> str:
    summary = get_records_summary_by_cat(records)
    month_expenses = summary["expenses"]
    total = summary["total"]
    food_total = summary["food"]
    dating_total = summary["dating"]
    gas_total = summary["gas"]
    rent_total = summary["rent"]
    other_total = summary["other"]
    long_invest_total = summary["long_investment"]
    opportunity_invest_total = summary["opportunity_investment"]
    investment_total = summary["investment"]
    support_parent_total = summary["support_parent"]
    food_and_travel_total = food_total + gas_total + other_total

    total_income = get_month_budget_by_sheet(sheet)

    category_budget = get_category_percentages_by_sheet(sheet)
    food_and_travel_budget = category_budget[const.FOOD_TRAVEL]
    rent_budget = category_budget[const.RENT]
    long_invest_budget = category_budget[const.LONG_INVEST]
    opportunity_invest_budget = category_budget[const.OPPORTUNITY_INVEST]
    support_parent_budget = category_budget[const.SUPPORT_PARENT]
    dating_budget = category_budget[const.DATING]

    count = len(month_expenses)
    month = time_with_offset.strftime("%m")
    year = time_with_offset.strftime("%Y")
    month_display = util.get_month_display(month, year)

    # Calculate estimated amounts based on percentages and income
    food_and_travel_estimate = (
        total_income * (food_and_travel_budget / 100) if total_income > 0 else 0
    )
    rent_estimate = total_income * (rent_budget / 100) if total_income > 0 else 0
    long_invest_estimate = (
        total_income * (long_invest_budget / 100) if total_income > 0 else 0
    )
    opportunity_invest_estimate = (
        total_income * (opportunity_invest_budget / 100) if total_income > 0 else 0
    )
    support_parent_estimate = (
        total_income * (support_parent_budget / 100) if total_income > 0 else 0
    )
    dating_estimate = total_income * (dating_budget / 100) if total_income > 0 else 0

    response = (
        f"{category_display['summarized']} {month_display}:\n"
        f"{category_display['income']}: {total_income:,.0f} VND\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['balance']}: {total_income - total:,.0f} VND\n\n"
        f"{category_display['estimate_budget']}:\n"
        f"{category_display['rent']}: {rent_budget:.0f}% = {rent_estimate:,.0f} VND\n"
        f"{category_display['food_and_travel']}: {food_and_travel_budget:.0f}% = {food_and_travel_estimate:,.0f} VND\n"
        f"{category_display['support_parent']}: {support_parent_budget:.0f}% = {support_parent_estimate:,.0f} VND\n"
        f"{category_display['dating']}: {dating_budget:.0f}% = {dating_estimate:,.0f} VND\n"
        f"{category_display['long_investment']}: {long_invest_budget:.0f}% = {long_invest_estimate:,.0f} VND\n"
        f"{category_display['opportunity_investment']}: {opportunity_invest_budget:.0f}% = {opportunity_invest_estimate:,.0f} VND\n\n"
        f"{category_display['actual_spend']}:\n"
        f"{category_display['rent']}: {rent_total:,.0f} VND ({rent_estimate - rent_total:+,.0f})\n"
        f"{category_display['food_and_travel']}: {food_and_travel_total:,.0f} VND ({food_and_travel_estimate - food_and_travel_total:+,.0f})\n"
        f"{category_display['support_parent']}: {support_parent_total:,.0f} VND ({support_parent_estimate - support_parent_total:+,.0f})\n"
        f"{category_display['dating']}: {dating_total:,.0f} VND ({dating_estimate - dating_total:+,.0f})\n"
        f"{category_display['long_investment']}: {long_invest_total:,.0f} VND ({long_invest_estimate - long_invest_total:+,.0f})\n"
        f"{category_display['opportunity_investment']}: {opportunity_invest_total:,.0f} VND ({opportunity_invest_estimate - opportunity_invest_total:+,.0f})\n\n"
        f"{category_display['detail']}:\n"
        f"{category_display['rent']}: {rent_total:,.0f} VND\n"
        f"{category_display['food']}: {food_total:,.0f} VND\n"
        f"{category_display['gas']}: {gas_total:,.0f} VND\n"
        f"{category_display['support_parent']}: {support_parent_total:,.0f} VND\n"
        f"{category_display['dating']}: {dating_total:,.0f} VND\n"
        f"{category_display['investment']}: {investment_total:,.0f} VND\n"
        f"{category_display['other']}: {other_total:,.0f} VND\n"
    )

    return response


# Helper to get week's expenses from relevant month sheets
async def get_week_process_data(time_with_offset: datetime.datetime) -> dict:
    now = time_with_offset
    # Calculate week boundaries
    week_start = now - datetime.timedelta(days=now.weekday())  # Monday
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)

    logger.info(f"Getting week expenses from {week_start:%d/%m} to {week_end:%d/%m}")

    # Collect all months the week spans
    months_to_check = sorted(
        {(week_start + datetime.timedelta(days=i)).strftime("%m/%Y") for i in range(7)},
        key=lambda s: datetime.datetime.strptime(s, "%m/%Y"),
    )

    week_expenses = []
    total = 0.0
    week_records = []

    tasks = [
        asyncio.to_thread(get_cached_sheet_data, month) for month in months_to_check
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process each relevant sheet
    for target_month, all_values in zip(months_to_check, results):
        try:
            records = convert_values_to_records(all_values)
            year = target_month.split("/")[1]
            for r in records:
                raw_date = r["date"].strip()
                raw_amount = r["vnd"]

                if not raw_date or not raw_amount:
                    continue

                try:
                    # Parse dd/mm with inferred year
                    if "/" not in raw_date:
                        continue
                    day, month = raw_date.split("/")[:2]
                    date_obj = datetime.datetime.strptime(
                        f"{day}/{month}/{year}", "%d/%m/%Y"
                    )
                    expense_date = date_obj.replace(tzinfo=week_start.tzinfo)

                    if week_start <= expense_date <= week_end:
                        amount = parse_amount(raw_amount)
                        if amount == 0:
                            continue
                        r["expense_date"] = expense_date
                        week_expenses.append(r)
                        total += amount
                        week_records.append(r)
                except Exception as e:
                    logger.debug(
                        f"Skipping invalid date {raw_date} in {target_month}: {e}"
                    )
                    continue

        except Exception as sheet_error:
            logger.warning(f"Could not access sheet {target_month}: {sheet_error}")
            continue

    # Prepare grouped details
    count = len(week_expenses)
    logger.info(f"Found {count} expenses with total {total} VND")

    return {
        "total": total,
        "week_expenses": week_expenses,
        "week_start": week_start,
        "week_end": week_end,
        "records": week_records,
    }


# Helper to get today's expenses from relevant month sheet
async def get_daily_process_data(time_with_offset: datetime.datetime) -> dict:
    now = time_with_offset
    today_str = now.strftime("%d/%m")
    target_month = now.strftime("%m/%Y")

    logger.info(f"Getting today's expenses for {today_str} in sheet {target_month}")

    try:
        # Use optimized today data fetching with shorter cache
        all_values = await asyncio.to_thread(
            get_cached_today_data, target_month, today_str
        )
        logger.info(f"Retrieved {len(all_values)} rows from sheet (today cache)")
    except Exception as sheet_error:
        logger.error(
            f"Error getting sheet data for {target_month}: {sheet_error}", exc_info=True
        )
        return

    today_expenses = []
    total = 0
    today_records = []
    records = convert_values_to_records(all_values)
    for r in records:
        record_date = r["date"].strip().lstrip("'")
        if record_date and record_date > today_str:
            continue

        if record_date == today_str:
            record_amount = r["vnd"]
            amount = parse_amount(record_amount)
            if amount > 0:  # Only include records with valid amounts
                today_expenses.append(r)
                total += amount
                today_records.append(r)

    count = len(today_expenses)
    logger.info(f"Found {count} expenses for today with total {total} VND")
    logger.info(
        f"Today date string: '{today_str}', Rows processed: {len(all_values)}"
    )  # Debug info

    return {
        "total": total,
        "today_expenses": today_expenses,
        "date_str": today_str,
        "records": today_records,
    }


# helper for month budget
async def get_month_budget(month: str) -> int:
    current_sheet = await asyncio.to_thread(get_cached_worksheet, month)

    # Get income from sheet
    salary = current_sheet.acell(const.SALARY_CELL).value
    freelance = current_sheet.acell(const.FREELANCE_CELL).value

    # fallback from config if empty/invalid
    if not salary or not str(salary).strip().isdigit():
        salary = config["income"].get("salary", 0)
    if not freelance or not str(freelance).strip().isdigit():
        freelance = config["income"].get("freelance", 0)

    # convert safely to int
    salary = safe_int(salary)
    freelance = safe_int(freelance)
    month_budget = salary + freelance

    return month_budget


# helper for month budget by sheet
def get_month_budget_by_sheet(current_sheet: gspread.Worksheet) -> int:
    # Get income from sheet
    result = current_sheet.batch_get([const.SALARY_CELL, const.FREELANCE_CELL])
    salary = (
        result[0][0][0]
        if result and len(result) > 0 and len(result[0]) > 0
        else config["income"].get("salary", 0)
    )
    freelance = (
        result[1][0][0]
        if result and len(result) > 1 and len(result[1]) > 0
        else config["income"].get("freelance", 0)
    )

    # convert safely to int
    salary = safe_int(salary)
    freelance = safe_int(freelance)

    return salary + freelance


# helper for month budget percentages
async def get_category_percentages_by_sheet_name(sheet_name: str) -> dict:
    current_sheet = await asyncio.to_thread(get_cached_worksheet, sheet_name)
    cat_percentage = get_category_percentages_by_sheet(current_sheet)
    return cat_percentage


def get_category_percentages_by_sheet(current_sheet: gspread.Worksheet) -> dict:
    """
    Reads all category percentages from a single row (L2:Q2) efficiently.
    Falls back to config defaults if cells are empty or invalid.
    """

    try:
        cell_range = "L2:Q2"
        result = current_sheet.get(cell_range)
        row = result[0] if result else []
        categories = list(const.CATEGORY_CELLS.keys())
        cat_percentage = {}

        for i, category in enumerate(categories):
            raw_value = row[i] if i < len(row) else None
            if not raw_value or not str(raw_value).strip().isdigit():
                cat_percentage[category] = config["budgets"].get(category, 0)
            else:
                cat_percentage[category] = int(raw_value)

        return cat_percentage

    except Exception as e:
        logger.error(f"Error fetching category percentages: {e}")
        # 4️⃣ Fail-safe fallback to config defaults
        return {
            cat: config["budgets"].get(cat, 0) for cat in const.CATEGORY_CELLS.keys()
        }


# helper for get percentage spend for a category
def get_category_percentage(current_sheet: gspread.Worksheet, category: str) -> float:
    cell = const.CATEGORY_CELLS.get(category)
    percentage = current_sheet.acell(
        cell, value_render_option="UNFORMATTED_VALUE"
    ).value
    if not percentage:
        percentage = config["budgets"].get(category, 0)

    return float(percentage)


# helper for sync config command
def sync_config_to_sheet() -> str:
    """Helper to sync config to sheet for a next month"""
    # next month
    now = get_current_time() + relativedelta(months=1)
    target_month = now.strftime("%m")
    year = now.strftime("%Y")
    month_display = util.get_month_display(target_month, year)

    try:
        logger.info(f"Syncing config to sheet for month {target_month}")
        current_sheet = get_cached_worksheet(target_month)
        update_config_to_sheet(current_sheet)
        return f"{category_display['sync']} cấu hình {month_display} thành công!"
    except Exception as e:
        logger.error(
            f"Error syncing config to sheet for month {target_month}: {e}",
            exc_info=True,
        )
        return f"{category_display['sync']} cấu hình {month_display} thất bại!"


# helper for update config to sheet
def update_config_to_sheet(current_sheet: gspread.Worksheet):
    """Helper to update config to sheet for a given month"""
    try:
        cells_to_update = []
        salary_income = config["income"]["salary"]
        row, col = a1_to_rowcol(const.SALARY_CELL)
        cells_to_update.append(gspread.Cell(row=row, col=col, value=salary_income))

        freelance_income = config["income"]["freelance"]
        row, col = a1_to_rowcol(const.FREELANCE_CELL)
        cells_to_update.append(gspread.Cell(row=row, col=col, value=freelance_income))

        # write category percentages from config
        for category in config["budgets"]:
            if category not in const.CATEGORY_CELLS:
                continue

            cell = const.CATEGORY_CELLS[category]
            percent = f"{config['budgets'][category]}%"
            logger.info(
                f"Updating category {category} percentage to {percent} in cell {cell}"
            )
            row, col = a1_to_rowcol(cell)
            cells_to_update.append(gspread.Cell(row=row, col=col, value=percent))

        # update cells in batch to reduce API calls
        if cells_to_update:
            current_sheet.update_cells(
                cells_to_update, value_input_option="USER_ENTERED"
            )

    except Exception as e:
        logger.error(
            f"Error updating config to sheet: {e}",
            exc_info=True,
        )


async def sort_expenses_by_date(month_offset: int) -> str:
    """Helper to sort expenses in a given month sheet by date"""
    try:
        now = get_current_time() + relativedelta(months=month_offset)
        target_month = now.strftime("%m/%Y")
        sheet_name = target_month
        current_sheet = await asyncio.to_thread(get_cached_worksheet, sheet_name)

        # Get all data
        all_values = await asyncio.to_thread(get_cached_sheet_data, sheet_name)

        if len(all_values) > 2:  # More than header + 1 row
            data_rows = all_values[1:]
            sorted_data = sorted(data_rows, key=parse_date_time)

            # format amounts VND
            for row in sorted_data:
                if len(row) >= 3 and row[2]:
                    try:
                        row[2] = int(
                            float(str(row[2]).replace(",", "").replace("₫", "").strip())
                        )
                    except (ValueError, TypeError):
                        pass

            # Update the sorted data
            await asyncio.to_thread(
                lambda: current_sheet.update(
                    f"A2:D{len(sorted_data) + 1}", sorted_data, value_input_option="RAW"
                )
            )

            # Invalidate cache
            invalidate_sheet_cache(sheet_name)
            logger.info(
                f"Manually sorted {len(sorted_data)} rows in sheet {sheet_name}"
            )
            return f"{category_display['sort']} thành công {len(sorted_data)} mục trong bảng {sheet_name}."
        else:
            logger.info(f"No data to sort in sheet {sheet_name}")
            return "Không có dữ liệu để sắp xếp."

    except Exception as e:
        logger.error(f"Error starting sort for sheet {sheet_name}: {e}", exc_info=True)
        return "Đã xảy ra lỗi khi sắp xếp dữ liệu."


async def get_ai_analyze_summary(month_offset) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")

    logger.info(f"Getting month expenses for sheet {target_month}")

    try:
        current_sheet = await asyncio.to_thread(get_cached_worksheet, target_month)
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error getting/creating sheet {target_month}: {sheet_error}",
            exc_info=True,
        )
        return

    try:
        all_values = await asyncio.to_thread(get_cached_sheet_data, target_month)
        logger.info(f"Retrieved {len(all_values)} records from sheet")
    except Exception as records_error:
        logger.error(
            f"Error retrieving records from sheet: {records_error}", exc_info=True
        )
        return

    records = convert_values_to_records(all_values)
    raw_data = get_month_response(records, current_sheet, now)

    client = InferenceClient(token=const.HUGGING_FACE_TOKEN)
    model = "meta-llama/Llama-3.1-8B-Instruct"

    # Use chat_completion for instruction/chat models
    ai_response = client.chat_completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Bạn là một trợ lý tài chính cá nhân thông minh, phản hồi hoàn toàn bằng tiếng Việt. "
                    "Phân tích dữ liệu chi tiêu hàng tháng (bao gồm thu nhập, ngân sách và chi tiêu thực tế) để đưa ra phân tích và khuyến nghị.\n\n"
                    "⚙️ Quy ước dữ liệu:\n"
                    "- Mỗi dòng chi tiêu có dạng: <Tên hạng mục>: <Chi tiêu thực tế> VND (<Chênh lệch>)\n"
                    "- Giá trị trong ngoặc thể hiện CHÊNH LỆCH giữa chi tiêu thực tế và ngân sách:\n"
                    "    • Dấu (+) nghĩa là chi tiêu ÍT HƠN ngân sách (TIẾT KIỆM)\n"
                    "    • Dấu (-) nghĩa là chi tiêu NHIỀU HƠN ngân sách (VƯỢT CHI)\n"
                    "- Ví dụ: (+1,000,000) = tiết kiệm 1 triệu. (-500,000) = vượt ngân sách 500 nghìn.\n\n"
                    "⚙️ Phân tích yêu cầu:\n"
                    "1️⃣ Xác định các hạng mục chi vượt ngân sách (dấu -) và hạng mục tiết kiệm (dấu +), nêu rõ số tiền chênh lệch.\n"
                    "2️⃣ So sánh tổng chi tiêu và thu nhập để xác định thặng dư hoặc thâm hụt.\n"
                    "3️⃣ Phát hiện 2–3 xu hướng nổi bật trong chi tiêu.\n"
                    "4️⃣ Đưa ra 2–3 khuyến nghị cụ thể giúp cải thiện cân bằng tài chính.\n\n"
                    "📋 Định dạng đầu ra (HTML-friendly cho Telegram):\n"
                    "🧾 <b>Tóm tắt:</b> Một đoạn ngắn mô tả tình hình tài chính tháng.\n"
                    "📊 <b>Phân tích chi tiêu vượt ngân sách:</b> Liệt kê rõ từng mục vượt và tiết kiệm.\n"
                    "📈 <b>Xu hướng chi tiêu:</b> 2–3 xu hướng nổi bật.\n"
                    "💡 <b>Khuyến nghị:</b> 2–3 gợi ý cụ thể.\n\n"
                    "💬 <b>Yêu cầu:</b>\n"
                    "- Giọng văn thân thiện, chuyên nghiệp, có cảm xúc.\n"
                    "- Sử dụng emoji phù hợp (🧾📊📈💡💰✨...) để tăng tính dễ đọc.\n"
                ),
            },
            {"role": "user", "content": f"{raw_data}"},
        ],
        max_tokens=1000,
    )

    summary = markdown_to_html(ai_response["choices"][0]["message"]["content"].strip())
    return summary


def process_income_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting income summary for sheet {target_month}")

    try:
        current_sheet = get_cached_worksheet(target_month)
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error getting/creating sheet {target_month}: {sheet_error}",
            exc_info=True,
        )
        exit(1)

    try:
        previous_sheet = get_cached_worksheet(previous_month)
        logger.info(f"Successfully obtained sheet for {previous_month}")
    except Exception as prev_sheet_error:
        logger.error(
            f"Error getting/creating sheet {previous_month}: {prev_sheet_error}",
            exc_info=True,
        )
        exit(1)

    # Get income from current month's sheet
    freelance_income = current_sheet.acell(const.FREELANCE_CELL).value
    salary_income = current_sheet.acell(const.SALARY_CELL).value

    if not freelance_income or freelance_income.strip() == "":
        logger.info("Freelance income cell is empty, using config fallback")
        exit(1)

    if not salary_income or salary_income.strip() == "":
        logger.info("Salary income cell is empty, using config fallback")
        exit(1)

    freelance_income = safe_int(freelance_income)
    salary_income = safe_int(salary_income)

    # Get income from previous month's sheet for comparison
    prev_freelance_income = previous_sheet.acell(const.FREELANCE_CELL).value
    prev_salary_income = previous_sheet.acell(const.SALARY_CELL).value

    if not prev_freelance_income or prev_freelance_income.strip() == "":
        logger.info("Previous freelance income cell is empty, using config fallback")
        prev_freelance_income = 0

    if not prev_salary_income or prev_salary_income.strip() == "":
        logger.info("Previous salary income cell is empty, using config fallback")
        prev_salary_income = 0

    prev_freelance_income = safe_int(prev_freelance_income)
    prev_salary_income = safe_int(prev_salary_income)

    prev_total_income = prev_freelance_income + prev_salary_income
    total_income = freelance_income + salary_income

    # Calculate percentage change
    if prev_total_income > 0:
        percentage_change = (
            (total_income - prev_total_income) / prev_total_income
        ) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    summary = (
        f"{category_display['income']} {month_display}:\n"
        f"{category_display['salary']}: {salary_income:,.0f} VND\n"
        f"{category_display['freelance']}: {freelance_income:,.0f} VND\n"
        f"{category_display['total']}: {total_income:,.0f} VND\n"
        f"{category_display['compare']} {previous_month}: {total_income - prev_total_income:+,.0f} VND {percentage_text}\n"
    )

    return summary


def process_salary(month_offset: int, amount: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    target_year = now.strftime("%Y")
    month_display = util.get_month_display(target_month, target_year)
    current_sheet = get_cached_worksheet(target_month)

    amount = amount * 1000
    current_sheet.update_acell(const.SALARY_CELL, amount)

    if month_offset == 0:
        # Update config
        config["income"]["salary"] = amount
        save_config()

    response = f"✅ Đã ghi nhận thu nhập lương {month_display}: {amount:,.0f} VND"
    return response


def process_freelance(month_offset: int, amount: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    target_year = now.strftime("%Y")
    month_display = util.get_month_display(target_month, target_year)
    current_sheet = get_cached_worksheet(target_month)

    amount = amount * 1000
    current_sheet.update_acell(const.FREELANCE_CELL, amount)

    # Update config
    if month_offset == 0:
        config["income"]["freelance"] = amount
        save_config()

    response = f"✅ Đã ghi nhận thu nhập freelance {month_display}: {amount:,.0f} VND"
    return response


def process_other_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting other expenses for sheet {target_month}")

    other_expenses, total = get_other_total(target_month)
    count = len(other_expenses)
    logger.info(f"Found {count} other expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in other_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += format_expense(r, i) + "\n"

    _, previous_total = get_other_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['other']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_dating_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting dating expenses for sheet {target_month}")

    dating_expenses, total = get_dating_total(target_month)
    count = len(dating_expenses)
    logger.info(f"Found {count} dating expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in dating_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += format_expense(r, i) + "\n"

    _, previous_total = get_dating_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['dating']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_food_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting food expenses for sheet {target_month}")

    food_expenses, total = get_food_total(target_month)
    count = len(food_expenses)
    logger.info(f"Found {count} food expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in food_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += format_expense(r, i) + "\n"

    _, previous_total = get_food_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['food']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_gas_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting gas expenses for sheet {target_month}")

    gas_expenses, total = get_gas_total(target_month)
    count = len(gas_expenses)
    logger.info(f"Found {count} gas expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in gas_expenses:
        grouped[r.get("Date", "")].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += format_expense(r, i) + "\n"

    _, previous_total = get_gas_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['gas']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_month_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")

    logger.info(f"Getting month expenses for sheet {target_month}")

    try:
        current_sheet = get_cached_worksheet(target_month)
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error obtaining sheet for {target_month}: {sheet_error}",
            exc_info=True,
        )
        exit(1)

    try:
        all_values = get_cached_sheet_data(target_month)
        logger.info(f"Retrieved {len(all_values)} records from sheet")
    except Exception as records_error:
        logger.error(
            f"Error retrieving records from sheet: {records_error}",
            exc_info=True,
        )
        exit(1)

    records = convert_values_to_records(all_values)
    response = get_month_response(records, current_sheet, now)
    return response


async def process_week_summay(week_offset: int) -> str:
    now = get_current_time() + datetime.timedelta(weeks=week_offset)
    week_data = await get_week_process_data(now)
    total = week_data["total"]
    week_expenses = week_data["week_expenses"]
    count = len(week_expenses)
    week_start = week_data["week_start"]
    week_end = week_data["week_end"]

    grouped = defaultdict(list)
    for r in week_expenses:
        date_str = r["expense_date"].strftime("%d/%m/%Y")
        grouped[date_str].append(r)

    details_lines = []
    for day, rows in sorted(
        grouped.items(),
        key=lambda d: datetime.datetime.strptime(d[0], "%d/%m/%Y"),
    ):
        day_total = sum(parse_amount(r["vnd"]) for r in rows)
        details_lines.append(f"\n📅 {day}: {day_total:,.0f} VND")
        details_lines.extend(
            "\n" + format_expense(r, i) for i, r in enumerate(rows, start=1)
        )
        details_lines.append("\n")

    summay = (
        f"{category_display['summarized']} tuần này ({week_start:%d/%m} - {week_end:%d/%m}):\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
    )

    if details_lines:
        summay += f"\n📝 Chi tiết:{''.join(details_lines)}"

    return summay


async def process_today_summary() -> str:
    now = get_current_time()
    today_data = await get_daily_process_data(now)
    total = today_data["total"]
    today_expenses = today_data["today_expenses"]
    count = len(today_expenses)
    today_str = today_data["date_str"]

    summary = (
        f"{category_display['summarized']} hôm nay ({today_str}):\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
    )

    if today_expenses:
        details = "\n".join(
            format_expense(r, i + 1) for i, r in enumerate(today_expenses)
        )
        summary += f"\n📝 Chi tiết:\n{details}"

    return summary
