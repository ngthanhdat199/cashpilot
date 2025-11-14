import asyncio
import time
from telegram import Bot
from collections import defaultdict, deque
from src.track_py.utils.logger import logger
import src.track_py.utils.sheet as sheet
import src.track_py.const as const
from src.track_py.config import config
import src.track_py.utils.sheet.asset as asset
import re

# Background expense logging queue for better performance
log_expense_queue = deque()
delete_expense_queue = deque()
get_expense_queue = deque()
_log_queue_processor_running = False
_delete_queue_processor_running = False
_get_queue_processor_running = False
_background_tasks = set()  # Keep track of background tasks


async def wait_for_background_tasks(timeout=30) -> bool:
    """Wait for all background tasks (log + delete + get) to complete before shutdown"""
    if (
        not _background_tasks
        and not log_expense_queue
        and not delete_expense_queue
        and not get_expense_queue
    ):
        logger.info("No background tasks to wait for")
        return True

    logger.info(
        f"Waiting for {len(_background_tasks)} background tasks, "
        f"{len(log_expense_queue)} log queue, {len(delete_expense_queue)} delete queue, "
        f"and {len(get_expense_queue)} get queue to complete..."
    )

    start_time = time.time()
    while (
        _background_tasks
        or log_expense_queue
        or delete_expense_queue
        or get_expense_queue
    ) and (time.time() - start_time) < timeout:
        await asyncio.sleep(0.1)

    if (
        _background_tasks
        or log_expense_queue
        or delete_expense_queue
        or get_expense_queue
    ):
        logger.warning(
            f"Timeout waiting for background tasks. "
            f"Remaining: {len(_background_tasks)} tasks, "
            f"{len(log_expense_queue)} log, {len(delete_expense_queue)} delete, "
            f"{len(get_expense_queue)} get"
        )
        return False
    else:
        logger.info("✅ All background tasks completed successfully")
        return True


async def process_log_expense_queue() -> None:
    """Process expenses from queue in batches for better API efficiency"""
    global _log_queue_processor_running

    if _log_queue_processor_running:
        return

    _log_queue_processor_running = True

    try:
        while log_expense_queue:
            # Get up to 5 expenses to process in batch
            batch = []
            for _ in range(min(5, len(log_expense_queue))):
                if log_expense_queue:
                    batch.append(log_expense_queue.popleft())

            if not batch:
                break

            # Group by target_month for batch processing
            grouped_by_month = defaultdict(list)
            for expense_data in batch:
                target_month = expense_data["target_month"]
                grouped_by_month[target_month].append(expense_data)

            # Process each month's expenses
            for target_month, expenses in grouped_by_month.items():
                try:
                    await process_log_month_expenses(target_month, expenses)
                except Exception as month_error:
                    logger.error(
                        f"Error processing expenses for month {target_month}: {month_error}"
                    )
                    # Send error notifications for this month's expenses
                    for expense_data in expenses:
                        await send_error_notification(
                            expense_data, month_error, const.LOG_ACTION
                        )

            # Small delay between batches to avoid overwhelming the API
            await asyncio.sleep(0.5)

    except Exception as queue_error:
        logger.error(f"Error in expense queue processor: {queue_error}")
    finally:
        _log_queue_processor_running = False


async def process_delete_expense_queue() -> None:
    """Process expenses from queue in batches for better API efficiency"""
    global _delete_queue_processor_running

    if _delete_queue_processor_running:
        return

    _delete_queue_processor_running = True

    try:
        while delete_expense_queue:
            # Get up to 5 expenses to process in batch
            batch = []
            for _ in range(min(5, len(delete_expense_queue))):
                if delete_expense_queue:
                    batch.append(delete_expense_queue.popleft())

            if not batch:
                break

            # Group by target_month for batch processing
            grouped_by_month = defaultdict(list)
            for expense_data in batch:
                target_month = expense_data["target_month"]
                grouped_by_month[target_month].append(expense_data)

            # Process each month's expenses
            for target_month, expenses in grouped_by_month.items():
                try:
                    await process_delete_month_expenses(target_month, expenses)
                except Exception as month_error:
                    logger.error(
                        f"Error processing delete expenses for month {target_month}: {month_error}"
                    )
                    # Send error notifications for this month's expenses
                    for expense_data in expenses:
                        await send_error_notification(
                            expense_data, month_error, const.DELETE_ACTION
                        )

            # Small delay between batches to avoid overwhelming the API
            await asyncio.sleep(0.5)

    except Exception as queue_error:
        logger.error(f"Error in delete expense queue processor: {queue_error}")
    finally:
        _delete_queue_processor_running = False


