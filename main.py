from telegram.ext import Application, MessageHandler, CommandHandler, filters
import gspread
from google.oauth2.service_account import Credentials
import datetime
import os
import logging
import json
import pytz
from flask import Flask
from threading import Thread

# Flask web server for keep-alive
app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run():
    app.run(host='0.0.0.0', port=8080)

# Start Flask server in background thread
Thread(target=run).start()

# Load configuration
try:
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=getattr(logging, config["settings"]["logging_level"]))
    logger.info("Configuration loaded successfully")
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
    creds = Credentials.from_service_account_file(config["google_sheets"]["credentials_file"], scopes=scope)
    client = gspread.authorize(creds)
    # Open the specific Google Sheet by ID from the URL
    spreadsheet = client.open_by_key(config["google_sheets"]["spreadsheet_id"])
    logger.info("Google Sheets connected successfully")
except Exception as e:
    logger.error(f"Failed to connect to Google Sheets: {e}")
    print("⚠️  Please make sure you have:")
    print(f"1. Created {config['google_sheets']['credentials_file']} file")
    print(f"2. Shared the Google Sheet (ID: {config['google_sheets']['spreadsheet_id']}) with your service account email")
    print("3. The sheet has the correct permissions")
    exit(1)

# Telegram bot
TOKEN = config["telegram"]["bot_token"]

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
                    logger.info(f"Copying from template sheet")
                    
                    # Create new sheet by duplicating the template
                    new_sheet = template_sheet.duplicate(new_sheet_name=sheet_name)
                    
                    # Clear only the data rows, keep headers and formatting
                    # Get all values to identify where data starts (after headers)
                    all_values = new_sheet.get_all_values()
                    
                    if len(all_values) > 1:  # If there's more than just headers
                        # Clear data from row 2 onwards (keep row 1 as headers)
                        range_to_clear = f"A2:Z{len(all_values)}"
                        new_sheet.batch_clear([range_to_clear])
                    
                    logger.info(f"Created new sheet from template: {sheet_name}")
                    return new_sheet
                    
                except gspread.WorksheetNotFound:
                    logger.warning("Template sheet not found, creating basic sheet")
                    # Create a basic sheet if template doesn't exist
                    new_sheet = spreadsheet.add_worksheet(title=sheet_name, rows="100", cols="10")
                    
                    # Add basic headers
                    headers = ["Ngày", "Thời gian", "VND", "Ghi chú"]
                    new_sheet.append_row(headers)
                    
                    logger.info(f"Created basic sheet: {sheet_name}")
                    return new_sheet
                    
            except Exception as e:
                logger.error(f"Error creating sheet {sheet_name}: {e}")
                # Fallback to first available sheet
                return spreadsheet.sheet1
                
    except Exception as e:
        logger.error(f"Error in get_or_create_monthly_sheet: {e}")
        # Fallback to default sheet
        return spreadsheet.sheet1

async def start(update, context):
    """Send welcome message when bot starts"""
    welcome_msg = """
👋 Chào mừng đến với Money Tracker Bot!

📝 Các định dạng hỗ trợ:
• 1000 ăn trưa (thời gian hiện tại)
• 02/09 5000 cafe (ngày cụ thể, 12:00)  
• 02/09 08:30 15000 breakfast (ngày + giờ)

�️ Xóa giao dịch:
• del 14/10 00:11 (xóa theo ngày + giờ)

�📊 Lệnh có sẵn:
• /today - Xem tổng chi tiêu hôm nay
• /week - Xem tổng chi tiêu tuần này
• /help - Xem hướng dẫn

Bot sẽ tự động sắp xếp theo thời gian! 🕐💰
    """
    await update.message.reply_text(welcome_msg)

async def help_command(update, context):
    """Show help message"""
    help_msg = """
📖 Hướng dẫn sử dụng Money Tracker Bot:

💰 Các định dạng ghi chi tiêu:

🔸 Mặc định (thời gian hiện tại):
• 45000 ăn sáng
• 200000 mua áo

🔸 Chỉ định ngày (12:00 mặc định):
• 02/09 15000 cà phê
• 05/09 80000 ăn tối

� Chỉ định ngày + giờ:
• 02/09 08:30 25000 sáng
• 03/09 14:00 120000 trưa

�📊 Lệnh thống kê:
• /today - Chi tiêu hôm nay
• /week - Chi tiêu tuần này

🤖 Bot tự động sắp xếp theo thời gian!
    """
    await update.message.reply_text(help_msg)

