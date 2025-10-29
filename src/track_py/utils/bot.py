import asyncio
import time
from collections import defaultdict, deque
from src.track_py.utils.logger import logger
from src.track_py.utils.sheet import (
    get_cached_worksheet,
    invalidate_sheet_cache,
    get_cached_sheet_data,
    convert_values_to_records,
    parse_amount,
)
from src.track_py.const import LOG_ACTION, DELETE_ACTION

# Background expense logging queue for better performance
log_expense_queue = deque()
delete_expense_queue = deque()
_log_queue_processor_running = False
_delete_queue_processor_running = False
_background_tasks = set()  # Keep track of background tasks


async def wait_for_background_tasks(timeout=30):
    """Wait for all background tasks (log + delete) to complete before shutdown"""
    if not _background_tasks and not log_expense_queue and not delete_expense_queue:
        logger.info("No background tasks to wait for")
        return True

    logger.info(
        f"Waiting for {len(_background_tasks)} background tasks, "
        f"{len(log_expense_queue)} log queue, and {len(delete_expense_queue)} delete queue to complete..."
    )

    start_time = time.time()
    while (_background_tasks or log_expense_queue or delete_expense_queue) and (
        time.time() - start_time
    ) < timeout:
        await asyncio.sleep(0.1)

    if _background_tasks or log_expense_queue or delete_expense_queue:
        logger.warning(
            f"Timeout waiting for background tasks. "
            f"Remaining: {len(_background_tasks)} tasks, "
            f"{len(log_expense_queue)} log, {len(delete_expense_queue)} delete"
        )
        return False
    else:
        logger.info("✅ All background tasks completed successfully")
        return True


async def process_log_expense_queue():
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
                            expense_data, month_error, LOG_ACTION
                        )

            # Small delay between batches to avoid overwhelming the API
            await asyncio.sleep(0.5)

    except Exception as queue_error:
        logger.error(f"Error in expense queue processor: {queue_error}")
    finally:
        _log_queue_processor_running = False


async def process_delete_expense_queue():
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
                            expense_data, month_error, DELETE_ACTION
                        )

            # Small delay between batches to avoid overwhelming the API
            await asyncio.sleep(0.5)

    except Exception as queue_error:
        logger.error(f"Error in delete expense queue processor: {queue_error}")
    finally:
        _delete_queue_processor_running = False


async def process_log_month_expenses(target_month, expenses):
    """Process all expenses for a specific month"""
    try:
        logger.info(f"Processing expenses for month: {target_month}")

        # Send progress update if processing takes longer than expected
        for expense_data in expenses:
            progress_message = (
                f"⚡ *Đã ghi nhận {LOG_ACTION}!*\n"
                f"💰 {expense_data['amount']:,} VND\n"
                f"📝 {expense_data['note']}\n"
                f"📅 {expense_data['entry_date']} • {expense_data['entry_time']}\n\n"
                f"📊 *Đang xử lý batch ({len(expenses)} giao dịch)...*\n"
                f"⏳ _Kết nối Google Sheets thành công_"
            )
            await send_progress_update(expense_data, progress_message)

        # Get sheet once for all expenses in this month
        sheet = await asyncio.to_thread(get_cached_worksheet, target_month)
        logger.info(f"Got sheet for month {target_month}: {sheet.title}")

        # Prepare all rows for batch append
        rows_to_append = []
        for expense_data in expenses:
            row = [
                expense_data["entry_date"],
                expense_data["entry_time"],
                int(expense_data["amount"]),
                expense_data["note"],
            ]
            rows_to_append.append(row)

        # Batch append all rows at once (more efficient than individual appends)
        if len(rows_to_append) == 1:
            # Single expense - use append_row
            await asyncio.to_thread(
                lambda: sheet.append_row(rows_to_append[0], value_input_option="RAW")
            )
        else:
            # Multiple expenses - use batch append
            await asyncio.to_thread(
                lambda: sheet.append_rows(rows_to_append, value_input_option="RAW")
            )

        # Invalidate cache since we've updated the sheet
        invalidate_sheet_cache(target_month)

        logger.info(f"Batch processed {len(expenses)} expenses for {target_month}")

        # Send success notifications after sheet operations complete
        for expense_data in expenses:
            try:
                await send_success_notification(expense_data, LOG_ACTION)
            except Exception as notification_error:
                logger.warning(
                    f"Failed to send success notification: {notification_error}"
                )

        logger.info(f"Background processing completed for {len(expenses)} expenses")

    except Exception as process_error:
        logger.error(f"Error processing month {target_month} expenses: {process_error}")
        raise


