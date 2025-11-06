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
import src.track_py.utils.sheet as sheet


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


class Record(TypedDict):
    date: str
    time: str
    vnd: int
    note: str


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
                        sheet.update_config_to_sheet(new_sheet)
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


def get_monthly_expense(sheet_name: str) -> int:
    """Fetch total expense for a given month sheet"""
    total = 0
    try:
        # Try to get the sheet for this month (don't create if it doesn't exist)
        current_sheet = sheet.get_monthly_sheet_if_exists(sheet_name)
        if current_sheet:
            # Get value from cell G2 (total expenses cell)
            try:
                total_cell_value = current_sheet.acell(const.TOTAL_EXPENSE_CELL).value
                if total_cell_value:
                    # Parse the amount (remove currency symbols, commas, etc.)
                    total = sheet.sheet.parse_amount(total_cell_value)
            except Exception as cell_error:
                logger.warning(
                    f"Could not read G2 from sheet {sheet_name}: {cell_error}"
                )
    except Exception as sheet_error:
        logger.error(f"Error accessing sheet {sheet_name}: {sheet_error}")

    return total


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
        asyncio.to_thread(sheet.get_cached_sheet_data, month)
        for month in months_to_check
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process each relevant sheet
    for target_month, all_values in zip(months_to_check, results):
        try:
            records = sheet.convert_values_to_records(all_values)
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
                        amount = sheet.parse_amount(raw_amount)
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
            sheet.get_cached_today_data, target_month, today_str
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
    records = sheet.convert_values_to_records(all_values)
    for r in records:
        record_date = r["date"].strip().lstrip("'")
        if record_date and record_date > today_str:
            continue

        if record_date == today_str:
            record_amount = r["vnd"]
            amount = sheet.parse_amount(record_amount)
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
    current_sheet = await asyncio.to_thread(sheet.get_cached_worksheet, month)

    # Get income from sheet
    salary = current_sheet.acell(const.SALARY_CELL).value
    freelance = current_sheet.acell(const.FREELANCE_CELL).value

    # fallback from config if empty/invalid
    if not salary or not str(salary).strip().isdigit():
        salary = config["income"].get("salary", 0)
    if not freelance or not str(freelance).strip().isdigit():
        freelance = config["income"].get("freelance", 0)

    # convert safely to int
    salary = sheet.safe_int(salary)
    freelance = sheet.safe_int(freelance)
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
    salary = sheet.safe_int(salary)
    freelance = sheet.safe_int(freelance)

    return salary + freelance


# helper for month budget percentages
async def get_category_percentages_by_sheet_name(sheet_name: str) -> dict:
    current_sheet = await asyncio.to_thread(sheet.get_cached_worksheet, sheet_name)
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
        current_sheet = sheet.get_cached_worksheet(target_month)
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
        current_sheet = await asyncio.to_thread(sheet.get_cached_worksheet, sheet_name)

        # Get all data
        all_values = await asyncio.to_thread(sheet.get_cached_sheet_data, sheet_name)

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
            sheet.invalidate_sheet_cache(sheet_name)
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


def get_gas_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total gas expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        gas_expenses = []
        total = 0

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(note, const.TRANSPORT_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    gas_expenses.append(r)
                    total += sheet.parse_amount(amount)

        return gas_expenses, total
    except Exception as e:
        logger.error(f"Error getting gas total for {month}: {e}", exc_info=True)
        return [], 0


# helper for food totals
def get_food_total(month: str) -> tuple[list[Record], int]:
    """Helper to get total food expenses for a given month"""
    try:
        # Use cached data for read-only operations
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        food_expenses = []
        total = 0

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(note, const.FOOD_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    food_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(note, const.DATING_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    date_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if const.RENT_KEYWORD in note:
                amount = r["vnd"]
                if amount:
                    rent_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if not (
                sheet.has_keyword(note, const.FOOD_KEYWORDS)
                or sheet.has_keyword(note, const.DATING_KEYWORDS)
                or sheet.has_keyword(note, const.TRANSPORT_KEYWORDS)
                or sheet.has_keyword(note, const.LONG_INVEST_KEYWORDS)
                or sheet.has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS)
                or sheet.has_keyword(note, const.SUPPORT_PARENT_KEYWORDS)
                or sheet.has_keyword(note, const.RENT_KEYWORD)
            ):
                amount = r["vnd"]
                if amount:
                    other_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(note, const.LONG_INVEST_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    invest_expenses.append(r)
                    total += sheet.parse_amount(amount)

        return invest_expenses, total
    except Exception as e:
        logger.error(f"Error getting investment total for {month}: {e}", exc_info=True)
        return [], 0


def get_opportunity_investment_total(
    month: str,
) -> tuple[list[Record], int]:
    """Helper to get total opportunity investment expenses for a given month"""
    try:
        # Skip header row and convert to records-like format
        invest_expenses = []
        total = 0

        # Use cached data for read-only operations
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    invest_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(
                note, const.OPPORTUNITY_INVEST_KEYWORDS
            ) or sheet.has_keyword(note, const.LONG_INVEST_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    invest_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        all_values = sheet.get_cached_sheet_data(month)
        records = sheet.convert_values_to_records(all_values)

        for r in records:
            note = r["note"].lower()
            if sheet.has_keyword(note, const.SUPPORT_PARENT_KEYWORDS):
                amount = r["vnd"]
                if amount:
                    support_parent_expenses.append(r)
                    total += sheet.parse_amount(amount)

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
        amount = sheet.parse_amount(r["vnd"])

        if amount == 0:
            continue

        totals["expenses"].append(r)
        totals["total"] += amount

        if sheet.has_keyword(note, const.FOOD_KEYWORDS):
            totals["food"] += amount
            totals["essential"] += amount
        elif sheet.has_keyword(note, const.TRANSPORT_KEYWORDS):
            totals["gas"] += amount
            totals["essential"] += amount
        elif sheet.has_keyword(note, const.RENT_KEYWORD):
            totals["rent"] += amount
            totals["essential"] += amount
        elif sheet.has_keyword(note, const.DATING_KEYWORDS):
            totals["dating"] += amount
        elif sheet.has_keyword(note, const.LONG_INVEST_KEYWORDS):
            totals["long_investment"] += amount
            totals["investment"] += amount
        elif sheet.has_keyword(note, const.OPPORTUNITY_INVEST_KEYWORDS):
            totals["opportunity_investment"] += amount
            totals["investment"] += amount
        elif sheet.has_keyword(note, const.SUPPORT_PARENT_KEYWORDS):
            totals["support_parent"] += amount
        else:
            totals["other"] += amount
            totals["essential"] += amount

    # Calculate food_and_travel total
    totals["food_and_travel"] = totals["food"] + totals["gas"]

    return totals


# helper for get total income
def get_total_income(current_sheet: gspread.Worksheet) -> int:
    """Helper to get total income from salary and freelance"""
    try:
        salary = current_sheet.acell(const.SALARY_CELL).value
        freelance = current_sheet.acell(const.FREELANCE_CELL).value

        if not salary or salary.strip() == "":
            salary = config["income"]["salary"]
        if not freelance or freelance.strip() == "":
            freelance = config["income"]["freelance"]

        salary = sheet.safe_int(salary)
        freelance = sheet.safe_int(freelance)
        total_income = salary + freelance
        return total_income
    except Exception as e:
        logger.error(f"Error getting total income: {e}", exc_info=True)
        return 0