async def log_expense(update, context):
    """Log expense to Google Sheet with smart date/time parsing"""
    text = update.message.text.strip()
    parts = text.split()

    try:
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

        # Get or create the target month's sheet
        sheet = get_or_create_monthly_sheet(target_month)
        
        # Find the correct position to insert the record
        all_values = sheet.get_all_values()
        insert_row = len(all_values) + 1  # Default to append at end
        
        # Skip header row and find correct position based on date/time
        if len(all_values) > 1:
            for i, row in enumerate(all_values[1:], start=2):  # Start from row 2 (after headers)
                if len(row) >= 2:
                    existing_date = row[0].strip()
                    existing_time = row[1].strip()
                    
                    if existing_date and existing_time:
                        # Compare dates first, then times
                        if entry_date < existing_date or (entry_date == existing_date and entry_time < existing_time):
                            insert_row = i
                            break
        
        # Insert the record at the correct position
        if insert_row <= len(all_values):
            # Insert at specific position
            sheet.insert_row([entry_date, entry_time, amount, note], insert_row)
            position_msg = f"📍 Vị trí: Dòng {insert_row}"
        else:
            # Append at the end
            sheet.append_row([entry_date, entry_time, amount, note])
            position_msg = "📍 Vị trí: Cuối bảng"

        response = f"✅ Đã ghi nhận:\n💰 {amount:,} VND\n📝 {note}\n🕐 {entry_date} {entry_time}\n{position_msg}\n📊 Sheet: {target_month}"
        await update.message.reply_text(response)
        
        logger.info(f"Logged expense: {amount} VND - {note} at {entry_date} {entry_time} (row {insert_row}) in sheet {target_month}")
        
    except ValueError as ve:
        await update.message.reply_text("❌ Lỗi định dạng số tiền!\n\n📝 Các định dạng hỗ trợ:\n• 1000 ăn trưa\n• 02/09 5000 cafe\n• 02/09 08:30 15000 breakfast")
    except Exception as e:
        logger.error(f"Error logging expense: {e}")
        await update.message.reply_text("❌ Có lỗi xảy ra. Vui lòng thử lại!")

async def delete_expense(update, context):
    """Delete expense from Google Sheet"""
    text = update.message.text.strip()
    
    # Remove "del " prefix
    if text.lower().startswith("del "):
        text = text[4:].strip()
    
    parts = text.split()

    try:
        entry_date = None
        entry_time = None
        target_month = None
        
        # Parse delete format: del 14/10 00:11 6000 cafe
        # We only need date and time to find the entry
        if len(parts) >= 2 and "/" in parts[0] and ":" in parts[1]:
            entry_date = parts[0]
            entry_time = parts[1]
            
            # Extract month from date for target sheet
            day, month = entry_date.split("/")
            current_year = get_current_time().year
            target_month = f"{month.zfill(2)}/{current_year}"
            
        else:
            await update.message.reply_text("❌ Định dạng xóa không đúng!\n\n📝 Định dạng: del 14/10 00:11\n(Chỉ cần ngày và giờ để tìm và xóa)")
            return

        # Get the target month's sheet
        try:
            sheet = get_or_create_monthly_sheet(target_month)
        except:
            await update.message.reply_text(f"❌ Không tìm thấy sheet tháng {target_month}")
            return
        
        # Find and delete the matching entry
        all_values = sheet.get_all_values()
        deleted_row = None
        deleted_entry = None
        
        # Search through all rows (skip header)
        if len(all_values) > 1:
            for i, row in enumerate(all_values[1:], start=2):  # Start from row 2 (after headers)
                if len(row) >= 4:  # Ensure we have all columns
                    existing_date = row[0].strip()
                    existing_time = row[1].strip()
                    
                    # Check for exact match on date and time
                    if existing_date == entry_date and existing_time == entry_time:
                        deleted_entry = {
                            'date': existing_date,
                            'time': existing_time,
                            'amount': row[2],
                            'note': row[3]
                        }
                        deleted_row = i
                        break
        
        if deleted_row:
            # Delete the row
            sheet.delete_rows(deleted_row)
            
            response = f"🗑️ Đã xóa:\n📅 {deleted_entry['date']} {deleted_entry['time']}\n💰 {deleted_entry['amount']} VND\n📝 {deleted_entry['note']}\n📊 Sheet: {target_month}"
            await update.message.reply_text(response)
            
            logger.info(f"Deleted expense: {deleted_entry['amount']} VND at {deleted_entry['date']} {deleted_entry['time']} from sheet {target_month}")
            
        else:
            await update.message.reply_text(f"❌ Không tìm thấy giao dịch:\n📅 {entry_date} {entry_time}\n📊 Sheet: {target_month}\n\n💡 Kiểm tra lại ngày và giờ chính xác!")
        
    except Exception as e:
        logger.error(f"Error deleting expense: {e}")
        await update.message.reply_text("❌ Có lỗi xảy ra khi xóa. Vui lòng thử lại!")

