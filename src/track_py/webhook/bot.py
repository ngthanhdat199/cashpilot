from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import MenuButtonCommands, BotCommand
import src.track_py.const as const
from src.track_py.utils.logger import logger
import src.track_py.webhook.handlers as handlers


# Initialize bot application immediately
def setup_bot():
    """Setup the bot application (synchronous part only)"""
    try:
        bot_app = Application.builder().token(const.TELEGRAM_TOKEN).build()

        # Command handlers
        bot_app.add_handler(CommandHandler(["start", "st"], handlers.start))
        bot_app.add_handler(CommandHandler(["help", "h"], handlers.help))
        bot_app.add_handler(CommandHandler(["today", "t"], handlers.today))
        bot_app.add_handler(CommandHandler(["week", "w"], handlers.week))
        bot_app.add_handler(CommandHandler(["month", "m"], handlers.month))
        bot_app.add_handler(CommandHandler(["gas", "g"], handlers.gas))
        bot_app.add_handler(CommandHandler(["food", "f"], handlers.food))
        bot_app.add_handler(CommandHandler(["dating", "d"], handlers.dating))
        bot_app.add_handler(CommandHandler(["other", "o"], handlers.other))
        bot_app.add_handler(CommandHandler(["investment", "i"], handlers.investment))
        bot_app.add_handler(CommandHandler(["freelance", "fl"], handlers.freelance))
        bot_app.add_handler(CommandHandler(["salary", "sl"], handlers.salary))
        bot_app.add_handler(CommandHandler(["income", "inc"], handlers.income))
        bot_app.add_handler(CommandHandler(["sort", "s"], handlers.sort))
        bot_app.add_handler(CommandHandler(["ai", "a"], handlers.ai_analyze))
        bot_app.add_handler(CommandHandler(["stats", "stat"], handlers.stats))
        bot_app.add_handler(CommandHandler(["categories", "cat"], handlers.categories))
        bot_app.add_handler(CommandHandler(["sync", "sync"], handlers.sync_config))
        bot_app.add_handler(CommandHandler(["keywords", "kw"], handlers.list_keywords))
        bot_app.add_handler(CommandHandler(["assets", "as"], handlers.assets))

        # Message handler for expenses and delete commands
        bot_app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message)
        )

        # Add error handler to prevent "No error handlers are registered" warnings
        async def error_handler(update, context):
            """Global error handler for main bot instance"""
            logger.error(
                f"Error in main bot instance: {context.error}", exc_info=context.error
            )
            if update and update.effective_message:
                try:
                    await update.effective_message.reply_text(
                        "❌ Có lỗi xảy ra. Vui lòng thử lại!"
                    )
                except Exception as reply_error:
                    logger.error(f"Failed to send error message: {reply_error}")

        bot_app.add_error_handler(error_handler)

        logger.info("Bot application setup completed!")
        return bot_app

    except Exception as e:
        logger.error(f"Error setting up bot: {e}")
        raise


async def setup_bot_commands(bot_app):
    """Setup bot commands and menu (async part)"""
    try:
        # Set custom menu button
        commands = [
            BotCommand("start", f"{const.CATEGORY_ICONS['start']} Start the bot"),
            BotCommand("help", f"{const.CATEGORY_ICONS['help']} Show help info"),
            BotCommand(
                "today", f"{const.CATEGORY_ICONS['today']} Show today's expense"
            ),
            BotCommand(
                "week", f"{const.CATEGORY_ICONS['week']} Show this week's expenses"
            ),
            BotCommand(
                "month", f"{const.CATEGORY_ICONS['month']} Show this month's expenses"
            ),
            BotCommand("gas", f"{const.CATEGORY_ICONS['gas']} Show gas expense"),
            BotCommand("food", f"{const.CATEGORY_ICONS['food']} Show food expense"),
            BotCommand(
                "dating", f"{const.CATEGORY_ICONS['dating']} Show dating expense"
            ),
            BotCommand("other", f"{const.CATEGORY_ICONS['other']} Show other expense"),
            BotCommand(
                "investment",
                f"{const.CATEGORY_ICONS['investment']} Show investment strategy",
            ),
            BotCommand(
                "freelance", f"{const.CATEGORY_ICONS['freelance']} Add freelance income"
            ),
            BotCommand("salary", f"{const.CATEGORY_ICONS['salary']} Add salary income"),
            BotCommand(
                "income", f"{const.CATEGORY_ICONS['income']} Show income details"
            ),
            BotCommand("sort", f"{const.CATEGORY_ICONS['sort']} Sort expenses"),
            BotCommand("ai", f"{const.CATEGORY_ICONS['ai']} Analyze expenses with AI"),
            BotCommand(
                "stats", f"{const.CATEGORY_ICONS['stats']} Show expense statistics"
            ),
            BotCommand(
                "categories",
                f"{const.CATEGORY_ICONS['categories']} Show expense categories",
            ),
            BotCommand(
                "sync",
                f"{const.CATEGORY_ICONS['sync']} Sync config with sheet of next month",
            ),
            BotCommand(
                "keywords", f"{const.CATEGORY_ICONS['keywords']} List all keywords"
            ),
            BotCommand(
                "assets", f"{const.CATEGORY_ICONS['asset']} Show assets summary"
            ),
        ]
        await bot_app.bot.set_my_commands(commands)
        await bot_app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

        logger.info("Bot commands and menu setup completed!")

    except Exception as e:
        logger.error(f"Error setting up bot commands: {e}")
        raise