async def process_get_expense_queue() -> None:
    """Process get expense requests from queue"""
    global _get_queue_processor_running

    if _get_queue_processor_running:
        return

    _get_queue_processor_running = True

    try:
        while get_expense_queue:
            # Process one request at a time for get expense operations
            if not get_expense_queue:
                break

            request_data = get_expense_queue.popleft()
            handler_type = request_data["handler_type"]
            offset = request_data.get("offset", 0)
            user_id = request_data["user_id"]
            chat_id = request_data["chat_id"]
            bot_token = request_data["bot_token"]
            message_id = request_data["message_id"]
            start_time = request_data.get("timestamp", time.time())
            handler_display = const.HANDLER_ACTIONS.get(handler_type, handler_type)

            try:
                # Send progress update
                progress_message = (
                    f"⚡ *Đã ghi nhận xem {handler_display}!*\n"
                    f"🔄 *Đang lấy dữ liệu...*\n"
                    f"📊 *Đang đồng bộ với Google Sheets...*\n"
                )
                try:
                    notification_bot = Bot(token=bot_token)
                    await notification_bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=progress_message,
                        parse_mode="Markdown",
                    )
                except Exception as progress_error:
                    logger.warning(f"Could not send progress update: {progress_error}")

                # Call appropriate sheet function based on handler type
                response = None
                parse_mode = "Markdown"

                if handler_type == "today":
                    response = await sheet.process_today_summary()
                elif handler_type == "week":
                    response = await sheet.process_week_summary(offset)
                elif handler_type == "month":
                    # process_month_summary is not async, so wrap it
                    response = await asyncio.to_thread(
                        sheet.process_month_summary, offset
                    )
                elif handler_type == "assets":
                    response = await sheet.get_assets_response()
                    # Assets uses MarkdownV2 and needs escaping
                    parse_mode = "MarkdownV2"
                    escaped_response = escape_markdown_v2(response)
                    response = f"```{escaped_response}```"
                else:
                    raise ValueError(f"Unknown handler type: {handler_type}")

                # Send success notification with response
                elapsed_time = time.time() - start_time
                try:
                    notification_bot = Bot(token=bot_token)
                    # Add response time to the message if it's not already there
                    # For Markdown mode, append time at the end
                    if parse_mode == "Markdown":
                        response_with_time = (
                            f"{response}\n⚡ _Hoàn thành trong {elapsed_time:.1f}s_"
                        )
                    else:
                        # For MarkdownV2 (assets), keep original response as it's already formatted
                        response_with_time = response

                    await notification_bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=response_with_time,
                        parse_mode=parse_mode,
                    )
                    logger.info(
                        f"✅ Successfully sent {handler_type} response to user {user_id} in {elapsed_time:.1f}s"
                    )
                except Exception as send_error:
                    logger.error(f"Failed to send response message: {send_error}")
                    # Fallback: send new message
                    try:
                        fallback_bot = Bot(token=bot_token)
                        # Add response time to fallback message too
                        if parse_mode == "Markdown":
                            fallback_response = f"{response}\n\n⚡ _Hoàn thành trong {elapsed_time:.1f}s_"
                        else:
                            fallback_response = response
                        await fallback_bot.send_message(
                            chat_id=chat_id,
                            text=fallback_response,
                            parse_mode=parse_mode,
                        )
                    except Exception as fallback_error:
                        logger.error(f"Fallback message also failed: {fallback_error}")

            except Exception as process_error:
                logger.error(
                    f"Error processing get expense request for user {user_id}, handler_type={handler_type}: {process_error}",
                    exc_info=True,
                )
                # Send error notification
                try:
                    error_bot = Bot(token=bot_token)
                    error_message = (
                        f"❌ *Lỗi khi lấy dữ liệu*\n\n"
                        f"⚠️ *Lỗi:* `{str(process_error)}`\n\n"
                        f"💡 _Vui lòng thử lại hoặc liên hệ admin_"
                    )
                    await error_bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=error_message,
                        parse_mode="Markdown",
                    )
                except Exception as error_notify_error:
                    logger.error(
                        f"Failed to send error notification: {error_notify_error}"
                    )
                    # Fallback: send new error message
                    try:
                        fallback_bot = Bot(token=bot_token)
                        await fallback_bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ Lỗi khi lấy dữ liệu: {str(process_error)}",
                        )
                    except Exception as fallback_error:
                        logger.error(
                            f"Fallback error message also failed: {fallback_error}"
                        )

            # Small delay between requests to avoid overwhelming the API
            await asyncio.sleep(0.3)

    except Exception as queue_error:
        logger.error(f"Error in get expense queue processor: {queue_error}")
    finally:
        _get_queue_processor_running = False


