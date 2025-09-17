from telegram.ext import Application, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from const import TOKEN
from utils.logger import logger
from handlers import start, help, today, week, month, gas, handle_message, handle_quick_expense

# Initialize bot application immediately
def setup_bot():
    """Setup the bot application"""
    try:
        bot_app = Application.builder().token(TOKEN).build()
        
        # Command handlers
        bot_app.add_handler(CommandHandler(["start", "s"], start))
        bot_app.add_handler(CommandHandler(["help", "h"], help))
        bot_app.add_handler(CommandHandler(["today", "t"], today))
        bot_app.add_handler(CommandHandler(["week", "w"], week))
        bot_app.add_handler(CommandHandler(["month", "m"], month))
        bot_app.add_handler(CommandHandler(["gas", "g"], gas))

        # Callback handler for quick expense buttons
        bot_app.add_handler(CallbackQueryHandler(handle_quick_expense))

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
        fresh_app.add_handler(CommandHandler(["start", "s"], start))
        fresh_app.add_handler(CommandHandler(["help", "h"], help))
        fresh_app.add_handler(CommandHandler(["today", "t"], today))
        fresh_app.add_handler(CommandHandler(["week", "w"], week))
        fresh_app.add_handler(CommandHandler(["month", "m"], month))
        fresh_app.add_handler(CommandHandler(["gas", "g"], gas))
        fresh_app.add_handler(CallbackQueryHandler(handle_quick_expense))
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
