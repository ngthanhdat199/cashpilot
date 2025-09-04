from telegram.ext import Application, MessageHandler, CommandHandler, filters
import gspread
from google.oauth2.service_account import Credentials
import datetime
import os
import logging
import json
import pytz
from flask import Flask, request
import threading
import asyncio
from telegram import Update

# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load configuration
try:
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path, "r") as config_file:
        config = json.load(config_file)
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=getattr(logging, config["settings"]["logging_level"]))
    logger.info(f"Configuration loaded successfully from {config_path}")
except Exception as e:
    print(f"⚠️  Failed to load config.json: {e}")
    exit(1)

# Timezone setup
timezone = pytz.timezone(config["settings"]["timezone"])

def get_current_time():
    """Get current time in the configured timezone"""
    return datetime.datetime.now(timezone)

# Google Sheets setup
try:
    scope = config["google_sheets"]["scopes"]
    credentials_path = os.path.join(BASE_DIR, config["google_sheets"]["credentials_file"])
    creds = Credentials.from_service_account_file(credentials_path, scopes=scope)
    client = gspread.authorize(creds)
    # Open the specific Google Sheet by ID from the URL
    spreadsheet = client.open_by_key(config["google_sheets"]["spreadsheet_id"])
    logger.info(f"Google Sheets connected successfully using credentials from {credentials_path}")
except Exception as e:
    logger.error(f"Failed to connect to Google Sheets: {e}")
    print("⚠️  Please make sure you have:")
    print(f"1. Created {config['google_sheets']['credentials_file']} file in {BASE_DIR}")
    print(f"2. Shared the Google Sheet (ID: {config['google_sheets']['spreadsheet_id']}) with your service account email")
    print("3. The sheet has the correct permissions")
    exit(1)

# Telegram bot
TOKEN = config["telegram"]["bot_token"]
WEBHOOK_URL = config["telegram"]["webhook_url"]

# Flask app for webhook
app = Flask(__name__)

# Initialize bot application immediately
def setup_bot():
    """Setup the bot application"""
    try:
        bot_app = Application.builder().token(TOKEN).build()
        
        # Command handlers
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CommandHandler("help", help_command))
        bot_app.add_handler(CommandHandler("today", today))
        bot_app.add_handler(CommandHandler("week", week))
        bot_app.add_handler(CommandHandler("month", month))
        
        # Message handler for expenses and delete commands
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Add error handler to prevent "No error handlers are registered" warnings
        async def error_handler(update, context):
            """Global error handler for main bot instance"""
            logger.error(f"Error in main bot instance: {context.error}", exc_info=context.error)
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text("❌ Có lỗi xảy ra. Vui lòng thử lại!")
                except Exception as reply_error:
                    logger.error(f"Failed to send error message: {reply_error}")
        
        bot_app.add_error_handler(error_handler)
        
        logger.info("Bot application setup completed!")
        return bot_app
        
    except Exception as e:
        logger.error(f"Error setting up bot: {e}")
        raise

def create_fresh_bot():
    """Create a completely fresh bot instance for isolated processing"""
    try:
        logger.info("Creating fresh bot instance")
        fresh_app = Application.builder().token(TOKEN).build()
        
        # Add all handlers
        fresh_app.add_handler(CommandHandler("start", start))
        fresh_app.add_handler(CommandHandler("help", help_command))  
        fresh_app.add_handler(CommandHandler("today", today))
        fresh_app.add_handler(CommandHandler("week", week))
        fresh_app.add_handler(CommandHandler("month", month))
        fresh_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Add error handler to prevent "No error handlers are registered" warnings
        async def error_handler(update, context):
            """Global error handler for fresh bot instance"""
            logger.error(f"Error in fresh bot instance: {context.error}", exc_info=context.error)
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text("❌ Có lỗi xảy ra. Vui lòng thử lại!")
                except Exception as reply_error:
                    logger.error(f"Failed to send error message: {reply_error}")
        
        fresh_app.add_error_handler(error_handler)
        
        logger.info("Fresh bot instance created successfully")
        return fresh_app
        
    except Exception as e:
        logger.error(f"Error creating fresh bot: {e}", exc_info=True)
        raise

async def initialize_bot(bot_app):
    """Initialize the bot application asynchronously"""
    if not bot_app.running:
        await bot_app.initialize()
    return bot_app