async def process_log_month_expenses(target_month: str, expenses: list[dict]) -> None:
    """Process all expenses for a specific month"""
    try:
        logger.info(f"Processing log expenses for month: {target_month}")

        # Send progress update if processing takes longer than expected
        for expense_data in expenses:
            progress_message = (
                f"⚡ *Đã ghi nhận {const.LOG_ACTION}!*\n"
                f"💰 {expense_data['amount']:,} VND\n"
                f"📝 {expense_data['note']}\n"
                f"📅 {expense_data['entry_date']} • {expense_data['entry_time']}\n\n"
                f"📊 *Đang xử lý batch ({len(expenses)} giao dịch)...*\n"
                f"⏳ _Kết nối Google Sheets thành công_"
            )
            await send_progress_update(expense_data, progress_message)

        # Get sheet once for all expenses in this month
        current_sheet = await asyncio.to_thread(
            sheet.get_cached_worksheet, target_month
        )
        logger.info(f"Got sheet for month {target_month}: {current_sheet.title}")

        asset_sheet = await asyncio.to_thread(
            sheet.get_cached_worksheet, config["settings"]["assets_sheet_name"]
        )
        logger.info(f"Got asset sheet: {asset_sheet.title}")

        # Prepare all rows for batch append
        rows_to_append = []
        assets_to_append = []

        # Prepare asset prices once
        prices = asset.prepare_prices()

        for expense_data in expenses:
            row = [
                expense_data["entry_date"],
                expense_data["entry_time"],
                int(expense_data["amount"]),
                expense_data["note"],
            ]
            rows_to_append.append(row)

            # Check if this expense should also be logged to asset sheet
            note = expense_data["note"].lower()
            if sheet.has_keyword(note, const.LONG_INVEST_KEYWORDS) or sheet.has_keyword(
                note, const.OPPORTUNITY_INVEST_KEYWORDS
            ):
                logger.info(f"Logging asset expense for note: {expense_data}")
                asset_row = sheet.prepare_asset_to_append(expense_data, prices)
                assets_to_append.append(asset_row)

        # Batch append all rows at once (more efficient than individual appends)
        if len(rows_to_append) == 1:
            # Single expense - use append_row
            await asyncio.to_thread(
                lambda: current_sheet.append_row(
                    rows_to_append[0], value_input_option="RAW", table_range="A2:D"
                )
            )
        else:
            # Multiple expenses - use batch append
            await asyncio.to_thread(
                lambda: current_sheet.append_rows(
                    rows_to_append, value_input_option="RAW", table_range="A2:D"
                )
            )

        # Also log to asset sheet if applicable
        if assets_to_append:
            await asyncio.to_thread(
                lambda: asset_sheet.append_row(
                    assets_to_append[0], value_input_option="RAW", table_range="A2:D"
                )
            )
        else:
            await asyncio.to_thread(
                lambda: asset_sheet.append_rows(
                    assets_to_append, value_input_option="RAW", table_range="A2:D"
                )
            )

        # Invalidate cache since we've updated the sheet
        sheet.invalidate_sheet_cache(target_month)

        logger.info(f"Batch processed {len(expenses)} expenses for {target_month}")

        # Send success notifications after sheet operations complete
        for expense_data in expenses:
            try:
                await send_success_notification(expense_data, const.LOG_ACTION)
            except Exception as notification_error:
                logger.warning(
                    f"Failed to send success notification: {notification_error}"
                )

        logger.info(f"Background processing completed for {len(expenses)} expenses")

    except Exception as process_error:
        logger.error(f"Error processing month {target_month} expenses: {process_error}")
        raise


