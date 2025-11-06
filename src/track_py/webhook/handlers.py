from telegram import (
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    Update,
)
from telegram.ext import CallbackContext
import asyncio
from src.track_py.const import MONTH_NAMES, HELP_MSG
from src.track_py.utils.logger import logger
import src.track_py.utils.sheet as sheet
import src.track_py.const as const
from src.track_py.utils.category import get_categories_response
import src.track_py.utils.bot as bot


def safe_async_handler(handler_func):
    """Decorator to ensure handlers run in a safe async context"""

    async def wrapper(update: Update, context: CallbackContext):
        try:
            # Get information about the current async context
            try:
                current_loop = asyncio.get_running_loop()
                logger.debug(
                    f"Handler {handler_func.__name__} running in loop: {id(current_loop)}"
                )

                if current_loop.is_closed():
                    logger.error(
                        f"Current event loop is closed in {handler_func.__name__}"
                    )
                    raise RuntimeError("Event loop is closed")

            except RuntimeError as loop_error:
                logger.error(
                    f"Event loop issue in {handler_func.__name__}: {loop_error}"
                )
                # Try to send a basic error message without using the problematic loop
                try:
                    await update.message.reply_text(
                        f"❌ Có lỗi hệ thống xảy ra. Vui lòng thử lại!\n\nLỗi: {loop_error}"
                    )
                except:
                    pass
                return

            # Execute the actual handler
            return await handler_func(update, context)

        except Exception as e:
            logger.error(
                f"Error in safe_async_handler for {handler_func.__name__}: {e}",
                exc_info=True,
            )
            try:
                # Try to send error message, but don't fail if this also fails
                await update.message.reply_text(
                    f"❌ Có lỗi hệ thống xảy ra. Vui lòng thử lại sau!\n\nLỗi: {e}"
                )
            except Exception as reply_error:
                logger.error(
                    f"Failed to send error message in {handler_func.__name__}: {reply_error}"
                )

    wrapper.__name__ = handler_func.__name__
    return wrapper