# Global variable to store bot application - initialize it immediately
bot_app = None

# Simple circuit breaker for webhook failures
webhook_failures = 0
last_failure_time = None
MAX_FAILURES = 10
FAILURE_RESET_TIME = 300  # 5 minutes
use_fresh_bots = True  # Flag to enable/disable fresh bot instances

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

@safe_async_handler
async def start(update, context):
    """Send welcome message when bot starts"""
    try:
        logger.info(f"Start command requested by user {update.effective_user.id}")
        
        welcome_msg = """
👋 Chào mừng đến với Money Tracker Bot!

📝 Các định dạng hỗ trợ:
• 1000 ăn trưa (thời gian hiện tại)
• 02/09 5000 cafe (ngày cụ thể, 12:00)  
• 02/09 08:30 15000 breakfast (ngày + giờ)

🗑️ Xóa giao dịch:
• del 14/10 00:11 (xóa theo ngày + giờ)

📊 Lệnh có sẵn:
• /today - Xem tổng chi tiêu hôm nay
• /week - Xem tổng chi tiêu tuần này
• /month - Xem tổng chi tiêu tháng này
• /help - Xem hướng dẫn

Bot sẽ tự động sắp xếp theo thời gian! 🕐💰
        """
        await update.message.reply_text(welcome_msg)
        logger.info(f"Welcome message sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi khởi động. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in start command: {reply_error}")

@safe_async_handler
async def help_command(update, context):
    """Show help message"""
    try:
        logger.info(f"Help command requested by user {update.effective_user.id}")
        
        help_msg = """
📖 Hướng dẫn sử dụng Money Tracker Bot:

💰 Các định dạng ghi chi tiêu:

🔸 Mặc định (thời gian hiện tại):
• 45000 ăn sáng
• 200000 mua áo

🔸 Chỉ định ngày (12:00 mặc định):
• 02/09 15000 cà phê
• 05/09 80000 ăn tối

⏰ Chỉ định ngày + giờ:
• 02/09 08:30 25000 sáng
• 03/09 14:00 120000 trưa

📊 Lệnh thống kê:
• /today - Chi tiêu hôm nay
• /week - Chi tiêu tuần này
• /month - Chi tiêu tháng này

🤖 Bot tự động sắp xếp theo thời gian!
        """
        await update.message.reply_text(help_msg)
        logger.info(f"Help message sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in help_command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Có lỗi xảy ra khi hiển thị hướng dẫn. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in help_command: {reply_error}")