async def process_delete_month_expenses(
    target_month: str, expenses: list[dict]
) -> None:
    """Process all expenses for a specific month"""
    try:
        logger.info(f"Processing delete expenses for month: {target_month}")

        # Send progress update if processing takes longer than expected
        for expense_data in expenses:
            progress_message = (
                f"⚡ *Đã ghi nhận {const.DELETE_ACTION}!*\n"
                f"📅 {expense_data['entry_date']} • {expense_data['entry_time']}\n\n"
                f"📊 *Đang xử lý batch ({len(expenses)} giao dịch)...*\n"
                f"⏳ _Kết nối Google Sheets thành công_"
            )
            await send_progress_update(expense_data, progress_message)

        # Get sheet once for all expenses in this month
        current_sheet = await asyncio.to_thread(
            sheet.get_cached_worksheet, target_month
        )
        logger.info(f"Got sheet for month {target_month}: {current_sheet.title}")

        # Process each delete request
        for expense_data in expenses:
            entry_date = expense_data["entry_date"]
            entry_time = expense_data["entry_time"]

            try:
                # Get all sheet data to search for the expense
                all_values = await asyncio.to_thread(
                    sheet.get_cached_sheet_data, target_month
                )
                if not all_values or len(all_values) < 2:
                    logger.warning(f"No data in sheet {target_month} for deletion")
                    await send_error_notification(
                        expense_data,
                        "Không có dữ liệu trong sheet này",
                        const.DELETE_ACTION,
                    )
                    continue
                records = sheet.convert_values_to_records(all_values)

                found_row = None
                for i, r in enumerate(records):
                    row_date = r["date"]
                    row_time = r["time"]
                    row_amount = sheet.parse_amount(r["vnd"])
                    row_note = r["note"]
                    expense_data["amount"] = int(row_amount)
                    expense_data["note"] = row_note

                    if row_date == entry_date and row_time == entry_time:
                        found_row = (
                            i + 2
                        )  # +2 because records start from row 2 (header is row 1)
                        break

                if found_row:
                    # Delete the row from the sheet
                    await asyncio.to_thread(
                        lambda: current_sheet.delete_rows(found_row)
                    )
                    logger.info(
                        f"Successfully deleted expense: {entry_date} {entry_time} from row {found_row}"
                    )
                else:
                    logger.warning(f"Expense not found: {entry_date} {entry_time}")
                    await send_error_notification(
                        expense_data,
                        f"Không tìm thấy giao dịch: {entry_date} {entry_time}",
                        const.DELETE_ACTION,
                    )
                    continue

            except Exception as delete_error:
                logger.error(
                    f"Error deleting expense {entry_date} {entry_time}: {delete_error}",
                    exc_info=True,
                )
                await send_error_notification(
                    expense_data, f"Lỗi khi xóa: {delete_error}", const.DELETE_ACTION
                )
                continue

        # Invalidate cache since we've updated the sheet
        sheet.invalidate_sheet_cache(target_month)

        logger.info(f"Batch processed {len(expenses)} expenses for {target_month}")

        # Send success notifications after sheet operations complete
        for expense_data in expenses:
            try:
                await send_success_notification(expense_data, const.DELETE_ACTION)
            except Exception as notification_error:
                logger.warning(
                    f"Failed to send success notification: {notification_error}"
                )

        logger.info(f"Background processing completed for {len(expenses)} expenses")

    except Exception as process_error:
        logger.error(f"Error processing month {target_month} expenses: {process_error}")
        raise


