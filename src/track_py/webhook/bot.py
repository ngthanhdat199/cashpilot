from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import MenuButtonCommands
from src.track_py.const import TELEGRAM_TOKEN
from src.track_py.utils.logger import logger
from src.track_py.webhook.handlers import start, help, today, week, month, gas, food, dating, other, investment, handle_message, freelance, income, salary, sort, ai_analyze

# Initialize bot application immediately
def setup_bot():
    """Setup the bot application"""
    try:
        bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Command handlers
        bot_app.add_handler(CommandHandler(["start", "st"], start))
        bot_app.add_handler(CommandHandler(["help", "h"], help))
        bot_app.add_handler(CommandHandler(["today", "t"], today))
        bot_app.add_handler(CommandHandler(["week", "w"], week))
        bot_app.add_handler(CommandHandler(["month", "m"], month))
        bot_app.add_handler(CommandHandler(["gas", "g"], gas))
        bot_app.add_handler(CommandHandler(["food", "f"], food))
        bot_app.add_handler(CommandHandler(["dating", "d"], dating))
        bot_app.add_handler(CommandHandler(["other", "o"], other))
        bot_app.add_handler(CommandHandler(["investment", "i"], investment))
        bot_app.add_handler(CommandHandler(["freelance", "fl"], freelance))
        bot_app.add_handler(CommandHandler(["salary", "sl"], salary))
        bot_app.add_handler(CommandHandler(["income", "inc"], income))
        bot_app.add_handler(CommandHandler(["sort", "s"], sort))
        bot_app.add_handler(CommandHandler(["ai", "a"], ai_analyze))

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

        # Set custom menu button
        bot_app.bot.set_chat_menu_button(menu_button=MenuButtonCommands(
            text="Commands",
            command_list=[
                "/start - Bắt đầu sử dụng bot",
                "/help - Xem hướng dẫn sử dụng",
                "/today - Xem chi tiêu hôm nay",
                "/week - Xem chi tiêu tuần này",
                "/month - Xem chi tiêu tháng này",
                "/gas - Thêm chi tiêu xăng xe",
                "/food - Thêm chi tiêu ăn uống",
                "/dating - Thêm chi tiêu hẹn hò",
                "/other - Thêm chi tiêu khác",
                "/investment - Thêm thu nhập đầu tư",
                "/freelance - Thêm thu nhập freelance",
                "/salary - Thêm thu nhập lương",
                "/income - Xem tổng thu nhập",
                "/sort - Sắp xếp chi tiêu",
                "/ai - Phân tích chi tiêu bằng AI"
            ]
        ))
        
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
