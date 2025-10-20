from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import MenuButtonCommands, BotCommand
from src.track_py.const import TELEGRAM_TOKEN
from src.track_py.utils.logger import logger
from src.track_py.webhook.handlers import start, help, today, week, month, gas, food, dating, other, investment, handle_message, freelance, income, salary, sort, ai_analyze

# Initialize bot application immediately
async def setup_bot():
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
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help info"),
        ]
        await bot_app.bot.set_my_commands(commands)
        await bot_app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

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