async def send_success_notification(expense_data, action: str) -> None:
    """Edit original message to show success after background processing completes"""
    try:
        # Edit the original message to show success
        bot_token = expense_data.get("bot_token")
        if bot_token and expense_data.get("message_id"):
            notification_bot = Bot(token=bot_token)

            success_message = (
                f"✅ *Đã {action} thành công!*\n"
                f"💰 {expense_data['amount']:,} VND\n"
                f"📝 {expense_data['note']}\n"
                f"📅 {expense_data['entry_date']} • {expense_data['entry_time']}\n\n"
                f"📊 _Đã đồng bộ với Google Sheets_\n"
                f"⚡ _Hoàn thành trong {time.time() - expense_data.get('timestamp', time.time()):.1f}s_"
            )

            await notification_bot.edit_message_text(
                chat_id=expense_data["chat_id"],
                message_id=expense_data["message_id"],
                text=success_message,
                parse_mode="Markdown",
            )
            logger.info(f"✅ Success message edited for user {expense_data['user_id']}")
        else:
            logger.warning(
                "No bot token or message ID available for success notification"
            )

    except Exception as msg_error:
        logger.warning(f"Could not edit success message: {msg_error}")
        # Fallback: send new message if editing fails
        try:
            if expense_data.get("bot_token"):

                fallback_bot = Bot(token=expense_data["bot_token"])
                await fallback_bot.send_message(
                    chat_id=expense_data["chat_id"],
                    text=f"✅ Đã lưu thành công: {expense_data['amount']:,} VND - {expense_data['note']}",
                )
        except Exception as fallback_error:
            logger.error(f"Fallback notification also failed: {fallback_error}")

    except Exception as msg_error:
        logger.warning(f"Could not send success notification: {msg_error}")


async def send_error_notification(expense_data, error: str, action: str) -> None:
    """Edit original message to show error if processing fails"""
    try:
        # Edit the original message to show error
        bot_token = expense_data.get("bot_token")
        if bot_token and expense_data.get("message_id"):
            notification_bot = Bot(token=bot_token)

            error_message = (
                f"❌ *Lỗi khi {action}*\n"
                f"💰 {expense_data['amount']:,} VND\n"
                f"📝 {expense_data['note']}\n"
                f"📅 {expense_data['entry_date']} • {expense_data['entry_time']}\n\n"
                f"⚠️ *Lỗi:* `{error}`\n\n"
                f"� _Vui lòng thử lại hoặc liên hệ admin_\n"
                f"💡 _Tip: Kiểm tra kết nối mạng và thử lại_"
            )

            await notification_bot.edit_message_text(
                chat_id=expense_data["chat_id"],
                message_id=expense_data["message_id"],
                text=error_message,
                parse_mode="Markdown",
            )
            logger.info(f"❌ Error message edited for user {expense_data['user_id']}")
        else:
            logger.warning(
                "No bot token or message ID available for error notification"
            )
            # Fallback: send new message if editing fails
            if expense_data.get("bot_token"):
                fallback_bot = Bot(token=expense_data["bot_token"])
                await fallback_bot.send_message(
                    chat_id=expense_data["chat_id"],
                    text=f"❌ Lỗi: {expense_data['amount']:,} VND - {expense_data['note']} - {error}",
                )

    except Exception as notify_error:
        logger.error(f"Failed to send error notification: {notify_error}")


async def send_progress_update(expense_data, progress_message: str) -> None:
    """Send intermediate progress update to improve UX for longer operations"""
    try:
        bot_token = expense_data.get("bot_token")
        if bot_token and expense_data.get("message_id"):
            notification_bot = Bot(token=bot_token)
            await notification_bot.edit_message_text(
                chat_id=expense_data["chat_id"],
                message_id=expense_data["message_id"],
                text=progress_message,
                parse_mode="Markdown",
            )
            logger.debug(f"Progress update sent for user {expense_data['user_id']}")

    except Exception as progress_error:
        logger.warning(f"Could not send progress update: {progress_error}")


async def send_message(text: str, parse_mode: str = "Markdown") -> None:
    """Utility to send message via bot token"""
    try:
        bot = Bot(token=const.TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=const.CHAT_ID,
            text=text,
            parse_mode=parse_mode,
        )
        logger.info(f"Message sent to chat {const.CHAT_ID}")
    except Exception as send_error:
        logger.error(f"Failed to send message to chat {const.CHAT_ID}: {send_error}")


