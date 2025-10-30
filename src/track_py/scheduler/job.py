from apscheduler.schedulers.background import BackgroundScheduler
from src.track_py.config import config
from src.track_py.utils.sheet import get_or_create_monthly_sheet
from src.track_py.utils.logger import logger
from src.track_py.utils.bot import send_message
from src.track_py.utils.timezone import get_current_time
import atexit
from dateutil.relativedelta import relativedelta
import asyncio

scheduler = BackgroundScheduler(timezone=config["settings"]["timezone"])
trigger_day = config["scheduler"].get("trigger_day")
scheduler_id = config["scheduler"].get("id")
scheduler_name = config["scheduler"].get("name")


def start_scheduler():
    """Initialize and start the background scheduler"""
    try:
        # Add the monthly sheet creation job
        # Runs every 25th (config) of the month at midnight (00:00)
        scheduler.add_job(
            func=monthly_sheet_job,
            trigger="cron",
            day=trigger_day,
            hour=0,
            minute=0,
            id=scheduler_id,
            name=scheduler_name,
            replace_existing=True,
        )

        # Add a manual trigger endpoint job for testing
        # This can be removed in production if not needed
        logger.info(
            f"🔧 Scheduled monthly sheet creation for {trigger_day} of each month at midnight"
        )

        scheduler.start()
        logger.info("🚀 Background scheduler started successfully")

        # Register shutdown handler
        atexit.register(lambda: scheduler.shutdown())

    except Exception as e:
        logger.error(f"💥 Failed to start scheduler: {e}", exc_info=True)


def monthly_sheet_job():
    """Wrapper function to call the create_next_month_sheet"""
    try:
        sheet_title = create_next_month_sheet()
        asyncio.run(send_message(f"✅ *Đã tạo bảng theo dõi cho tháng {sheet_title}*"))
        return True

    except Exception as e:
        logger.error(f"💥 Error executing monthly sheet job: {e}", exc_info=True)
        asyncio.run(
            send_message(text=f"❌ *Không thể tạo bảng cho tháng {sheet_title}*")
        )
        return False


def create_next_month_sheet():
    """
    Automated task to create next month's Google Sheet
    Runs on the 25th (config) of each month at midnight
    """
    try:
        logger.info("🕛 Starting automated monthly sheet creation")

        # Get current time
        now = get_current_time()

        # Calculate next month
        next_month = now + relativedelta(months=1)
        next_month_str = next_month.strftime("%m/%Y")

        logger.info(f"📅 Current month: {now.strftime('%m/%Y')}")
        logger.info(f"📅 Creating sheet for next month: {next_month_str}")

        # Create or get the sheet for next month
        sheet = get_or_create_monthly_sheet(next_month_str)
        if sheet:
            logger.info(f"✅ Successfully created/verified sheet: {next_month_str}")
            logger.info(f"📋 Sheet title: {sheet.title}")
            logger.info(f"🔢 Sheet ID: {sheet.id}")
            return next_month_str
        else:
            logger.error(f"❌ Failed to create sheet for {next_month_str}")

    except Exception as e:
        logger.error(
            f"💥 Error in automated monthly sheet creation: {e}", exc_info=True
        )
        return next_month_str
