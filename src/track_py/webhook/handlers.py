from dateutil.relativedelta import relativedelta
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import CallbackContext
import datetime
import asyncio
from collections import defaultdict
from huggingface_hub import InferenceClient
from src.track_py.const import MONTH_NAMES, HELP_MSG
from src.track_py.utils.logger import logger
from src.track_py.utils.sheet import get_current_time, normalize_date, normalize_time, get_or_create_monthly_sheet, parse_amount, format_expense, get_gas_total, get_food_total, get_dating_total, get_other_total, get_month_summary, safe_int, get_investment_total, get_total_income, get_cached_sheet_data, get_cached_worksheet, invalidate_sheet_cache, get_month_response
from src.track_py.utils.util import markdown_to_html
from src.track_py.const import LOG_EXPENSE_MSG, DELETE_EXPENSE_MSG, FREELANCE_CELL, SALARY_CELL, EXPECTED_HEADERS, SHORTCUTS, HUGGING_FACE_TOKEN, CATEGORY_ICONS, CATEGORY_NAMES
from src.track_py.config import config, save_config
from src.track_py.utils.category import category_display

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
                    await update.message.reply_text(f"❌ Có lỗi hệ thống xảy ra. Vui lòng thử lại!\n\nLỗi: {loop_error}")
                except:
                    pass
                return
            
            # Execute the actual handler
            return await handler_func(update, context)
            
        except Exception as e:
            logger.error(f"Error in safe_async_handler for {handler_func.__name__}: {e}", exc_info=True)
            try:
                # Try to send error message, but don't fail if this also fails
                await update.message.reply_text(f"❌ Có lỗi hệ thống xảy ra. Vui lòng thử lại sau!\n\nLỗi: {e}")
            except Exception as reply_error:
                logger.error(f"Failed to send error message in {handler_func.__name__}: {reply_error}")
            
    wrapper.__name__ = handler_func.__name__
    return wrapper


