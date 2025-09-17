from dateutil.relativedelta import relativedelta
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
import datetime
import asyncio
from collections import defaultdict
from const import month_names, help_msg
from utils.logger import logger
from utils.sheet import get_current_time, normalize_date, normalize_time, get_or_create_monthly_sheet, parse_amount, format_expense, get_gas_total, get_food_total, get_dating_total
from const import log_expense_msg, delete_expense_msg

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
            ["/gas", "/gas -1", "/food", "/food -1", "/dating", "/dating -1"],
            ["/help"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(help_msg, reply_markup=reply_markup)
        logger.info(f"Welcome message + keyboard sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi khởi động. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in start command: {reply_error}")

@safe_async_handler
async def help(update, context):
    """Show help message"""
    try:
        logger.info(f"Help command requested by user {update.effective_user.id}")
        await update.message.reply_text(help_msg)
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
            
            # Emoji shortcuts (copy-paste friendly)
            "☕": "cafe",
            "🍽️": "ăn",
            "🌅": "ăn sáng",
            "🌞": "ăn trưa", 
            "🌙": "ăn tối",
            "⛽": "xăng xe",
            "🚗": "grab",
            "🚌": "xe buýt",
            
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
            await update.message.reply_text(log_expense_msg)
            return

        # Smart amount multipliers for faster typing
        amount = amount * 1000

        logger.info(f"Parsed expense: {amount} VND on {entry_date} {entry_time} - {note} (sheet: {target_month})")

        # Get or create the target month's sheet
        sheet = get_or_create_monthly_sheet(target_month)

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
            await update.message.reply_text(delete_expense_msg)
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
            current_sheet = get_or_create_monthly_sheet(target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        # Find and delete the matching row
        try:
            all_records = current_sheet.get_all_records()
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
            current_sheet = get_or_create_monthly_sheet(target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        try:
            records = current_sheet.get_all_records()
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
            logger.error(f"Failed to send error message in today command: {reply_error}")

@safe_async_handler
async def week(update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Get this week's total expenses"""
    try:
        logger.info(f"Week command requested by user {update.effective_user.id}")
        
        now = get_current_time() + datetime.timedelta(weeks=offset)
        
        # Calculate week start (Monday)
        days_since_monday = now.weekday()
        week_start = now - datetime.timedelta(days=days_since_monday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        logger.info(f"Getting week expenses from {week_start.strftime('%d/%m')} to {week_end.strftime('%d/%m')}")
        
        # Get months that this week spans
        months_to_check = set()
        current_date = week_start
        while current_date <= week_end:
            months_to_check.add(current_date.strftime("%m/%Y"))
            current_date += datetime.timedelta(days=1)
        
        logger.info(f"Checking sheets for months: {list(months_to_check)}")
        
        week_expenses = []
        total = 0
        
        for target_month in months_to_check:
            try:
                current_sheet = get_or_create_monthly_sheet(target_month)
                logger.info(f"Successfully obtained sheet for {target_month}")
                
                records = current_sheet.get_all_records()
                logger.info(f"Retrieved {len(records)} records from sheet {target_month}")
                
                for r in records:
                    try:
                        day_month = r.get("Date", "")
                        if "/" in day_month:
                            # Parse the date from the record
                            date_parts = day_month.split("/")
                            if len(date_parts) == 2:
                                day, month = date_parts
                                year = target_month.split("/")[1]  # Get year from sheet name
                                date_obj = datetime.datetime.strptime(f"{day}/{month}/{year}", "%d/%m/%Y").date()
                                expense_date = datetime.datetime.combine(date_obj, datetime.time(0, 0, 0, tzinfo=week_start.tzinfo))
                                
                                logger.info("week_start: %s, expense_date: %s, week_end: %s", week_start, expense_date, week_end)  # Debug info

                                # Check if this date falls within our week
                                if week_start <= expense_date <= week_end:
                                    week_expenses.append(r)
                                    amount = r.get("VND", 0)
                                    total += parse_amount(amount)
                                else:
                                    logger.info(f"Skipping date {expense_date} not in week range")

                    except Exception as date_parse_error:
                        logger.warning(f"Could not parse date '{day_month}' from sheet {target_month}: {date_parse_error}")
                        continue
                        
            except Exception as sheet_error:
                logger.warning(f"Could not access sheet {target_month}: {sheet_error}")
                continue
                
        count = len(week_expenses)
        logger.info(f"Found {count} expenses for this week with total {total} VND")

        grouped = defaultdict(list)
        for r in week_expenses:
            grouped[r.get("Date", "")].append(r)

        details = ""
        for day, rows in sorted(grouped.items()):
            day_total = sum(parse_amount(r.get("VND", 0)) for r in rows)
            details += f"\n📅 {day}: {day_total:,.0f} VND\n"
            for i, r in enumerate(rows, start=1):
                details += format_expense(r, i) + "\n"

        response = (
            f"📊 Tổng kết tuần này ({week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}):\n"
            f"💰 {total:,.0f} VND\n"
            f"📝 {count} giao dịch\n"
        )

        if details:
            response += f"\n\n📝 Chi tiết:{details}"

        await update.message.reply_text(response)
        logger.info(f"Week summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in week command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in week command: {reply_error}")

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
            current_sheet = get_or_create_monthly_sheet(target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
        
        try:
            records = current_sheet.get_all_records()
            logger.info(f"Retrieved {len(records)} records from sheet")
        except Exception as records_error:
            logger.error(f"Error retrieving records from sheet: {records_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể đọc dữ liệu từ Google Sheets. Vui lòng thử lại!")
            return
        
        month_expenses = []
        total = 0
        
        for r in records:
            # Only count records with valid date and amount (not empty rows)
            record_date = r.get("Date", "").strip().lstrip("'")
            record_amount = r.get("VND", 0)

            if record_date and record_amount:  # Only count if both date and amount exist and are not empty
                month_expenses.append(r)
                total += parse_amount(record_amount)

        count = len(month_expenses)
        logger.info(f"Found {count} expenses for this month with total {total} VND")
        
        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{month_names.get(current_month, current_month)}/{current_year}"
        
        _, food_total = get_food_total(target_month)
        logger.info(f"Total food expenses for {target_month}: {food_total} VND")

        _, dating_total = get_dating_total(target_month)
        logger.info(f"Total dating expenses for {target_month}: {dating_total} VND")

        response = (
            f"📊 Tổng kết {month_display}:\n"
            f"💰 {total:,.0f} VND\n"
            f"📝 {count} giao dịch\n"
            f"📄 Sheet: {target_month}\n"
            f"🍽️ Ăn uống: {food_total:,.0f} VND\n"
            f"🎉 Hẹn hò: {dating_total:,.0f} VND\n"
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
            current_sheet = get_or_create_monthly_sheet(target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = current_sheet.get_all_records()
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
        month_display = f"{month_names.get(current_month, current_month)}/{current_year}"

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
            f"⛽ Tổng kết đổ xăng {month_display}\n"
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
            current_sheet = get_or_create_monthly_sheet(target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = current_sheet.get_all_records()
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
        month_display = f"{month_names.get(current_month, current_month)}/{current_year}"

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
            current_sheet = get_or_create_monthly_sheet(target_month)
            logger.info(f"Successfully obtained sheet for {target_month}")
        except Exception as sheet_error:
            logger.error(f"Error getting/creating sheet {target_month}: {sheet_error}", exc_info=True)
            await update.message.reply_text("❌ Không thể truy cập Google Sheets. Vui lòng thử lại!")
            return
    
        try:
            records = current_sheet.get_all_records()
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
        month_display = f"{month_names.get(current_month, current_month)}/{current_year}"

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
            f"🍽️ Tổng kết chi tiêu hẹn hò {month_display}\n"
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
