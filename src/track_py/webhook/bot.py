from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import MenuButtonCommands, BotCommand
from src.track_py.const import TELEGRAM_TOKEN, CATEGORY_ICONS
from src.track_py.utils.logger import logger
from src.track_py.webhook.handlers import (
    start,
    help,
    today,
    week,
    month,
    gas,
    food,
    dating,
    other,
    investment,
    handle_message,
    freelance,
    income,
    salary,
    sort,
    ai_analyze,
    stats,
    categories,
)


# Initialize bot application immediately
def setup_bot():
    """Setup the bot application (synchronous part only)"""
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
        bot_app.add_handler(CommandHandler(["stats", "stat"], stats))
        bot_app.add_handler(CommandHandler(["categories", "cat"], categories))

        # Message handler for expenses and delete commands
        bot_app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
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
            BotCommand("start", f"{CATEGORY_ICONS['start']} Start the bot"),
            BotCommand("help", f"{CATEGORY_ICONS['help']} Show help info"),
            BotCommand("today", f"{CATEGORY_ICONS['today']} Show today's expense"),
            BotCommand("week", f"{CATEGORY_ICONS['week']} Show this week's expenses"),
            BotCommand(
                "month", f"{CATEGORY_ICONS['month']} Show this month's expenses"
            ),
            BotCommand("gas", f"{CATEGORY_ICONS['gas']} Show gas expense"),
            BotCommand("food", f"{CATEGORY_ICONS['food']} Show food expense"),
            BotCommand("dating", f"{CATEGORY_ICONS['dating']} Show dating expense"),
            BotCommand("other", f"{CATEGORY_ICONS['other']} Show other expense"),
            BotCommand(
                "investment", f"{CATEGORY_ICONS['investment']} Show investment strategy"
            ),
            BotCommand(
                "freelance", f"{CATEGORY_ICONS['freelance']} Add freelance income"
            ),
            BotCommand("salary", f"{CATEGORY_ICONS['salary']} Add salary income"),
            BotCommand("income", f"{CATEGORY_ICONS['income']} Show income details"),
            BotCommand("sort", f"{CATEGORY_ICONS['sort']} Sort expenses"),
            BotCommand("ai", f"{CATEGORY_ICONS['ai']} Analyze expenses with AI"),
            BotCommand("stats", f"{CATEGORY_ICONS['stats']} Show expense statistics"),
            BotCommand(
                "categories", f"{CATEGORY_ICONS['categories']} Show expense categories"
            ),
        ]
        await bot_app.bot.set_my_commands(commands)
        await bot_app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

        logger.info("Bot commands and menu setup completed!")

    except Exception as e:
        logger.error(f"Error setting up bot commands: {e}")
        raise