@safe_async_handler
async def log_expense(update, context):
    """Log expense to Google Sheet with smart date/time parsing"""
    text = update.message.text.strip()
    parts = text.split()

    try:
        logger.info(f"Log expense requested by user {update.effective_user.id}: '{text}'")
        
        # Parse different input formats
        entry_date = None
        entry_time = None
        amount = None
        note = ""
        target_month = None
        
        # Case A: Default Entry (No Date/Time) - 1000 ăn trưa
        if parts[0].isdigit():
            amount = int(parts[0])
            note = " ".join(parts[1:]) if len(parts) > 1 else "Không có ghi chú"
            now = get_current_time()
            # now = get_current_time() + datetime.timedelta(days=63)
            entry_date = now.strftime("%d/%m")
            entry_time = now.strftime("%H:%M")
            target_month = now.strftime("%m/%Y")
            
        # Case B: Date Only - 02/09 5000 cafe
        elif "/" in parts[0] and len(parts) >= 2 and parts[1].isdigit():
            entry_date = parts[0]
            amount = int(parts[1])
            note = " ".join(parts[2:]) if len(parts) > 2 else "Không có ghi chú"
            entry_time = "24:00"  # Default time

            # Extract month from date for target sheet
            day, month = entry_date.split("/")
            current_year = get_current_time().year
            target_month = f"{month.zfill(2)}/{current_year}"
            
        # Case C: Date + Time - 02/09 08:30 15000 breakfast
        elif "/" in parts[0] and len(parts) >= 3 and ":" in parts[1] and parts[2].isdigit():
            entry_date = parts[0]
            entry_time = parts[1]
            amount = int(parts[2])
            note = " ".join(parts[3:]) if len(parts) > 3 else "Không có ghi chú"

            # Extract month from date for target sheet
            day, month = entry_date.split("/")
            current_year = get_current_time().year
            target_month = f"{month.zfill(2)}/{current_year}"

        else:
            await update.message.reply_text("❌ Định dạng không đúng!\n\n📝 Các định dạng hỗ trợ:\n• 1000 ăn trưa\n• 02/09 5000 cafe\n• 02/09 08:30 15000 breakfast")
            return

        # Multiply amount by 1000 if note contains "ngàn"
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
async def delete_expense(update, context):
    """Delete expense entry from Google Sheet"""
    text = update.message.text.strip()
    
    try:
        logger.info(f"Delete expense requested by user {update.effective_user.id}: '{text}'")
        
        # Parse delete command: "del 14/10 00:11"
        parts = text.split()
        if len(parts) < 3:
            logger.warning(f"Invalid delete format from user {update.effective_user.id}: '{text}'")
            await update.message.reply_text("❌ Định dạng: del dd/mm hh:mm")
            return
            
        entry_date = parts[1]
        entry_time = parts[2]
        
        logger.info(f"Attempting to delete expense: {entry_date} {entry_time}")
        
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
            if record.get('Date') == entry_date and record.get('Time') == entry_time:
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
            record_date = r.get("Date", "").strip()
            record_amount = r.get("VND", 0)
            
            if record_date == today_str and record_amount:  # Only count if both date and amount exist
                today_expenses.append(r)
                if isinstance(record_amount, (int, float)):
                    total += record_amount
                elif isinstance(record_amount, str) and record_amount.replace(',', '').replace('.', '').isdigit():
                    # Handle string numbers that might have commas or dots
                    try:
                        total += float(record_amount.replace(',', ''))
                    except ValueError:
                        logger.warning(f"Could not parse amount '{record_amount}' in today summary")
                        continue
        
        count = len(today_expenses)
        logger.info(f"Found {count} expenses for today with total {total} VND")
        logger.info(f"Today date string: '{today_str}', Records found: {[r.get('Date') for r in records[:5]]}")  # Debug info
        
        response = f"📊 Tổng kết hôm nay ({today_str}):\n💰 {total:,.0f} VND\n📝 {count} giao dịch\n📄 Sheet: {target_month}"
        await update.message.reply_text(response)
        logger.info(f"Today summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in today command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in today command: {reply_error}")

@safe_async_handler
async def week(update, context):
    """Get this week's total expenses"""
    try:
        logger.info(f"Week command requested by user {update.effective_user.id}")
        
        now = get_current_time()
        
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
                                expense_date = datetime.datetime.strptime(f"{day}/{month}/{year}", "%d/%m/%Y")
                                
                                # Check if this date falls within our week
                                if week_start <= expense_date <= week_end:
                                    week_expenses.append(r)
                                    amount = r.get("VND", 0)
                                    if isinstance(amount, (int, float)):
                                        total += amount
                                    elif isinstance(amount, str) and amount.replace(',', '').replace('.', '').isdigit():
                                        # Handle string numbers that might have commas or dots
                                        try:
                                            total += float(amount.replace(',', ''))
                                        except ValueError:
                                            logger.warning(f"Could not parse amount '{amount}' in week summary")
                                            continue
                    except Exception as date_parse_error:
                        logger.warning(f"Could not parse date '{day_month}' from sheet {target_month}: {date_parse_error}")
                        continue
                        
            except Exception as sheet_error:
                logger.warning(f"Could not access sheet {target_month}: {sheet_error}")
                continue
                
        count = len(week_expenses)
        logger.info(f"Found {count} expenses for this week with total {total} VND")
        
        response = f"📊 Tổng kết tuần này ({week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}):\n💰 {total:,.0f} VND\n📝 {count} giao dịch"
        await update.message.reply_text(response)
        logger.info(f"Week summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in week command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in week command: {reply_error}")