async def background_log_expense(
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
) -> None:
    """Background task to queue expense for processing"""
    try:
        # Add expense to queue
        expense_data = {
            "entry_date": entry_date,
            "entry_time": entry_time,
            "entry_year": entry_year,
            "amount": amount,
            "note": note,
            "target_month": target_month,
            "user_id": user_id,
            "chat_id": chat_id,
            "bot_token": bot_token,  # Store bot token instead of bot instance
            "message_id": message_id,  # Store message ID for editing
            "timestamp": time.time(),
        }

        log_expense_queue.append(expense_data)
        queue_position = len(log_expense_queue)
        logger.info(
            f"Queued expense: {amount} VND - {note} for user {user_id}. Queue size: {queue_position}"
        )

        # Send queue position update if there are multiple items waiting
        if queue_position > 1:
            queue_update_message = (
                f"⚡ *Đã ghi nhận {const.LOG_ACTION}!*\n"
                f"💰 {amount:,} VND\n"
                f"📝 {note}\n"
                f"📅 {entry_date} • {entry_time}\n\n"
                f"📋 *Vị trí trong hàng đợi: #{queue_position}*\n"
                f"⏳ _Ước tính: {queue_position * 2}-{queue_position * 3} giây_"
            )
            try:
                queue_bot = Bot(token=bot_token)
                await queue_bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=queue_update_message,
                    parse_mode="Markdown",
                )
            except Exception as queue_msg_error:
                logger.warning(
                    f"Could not send queue position update: {queue_msg_error}"
                )

        # Start queue processor if not running and keep track of the task
        # Use asyncio.create_task with explicit loop to ensure task survives bot shutdown
        try:
            current_loop = asyncio.get_running_loop()
            task = current_loop.create_task(process_log_expense_queue())
            _background_tasks.add(task)
            # Remove the task from the set when it's done to prevent memory leak
            task.add_done_callback(lambda t: _background_tasks.discard(t))
            logger.info("Background expense processor task started successfully")
        except Exception as task_error:
            logger.error(f"Failed to create background task: {task_error}")
            # Fallback: try to process synchronously
            await process_log_expense_queue()

    except Exception as bg_error:
        logger.error(
            f"Background expense queueing failed for user {user_id}: {bg_error}",
            exc_info=True,
        )
        expense_data = {
            "amount": amount,
            "note": note,
            "entry_date": entry_date,
            "entry_time": entry_time,
            "chat_id": chat_id,
            "bot_token": bot_token,
        }
        await send_error_notification(expense_data, bg_error, const.LOG_ACTION)


async def background_delete_expense(
    entry_date, entry_time, target_month, user_id, chat_id, bot_token, message_id
) -> None:
    """Background task to delete expense from processing queue"""
    try:
        # Add expense to queue
        expense_data = {
            "entry_date": entry_date,
            "entry_time": entry_time,
            "target_month": target_month,
            "user_id": user_id,
            "chat_id": chat_id,
            "bot_token": bot_token,  # Store bot token instead of bot instance
            "message_id": message_id,  # Store message ID for editing
            "timestamp": time.time(),
        }

        delete_expense_queue.append(expense_data)
        queue_position = len(delete_expense_queue)
        logger.info(
            f"Queued expense deletion for user {user_id}. Queue size: {queue_position}"
        )

        # Send queue position update if there are multiple items waiting
        if queue_position > 1:
            queue_update_message = (
                f"⚡ *Đã ghi nhận {const.DELETE_ACTION}!*\n"
                f"📅 {entry_date} • {entry_time}\n\n"
                f"📋 *Vị trí trong hàng đợi: #{queue_position}*\n"
                f"⏳ _Ước tính: {queue_position * 2}-{queue_position * 3} giây_"
            )
            try:
                queue_bot = Bot(token=bot_token)
                await queue_bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=queue_update_message,
                    parse_mode="Markdown",
                )
            except Exception as queue_msg_error:
                logger.warning(
                    f"Could not send queue position update: {queue_msg_error}"
                )

        # Start queue processor if not running and keep track of the task
        # Use asyncio.create_task with explicit loop to ensure task survives bot shutdown
        try:
            current_loop = asyncio.get_running_loop()
            task = current_loop.create_task(process_delete_expense_queue())
            _background_tasks.add(task)
            # Remove the task from the set when it's done to prevent memory leak
            task.add_done_callback(lambda t: _background_tasks.discard(t))
            logger.info("Background delete expense processor task started successfully")
        except Exception as task_error:
            logger.error(f"Failed to create background task: {task_error}")
            # Fallback: try to process synchronously
            await process_delete_expense_queue()

    except Exception as bg_error:
        logger.error(
            f"Background expense queueing failed for user {user_id}: {bg_error}",
            exc_info=True,
        )
        expense_data = {
            "entry_date": entry_date,
            "entry_time": entry_time,
            "chat_id": chat_id,
            "bot_token": bot_token,
        }
        await send_error_notification(expense_data, bg_error, const.DELETE_ACTION)