async def process_delete_month_expenses(target_month, expenses):
    """Process all expenses for a specific month"""
    try:
        logger.info(f"Processing expenses for month: {target_month}")

        # Send progress update if processing takes longer than expected
        for expense_data in expenses:
            progress_message = (
                f"⚡ *Đã ghi nhận {DELETE_ACTION}!*\n"
                f"📅 {expense_data['entry_date']} • {expense_data['entry_time']}\n\n"
                f"📊 *Đang xử lý batch ({len(expenses)} giao dịch)...*\n"
                f"⏳ _Kết nối Google Sheets thành công_"
            )
            await send_progress_update(expense_data, progress_message)

        # Get sheet once for all expenses in this month
        sheet = await asyncio.to_thread(get_cached_worksheet, target_month)
        logger.info(f"Got sheet for month {target_month}: {sheet.title}")

        # Process each delete request
        for expense_data in expenses:
            entry_date = expense_data["entry_date"]
            entry_time = expense_data["entry_time"]

            try:
                # Get all sheet data to search for the expense
                all_values = await asyncio.to_thread(
                    get_cached_sheet_data, target_month
                )
                if not all_values or len(all_values) < 2:
                    logger.warning(f"No data in sheet {target_month} for deletion")
                    await send_error_notification(
                        expense_data, "Không có dữ liệu trong sheet này", DELETE_ACTION
                    )
                    continue
                records = convert_values_to_records(all_values)

                found_row = None
                for i, r in enumerate(records):
                    row_date = r.get("Date", "")
                    row_time = r.get("Time", "")
                    row_amount = parse_amount(r.get("VND", 0))
                    row_note = r.get("Note", "")
                    expense_data["amount"] = int(row_amount)
                    expense_data["note"] = row_note

                    if row_date == entry_date and row_time == entry_time:
                        found_row = (
                            i + 2
                        )  # +2 because records start from row 2 (header is row 1)
                        break

                if found_row:
                    # Delete the row from the sheet
                    await asyncio.to_thread(lambda: sheet.delete_rows(found_row))
                    logger.info(
                        f"Successfully deleted expense: {entry_date} {entry_time} from row {found_row}"
                    )
                else:
                    logger.warning(f"Expense not found: {entry_date} {entry_time}")
                    await send_error_notification(
                        expense_data,
                        f"Không tìm thấy giao dịch: {entry_date} {entry_time}",
                        DELETE_ACTION,
                    )
                    continue

            except Exception as delete_error:
                logger.error(
                    f"Error deleting expense {entry_date} {entry_time}: {delete_error}",
                    exc_info=True,
                )
                await send_error_notification(
                    expense_data, f"Lỗi khi xóa: {delete_error}", DELETE_ACTION
                )
                continue

        # Invalidate cache since we've updated the sheet
        invalidate_sheet_cache(target_month)

        logger.info(f"Batch processed {len(expenses)} expenses for {target_month}")

        # Send success notifications after sheet operations complete
        for expense_data in expenses:
            try:
                await send_success_notification(expense_data, DELETE_ACTION)
            except Exception as notification_error:
                logger.warning(
                    f"Failed to send success notification: {notification_error}"
                )

        logger.info(f"Background processing completed for {len(expenses)} expenses")

    except Exception as process_error:
        logger.error(f"Error processing month {target_month} expenses: {process_error}")
        raise


async def send_success_notification(expense_data, action):
    """Edit original message to show success after background processing completes"""
    try:
        # Edit the original message to show success
        bot_token = expense_data.get("bot_token")
        if bot_token and expense_data.get("message_id"):
            from telegram import Bot

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
                from telegram import Bot

                fallback_bot = Bot(token=expense_data["bot_token"])
                await fallback_bot.send_message(
                    chat_id=expense_data["chat_id"],
                    text=f"✅ Đã lưu thành công: {expense_data['amount']:,} VND - {expense_data['note']}",
                )
        except Exception as fallback_error:
            logger.error(f"Fallback notification also failed: {fallback_error}")

    except Exception as msg_error:
        logger.warning(f"Could not send success notification: {msg_error}")


async def send_error_notification(expense_data, error, action):
    """Edit original message to show error if processing fails"""
    try:
        # Edit the original message to show error
        bot_token = expense_data.get("bot_token")
        if bot_token and expense_data.get("message_id"):
            from telegram import Bot

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
                from telegram import Bot

                fallback_bot = Bot(token=expense_data["bot_token"])
                await fallback_bot.send_message(
                    chat_id=expense_data["chat_id"],
                    text=f"❌ Lỗi: {expense_data['amount']:,} VND - {expense_data['note']} - {error}",
                )

    except Exception as notify_error:
        logger.error(f"Failed to send error notification: {notify_error}")


async def send_progress_update(expense_data, progress_message):
    """Send intermediate progress update to improve UX for longer operations"""
    try:
        bot_token = expense_data.get("bot_token")
        if bot_token and expense_data.get("message_id"):
            from telegram import Bot

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


async def background_log_expense(
    entry_date,
    entry_time,
    amount,
    note,
    target_month,
    user_id,
    chat_id,
    bot_token,
    message_id,
):
    """Background task to queue expense for processing"""
    try:
        # Add expense to queue
        expense_data = {
            "entry_date": entry_date,
            "entry_time": entry_time,
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
                f"⚡ *Đã ghi nhận {LOG_ACTION}!*\n"
                f"💰 {amount:,} VND\n"
                f"📝 {note}\n"
                f"📅 {entry_date} • {entry_time}\n\n"
                f"📋 *Vị trí trong hàng đợi: #{queue_position}*\n"
                f"⏳ _Ước tính: {queue_position * 2}-{queue_position * 3} giây_"
            )
            try:
                from telegram import Bot

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
        await send_error_notification(expense_data, bg_error, LOG_ACTION)


async def background_delete_expense(
    entry_date, entry_time, target_month, user_id, chat_id, bot_token, message_id
):
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
                f"⚡ *Đã ghi nhận {DELETE_ACTION}!*\n"
                f"📅 {entry_date} • {entry_time}\n\n"
                f"📋 *Vị trí trong hàng đợi: #{queue_position}*\n"
                f"⏳ _Ước tính: {queue_position * 2}-{queue_position * 3} giây_"
            )
            try:
                from telegram import Bot

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
        await send_error_notification(expense_data, bg_error, DELETE_ACTION)