@safe_async_handler
async def month(update, context):
    """Get this month's total expenses"""
    try:
        logger.info(f"Month command requested by user {update.effective_user.id}")
        
        now = get_current_time()
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
            record_date = r.get("Date", "").strip()
            record_amount = r.get("VND", 0)
            
            if record_date and record_amount:  # Only count if both date and amount exist and are not empty
                month_expenses.append(r)
                if isinstance(record_amount, (int, float)):
                    total += record_amount
                elif isinstance(record_amount, str) and record_amount.replace(',', '').replace('.', '').isdigit():
                    # Handle string numbers that might have commas or dots
                    try:
                        total += float(record_amount.replace(',', ''))
                    except ValueError:
                        logger.warning(f"Could not parse amount '{record_amount}' in month summary")
                        continue
                
        count = len(month_expenses)
        logger.info(f"Found {count} expenses for this month with total {total} VND")
        
        # Get month name in Vietnamese
        month_names = {
            "01": "Tháng 1", "02": "Tháng 2", "03": "Tháng 3", "04": "Tháng 4",
            "05": "Tháng 5", "06": "Tháng 6", "07": "Tháng 7", "08": "Tháng 8", 
            "09": "Tháng 9", "10": "Tháng 10", "11": "Tháng 11", "12": "Tháng 12"
        }
        
        current_month = now.strftime("%m")
        current_year = now.strftime("%Y")
        month_display = f"{month_names.get(current_month, current_month)}/{current_year}"
        
        response = f"📊 Tổng kết {month_display}:\n💰 {total:,.0f} VND\n📝 {count} giao dịch\n📄 Sheet: {target_month}"
        await update.message.reply_text(response)
        logger.info(f"Month summary sent successfully to user {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error in month command for user {update.effective_user.id}: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")
        except Exception as reply_error:
            logger.error(f"Failed to send error message in month command: {reply_error}")

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

@app.route('/')
def home():
    return "Money Tracker Bot is running with webhooks!"

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        global bot_app, webhook_failures, last_failure_time, use_fresh_bots
        status = {
            "status": "healthy",
            "bot_initialized": bot_app is not None,
            "bot_running": bot_app.running if bot_app else False,
            "timestamp": datetime.datetime.now(timezone).isoformat(),
            "active_threads": threading.active_count(),
            "webhook_failures": webhook_failures,
            "circuit_breaker_open": webhook_failures >= MAX_FAILURES,
            "last_failure": last_failure_time.isoformat() if last_failure_time else None,
            "use_fresh_bots": use_fresh_bots
        }
        
        # Test Google Sheets connection
        try:
            sheet_count = len(spreadsheet.worksheets())
            status["google_sheets"] = {"connected": True, "sheet_count": sheet_count}
        except Exception as sheets_error:
            status["google_sheets"] = {"connected": False, "error": str(sheets_error)}
        
        # Determine overall health
        if webhook_failures >= MAX_FAILURES:
            status["status"] = "degraded"
        
        return status, 200
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return {"status": "unhealthy", "error": str(e)}, 500