@safe_async_handler
async def start(update, context):
    """Send welcome message when bot starts"""
    try:
        logger.info(f"Start command requested by user {update.effective_user.id}")
        keyboard = [
            ["/today", "/week", "/month", "/month -1", "/sort"],
            ["/gas", "/food", "/other", "/dating"],
            ["/investment", "/investment -1"],
            ["/income", "/income -1"],
            ["/fl", "/sl", "/ai"],
            ["/help"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(HELP_MSG, reply_markup=reply_markup)
        logger.info(f"Welcome message + keyboard sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi khởi động. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in start command 12: {reply_error}")

@safe_async_handler
async def help(update, context):
    """Show help message"""
    try:
        logger.info(f"Help command requested by user {update.effective_user.id}")
        await update.message.reply_text(HELP_MSG)
        logger.info(f"Help message sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in help for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi hiển thị hướng dẫn. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in help: {reply_error}")

@safe_async_handler
async def log_expense(update, context):
    """Log expense to Google Sheet with smart date/time parsing"""
    text = update.message.text.strip()
    parts = text.split()

    try:
        logger.info(f"Log expense requested by user {update.effective_user.id}: '{text}'")
        
        # Quick shortcuts for common expenses
        shortcuts = SHORTCUTS
        
        # Parse different input formats
        entry_date = None
        entry_time = None
        amount = None
        note = ""
        target_month = None
        
        # Case A: Default Entry (No Date/Time) - 1000 ăn trưa or 5 cf or just "5"
        if parts[0].isdigit():
            amount = int(parts[0])
            raw_note = " ".join(parts[1:])
            
            # Apply shortcuts to note
            note_parts = raw_note.split()
            expanded_parts = []
            for part in note_parts:
                expanded_parts.append(shortcuts.get(part.lower(), part))
            note = " ".join(expanded_parts)
            
            now = get_current_time()
            # now = get_current_time() + datetime.timedelta(days=63)
            entry_date = now.strftime("%d/%m")
            entry_time = now.strftime("%H:%M:%S")
            target_month = now.strftime("%m/%Y")
            
        # Case B: Date Only - 02/09 5000 cafe or 02/09 5 cf
        elif "/" in parts[0] and len(parts) >= 2 and parts[1].isdigit():
            entry_date = normalize_date(parts[0])
            amount = int(parts[1])
            raw_note = " ".join(parts[2:]) if len(parts) > 2 else "Không có ghi chú"
            
            # Apply shortcuts to note
            note_parts = raw_note.split()
            expanded_parts = []
            for part in note_parts:
                expanded_parts.append(shortcuts.get(part.lower(), part))
            note = " ".join(expanded_parts)
            
            entry_time = "00:00:00"  # Default time

            day, month = entry_date.split("/")
            current_year = get_current_time().year
            target_month = f"{month}/{current_year}"
            
        # Case C: Date + Time - 02/09 08:30 15000 breakfast or 02/09 08:30 15 cf
        elif "/" in parts[0] and len(parts) >= 3 and (":" in parts[1] or "h" in parts[1].lower()) and parts[2].isdigit():
            entry_date = normalize_date(parts[0])
            entry_time = normalize_time(parts[1])
            amount = int(parts[2])
            raw_note = " ".join(parts[3:]) if len(parts) > 3 else "Không có ghi chú"
            
            # Apply shortcuts to note
            note_parts = raw_note.split()
            expanded_parts = []
            for part in note_parts:
                expanded_parts.append(shortcuts.get(part.lower(), part))
            note = " ".join(expanded_parts)

            day, month = entry_date.split("/")
            current_year = get_current_time().year
            target_month = f"{month}/{current_year}"

        else:
            await update.message.reply_text(LOG_EXPENSE_MSG)
            return

        # Smart amount multipliers for faster typing
        amount = amount * 1000

        logger.info(f"Parsed expense: {amount} VND on {entry_date} {entry_time} - {note} (sheet: {target_month})")

        # OPTIMIZATION: Get or create the target month's sheet
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)

        await asyncio.to_thread(
            lambda: sheet.append_row(
                [entry_date, entry_time, int(amount), note],
                value_input_option='RAW'
            )
        )
        
        # Invalidate cache since we've updated the sheet
        invalidate_sheet_cache(target_month)

        # response = f"✅ Đã ghi nhận:\n💰 {amount:,} VND\n📝 {note}\n� {entry_date} {entry_time}\n{position_msg}\n� Sheet: {target_month}"
        response = f"✅ Đã ghi nhận:\n💰 {amount:,} VND\n📝 {note}\n📅 {entry_date} {entry_time}\n📄 Sheet: {target_month}"
        await update.message.reply_text(response)

        logger.info(f"Logged expense: {amount} VND - {note} at {entry_date} {entry_time} in sheet {target_month}")

    except ValueError as ve:
        await update.message.reply_text("❌ Lỗi định dạng số tiền!\n\n📝 Các định dạng hỗ trợ:\n• 1000 ăn trưa\n• 02/09 5000 cafe\n• 02/09 08:30 15000 breakfast")
    except Exception as e:
        logger.error(f"Error logging expense: {e}")
        await update.message.reply_text(f"❌ Có lỗi xảy ra. Vui lòng thử lại!\n\nLỗi: {e}")

@safe_async_handler
async def delete_expense(update, context):
    """Delete expense entry from Google Sheet"""
    text = update.message.text.strip()
    
    try:
        logger.info(f"Delete expense requested by user {update.effective_user.id}: '{text}'")
        
        parts = text.split()
        # Only "del 00h11s00" -> assume today's date
        if len(parts) == 2:
            entry_date = get_current_time().strftime("%d/%m")
            entry_time = normalize_time(parts[1])
        # Parse delete command: "del 14/10 00h11s00"
        elif len(parts) >= 3:
            entry_date = normalize_date(parts[1])
            entry_time = normalize_time(parts[2])
            logger.info(f"Attempting to delete expense: {entry_date} {entry_time}")
        else:
            await update.message.reply_text(DELETE_EXPENSE_MSG)
            return
        
        # Determine target month
        now = get_current_time()
        # now = get_current_time() + datetime.timedelta(days=63)
        target_month = now.strftime("%m/%Y")
        
        # Check if different month
        if "/" in entry_date:
            day, month = entry_date.split("/")
            if len(month) == 2:
                target_month = f"{month}/{now.year}"
        
        logger.info(f"Target sheet: {target_month}")
        
        # OPTIMIZATION: Use cached data or fetch efficiently
        try:
            all_values = await asyncio.to_thread(get_cached_sheet_data, target_month)
            if not all_values or len(all_values) < 2:
                await update.message.reply_text("❌ Không có dữ liệu trong sheet này.")
                return
            logger.info(f"Retrieved {len(all_values)} rows from sheet (cached)")
        except Exception as sheet_error:
            logger.error(f"Error getting sheet data for {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
        
        # OPTIMIZATION: Search through values array instead of records (faster)
        found_row = None
        for i, row in enumerate(all_values[1:], start=2):  # Skip header row
            if len(row) >= 2:
                row_date = normalize_date(row[0].strip()) if row[0] else ""
                row_time = normalize_time(row[1].strip()) if row[1] else ""
                
                if row_date == entry_date and row_time == entry_time:
                    found_row = i
                    break
        
        if found_row:
            try:
                current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
                await asyncio.to_thread(lambda: current_sheet.delete_rows(found_row))
                
                # Invalidate cache since we've modified the sheet
                invalidate_sheet_cache(target_month)
                
                logger.info(f"Successfully deleted expense: {entry_date} {entry_time} from row {found_row}")
                await update.message.reply_text(f"✅ Đã xóa giao dịch: {entry_date} {entry_time}")
                
            except Exception as delete_error:
                logger.error(f"Error deleting row {found_row}: {delete_error}", exc_info=True)
                await update.message.reply_text(f"❌ Có lỗi xảy ra khi xóa giao dịch. Vui lòng thử lại!\n\nLỗi: {delete_error}")
        else:
            logger.warning(f"Expense not found: {entry_date} {entry_time}")
            await update.message.reply_text(f"❌ Không tìm thấy giao dịch: {entry_date} {entry_time}")
            
    except Exception as e:
        logger.error(f"Error in delete_expense for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi xóa! Vui lòng thử lại.\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in delete_expense 12: {reply_error}")

@safe_async_handler
async def sort(update, context):
    """Manually sort sheet data when needed (can be called periodically with /sort command)"""
    try:
        now = get_current_time()
        target_month = now.strftime("%m/%Y")
        
        # Allow specifying different month: /sort 09/2025
        if context.args and len(context.args) > 0:
            target_month = context.args[0]
        
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
        
        # Get all data
        all_values = await asyncio.to_thread(lambda: sheet.get_values("A:D"))
        
        if len(all_values) > 2:  # More than header + 1 row
            data_rows = all_values[1:]
            
            # Sort by date and time
            sorted_data = sorted(data_rows, key=lambda x: (
                x[0] if len(x) > 0 else "",  # Date
                x[1] if len(x) > 1 else ""   # Time
            ))
            
            # Clean up amounts
            for row in sorted_data:
                if len(row) >= 3 and row[2]:
                    try:
                        row[2] = int(float(str(row[2]).replace(',', '').replace('₫', '').strip()))
                    except (ValueError, TypeError):
                        pass
            
            # Update the sorted data
            await asyncio.to_thread(
                lambda: sheet.update(f"A2:D{len(sorted_data) + 1}", sorted_data, value_input_option='RAW')
            )
            
            # Invalidate cache
            invalidate_sheet_cache(target_month)
            
            await update.message.reply_text(f"✅ Đã sắp xếp {len(sorted_data)} dòng dữ liệu trong sheet {target_month}")
            logger.info(f"Manually sorted {len(sorted_data)} rows in sheet {target_month}")
        else:
            await update.message.reply_text("📋 Sheet không cần sắp xếp (ít hơn 2 dòng dữ liệu)")
            
    except Exception as e:
        logger.error(f"Error sorting sheet data: {e}")
        await update.message.reply_text(f"❌ Có lỗi khi sắp xếp dữ liệu: {e}")

@safe_async_handler
async def today(update, context):
    """Get today's total expenses"""
    try:
        logger.info(f"Today command requested by user {update.effective_user.id}")
        
        now = get_current_time()
        # now = get_current_time() + datetime.timedelta(days=63)
        today_str = now.strftime("%d/%m")
        target_month = now.strftime("%m/%Y")
        
        logger.info(f"Getting today's expenses for {today_str} in sheet {target_month}")
        
        # OPTIMIZATION: Use cached data for better performance
        try:
            all_values = await asyncio.to_thread(get_cached_sheet_data, target_month)
            if not all_values or len(all_values) < 2:
                await update.message.reply_text(f"📊 Hôm nay chưa có giao dịch nào ({today_str})")
                return
            logger.info(f"Retrieved {len(all_values)} rows from sheet (cached)")
        except Exception as sheet_error:
            logger.error(f"Error getting sheet data for {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
        
        # OPTIMIZATION: Process data directly from values array
        today_expenses = []
        total = 0
        
        # Skip header row (index 0)
        for row in all_values[1:]:
            if len(row) >= 3:  # Need at least date, time, amount
                record_date = row[0].strip().lstrip("'") if row[0] else ""
                record_amount = row[2] if len(row) > 2 else 0
                
                if record_date == today_str and record_amount:
                    # Convert row to record format for compatibility
                    record = {
                        "Date": record_date,
                        "Time": row[1] if len(row) > 1 else "",
                        "VND": record_amount,
                        "Note": row[3] if len(row) > 3 else ""
                    }
                    today_expenses.append(record)
                    total += parse_amount(record_amount)
        
        count = len(today_expenses)
        logger.info(f"Found {count} expenses for today with total {total} VND")
        logger.info(f"Today date string: '{today_str}', Rows processed: {len(all_values)}")  # Debug info
        
        response = (
            f"{category_display['summarized']} hôm nay ({today_str}):\n"
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
        )
        
        if today_expenses:
            details = "\n".join(
                format_expense(r, i+1) for i, r in enumerate(today_expenses)
            )
            response += f"\n\n📝 Chi tiết:\n{details}"

        await update.message.reply_text(response)
        logger.info(f"Today summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in today command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in today command 1: {reply_error}")

@safe_async_handler
async def week(update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        now = get_current_time() + datetime.timedelta(weeks=offset)

        # Calculate week boundaries
        week_start = now - datetime.timedelta(days=now.weekday())  # Monday
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)

        logger.info(f"Getting week expenses from {week_start:%d/%m} to {week_end:%d/%m}")

        # Collect all months the week spans
        months_to_check = sorted({
            (week_start + datetime.timedelta(days=i)).strftime("%m/%Y")
            for i in range(7)
        }, key=lambda s: datetime.datetime.strptime(s, "%m/%Y"))

        week_expenses = []
        total = 0.0

        # Process each relevant sheet
        for target_month in months_to_check:
            try:
                current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
                records = await asyncio.to_thread(
                    lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
                )

                year = target_month.split("/")[1]

                for r in records:
                    raw_date = (r.get("Date") or "").strip()
                    raw_amount = r.get("VND", 0)

                    if not raw_date or not raw_amount:
                        continue

                    try:
                        # Parse dd/mm with inferred year
                        if "/" not in raw_date:
                            continue
                        day, month = raw_date.split("/")[:2]
                        date_obj = datetime.datetime.strptime(f"{day}/{month}/{year}", "%d/%m/%Y")
                        expense_date = date_obj.replace(tzinfo=week_start.tzinfo)

                        if week_start <= expense_date <= week_end:
                            amount = parse_amount(raw_amount)
                            if amount == 0:
                                continue
                            r["expense_date"] = expense_date
                            week_expenses.append(r)
                            total += amount
                    except Exception as e:
                        logger.debug(f"Skipping invalid date {raw_date} in {target_month}: {e}")
                        continue

            except Exception as sheet_error:
                logger.warning(f"Could not access sheet {target_month}: {sheet_error}")
                continue

        # Prepare grouped details
        count = len(week_expenses)
        logger.info(f"Found {count} expenses with total {total} VND")

        grouped = defaultdict(list)
        for r in week_expenses:
            # grouped[r.get("Date", "")].append(r)
            date_str = r["expense_date"].strftime("%d/%m/%Y")
            grouped[date_str].append(r)

        details_lines = []
        for day, rows in sorted(grouped.items(), key=lambda d: datetime.datetime.strptime(d[0], "%d/%m/%Y")):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details_lines.append(f"\n📅 {day}: {day_total:,.0f} VND")
            details_lines.extend(format_expense(r, i) for i, r in enumerate(rows, start=1))

        response_parts = [
            f"{category_display['summarized']} tuần này ({week_start:%d/%m} - {week_end:%d/%m}):",
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
        ]

        if details_lines:
            response_parts.append("\n📝 Chi tiết:")
            response_parts.extend(details_lines)

        await update.message.reply_text("\n".join(response_parts))

    except Exception as e:
        logger.error(f"Error in week command: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")


@safe_async_handler
async def month(update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total expenses"""
    try:
        logger.info(f"Month command requested by user {update.effective_user.id}")
        
        now = get_current_time() + relativedelta(months=offset)
        target_month = now.strftime("%m/%Y")
        
        logger.info(f"Getting month expenses for sheet {target_month}")
        
        try:
            current_sheet = await asyncio.to_thread(get_cached_worksheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
        
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return

        response = get_month_response(records, current_sheet, now)
        await update.message.reply_text(response)
        logger.info(f"Month summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in month command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in month command: {reply_error}")

@safe_async_handler
async def ai_analyze(update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total expenses with AI analysis"""
    try:
        logger.info(f"Month command requested by user {update.effective_user.id}")
        
        now = get_current_time() + relativedelta(months=offset)
        target_month = now.strftime("%m/%Y")
        
        logger.info(f"Getting month expenses for sheet {target_month}")
        
        try:
            current_sheet = await asyncio.to_thread(get_cached_worksheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
        
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return
        
        raw_data = get_month_response(records, current_sheet, now)

        client = InferenceClient(token=HUGGING_FACE_TOKEN)
        model = "meta-llama/Llama-3.1-8B-Instruct"

        # Use chat_completion for instruction/chat models
        ai_response = client.chat_completion(
            model=model,
            messages=[
            {
                "role": "system",
                "content": 
                (
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
                )
            },
            {
                "role": "user",
                "content": f"{raw_data}"
            }
            ],
            max_tokens=1000,
        )

        markdown_response = markdown_to_html(ai_response['choices'][0]['message']['content'].strip())
        await update.message.reply_text(markdown_response, parse_mode='HTML')
        logger.info(f"Month summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in month command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in month command: {reply_error}")


@safe_async_handler
async def gas(update, context):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total gas expenses"""
    try:
        logger.info(f"Gas command requested by user {update.effective_user.id}")

        now = get_current_time() + relativedelta(months=offset)    
        target_month = now.strftime("%m/%Y")
        previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

        logger.info(f"Getting gas expenses for sheet {target_month}")

        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return

        gas_expenses, total = get_gas_total(target_month)
        count = len(gas_expenses)
        logger.info(f"Found {count} gas expenses for this month with total {total} VND")

        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        grouped = defaultdict(list)
        for r in gas_expenses:
            grouped[r.get("Date", "")].append(r)

        details = ""
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details += f"\n📅 {day}: {day_total:,.0f} VND\n"
            for i, r in enumerate(rows, start=1):
                details += format_expense(r, i) + "\n"

        _, previous_total = get_gas_total(previous_month)

        # Calculate percentage change
        if previous_total > 0:
            percentage_change = ((total - previous_total) / previous_total) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""

        response = (
            f"{category_display['gas']} {month_display}:\n" 
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
            f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Gas summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in gas command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in gas command: {reply_error}")

@safe_async_handler
async def food(update, context):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total food expenses"""
    try:
        logger.info(f"Food command requested by user {update.effective_user.id}")

        now = get_current_time() + relativedelta(months=offset)    
        target_month = now.strftime("%m/%Y")
        previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

        logger.info(f"Getting food expenses for sheet {target_month}")

        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return

        food_expenses, total = get_food_total(target_month)
        count = len(food_expenses)
        logger.info(f"Found {count} food expenses for this month with total {total} VND")

        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        grouped = defaultdict(list)
        for r in food_expenses:
            grouped[r.get("Date", "")].append(r)

        details = ""
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details += f"\n📅 {day}: {day_total:,.0f} VND\n"
            for i, r in enumerate(rows, start=1):
                details += format_expense(r, i) + "\n"

        _, previous_total = get_food_total(previous_month)

        # Calculate percentage change
        if previous_total > 0:
            percentage_change = ((total - previous_total) / previous_total) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""

        response = (
            f"{category_display['food']} {month_display}:\n" 
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
            f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Food summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in food command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in food command: {reply_error}")

@safe_async_handler
async def dating(update, context):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total dating expenses"""
    try:
        logger.info(f"Dating command requested by user {update.effective_user.id}")

        now = get_current_time() + relativedelta(months=offset)    
        target_month = now.strftime("%m/%Y")
        previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

        logger.info(f"Getting dating expenses for sheet {target_month}")

        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return

        dating_expenses, total = get_dating_total(target_month)
        count = len(dating_expenses)
        logger.info(f"Found {count} dating expenses for this month with total {total} VND")

        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        grouped = defaultdict(list)
        for r in dating_expenses:
            grouped[r.get("Date", "")].append(r)

        details = ""
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details += f"\n📅 {day}: {day_total:,.0f} VND\n"
            for i, r in enumerate(rows, start=1):
                details += format_expense(r, i) + "\n"

        _, previous_total = get_dating_total(previous_month)

        # Calculate percentage change
        if previous_total > 0:
            percentage_change = ((total - previous_total) / previous_total) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""

        response = (
            f"{category_display['dating']} {month_display}:\n" 
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
            f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Dating summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in dating command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in food command: {reply_error}")

@safe_async_handler
async def other(update, context):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total other expenses"""
    try:
        logger.info(f"Other command requested by user {update.effective_user.id}")

        now = get_current_time() + relativedelta(months=offset)    
        target_month = now.strftime("%m/%Y")
        previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

        logger.info(f"Getting other expenses for sheet {target_month}")

        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return

        other_expenses, total = get_other_total(target_month)
        count = len(other_expenses)
        logger.info(f"Found {count} other expenses for this month with total {total} VND")

        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        grouped = defaultdict(list)
        for r in other_expenses:
            grouped[r.get("Date", "")].append(r)

        details = ""
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details += f"\n📅 {day}: {day_total:,.0f} VND\n"
            for i, r in enumerate(rows, start=1):
                details += format_expense(r, i) + "\n"

        _, previous_total = get_other_total(previous_month)

        # Calculate percentage change
        if previous_total > 0:
            percentage_change = ((total - previous_total) / previous_total) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""

        response = (
            f"{category_display['other']} {month_display}:\n" 
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
            f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Other summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in other command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in other command: {reply_error}")

@safe_async_handler
async def investment(update, context):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this month's total investment expenses"""
    try:
        logger.info(f"Investment command requested by user {update.effective_user.id}")

        now = get_current_time() + relativedelta(months=offset)    
        target_month = now.strftime("%m/%Y")
        previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

        logger.info(f"Getting investment expenses for sheet {target_month}")

        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!\n\nLỗi: {records_error}")
            return

        investment_expenses, total = get_investment_total(target_month)
        count = len(investment_expenses)
        logger.info(f"Found {count} investment expenses for this month with total {total} VND")

        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        grouped = defaultdict(list)
        for r in investment_expenses:
            grouped[r.get("Date", "")].append(r)

        details = ""
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details += f"\n📅 {day}: {day_total:,.0f} VND\n"
            for i, r in enumerate(rows, start=1):
                details += format_expense(r, i) + "\n"

        _, previous_total = get_investment_total(previous_month)

        # Calculate percentage change
        if previous_total > 0:
            percentage_change = ((total - previous_total) / previous_total) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""


        # Get income from sheet
        total_income = get_total_income(current_sheet)
        long_invest_budget = config["budgets"].get("long_investment", 0)
        opportunity_invest_budget = config["budgets"].get("opportunity_investment", 0)
        long_invest_estimate = total_income * (long_invest_budget / 100) if total_income > 0 else 0
        opportunity_invest_estimate = total_income * (opportunity_invest_budget / 100) if total_income > 0 else 0

        response = (
            f"{category_display['investment']} {month_display}:\n" 
            f"{category_display['spend']}: {total:,.0f} VND\n"
            f"{category_display['transaction']}: {count}\n"
            f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "📌 Phân bổ danh mục\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"📈 Đầu tư dài hạn: {long_invest_estimate:,.0f} VND\n"
            f"   • 📊 ETF (60%) → {long_invest_estimate * 0.6:,.0f} VND\n"
            f"   • ₿ BTC/ETH (40%) → {long_invest_estimate * 0.4:,.0f} VND\n"
            f"      - ₿ BTC (70%) → {long_invest_estimate * 0.4 * 0.7:,.0f} VND\n"
            f"      - Ξ ETH (30%) → {long_invest_estimate * 0.4 * 0.3:,.0f} VND\n\n"

            f"🚀 Đầu tư cơ hội: {opportunity_invest_estimate:,.0f} VND\n"
            f"   • 🪙 Altcoin (50%) → {opportunity_invest_estimate * 0.5:,.0f} VND\n"
            f"   • 📈 Growth Stocks / Thematic ETF (50%) → {opportunity_invest_estimate * 0.5:,.0f} VND\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "📌 Lịch sử giao dịch\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )
        
        if details:
            response += details


        await update.message.reply_text(response)
        logger.info(f"Investment summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in investment command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in investment command: {reply_error}")

@safe_async_handler
# 200
async def freelance(update, context):
    args = context.args
    offset = 0
    amount = 0

    if args:
        if len(args) == 1:
            # Single argument: /fl 200 -> offset=0, amount=200
            try:
                amount = int(args[0])
                offset = 0
            except ValueError:
                await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương.")
                return
        elif len(args) >= 2:
            # Two arguments: /fl 1 200 -> offset=1, amount=200
            try:
                offset = int(args[0])
            except ValueError:
                offset = 0
            amount = safe_int(args[1])
    else:
        await update.message.reply_text("❌ Vui lòng cung cấp số tiền thu nhập. Ví dụ: '/fl 200'")
        return
    
    if amount <= 0:
        await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương.")
        return

    try:
        now = get_current_time() + relativedelta(months=offset)
        target_month = now.strftime("%m/%Y")
        target_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(now.strftime('%m'), now.strftime('%m'))}/{target_year}"
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)

        amount = amount * 1000
        sheet.update_acell(FREELANCE_CELL, amount)

        # Update config
        if offset == 0:
            config["income"]["freelance"] = amount  
            save_config()

        logger.info(f"Freelance income of {amount} VND logged successfully for user {update.effective_user.id}")
        await update.message.reply_text(
            f"✅ Đã ghi nhận thu nhập freelance {month_display}: {amount:,.0f} VND"
        )

    except Exception as e:
        logger.error(f"Error in freelance command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi ghi nhận thu nhập. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in freelance command: {reply_error}")

@safe_async_handler
# 200
async def salary(update, context):
    args = context.args
    offset = 0
    amount = 0

    if args:
        if len(args) == 1:
            # Single argument: /sl 2000 -> offset=0, amount=2000
            try:
                amount = int(args[0])
                offset = 0
            except ValueError:
                await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương.")
                return
        elif len(args) >= 2:
            # Two arguments: /sl 1 2000 -> offset=1, amount=2000
            try:
                offset = int(args[0])
            except ValueError:
                offset = 0
            amount = safe_int(args[1])
    else:
        await update.message.reply_text("❌ Vui lòng cung cấp số tiền thu nhập. Ví dụ: '/sl 200' hoặc '/sl 1 200'")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương.")
        return

    try:
        now = get_current_time() + relativedelta(months=offset)
        target_month = now.strftime("%m/%Y")
        target_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(now.strftime('%m'), now.strftime('%m'))}/{target_year}"
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)

        amount = amount * 1000
        sheet.update_acell(SALARY_CELL, amount)

        if offset == 0:
            # Update config
            config["income"]["salary"] = amount
            save_config()

        logger.info(f"Salary income of {amount} VND logged successfully for user {update.effective_user.id}")
        await update.message.reply_text(
            f"✅ Đã ghi nhận thu nhập lương {month_display}: {amount:,.0f} VND"
        )

    except Exception as e:
        logger.error(f"Error in salary command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi ghi nhận thu nhập. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in salary command: {reply_error}")

@safe_async_handler
async def income(update, context):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Show total income from sheet"""
    try:
        logger.info(f"Income summary requested by user {update.effective_user.id}")
        
        now = get_current_time() + relativedelta(months=offset)
        target_month = now.strftime("%m/%Y")
        previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

        logger.info(f"Getting income summary for sheet {target_month}")

        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets. Vui lòng thử lại!\n\nLỗi: {sheet_error}")
            return
        
        try:
            previous_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, previous_month)
            logger.info(f"Successfully obtained sheet for {previous_month}")
        except Exception as prev_sheet_error:
            logger.error(f"Error getting/creating sheet {previous_month}: {prev_sheet_error}", exc_info=True)
            await update.message.reply_text(f"❌ Không thể truy cập Google Sheets tháng trước. Vui lòng thử lại!\n\nLỗi: {prev_sheet_error}")
            return
            
        # Get income from current month's sheet
        freelance_income = current_sheet.acell(FREELANCE_CELL).value
        salary_income = current_sheet.acell(SALARY_CELL).value

        if not freelance_income or freelance_income.strip() == "":
            logger.info("Freelance income cell is empty, using config fallback")
            await update.message.reply_text("⚠️ Thu nhập freelance chưa được ghi nhận trong tháng này. Vui lòng sử dụng lệnh /fl để cập nhật.")
            return

        if not salary_income or salary_income.strip() == "":    
            logger.info("Salary income cell is empty, using config fallback")
            await update.message.reply_text("⚠️ Thu nhập lương chưa được ghi nhận trong tháng này. Vui lòng sử dụng lệnh /sl để cập nhật.")
            return

        freelance_income = safe_int(freelance_income)
        salary_income = safe_int(salary_income)

        # Get income from previous month's sheet for comparison
        prev_freelance_income = previous_sheet.acell(FREELANCE_CELL).value
        prev_salary_income = previous_sheet.acell(SALARY_CELL).value

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
            percentage_change = ((total_income - prev_total_income) / prev_total_income) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""
        
        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        response = (
            f"{category_display['incom']} {month_display}:\n"
            f"{category_display['salary']}: {salary_income:,.0f} VND\n"
            f"{category_display['freelance']}: {freelance_income:,.0f} VND\n"
            f"{category_display['total']}: {total_income:,.0f} VND\n"
            f"{category_display['compare']} {previous_month}: {total_income - prev_total_income:+,.0f} VND {percentage_text}\n"

        )
        
        await update.message.reply_text(response)
        logger.info(f"Income summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in income command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi lấy dữ liệu thu nhập. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in income command: {reply_error}")

@safe_async_handler
async def handle_message(update, context):
    """Route messages to appropriate handlers"""
    try:
        text = update.message.text.strip()
        user_id = update.effective_user.id
        logger.info(f"Message received from user {user_id}: '{text}'")
        
        if text.lower().startswith("del "):
            logger.info(f"Routing to delete_expense for user {user_id}")
            await delete_expense(update, context)
        else:
            logger.info(f"Routing to log_expense for user {user_id}")
            await log_expense(update, context)
            
    except Exception as e:
        logger.error(f"Error in handle_message for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Có lỗi xảy ra khi xử lý tin nhắn. Vui lòng thử lại!\n\nLỗi: {e}")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in handle_message: {reply_error}")

@safe_async_handler
async def stats(update, context):
    """Show dashboard link"""
    dashboard_webapp = WebAppInfo(url="https://track-money-ui.vercel.app/")
    keyboard = [[InlineKeyboardButton("📊 Mở Dashboard", web_app=dashboard_webapp)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Biểu đồ thu nhập 🚀",
        reply_markup=reply_markup
    )

@safe_async_handler
async def categories(update, context):
    """Show expense categories"""

    message = f"{category_display['categories']} chi tiêu hiện có:\n\n"
    for category, icon in CATEGORY_ICONS.items():
        message += f"• {icon} {CATEGORY_NAMES[category]}\n"

    await update.message.reply_text(message)