async def today(update, context):
    """Show today's total expenses"""
    try:
        now = get_current_time()
        # now = get_current_time() + datetime.timedelta(days=63)
        today_day_month = now.strftime("%d/%m")
        
        # Get current month's sheet
        sheet = get_or_create_monthly_sheet()
        records = sheet.get_all_records()
        
        # Filter records for today based on day/month in column B
        today_expenses = []
        total = 0
        
        for r in records:
            # Check if the record matches today's day/month
            record_day_month = str(r.get("Ngày", "")).strip()  # Column B
            amount = r.get("VND", 0)  # Column D
            
            if record_day_month == today_day_month:
                today_expenses.append(r)
                if isinstance(amount, (int, float)):
                    total += amount
        
        count = len(today_expenses)
        
        if count == 0:
            await update.message.reply_text(f"📊 Hôm nay ({today_day_month}):\n💰 Chưa có chi tiêu nào\n📄 Sheet: {now.strftime('%m/%Y')}")
        else:
            response = f"📊 Tổng kết hôm nay ({today_day_month}):\n💰 {total:,.0f} VND\n📝 {count} giao dịch\n📄 Sheet: {now.strftime('%m/%Y')}"
            await update.message.reply_text(response)
            
    except Exception as e:
        logger.error(f"Error getting today's expenses: {e}")
        await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")

async def week(update, context):
    """Show this week's total expenses"""
    try:
        now = datetime.datetime.now()
        # now = datetime.datetime.now() + datetime.timedelta(days=63)
        week_start = now - datetime.timedelta(days=now.weekday())
        
        # Get current month's sheet
        sheet = get_or_create_monthly_sheet()
        records = sheet.get_all_records()
        week_expenses = []
        total = 0
        
        for r in records:
            try:
                # Parse day/month from column B and add current year
                day_month = r.get("Ngày", "")
                if day_month:
                    expense_date = datetime.datetime.strptime(f"{day_month}/{now.year}", "%d/%m/%Y")
                    if expense_date >= week_start:
                        week_expenses.append(r)
                        amount = r.get("VND", 0)
                        if isinstance(amount, (int, float)):
                            total += amount
            except:
                continue
                
        count = len(week_expenses)
        
        response = f"📊 Tổng kết tuần này:\n💰 {total:,.0f} VND\n📝 {count} giao dịch\n📄 Sheet: {now.strftime('%m/%Y')}"
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Error getting week's expenses: {e}")
        await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")

async def handle_message(update, context):
    """Route messages to appropriate handlers"""
    text = update.message.text.strip()
    
    if text.lower().startswith("del "):
        await delete_expense(update, context)
    else:
        await log_expense(update, context)

def main():
    """Main function to run the bot"""
    try:
        app = Application.builder().token(TOKEN).build()
        
        # Command handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("today", today))
        app.add_handler(CommandHandler("week", week))
        # Removed month command as requested
        
        # Message handler for expenses and delete commands
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("Bot started successfully!")
        print("🚀 Money Tracker Bot is running...")
        print("📊 Connected to Google Sheets")
        print("💬 Listening for messages...")
        print("Press Ctrl+C to stop the bot")
        
        # Run the bot
        app.run_polling()
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        print(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    main()