async def background_get_expense(
    handler_type: str,
    user_id: int,
    chat_id: int,
    bot_token: str,
    message_id: int,
    offset: int = 0,
) -> None:
    """Background task to queue get expense request for processing"""
    try:
        # Add request to queue
        request_data = {
            "handler_type": handler_type,
            "offset": offset,
            "user_id": user_id,
            "chat_id": chat_id,
            "bot_token": bot_token,
            "message_id": message_id,
            "timestamp": time.time(),
        }

        get_expense_queue.append(request_data)
        queue_position = len(get_expense_queue)
        logger.info(
            f"Queued get expense request: handler_type={handler_type}, offset={offset} for user {user_id}. Queue size: {queue_position}"
        )

        # Determine handler display name
        handler_display = const.HANDLER_ACTIONS.get(handler_type, handler_type)

        # Send queue position update if there are multiple items waiting
        if queue_position > 1:
            queue_update_message = (
                f"⚡ *Đã ghi nhận xem {handler_display}!*\n"
                f"📋 *Vị trí trong hàng đợi: #{queue_position}*\n"
                f"⏳ _Ước tính: {queue_position * 2}-{queue_position * 3} giây_"
            )
            try:
                queue_bot = Bot(token=bot_token)
                await queue_bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=queue_update_message,
                    parse_mode="Markdown",
                )
            except Exception as queue_msg_error:
                logger.warning(
                    f"Could not send queue position update: {queue_msg_error}"
                )

        # Start queue processor if not running and keep track of the task
        try:
            current_loop = asyncio.get_running_loop()
            task = current_loop.create_task(process_get_expense_queue())
            _background_tasks.add(task)
            # Remove the task from the set when it's done to prevent memory leak
            task.add_done_callback(lambda t: _background_tasks.discard(t))
            logger.info("Background get expense processor task started successfully")
        except Exception as task_error:
            logger.error(f"Failed to create background task: {task_error}")
            # Fallback: try to process synchronously
            await process_get_expense_queue()

    except Exception as bg_error:
        logger.error(
            f"Background get expense queueing failed for user {user_id}, handler_type={handler_type}: {bg_error}",
            exc_info=True,
        )
        # Send error notification
        try:
            error_bot = Bot(token=bot_token)
            error_message = (
                f"❌ *Lỗi khi lấy dữ liệu*\n\n"
                f"⚠️ *Lỗi:* `{str(bg_error)}`\n\n"
                f"💡 _Vui lòng thử lại hoặc liên hệ admin_"
            )
            await error_bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=error_message,
                parse_mode="Markdown",
            )
        except Exception as error_notify_error:
            logger.error(f"Failed to send error notification: {error_notify_error}")
            # Fallback: send new error message
            try:
                fallback_bot = Bot(token=bot_token)
                await fallback_bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Lỗi khi lấy dữ liệu: {str(bg_error)}",
                )
            except Exception as fallback_error:
                logger.error(f"Fallback error message also failed: {fallback_error}")


def escape_markdown_v2(text: str) -> str:
    """
    Escape only Telegram MarkdownV2 special characters in a string.
    """
    # Characters that must be escaped
    special_chars = r"_*[]()~`>#+-=|{}.!"
    # Replace each with a single backslash
    return "".join(f"\\{c}" if c in special_chars else c for c in text)