@safe_async_handler
async def start(update: Update, context: CallbackContext):
    """Send welcome message when bot starts"""
    try:
        logger.info(f"Start command requested by user {update.effective_user.id}")
        keyboard = [
            ["/today", "/week", "/month", "/month -1", "/sort"],
            ["/gas", "/food", "/other", "/dating"],
            ["/investment", "/investment -1"],
            ["/income", "/income -1"],
            ["/fl", "/sl", "/ai"],
            ["/help"],
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(HELP_MSG, reply_markup=reply_markup)
        logger.info(
            f"Welcome message + keyboard sent successfully to user {update.effective_user.id}"
        )

    except Exception as e:
        logger.error(
            f"Error in start command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi khởi động. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in start command 12: {reply_error}"
            )


@safe_async_handler
async def help(update: Update, context: CallbackContext):
    """Show help message"""
    try:
        logger.info(f"Help command requested by user {update.effective_user.id}")
        await update.message.reply_text(HELP_MSG)
        logger.info(
            f"Help message sent successfully to user {update.effective_user.id}"
        )

    except Exception as e:
        logger.error(
            f"Error in help for user {update.effective_user.id}: {e}", exc_info=True
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi hiển thị hướng dẫn. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(f"Failed to send error message in help: {reply_error}")


@safe_async_handler
async def log_expense(update: Update, context: CallbackContext):
    """Log expense to Google Sheet with smart date/time parsing - Enhanced UX with Progressive Loading

    Features:
    - Instant acknowledgment with estimated time
    - Queue position tracking for multiple requests
    - Progress updates for batch operations
    - Real-time completion feedback with timing
    - Enhanced error messages with retry guidance
    """
    text = update.message.text.strip()
    parts = text.split()

    try:
        logger.info(
            f"Log expense requested by user {update.effective_user.id}: '{text}'"
        )

        # Quick shortcuts for common expenses
        shortcuts = const.SHORTCUTS

        # Parse different input formats
        entry_date = None
        entry_time = None
        entry_year = None
        amount = None
        note = ""
        target_month = None

        # Case A: Default Entry (No Date/Time) - 1000 ăn trưa or 5 cf or just "5"
        if parts[0].isdigit():
            amount = int(parts[0])
            raw_note = " ".join(parts[1:])

            # Apply shortcuts to note
            note_parts = raw_note.split()
            expanded_parts = []
            for part in note_parts:
                expanded_parts.append(shortcuts.get(part.lower(), part))
            note = " ".join(expanded_parts)

            entry_date = sheet.get_current_time().strftime("%d/%m")
            entry_time = sheet.get_current_time().strftime("%H:%M:%S")
            entry_year = sheet.get_current_time().year
            target_month = sheet.get_current_time().strftime("%m/%Y")

        # Case B: Date Only - 02/09 5000 cafe or 02/09 5 cf
        elif "/" in parts[0] and len(parts) >= 2 and parts[1].isdigit():
            entry_date = sheet.normalize_date(parts[0])
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
            entry_year = sheet.get_current_time().year
            target_month = f"{month}/{entry_year}"

        # Case C: Date + Time - 02/09 08:30 15000 breakfast or 02/09 08:30 15 cf
        elif (
            "/" in parts[0]
            and len(parts) >= 3
            and (":" in parts[1] or "h" in parts[1].lower())
            and parts[2].isdigit()
        ):
            entry_date = sheet.normalize_date(parts[0])
            entry_time = sheet.normalize_time(parts[1])
            entry_year = sheet.get_current_time().year
            amount = int(parts[2])
            raw_note = " ".join(parts[3:]) if len(parts) > 3 else "Không có ghi chú"

            # Apply shortcuts to note
            note_parts = raw_note.split()
            expanded_parts = []
            for part in note_parts:
                expanded_parts.append(shortcuts.get(part.lower(), part))
            note = " ".join(expanded_parts)

            day, month = entry_date.split("/")
            current_year = sheet.get_current_time().year
            target_month = f"{month}/{current_year}"

        else:
            await update.message.reply_text(const.LOG_EXPENSE_MSG)
            return

        # Smart amount multipliers for faster typing
        amount = amount * 1000

        logger.info(
            f"Parsed expense: {amount} VND on {entry_date} {entry_time} - {note} (sheet: {target_month})"
        )

        # ENHANCED PRELOADING: Send immediate response with better loading UX
        response = (
            f"⚡ *Đã ghi nhận {const.LOG_ACTION}!*\n"
            f"💰 {amount:,} VND\n"
            f"📝 {note}\n"
            f"📅 {entry_date} • {entry_time}\n\n"
            f"🔄 *Đang đồng bộ với Google Sheets...*\n"
        )
        sent_message = await update.message.reply_text(response, parse_mode="Markdown")

        # Start background task to actually log to Google Sheets
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message_id = sent_message.message_id  # Store message ID for editing later

        # Get bot token reliably
        try:
            bot_token = context.bot.token
        except Exception:
            # Fallback to config token
            bot_token = const.TELEGRAM_TOKEN

        # Create background task (fire and forget) but ensure it can complete
        task = asyncio.create_task(
            bot.background_log_expense(
                entry_date,
                entry_time,
                entry_year,
                amount,
                note,
                target_month,
                user_id,
                chat_id,
                bot_token,
                message_id,
            )
        )

        # Add task to background tasks set for tracking
        bot._background_tasks.add(task)
        task.add_done_callback(bot._background_tasks.discard)

        logger.info(
            f"Background logging task created for expense: {amount} VND - {note} at {entry_date} {entry_time}"
        )

    except ValueError as ve:
        await update.message.reply_text(
            "❌ Lỗi định dạng số tiền!\n\n📝 Các định dạng hỗ trợ:\n• 1000 ăn trưa\n• 02/09 5000 cafe\n• 02/09 08:30 15000 breakfast"
        )
    except Exception as e:
        logger.error(f"Error in log_expense parsing: {e}")
        await update.message.reply_text(
            f"❌ Có lỗi xảy ra. Vui lòng thử lại!\n\nLỗi: {e}"
        )


@safe_async_handler
async def delete_expense(update: Update, context: CallbackContext):
    """Delete expense entry from Google Sheet"""
    text = update.message.text.strip()

    try:
        logger.info(
            f"Delete expense requested by user {update.effective_user.id}: '{text}'"
        )

        parts = text.split()
        # Only "del 00h11s00" -> assume today's date
        if len(parts) == 2:
            entry_date = sheet.get_current_time().strftime("%d/%m")
            entry_time = sheet.normalize_time(parts[1])
        # Parse delete command: "del 14/10 00h11s00"
        elif len(parts) >= 3:
            entry_date = sheet.normalize_date(parts[1])
            entry_time = sheet.normalize_time(parts[2])
            logger.info(f"Attempting to delete expense: {entry_date} {entry_time}")
        else:
            await update.message.reply_text(const.DELETE_EXPENSE_MSG)
            return

        # Determine target month
        now = sheet.get_current_time()
        target_month = sheet.get_current_time().strftime("%m/%Y")

        # Check if different month
        if "/" in entry_date:
            day, month = entry_date.split("/")
            if len(month) == 2:
                target_month = f"{month}/{now.year}"

        logger.info(f"Target sheet: {target_month}")

        response = (
            f"🔄 *Đã ghi nhận {const.DELETE_ACTION}*\n"
            f"📅 {entry_date} • {entry_time}\n\n"
            f"📊 *Đang đồng bộ với Google Sheets...*\n"
        )
        sent_message = await update.message.reply_text(response, parse_mode="Markdown")

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message_id = sent_message.message_id  # Store message ID for editing later

        # Get bot token reliably
        try:
            bot_token = context.bot.token
        except Exception:
            # Fallback to config token
            bot_token = const.TELEGRAM_TOKEN

        # Create background task (fire and forget) but ensure it can complete
        task = asyncio.create_task(
            bot.background_delete_expense(
                entry_date,
                entry_time,
                target_month,
                user_id,
                chat_id,
                bot_token,
                message_id,
            )
        )

        # Add task to background tasks set for tracking
        bot._background_tasks.add(task)
        task.add_done_callback(bot._background_tasks.discard)

    except Exception as e:
        logger.error(
            f"Error in delete_expense for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi xóa! Vui lòng thử lại.\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in delete_expense 12: {reply_error}"
            )


@safe_async_handler
async def handle_message(update: Update, context: CallbackContext):
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
        logger.error(
            f"Error in handle_message for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi xử lý tin nhắn. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in handle_message: {reply_error}"
            )


@safe_async_handler
async def sort(update: Update, context: CallbackContext):
    """Manually sort sheet data when needed (can be called periodically with /sort command)"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.sort_expenses_by_date(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Sorted sheet data successfully for user {update.effective_user.id}"
        )
    except Exception as sort_error:
        logger.error(f"Error sorting sheet data: {sort_error}")
        await update.message.reply_text(f"❌ Có lỗi khi sắp xếp sheet: {sort_error}")
        return

    except Exception as e:
        logger.error(f"Error sorting sheet data: {e}")
        await update.message.reply_text(f"❌ Có lỗi khi sắp xếp dữ liệu: {e}")


@safe_async_handler
async def today(update: Update, context: CallbackContext):
    """Get today's total expenses"""
    try:
        response = await sheet.process_today_summary()
        await update.message.reply_text(response)

        logger.info(
            f"Today summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in today command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in today command 1: {reply_error}"
            )


@safe_async_handler
async def week(update: Update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.process_week_summary(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Week summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(f"Error in week command: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
        )


@safe_async_handler
async def month(update: Update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = sheet.process_month_summary(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Month summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in month command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in month command: {reply_error}"
            )


@safe_async_handler
async def ai_analyze(update: Update, context: CallbackContext):
    """Get this month's total expenses with AI analysis"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.get_ai_analyze_summary(offset)
        await update.message.reply_text(response, parse_mode="HTML")

        logger.info(
            f"Month summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in month command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in month command: {reply_error}"
            )


@safe_async_handler
async def gas(update: Update, context: CallbackContext):
    """Get this month's total gas expenses"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.process_gas_summary(offset)
        await update.message.reply_text(response)

        logger.info(f"Gas summary sent successfully to user {update.effective_user.id}")
    except Exception as e:
        logger.error(
            f"Error in gas command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(f"Failed to send error message in gas command: {reply_error}")


@safe_async_handler
async def food(update: Update, context: CallbackContext):
    """Get this month's total food expenses"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.process_food_summary(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Food summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in food command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(f"Failed to send error message in food command: {reply_error}")


@safe_async_handler
async def dating(update: Update, context: CallbackContext):
    """Get this month's total dating expenses"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.process_dating_summary(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Dating summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in dating command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(f"Failed to send error message in food command: {reply_error}")


@safe_async_handler
async def other(update: Update, context: CallbackContext):
    """Get this month's total other expenses"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.process_other_summary(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Other summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in other command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in other command: {reply_error}"
            )


@safe_async_handler
async def investment(update: Update, context: CallbackContext):
    """Get this month's total investment expenses"""
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    try:
        response = await sheet.get_investment_response(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Investment summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in investment command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in investment command: {reply_error}"
            )


@safe_async_handler
# 200
async def freelance(update: Update, context: CallbackContext):
    args = context.args
    offset = 0
    amount = 0

    if args:
        if len(args) == 1:
            # Single argument: /fl 200 -> offset=0, amount=200
            try:
                amount = int(args[0])
                offset = 0
            except ValueError:
                await update.message.reply_text(
                    "❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương."
                )
                return
        elif len(args) >= 2:
            # Two arguments: /fl 1 200 -> offset=1, amount=200
            try:
                offset = int(args[0])
            except ValueError:
                offset = 0
            amount = int(args[1])
    else:
        await update.message.reply_text(
            "❌ Vui lòng cung cấp số tiền thu nhập. Ví dụ: '/fl 200'"
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương."
        )
        return

    try:
        response = sheet.process_freelance(offset, amount)
        await update.message.reply_text(response)

        logger.info(
            f"Freelance income of {amount} VND logged successfully for user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in freelance command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi ghi nhận thu nhập. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in freelance command: {reply_error}"
            )


@safe_async_handler
# 200
async def salary(update: Update, context: CallbackContext):
    args = context.args
    offset = 0
    amount = 0

    if args:
        if len(args) == 1:
            # Single argument: /sl 2000 -> offset=0, amount=2000
            try:
                amount = int(args[0])
                offset = 0
            except ValueError:
                await update.message.reply_text(
                    "❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương."
                )
                return
        elif len(args) >= 2:
            # Two arguments: /sl 1 2000 -> offset=1, amount=2000
            try:
                offset = int(args[0])
            except ValueError:
                offset = 0
            amount = int(args[1])
    else:
        await update.message.reply_text(
            "❌ Vui lòng cung cấp số tiền thu nhập. Ví dụ: '/sl 200' hoặc '/sl 1 200'"
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ Số tiền không hợp lệ. Vui lòng nhập số nguyên dương."
        )
        return

    try:
        response = sheet.process_salary(offset, amount)
        await update.message.reply_text(response)

        logger.info(
            f"Salary income of {amount} VND logged successfully for user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in salary command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi ghi nhận thu nhập. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in salary command: {reply_error}"
            )


@safe_async_handler
async def income(update: Update, context: CallbackContext):
    args = context.args
    offset = 0
    if args:
        try:
            offset = int(args[0])
        except ValueError:
            pass

    """Show total income from sheet"""
    try:
        response = await sheet.process_income_summary(offset)
        await update.message.reply_text(response)

        logger.info(
            f"Income summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in income command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Có lỗi xảy ra khi lấy dữ liệu thu nhập. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in income command: {reply_error}"
            )


@safe_async_handler
async def stats(update: Update, context: CallbackContext):
    """Show dashboard link"""
    dashboard_webapp = WebAppInfo(url="https://track-money-ui.vercel.app/")
    keyboard = [[InlineKeyboardButton("📊 Mở Dashboard", web_app=dashboard_webapp)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Biểu đồ thu nhập 🚀", reply_markup=reply_markup)


@safe_async_handler
async def categories(update: Update, context):
    """Show expense categories"""
    try:
        response = await get_categories_response()
        await update.message.reply_text(response, parse_mode="MarkdownV2")

        logger.info(
            f"Categories list sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in categories command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy danh mục chi tiêu. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in categories command: {reply_error}"
            )
        return


@safe_async_handler
async def sync_config(update: Update, context: CallbackContext):
    """Sync configuration to Google Sheets of next month"""
    try:
        response = sheet.sync_config_to_sheet()
        await update.message.reply_text(response, parse_mode="Markdown")

        logger.info(
            f"Config sync completed successfully for user {update.effective_user.id}"
        )

    except Exception as e:
        logger.error(
            f"Error in sync_config command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể đồng bộ cấu hình. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in sync_config command: {reply_error}"
            )


@safe_async_handler
async def list_keywords(update: Update, context: CallbackContext):
    """List all keywords from constants"""
    try:
        response = sheet.get_keywords_response()
        await update.message.reply_text(response, parse_mode="MarkdownV2")

        logger.info(
            f"Keywords list sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in list_keywords command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy danh sách từ khóa. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in list_keywords command: {reply_error}"
            )


@safe_async_handler
async def list_assets(update: Update, context: CallbackContext):
    """Show total assets"""
    try:
        response = await sheet.get_assets_response()
        await update.message.reply_text(response, parse_mode="Markdown")

        logger.info(
            f"Assets summary sent successfully to user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in assets command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể lấy dữ liệu tài sản. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in assets command: {reply_error}"
            )


@safe_async_handler
async def migrate_assets(update: Update, context: CallbackContext):
    """Migrate assets data to new format"""
    try:
        result = sheet.migrate_assets_data()
        await update.message.reply_text(result, parse_mode="Markdown")

        logger.info(
            f"Assets migration completed successfully for user {update.effective_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Error in migrate_assets command for user {update.effective_user.id}: {e}",
            exc_info=True,
        )
        try:
            await update.message.reply_text(
                f"❌ Không thể di chuyển dữ liệu tài sản. Vui lòng thử lại!\n\nLỗi: {e}"
            )
        except Exception as reply_error:
            logger.error(
                f"Failed to send error message in migrate_assets command: {reply_error}"
            )
