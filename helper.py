import os
import unicodedata
import re
import datetime
import pytz
from config import config, BASE_DIR
import asyncio
from sheet import spreadsheet
import gspread
from logger import logger

# Timezone setup
timezone = pytz.timezone(config["settings"]["timezone"])

def get_version():
    try:
        version_file = os.path.join(BASE_DIR, "VERSION")
        with open(version_file) as f:
            return f.read().strip()
    except Exception:
        return "unknown"

def get_current_time():
    """Get current time in the configured timezone"""
    return datetime.datetime.now(timezone)

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
    - '10h'   -> '10:00'
    - '01h'   -> '01:00'
    - '10h30' -> '10:30'
    - '10h5'  -> '10:05'
    - '10:05' -> '10:05' (unchanged)
    """
    time_str = time_str.strip().lower().replace(" ", "")
    
    if "h" in time_str:
        parts = time_str.split("h")
        hour = parts[0].zfill(2) if parts[0] else "00"
        minute = parts[1].zfill(2) if len(parts) > 1 and parts[1] else "00"
        return f"{hour}:{minute}"
    
    # Already colon format
    return time_str

def safe_async_handler(handler_func):
    """Decorator to ensure handlers run in a safe async context"""
    async def wrapper(update, context):
        try:
            # Get information about the current async context
            try:
                current_loop = asyncio.get_running_loop()
                logger.debug(f"Handler {handler_func.__name__} running in loop: {id(current_loop)}")
                
                if current_loop.is_closed():
                    logger.error(f"Current event loop is closed in {handler_func.__name__}")
                    raise RuntimeError("Event loop is closed")
                    
            except RuntimeError as loop_error:
                logger.error(f"Event loop issue in {handler_func.__name__}: {loop_error}")
                # Try to send a basic error message without using the problematic loop
                try:
                    await update.message.reply_text("❌ Có lỗi hệ thống xảy ra. Vui lòng thử lại!")
                except:
                    pass
                return
            
            # Execute the actual handler
            return await handler_func(update, context)
            
        except Exception as e:
            logger.error(f"Error in safe_async_handler for {handler_func.__name__}: {e}", exc_info=True)
            try:
                # Try to send error message, but don't fail if this also fails
                await update.message.reply_text("❌ Có lỗi hệ thống xảy ra. Vui lòng thử lại sau!")
            except Exception as reply_error:
                logger.error(f"Failed to send error message in {handler_func.__name__}: {reply_error}")
            
    wrapper.__name__ = handler_func.__name__
    return wrapper

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
                    try:
                        all_values = new_sheet.get_all_values()
                        
                        if len(all_values) > 1:  # If there's more than just headers
                            # Clear data from row 2 onwards (keep row 1 as headers)
                            range_to_clear = f"A2:Z{len(all_values)}"
                            new_sheet.batch_clear([range_to_clear])
                            logger.info(f"Cleared data rows from new sheet: {range_to_clear}")
                    except Exception as clear_error:
                        logger.warning(f"Could not clear template data: {clear_error}")
                    
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
        sheet = get_or_create_monthly_sheet(month)
        records = sheet.get_all_records()
        
        gas_expenses = []
        total = 0
        for r in records:
            note = r.get("Note", "").lower()
            if "đổ xăng" in note:
                amount = r.get("VND", 0)
                if amount:
                    gas_expenses.append(r)
                    total += parse_amount(amount)
        
        return gas_expenses, total
    except Exception as e:
        logger.error(f"Error getting gas total for {month}: {e}", exc_info=True)
        return [], 0