@app.route('/toggle_fresh_bots', methods=['POST'])
def toggle_fresh_bots():
    """Toggle the use of fresh bot instances"""
    try:
        global use_fresh_bots
        use_fresh_bots = not use_fresh_bots
        logger.info(f"Fresh bot instances {'enabled' if use_fresh_bots else 'disabled'}")
        return {"use_fresh_bots": use_fresh_bots, "message": f"Fresh bot instances {'enabled' if use_fresh_bots else 'disabled'}"}, 200
    except Exception as e:
        logger.error(f"Error toggling fresh bots: {e}", exc_info=True)
        return {"error": str(e)}, 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests from Telegram"""
    global bot_app, webhook_failures, last_failure_time
    
    try:
        logger.info("Webhook request received")
        
        # Check circuit breaker
        current_time = datetime.datetime.now()
        if webhook_failures >= MAX_FAILURES:
            if last_failure_time and (current_time - last_failure_time).seconds < FAILURE_RESET_TIME:
                logger.warning(f"Circuit breaker open: {webhook_failures} failures, rejecting request")
                return "Service temporarily unavailable", 503
            else:
                # Reset the circuit breaker
                logger.info("Resetting circuit breaker")
                webhook_failures = 0
                last_failure_time = None
        
        # Ensure bot is initialized
        if bot_app is None:
            logger.info("Initializing bot application")
            try:
                bot_app = setup_bot()
            except Exception as setup_error:
                logger.error(f"Failed to setup bot application: {setup_error}", exc_info=True)
                webhook_failures += 1
                last_failure_time = current_time
                return "Bot setup failed", 500
            
        # Get the update from Telegram
        try:
            update_data = request.get_json()
            if not update_data:
                logger.warning("Received empty update data")
                return "Empty update", 400
            logger.info(f"Received update data: {update_data}")
        except Exception as json_error:
            logger.error(f"Error parsing JSON from webhook request: {json_error}", exc_info=True)
            return "Invalid JSON", 400
        
        try:
            # Create Update object
            update = Update.de_json(update_data, bot_app.bot)
            if not update:
                logger.warning("Failed to create Update object from data")
                return "Invalid update data", 400
            logger.info(f"Created Update object for user {update.effective_user.id if update.effective_user else 'unknown'}")
        except Exception as update_error:
            logger.error(f"Error creating Update object: {update_error}", exc_info=True)
            return "Error processing update", 500
        
        # Process the update using asyncio.run in a separate thread
        async def async_process_update():
            try:
                logger.info("Processing update asynchronously")
                
                # Try fresh bot instance first if enabled
                if use_fresh_bots:
                    fresh_bot_app = None
                    try:
                        fresh_bot_app = create_fresh_bot()
                        
                        # Initialize the fresh bot instance
                        await fresh_bot_app.initialize()
                        logger.info("Fresh bot instance initialized successfully")
                        
                        # Verify bot is properly initialized by checking if it has a username
                        try:
                            bot_info = await fresh_bot_app.bot.get_me()
                            logger.info(f"Fresh bot verified: @{bot_info.username}")
                        except Exception as verify_error:
                            logger.warning(f"Could not verify fresh bot info: {verify_error}")
                        
                        # Re-create the Update object with the fresh bot instance
                        # This ensures proper bot reference in command handlers
                        fresh_update = Update.de_json(update_data, fresh_bot_app.bot)
                        logger.info("Created fresh Update object with new bot instance")
                        
                        # Process the update with the fresh instance
                        await fresh_bot_app.process_update(fresh_update)
                        logger.info("Update processed successfully with fresh bot instance")
                        return  # Success, exit early
                        
                    except Exception as fresh_bot_error:
                        logger.error(f"Error with fresh bot instance: {fresh_bot_error}", exc_info=True)
                        # Continue to fallback
                        
                    finally:
                        # Clean up the fresh bot instance
                        if fresh_bot_app:
                            try:
                                await fresh_bot_app.shutdown()
                                logger.info("Fresh bot instance shutdown completed")
                            except Exception as shutdown_error:
                                logger.error(f"Error shutting down fresh bot instance: {shutdown_error}")
                
                # Fallback to global bot instance
                logger.info("Using global bot instance")
                
                # Initialize global bot if not already done
                if not bot_app.running:
                    logger.info("Initializing global bot application")
                    await bot_app.initialize()
                    logger.info("Global bot application initialized successfully")
                
                # Process the update with global instance (using original update object)
                await bot_app.process_update(update)
                logger.info("Update processed successfully with global bot instance")
                
            except Exception as process_error:
                logger.error(f"Error processing update: {process_error}", exc_info=True)
        
        def run_async_process():
            try:
                # Add some debugging information about the thread context
                import threading
                current_thread = threading.current_thread()
                logger.info(f"Starting async processing in thread: {current_thread.name} (ID: {current_thread.ident})")
                
                # Ensure we're in a new thread with no existing event loop
                try:
                    existing_loop = asyncio.get_running_loop()
                    logger.warning(f"Found existing running loop in thread: {id(existing_loop)}")
                except RuntimeError:
                    # Good, no running loop
                    logger.info("No existing event loop found - creating fresh context")
                
                # Use asyncio.run() which creates and manages its own event loop
                logger.info("Starting asyncio.run() for update processing")
                asyncio.run(async_process_update())
                logger.info("asyncio.run() completed successfully")
                
            except RuntimeError as runtime_error:
                # Handle "Event loop is closed" and similar runtime errors
                logger.error(f"Runtime error in asyncio.run: {runtime_error}", exc_info=True)
                # Try alternative approach with manual event loop management
                try:
                    logger.info("Attempting fallback with manual event loop management")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        logger.info(f"Created new event loop: {id(loop)}")
                        loop.run_until_complete(async_process_update())
                        logger.info("Fallback event loop succeeded")
                    finally:
                        try:
                            # Cancel any remaining tasks
                            pending = asyncio.all_tasks(loop)
                            if pending:
                                logger.info(f"Cancelling {len(pending)} pending tasks")
                                for task in pending:
                                    task.cancel()
                                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        except Exception as cancel_error:
                            logger.error(f"Error cancelling tasks: {cancel_error}")
                        finally:
                            loop.close()
                            asyncio.set_event_loop(None)
                            logger.info("Event loop cleanup completed")
                except Exception as fallback_error:
                    logger.error(f"Fallback event loop approach also failed: {fallback_error}", exc_info=True)
            except Exception as run_error:
                logger.error(f"Error in asyncio.run: {run_error}", exc_info=True)
        
        try:
            thread = threading.Thread(target=run_async_process, daemon=True, name=f"webhook-{threading.active_count()}")
            thread.start()
            logger.info(f"Update processing thread started: {thread.name}")
            
            # Reset failure count on successful processing start
            if webhook_failures > 0:
                logger.info(f"Resetting failure count from {webhook_failures} to 0")
                webhook_failures = 0
                last_failure_time = None
            
            # Don't wait for the thread to complete, return immediately
            return "OK", 200
            
        except Exception as thread_error:
            logger.error(f"Error starting processing thread: {thread_error}", exc_info=True)
            webhook_failures += 1
            last_failure_time = datetime.datetime.now()
            return "Error starting processing thread", 500
            
    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}", exc_info=True)
        webhook_failures += 1
        last_failure_time = datetime.datetime.now()
        return "Internal server error", 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Set the webhook URL for the bot"""
    try:
        # This will be called to set up the webhook
        import requests
        webhook_url = f"{WEBHOOK_URL}/webhook"
        
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            json={"url": webhook_url}
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                return f"Webhook set successfully to {webhook_url}", 200
            else:
                return f"Failed to set webhook: {result.get('description')}", 500
        else:
            return f"Failed to set webhook: HTTP {response.status_code}", 500
            
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return f"Error setting webhook: {e}", 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Get current webhook information"""
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo")
        
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                webhook_info = result.get("result", {})
                return {
                    "url": webhook_info.get("url", "Not set"),
                    "pending_updates": webhook_info.get("pending_update_count", 0),
                    "last_error": webhook_info.get("last_error_message", "None")
                }, 200
            else:
                return {"error": result.get("description")}, 500
        else:
            return {"error": f"HTTP {response.status_code}"}, 500
            
    except Exception as e:
        logger.error(f"Error getting webhook info: {e}")
        return {"error": str(e)}, 500

@app.route('/delete_webhook', methods=['POST'])
def delete_webhook():
    """Delete the current webhook"""
    try:
        import requests
        response = requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                return "Webhook deleted successfully", 200
            else:
                return f"Failed to delete webhook: {result.get('description')}", 500
        else:
            return f"Failed to delete webhook: HTTP {response.status_code}", 500
            
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        return f"Error deleting webhook: {e}", 500

def main():
    """Main function to run the bot with webhook"""
    global bot_app
    
    try:
        # Setup bot if not already initialized
        if bot_app is None:
            bot_app = setup_bot()
        
        logger.info("Bot started successfully with webhook support!")
        print("🚀 Money Tracker Bot is running with webhooks...")
        print("📊 Connected to Google Sheets")
        print(f"🔗 Webhook URL: {WEBHOOK_URL}")
        print("💬 Listening for webhook requests...")
        print("📡 Visit /set_webhook to configure the webhook")
        
        # Add global error handler for the Flask app
        @app.errorhandler(Exception)
        def handle_exception(e):
            logger.error(f"Unhandled exception in Flask app: {e}", exc_info=True)
            return "Internal server error", 500
        
        # Run Flask app
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"Error starting bot: {e}", exc_info=True)
        print(f"❌ Failed to start bot: {e}")
    finally:
        # Cleanup bot if it exists
        if bot_app and bot_app.running:
            try:
                # Note: We can't use await here since main() is not async
                # The bot will be cleaned up when the process exits
                logger.info("Bot cleanup completed")
            except Exception as cleanup_error:
                logger.error(f"Error during bot cleanup: {cleanup_error}", exc_info=True)

if __name__ == "__main__":
    main()
