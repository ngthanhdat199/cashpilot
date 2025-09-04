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
        
        # Message handler for expenses and delete commands
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("Bot application setup completed!")
        return bot_app
        
    except Exception as e:
        logger.error(f"Error setting up bot: {e}")
        raise

async def initialize_bot(bot_app):
    """Initialize the bot application asynchronously"""
    if not bot_app.running:
        await bot_app.initialize()
    return bot_app

# Global variable to store bot application - initialize it immediately
bot_app = None

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

🗑️ Xóa giao dịch:
• del 14/10 00:11 (xóa theo ngày + giờ)

📊 Lệnh có sẵn:
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

⏰ Chỉ định ngày + giờ:
• 02/09 08:30 25000 sáng
• 03/09 14:00 120000 trưa

📊 Lệnh thống kê:
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
            entry_time = "12:00"  # Default time when only date is provided
            
            # Parse month/year from the date
            day_month = entry_date
            now = get_current_time()
            # now = get_current_time() + datetime.timedelta(days=63)
            target_month = now.strftime("%m/%Y")
            
            # Check if different month/year
            if "/" in day_month:
                day, month = day_month.split("/")
                if len(month) == 2:  # MM format
                    target_month = f"{month}/{now.year}"
                elif len(month) == 4:  # MM/YYYY format (day is actually day/month)
                    # Handle case where user inputs DD/MM/YYYY
                    parts_date = day_month.split("/")
                    if len(parts_date) == 3:
                        target_month = f"{parts_date[1]}/{parts_date[2]}"
                        entry_date = f"{parts_date[0]}/{parts_date[1]}"
            
        # Case C: Date + Time - 02/09 08:30 15000 breakfast
        elif "/" in parts[0] and ":" in parts[1] and len(parts) >= 3 and parts[2].isdigit():
            entry_date = parts[0]
            entry_time = parts[1]
            amount = int(parts[2])
            note = " ".join(parts[3:]) if len(parts) > 3 else "Không có ghi chú"
            
            # Parse month/year from the date
            day_month = entry_date
            now = get_current_time()
            # now = get_current_time() + datetime.timedelta(days=63)
            target_month = now.strftime("%m/%Y")
            
            # Check if different month/year
            if "/" in day_month:
                day, month = day_month.split("/")
                if len(month) == 2:  # MM format
                    target_month = f"{month}/{now.year}"
                elif len(month) == 4:  # MM/YYYY format
                    parts_date = day_month.split("/")
                    if len(parts_date) == 3:
                        target_month = f"{parts_date[1]}/{parts_date[2]}"
                        entry_date = f"{parts_date[0]}/{parts_date[1]}"

        else:
            await update.message.reply_text("❌ Định dạng không hợp lệ! Vui lòng thử lại.")
            return

        # Get the appropriate monthly sheet
        current_sheet = get_or_create_monthly_sheet(target_month)

        # Append row to Google Sheet
        row = [entry_date, entry_time, amount, note]
        current_sheet.append_row(row)

        # Sort the sheet by date and time
        try:
            # Get all rows with data
            all_rows = current_sheet.get_all_records()
            
            if len(all_rows) > 1:  # Only sort if there's more than header + 1 row
                # Sort by date and time
                sorted_rows = sorted(all_rows, key=lambda x: (
                    datetime.datetime.strptime(f"{x['Ngày']}/{target_month.split('/')[1]}", "%d/%m/%Y") if x['Ngày'] else datetime.datetime.min,
                    datetime.datetime.strptime(x['Thời gian'], "%H:%M") if x['Thời gian'] else datetime.datetime.min
                ))
                
                # Clear all data rows and re-add sorted data
                if len(sorted_rows) > 0:
                    range_to_clear = f"A2:D{len(sorted_rows) + 1}"
                    current_sheet.batch_clear([range_to_clear])
                    
                    # Re-add sorted data
                    for row_data in sorted_rows:
                        current_sheet.append_row([
                            row_data['Ngày'],
                            row_data['Thời gian'],
                            row_data['VND'],
                            row_data['Ghi chú']
                        ])
        except Exception as sort_error:
            logger.warning(f"Could not sort sheet: {sort_error}")
            # Continue without sorting if there's an error

        logger.info(f"Expense logged: {amount} VND at {entry_date} {entry_time} - {note}")
        
        response = f"✅ Đã ghi: {amount:,.0f} VND\n📅 {entry_date} {entry_time}\n📝 {note}\n📄 Sheet: {target_month}"
        await update.message.reply_text(response)

    except ValueError as ve:
        logger.error(f"Value error in log_expense: {ve}")
        await update.message.reply_text("❌ Số tiền không hợp lệ! Vui lòng nhập số.")
    except Exception as e:
        logger.error(f"Error logging expense: {e}")
        await update.message.reply_text("❌ Có lỗi xảy ra! Vui lòng thử lại.")

