from dateutil.relativedelta import relativedelta
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
import datetime
import asyncio
from collections import defaultdict
from const import MONTH_NAMES, HELP_MSG
from utils.logger import logger
from utils.sheet import get_current_time, normalize_date, normalize_time, get_or_create_monthly_sheet, parse_amount, format_expense, get_gas_total, get_food_total, get_dating_total, get_rent_total, get_other_total, get_long_investment_total, get_month_summary
from const import LOG_EXPENSE_MSG, DELETE_EXPENSE_MSG, FREELANCE_CELL, SALARY_CELL, EXPECTED_HEADERS
from config import config, save_config

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


@safe_async_handler
async def start(update, context):
    """Send welcome message when bot starts"""
    try:
        logger.info(f"Start command requested by user {update.effective_user.id}")
        keyboard = [
            ["/today", "/week", "/month"],
            ["/week -1", "/month -1"],
            ["/gas", "/gas -1"],
            ["/food", "/food -1"],
            ["/dating", "/dating -1"],
            ["/other", "/other -1"],
            ["/investment", "/investment -1"],
            ["/freelance [amount]", "/salary [amount]"],
            ["/income"],
            ["/help"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(HELP_MSG, reply_markup=reply_markup)
        logger.info(f"Welcome message + keyboard sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi khởi động. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Có lỗi xảy ra khi hiển thị hướng dẫn. Vui lòng thử lại!")
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
        shortcuts = {
            # Ultra-fast single characters
            "c": "cafe",
            "a": "ăn",
            "s": "ăn sáng", 
            "t": "ăn trưa",
            "o": "ăn tối",
            "x": "xăng xe",
            "g": "grab",
            "b": "xe buýt",
            "n": "thuê nhà",
            
            # Emoji shortcuts (copy-paste friendly)
            "☕": "cafe",
            "🍽️": "ăn",
            "🌅": "ăn sáng",
            "🌞": "ăn trưa", 
            "🌙": "ăn tối",
            "⛽": "xăng xe",
            "🚗": "grab",
            "🚌": "xe buýt",
            "🏠": "thuê nhà",
            
            # Regular shortcuts  
            "cf": "cafe",
            "an": "ăn",
            "sang": "ăn sáng", 
            "trua": "ăn trưa",
            "toi": "ăn tối",
            "xang": "xăng xe",
            "grab": "grab",
            "bus": "xe buýt",
            "com": "cơm",
            "pho": "phở",
            "bun": "bún",
            "mien": "miến"
        }
        
        # Parse different input formats
        entry_date = None
        entry_time = None
        amount = None
        note = ""
        target_month = None
        
        # Case A: Default Entry (No Date/Time) - 1000 ăn trưa or 5 cf or just "5"
        if parts[0].isdigit():
            amount = int(parts[0])
            
            # Super-fast mode: Just number, no description
            if len(parts) == 1:
                # User typed only a number, provide quick buttons
                display_amount = amount * 1000

                keyboard = [
                    [InlineKeyboardButton(f"🍽️ Ăn sáng ({display_amount:,})", callback_data=f"log_{amount}_s")],
                    [InlineKeyboardButton(f"🌅 Ăn trưa ({display_amount:,})", callback_data=f"log_{amount}_t")],
                    [InlineKeyboardButton(f"🌙 Ăn tối ({display_amount:,})", callback_data=f"log_{amount}_t")],
                    [InlineKeyboardButton(f"⛽ Xăng ({display_amount:,})", callback_data=f"log_{amount}_x")],
                    [InlineKeyboardButton(f"🚗 Grab ({display_amount:,})", callback_data=f"log_{amount}_g")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"💰 {display_amount:,} VND - Chọn loại chi tiêu:",
                    reply_markup=reply_markup
                )
                return
            
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

        # Get or create the target month's sheet
        # sheet = get_or_create_monthly_sheet(target_month)
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)

        # Always append the data to columns A-D, then sort if needed
        # Find the next empty row in columns A-D
        try:
            all_values = sheet.get_values("A:D")
        except Exception as get_error:
            logger.warning(f"Could not get values, using empty list: {get_error}")
            all_values = []
            
        next_row = len(all_values) + 1
        
        # Add the new entry to columns A-D
        range_name = f"A{next_row}:D{next_row}"
        # Ensure amount is stored as a plain number without formatting
        sheet.update(range_name, [[entry_date, entry_time, int(amount), note]], value_input_option='RAW')
        
        # Now sort only columns A-D by date and time to maintain order
        if len(all_values) > 1:  # Only sort if there's more than just the header
            try:
                # Get all data from columns A-D (excluding header)
                data_range = f"A2:D{next_row}"
                data_values = sheet.get_values(data_range)
                
                if data_values:
                    # Sort the data by date and time
                    sorted_data = sorted(data_values, key=lambda x: (
                        x[0] if len(x) > 0 else "",  # Date
                        x[1] if len(x) > 1 else ""   # Time
                    ))
                    
                    # Ensure all amounts are integers when updating
                    for row in sorted_data:
                        if len(row) >= 3 and row[2]:
                            try:
                                # Convert amount to integer to avoid formatting issues
                                row[2] = int(float(str(row[2]).replace(',', '').replace('₫', '').strip()))
                            except (ValueError, TypeError):
                                pass  # Keep original value if conversion fails
                    
                    # Update the sorted data back to columns A-D using RAW input
                    sheet.update(f"A2:D{len(sorted_data) + 1}", sorted_data, value_input_option='RAW')
                    
                    # Find where our entry ended up after sorting
                    for i, row in enumerate(sorted_data, start=2):
                        if (len(row) >= 4 and row[0] == entry_date and row[1] == entry_time and 
                            int(float(str(row[2]).replace(',', '').replace('₫', '').strip())) == int(amount) and row[3] == note):
                            position_msg = f"📍 Vị trí: Dòng {i}"
                            break
                    else:
                        position_msg = "📍 Vị trí: Đã sắp xếp"
                else:
                    position_msg = f"📍 Vị trí: Dòng {next_row}"
            except Exception as sort_error:
                logger.warning(f"Could not sort data: {sort_error}")
                position_msg = f"📍 Vị trí: Dòng {next_row}"
        else:
            position_msg = f"📍 Vị trí: Dòng {next_row}"

        response = f"✅ Đã ghi nhận:\n💰 {amount:,} VND\n📝 {note}\n� {entry_date} {entry_time}\n{position_msg}\n� Sheet: {target_month}"
        await update.message.reply_text(response)

        logger.info(f"Logged expense: {amount} VND - {note} at {entry_date} {entry_time} in sheet {target_month}")

    except ValueError as ve:
        await update.message.reply_text("❌ Lỗi định dạng số tiền!\n\n📝 Các định dạng hỗ trợ:\n• 1000 ăn trưa\n• 02/09 5000 cafe\n• 02/09 08:30 15000 breakfast")
    except Exception as e:
        logger.error(f"Error logging expense: {e}")
        await update.message.reply_text("❌ Có lỗi xảy ra. Vui lòng thử lại!")

@safe_async_handler  
async def handle_quick_expense(update, context):
    """Handle quick expense selection from inline buttons"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Parse callback data: "log_amount_shortcut"
        parts = query.data.split("_")
        if len(parts) != 3 or parts[0] != "log":
            return
            
        amount = int(parts[1])
        shortcut = parts[2]
        
        # Get the note from shortcuts
        shortcuts = {"s": "ăn sáng", "t": "ăn trưa", "t": "ăn tối", "x": "xăng xe", "g": "grab"}
        note = shortcuts.get(shortcut, "")
        
        # Smart amount handling
        amount = amount * 1000
        
        # Get current time
        now = get_current_time()
        entry_date = now.strftime("%d/%m")
        entry_time = now.strftime("%H:%M")
        target_month = now.strftime("%m/%Y")
        
        logger.info(f"Quick expense: {amount} VND - {note}")
        
        # Get or create the target month's sheet
        sheet = get_or_create_monthly_sheet(target_month)
        
        # Add the new entry
        try:
            all_values = sheet.get_values("A:D")
        except Exception:
            all_values = []
            
        next_row = len(all_values) + 1
        range_name = f"A{next_row}:D{next_row}"
        sheet.update(range_name, [[entry_date, entry_time, int(amount), note]], value_input_option='RAW')
        
        # Edit the original message to show success
        await query.edit_message_text(
            f"✅ Đã ghi nhận:\n💰 {amount:,} VND\n📝 {note}\n📅 {entry_date} {entry_time}\n📄 Sheet: {target_month}"
        )
        
        logger.info(f"Quick expense logged: {amount} VND - {note}")
        
    except Exception as e:
        logger.error(f"Error in handle_quick_expense: {e}", exc_info=True)
        try:
            await update.callback_query.edit_message_text("❌ Có lỗi xảy ra. Vui lòng thử lại!")
        except:
            pass

@safe_async_handler
async def delete_expense(update, context):
    """Delete expense entry from Google Sheet"""
    text = update.message.text.strip()
    
    try:
        logger.info(f"Delete expense requested by user {update.effective_user.id}: '{text}'")
        
        parts = text.split()
        # Only "del hh:mm" -> assume today's date
        if len(parts) == 2:
            entry_date = get_current_time().strftime("%d/%m")
            entry_time = normalize_time(parts[1])
        # Parse delete command: "del 14/10 00:11"
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
        
        # Get the appropriate monthly sheet
        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        # Find and delete the matching row
        try:
            all_records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(all_records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
            return
        
        found = False
        
        for i, record in enumerate(all_records, start=2):  # Start from row 2 (after header)
            record_date = normalize_date(record.get('Date', '').strip())
            record_time = normalize_time(record.get('Time', '').strip())
            
            if record_date == entry_date and record_time == entry_time:
                try:
                    current_sheet.delete_rows(i)
                    found = True
                    logger.info(f"Successfully deleted expense: {entry_date} {entry_time} from row {i}")
                    await update.message.reply_text(f"✅ Đã xóa giao dịch: {entry_date} {entry_time}")
                    break
                except Exception as delete_error:
                    logger.error(f"Error deleting row {i}: {delete_error}", exc_info=True)
                    await update.message.reply_text("❌ Có lỗi xảy ra khi xóa giao dịch. Vui lòng thử lại!")
                    return
        
        if not found:
            logger.warning(f"Expense not found: {entry_date} {entry_time}")
            await update.message.reply_text(f"❌ Không tìm thấy giao dịch: {entry_date} {entry_time}")
            
    except Exception as e:
        logger.error(f"Error in delete_expense for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi xóa! Vui lòng thử lại.")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in delete_expense: {reply_error}")

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
        
        try:
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
            return
        
        today_expenses = []
        total = 0
        
        for r in records:
            # Make sure we have valid data in the record
            record_date = r.get("Date", "").strip().lstrip("'")
            record_amount = r.get("VND", 0)
            
            if record_date == today_str and record_amount:  # Only count if both date and amount exist
                today_expenses.append(r)
                total += parse_amount(record_amount)
        
        count = len(today_expenses)
        logger.info(f"Found {count} expenses for today with total {total} VND")
        logger.info(f"Today date string: '{today_str}', Records found: {[r.get('Date') for r in records[:5]]}")  # Debug info
        
        response = f"📊 Tổng kết hôm nay ({today_str}):\n💰 {total:,.0f} VND\n📝 {count} giao dịch\n📄 Sheet: {target_month}"
        
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
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
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
        months_to_check = {
            (week_start + datetime.timedelta(days=i)).strftime("%m/%Y")
            for i in range(7)
        }

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
            grouped[r.get("Date", "")].append(r)

        details_lines = []
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details_lines.append(f"\n📅 {day}: {day_total:,.0f} VND")
            details_lines.extend(format_expense(r, i) for i, r in enumerate(rows, start=1))

        response_parts = [
            f"📊 Tổng kết tuần này ({week_start:%d/%m} - {week_end:%d/%m}):",
            f"💰 {total:,.0f} VND",
            f"📝 {count} giao dịch",
        ]
        if details_lines:
            response_parts.append("\n📝 Chi tiết:")
            response_parts.extend(details_lines)

        await update.message.reply_text("\n".join(response_parts))

    except Exception as e:
        logger.error(f"Error in week command: {e}", exc_info=True)
        await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")


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
            current_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
            return
        
        summary = get_month_summary(records)
        month_expenses = summary["expenses"]
        total = summary["total"]
        food_total = summary["food"]
        dating_total = summary["dating"]
        gas_total = summary["gas"]
        rent_total = summary["rent"]
        other_total = summary["other"]
        essential_total = summary["essential"]
        long_invest_total = summary["long_investment"]
        opportunity_invest_total = summary["opportunity_investment"]
        investment_total = summary["investment"]
        support_parent_total = summary["support_parent"]

        # Get income from sheet
        salary = current_sheet.acell(SALARY_CELL).value
        freelance = current_sheet.acell(FREELANCE_CELL).value

        # fallback from config if empty/invalid
        if not salary or not str(salary).strip().isdigit():
            salary = config["income"].get("salary", 0)
        if not freelance or not str(freelance).strip().isdigit():
            freelance = config["income"].get("freelance", 0)

        # convert safely to int
        try:
            salary = int(str(salary).strip())
        except ValueError:
            salary = 0

        try:
            freelance = int(str(freelance).strip())
        except ValueError:
            freelance = 0

        total_income = salary + freelance

        food_and_travel_total = food_total + gas_total + other_total
        food_and_travel_budget = config["budgets"].get("food_and_travel", 0)
        rent_budget = config["budgets"].get("rent", 0)
        essential_budget = food_and_travel_budget + rent_budget
        long_invest_budget = config["budgets"].get("long_investment", 0)
        opportunity_invest_budget = config["budgets"].get("opportunity_investment", 0)
        support_parent_budget = config["budgets"].get("support_parent", 0)
        dating_budget = config["budgets"].get("dating", 0)

        count = len(month_expenses)
        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{MONTH_NAMES.get(current_month, current_month)}/{current_year}"

        # Calculate estimated amounts based on percentages and income
        # essential_estimate = total_income * (essential_budget / 100) if total_income > 0 else 0
        food_and_travel_estimate = total_income * (food_and_travel_budget / 100) if total_income > 0 else 0
        rent_estimate = total_income * (rent_budget / 100) if total_income > 0 else 0
        long_invest_estimate = total_income * (long_invest_budget / 100) if total_income > 0 else 0
        opportunity_invest_estimate = total_income * (opportunity_invest_budget / 100) if total_income > 0 else 0
        support_parent_estimate = total_income * (support_parent_budget / 100) if total_income > 0 else 0
        dating_estimate = total_income * (dating_budget / 100) if total_income > 0 else 0

        response = (
            f"📊 Tổng kết {month_display}:\n"
            f"💰 Chi tiêu: {total:,.0f} VND\n"
            f"💵 Thu nhập: {total_income:,.0f} VND\n"
            f"📝 {count} giao dịch\n\n"

            f"📌 Ngân sách dự kiến (% thu nhập):\n"
            # f"🏠 Thiết yếu: {essential_budget:.0f}% = {essential_estimate:,.0f} VND\n"
            f"🏠 Thuê nhà: {rent_budget:.0f}% = {rent_estimate:,.0f} VND\n"
            f"🍽️ Ăn uống & 🚗 Đi lại: {food_and_travel_budget:.0f}% = {food_and_travel_estimate:,.0f} VND\n"
            f"👪 Hỗ trợ ba mẹ: {support_parent_budget:.0f}% = {support_parent_estimate:,.0f} VND\n"
            f"💖 Hẹn hò: {dating_budget:.0f}% = {dating_estimate:,.0f} VND\n"
            f"📈 Đầu tư dài hạn: {long_invest_budget:.0f}% = {long_invest_estimate:,.0f} VND\n"
            f"🚀 Đầu tư cơ hội: {opportunity_invest_budget:.0f}% = {opportunity_invest_estimate:,.0f} VND\n\n"

            f"💸 Chi tiêu thực tế:\n"
            # f"🏠 Thiết yếu: {essential_total:,.0f} VND ({essential_estimate - essential_total:+,.0f})\n"
            f"🏠 Thuê nhà: {rent_total:,.0f} VND ({rent_estimate - rent_total:+,.0f})\n"
            f"🍽️ Ăn uống & 🚗 Đi lại: {food_and_travel_total:,.0f} VND ({food_and_travel_estimate - food_and_travel_total:+,.0f})\n"
            f"👪 Hỗ trợ ba mẹ: {support_parent_total:,.0f} VND ({support_parent_estimate - support_parent_total:+,.0f})\n"
            f"💖 Hẹn hò: {dating_total:,.0f} VND ({dating_estimate - dating_total:+,.0f})\n"
            f"📈 Đầu tư dài hạn: {long_invest_total:,.0f} VND ({long_invest_estimate - long_invest_total:+,.0f})\n"
            f"🚀 Đầu tư cơ hội: {opportunity_invest_total:,.0f} VND ({opportunity_invest_estimate - opportunity_invest_total:+,.0f})\n\n"

            f"📋 Chi tiết:\n"
            f"🍽️ Ăn uống: {food_total:,.0f} VND\n"
            f"⛽ Xăng / Đi lại: {gas_total:,.0f} VND\n"
            f"🏠 Thuê nhà: {rent_total:,.0f} VND\n"
            f"🛍️ Khác: {other_total:,.0f} VND\n"
            f"💹 Đầu tư: {investment_total:,.0f} VND\n"
        )

        await update.message.reply_text(response)
        logger.info(f"Month summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in month command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
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
            f"⛽ Tổng kết đổ xăng / đi lại {month_display}\n"
            f"💰 Tổng chi: {total:,.0f} VND\n"
            f"📝 Giao dịch: {count}\n"
            f"📊 So với {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Gas summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in gas command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
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
            f"🍽️ Tổng kết chi tiêu ăn uống {month_display}\n"
            f"💰 Tổng chi: {total:,.0f} VND\n"
            f"📝 Giao dịch: {count}\n"
            f"📊 So với {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Food summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in food command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
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
            f"🎉 Tổng kết chi tiêu hẹn hò / giải trí {month_display}\n"
            f"💰 Tổng chi: {total:,.0f} VND\n"
            f"📝 Giao dịch: {count}\n"
            f"📊 So với {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Dating summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in dating command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
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
            f"🛍️ Tổng kết chi tiêu khác {month_display}\n"
            f"💰 Tổng chi: {total:,.0f} VND\n"
            f"📝 Giao dịch: {count}\n"
            f"📊 So với {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Other summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in other command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = await asyncio.to_thread(
                lambda: current_sheet.get_all_records(expected_headers=EXPECTED_HEADERS)
            )
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
            return

        investment_expenses, total = get_long_investment_total(target_month)
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

        _, previous_total = get_long_investment_total(previous_month)

        # Calculate percentage change
        if previous_total > 0:
            percentage_change = ((total - previous_total) / previous_total) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""

        response = (
            f"📈 Tổng kết chi tiêu đầu tư {month_display}\n"
            f"💰 Tổng chi: {total:,.0f} VND\n"
            f"📝 Giao dịch: {count}\n"
            f"📊 So với {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
        )
        
        if details:
            response += f"\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Investment summary sent successfully to user {update.effective_user.id}")
    
    except Exception as e:
        logger.error(f"Error in investment command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in investment command: {reply_error}")

@safe_async_handler
# 200
async def freelance(update, context):
    """Log freelance income to sheet"""
    text = update.message.text.strip()
    
    try:
        logger.info(f"Freelance income logging requested by user {update.effective_user.id}: '{text}'")
        
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Vui lòng cung cấp số tiền thu nhập. Ví dụ: '/fl 200'")
            return

        amount_str = parts[1]
        if not amount_str.isdigit():
            await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương.")
            return

        amount = int(amount_str)
        if amount <= 0:
            await update.message.reply_text("❌ Số tiền phải lớn hơn 0.")
            return

        target_month = get_current_time().strftime("%m/%Y")
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)

        amount = amount * 1000
        sheet.update_acell(FREELANCE_CELL, amount)

        # Update config
        config["income"]["freelance"] = amount  
        save_config()

        logger.info(f"Freelance income of {amount} VND logged successfully for user {update.effective_user.id}")
        await update.message.reply_text(
            f"✅ Đã ghi nhận thu nhập freelance: {amount:,.0f} VND\n"
            f"💰 Tổng thu nhập freelance hiện tại: {config['income']['freelance']:,.0f} VND"
        )

    except Exception as e:
        logger.error(f"Error in freelance command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi ghi nhận thu nhập. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in freelance command: {reply_error}")

@safe_async_handler
# 200
async def salary(update, context):
    """Log salary income to sheet"""
    text = update.message.text.strip()
    
    try:
        logger.info(f"Salary income logging requested by user {update.effective_user.id}: '{text}'")
        
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("❌ Vui lòng cung cấp số tiền thu nhập. Ví dụ: '/fl 200'")
            return

        amount_str = parts[1]
        if not amount_str.isdigit():
            await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương.")
            return

        amount = int(amount_str)
        if amount <= 0:
            await update.message.reply_text("❌ Số tiền phải lớn hơn 0.")
            return

        target_month = get_current_time().strftime("%m/%Y")
        sheet = await asyncio.to_thread(get_or_create_monthly_sheet, target_month)

        amount = amount * 1000
        sheet.update_acell(SALARY_CELL, amount)

        # Update config
        config["income"]["salary"] = amount
        save_config()

        logger.info(f"Salary income of {amount} VND logged successfully for user {update.effective_user.id}")
        await update.message.reply_text(
            f"✅ Đã ghi nhận thu nhập lương: {amount:,.0f} VND\n"
            f"💰 Tổng thu nhập lương hiện tại: {config['income']['salary']:,.0f} VND"
        )

    except Exception as e:
        logger.error(f"Error in salary command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi ghi nhận thu nhập. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        try:
            previous_sheet = await asyncio.to_thread(get_or_create_monthly_sheet, previous_month)
            logger.info(f"Successfully obtained sheet for {previous_month}")
        except Exception as prev_sheet_error:
            logger.error(f"Error getting/creating sheet {previous_month}: {prev_sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets tháng trước. Vui lòng thử lại!")
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

        try:
            freelance_income = int(freelance_income)
        except (ValueError, TypeError):
            freelance_income = 0
        
        try:
            salary_income = int(salary_income)
        except (ValueError, TypeError):
            salary_income = 0

        # Get income from previous month's sheet for comparison
        prev_freelance_income = previous_sheet.acell(FREELANCE_CELL).value
        prev_salary_income = previous_sheet.acell(SALARY_CELL).value

        try:
            prev_freelance_income = int(str(prev_freelance_income).strip()) if prev_freelance_income and str(prev_freelance_income).strip().isdigit() else 0
        except (ValueError, TypeError):
            prev_freelance_income = 0
        
        try:
            prev_salary_income = int(str(prev_salary_income).strip()) if prev_salary_income and str(prev_salary_income).strip().isdigit() else 0
        except (ValueError, TypeError):
            prev_salary_income = 0


        prev_total_income = prev_freelance_income + prev_salary_income
        total_income = freelance_income + salary_income

        # Calculate percentage change
        if prev_total_income > 0:
            percentage_change = ((total_income - prev_total_income) / prev_total_income) * 100
            change_symbol = "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
            percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
        else:
            percentage_text = ""
        
        response = (
            f"💼 Tổng thu nhập:\n"
            f"💰 Lương: {salary_income:,.0f} VND\n"
            f"💰 Freelance: {freelance_income:,.0f} VND\n"
            f"💵 Tổng cộng: {total_income:,.0f} VND"
            f"📊 So với {previous_month}: {total_income - prev_total_income:+,.0f} VND {percentage_text}\n"
        )
        
        await update.message.reply_text(response)
        logger.info(f"Income summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in income command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi lấy dữ liệu thu nhập. Vui lòng thử lại!")
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
            await update.message.reply_text("❌ Có lỗi xảy ra khi xử lý tin nhắn. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in handle_message: {reply_error}")