async def delete_expense(update, context):
    """Delete expense entry from Google Sheet"""
    text = update.message.text.strip()
    
    try:
        # Parse delete command: "del 14/10 00:11"
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ Định dạng: del dd/mm hh:mm")
            return
            
        entry_date = parts[1]
        entry_time = parts[2]
        
        # Determine target month
        now = get_current_time()
        # now = get_current_time() + datetime.timedelta(days=63)
        target_month = now.strftime("%m/%Y")
        
        # Check if different month
        if "/" in entry_date:
            day, month = entry_date.split("/")
            if len(month) == 2:
                target_month = f"{month}/{now.year}"
        
        # Get the appropriate monthly sheet
        current_sheet = get_or_create_monthly_sheet(target_month)
        
        # Find and delete the matching row
        all_records = current_sheet.get_all_records()
        found = False
        
        for i, record in enumerate(all_records, start=2):  # Start from row 2 (after header)
            if record.get('Ngày') == entry_date and record.get('Thời gian') == entry_time:
                current_sheet.delete_rows(i)
                found = True
                logger.info(f"Deleted expense: {entry_date} {entry_time}")
                await update.message.reply_text(f"✅ Đã xóa giao dịch: {entry_date} {entry_time}")
                break
        
        if not found:
            await update.message.reply_text(f"❌ Không tìm thấy giao dịch: {entry_date} {entry_time}")
            
    except Exception as e:
        logger.error(f"Error deleting expense: {e}")
        await update.message.reply_text("❌ Có lỗi xảy ra khi xóa! Vui lòng thử lại.")

async def today(update, context):
    """Get today's total expenses"""
    try:
        now = get_current_time()
        # now = get_current_time() + datetime.timedelta(days=63)
        today_str = now.strftime("%d/%m")
        target_month = now.strftime("%m/%Y")
        
        current_sheet = get_or_create_monthly_sheet(target_month)
        records = current_sheet.get_all_records()
        
        today_expenses = []
        total = 0
        
        for r in records:
            if r.get("Ngày") == today_str:
                today_expenses.append(r)
                amount = r.get("VND", 0)
                if isinstance(amount, (int, float)):
                    total += amount
        
        count = len(today_expenses)
        
        response = f"📊 Tổng kết hôm nay ({today_str}):\n💰 {total:,.0f} VND\n📝 {count} giao dịch\n📄 Sheet: {target_month}"
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Error getting today's expenses: {e}")
        await update.message.reply_text("❌ Không thể lấy dữ liệu. Vui lòng thử lại!")

async def week(update, context):
    """Get this week's total expenses"""
    try:
        now = get_current_time()
        # now = get_current_time() + datetime.timedelta(days=63)
        target_month = now.strftime("%m/%Y")
        
        # Calculate week start (Monday)
        days_since_monday = now.weekday()
        week_start = now - datetime.timedelta(days=days_since_monday)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        current_sheet = get_or_create_monthly_sheet(target_month)
        records = current_sheet.get_all_records()
        
        week_expenses = []
        total = 0
        
        for r in records:
            try:
                day_month = r.get("Ngày", "")
                if "/" in day_month:
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

@app.route('/')
def home():
    return "Money Tracker Bot is running with webhooks!"

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests from Telegram"""
    global bot_app
    
    try:
        # Ensure bot is initialized
        if bot_app is None:
            bot_app = setup_bot()
            
        # Get the update from Telegram
        update_data = request.get_json()
        
        if update_data:
            # Create Update object
            update = Update.de_json(update_data, bot_app.bot)
            
            # Process the update in a new event loop
            def process_update():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Initialize bot if not already done
                    if not bot_app.running:
                        loop.run_until_complete(bot_app.initialize())
                    
                    # Process the update
                    loop.run_until_complete(bot_app.process_update(update))
                finally:
                    loop.close()
            
            thread = threading.Thread(target=process_update)
            thread.start()
            
        return "OK", 200
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "Error", 500

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
        
        # Run Flask app
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        print(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    main()
