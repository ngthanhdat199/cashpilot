import datetime
import asyncio
import threading
from flask import Flask, request, jsonify
from dateutil.relativedelta import relativedelta
from src.track_py.utils.logger import logger
from telegram import Update
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_cors import CORS
from src.track_py.webhook.bot import setup_bot, setup_bot_commands
from src.track_py.utils.bot import wait_for_background_tasks
import src.track_py.const as const
import src.track_py.utils.sheet as sheet
from src.track_py.utils.timezone import get_current_time
from src.track_py.scheduler.job import scheduler, start_scheduler, monthly_sheet_job

# Flask app for webhook
app = Flask(__name__)

# Configure CORS with explicit settings
CORS(
    app,
    origins=["*"],  # Allow all origins for development
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
    supports_credentials=True,
)

# Start the scheduler when the module is loaded
start_scheduler()


@app.route("/")
def home():
    response = jsonify(
        {
            "message": "CashPilot is running with webhooks!",
            "scheduler_status": "running" if scheduler.running else "stopped",
            "scheduled_jobs": len(scheduler.get_jobs()),
        }
    )
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@app.route("/create_next_month_sheet", methods=["POST"])
def manual_create_next_month_sheet():
    """Manual endpoint to trigger next month sheet creation for testing"""
    try:
        logger.info("📋 Manual sheet creation triggered via API")
        success = monthly_sheet_job()

        if success:
            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Next month's sheet created successfully",
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {"success": False, "message": "Failed to create next month's sheet"}
                ),
                500,
            )

    except Exception as e:
        logger.error(f"Error in manual sheet creation: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


@app.route("/scheduler/status", methods=["GET"])
def scheduler_status():
    """Get scheduler status and job information"""
    try:
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                    "trigger": str(job.trigger),
                }
            )

        return (
            jsonify(
                {
                    "scheduler_running": scheduler.running,
                    "jobs": jobs,
                    "timezone": str(scheduler.timezone),
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/deploy", methods=["POST"])
def deploy():
    """Handle deployment webhook requests"""
    import subprocess
    import os

    def update_version():
        version_file = os.path.join(project_dir, "VERSION")
        # get the current git commit hash
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=project_dir, text=True
        ).strip()
        # write it to VERSION
        with open(version_file, "w") as f:
            f.write(commit_hash + "\n")

    try:
        logger.info("Deploy webhook request received")

        # Change to the project directory (assuming the script is in the project root)
        project_dir = os.path.dirname(os.path.abspath(__file__))

        # Execute deployment commands
        wsgi_path = f"/var/www/{const.WSGI_FILE}"
        commands = [
            (
                "Git pull",
                lambda: subprocess.run(
                    ["git", "pull", "origin", "--no-ff"],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                ),
            ),
            (
                "Update VERSION",
                update_version,
            ),
            ("Touch WSGI", lambda: subprocess.run(["touch", wsgi_path], check=True)),
        ]

        results = []
        for desc, func in commands:
            try:
                logger.info(f"Executing: {desc}")
                func()  # run the command
                logger.info(f"{desc} succeeded")
                results.append(f"✓ {desc}: Success")
            except subprocess.CalledProcessError as e:
                logger.error(f"{desc} failed (code {e.returncode})")
                if e.stdout:
                    logger.error(f"stdout: {e.stdout.strip()}")
                if e.stderr:
                    logger.error(f"stderr: {e.stderr.strip()}")
                results.append(f"✗ {desc}: Failed (code {e.returncode})")
            except Exception as e:
                logger.error(f"{desc} error: {str(e)}", exc_info=True)
                results.append(f"✗ {desc}: Error - {str(e)}")

        # for cmd in commands:
        #     try:
        #         logger.info(f"Executing command: {' '.join(cmd)}")
        #         result = subprocess.run(
        #             cmd, cwd=project_dir, capture_output=True, text=True, timeout=30
        #         )

        #         if result.returncode == 0:
        #             logger.info(f"Command succeeded: {' '.join(cmd)}")
        #             results.append(f"✓ {' '.join(cmd)}: Success")
        #             if result.stdout:
        #                 results.append(f"  stdout: {result.stdout.strip()}")
        #         else:
        #             logger.error(
        #                 f"Command failed: {' '.join(cmd)}, return code: {result.returncode}"
        #             )
        #             results.append(
        #                 f"✗ {' '.join(cmd)}: Failed (code {result.returncode})"
        #             )
        #             if result.stderr:
        #                 results.append(f"  stderr: {result.stderr.strip()}")

        #     except subprocess.TimeoutExpired:
        #         logger.error(f"Command timed out: {' '.join(cmd)}")
        #         results.append(f"✗ {' '.join(cmd)}: Timeout")
        #     except Exception as cmd_error:
        #         logger.error(f"Error executing command {' '.join(cmd)}: {cmd_error}")
        #         results.append(f"✗ {' '.join(cmd)}: Error - {str(cmd_error)}")

        # Return deployment results
        response_text = "Deployment completed:\n" + "\n".join(results)
        logger.info("Deploy webhook completed")
        return response_text, 200

    except Exception as e:
        logger.error(f"Error in deploy webhook: {e}", exc_info=True)
        return f"Deployment failed: {str(e)}", 500


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming webhook requests from Telegram"""

    try:
        logger.info("Webhook request received")

        # Check circuit breaker
        current_time = datetime.datetime.now()
        if const.webhook_failures >= const.MAX_FAILURES:
            if (
                const.last_failure_time
                and (current_time - const.last_failure_time).seconds
                < const.FAILURE_RESET_TIME
            ):
                logger.warning(
                    f"Circuit breaker open: {const.webhook_failures} failures, rejecting request"
                )
                return "Service temporarily unavailable", 503
            else:
                # Reset the circuit breaker
                logger.info("Resetting circuit breaker")
                const.webhook_failures = 0
                const.last_failure_time = None

        # Ensure bot is initialized
        if const.bot_app is None:
            logger.info("Initializing bot application")
            try:
                const.bot_app = setup_bot()
            except Exception as setup_error:
                logger.error(
                    f"Failed to setup bot application: {setup_error}", exc_info=True
                )
                const.webhook_failures += 1
                const.last_failure_time = current_time
                return "Bot setup failed", 500

        # Get the update from Telegram
        try:
            update_data = request.get_json()
            if not update_data:
                logger.warning("Received empty update data")
                return "Empty update", 400
            logger.info(f"Received update data: {update_data}")
        except Exception as json_error:
            logger.error(
                f"Error parsing JSON from webhook request: {json_error}", exc_info=True
            )
            return "Invalid JSON", 400

        try:
            # Create Update object
            update = Update.de_json(update_data, const.bot_app.bot)
            if not update:
                logger.warning("Failed to create Update object from data")
                return "Invalid update data", 400
            logger.info(
                f"Created Update object for user {update.effective_user.id if update.effective_user else 'unknown'}"
            )
        except Exception as update_error:
            logger.error(f"Error creating Update object: {update_error}", exc_info=True)
            return "Error processing update", 500

        # Process the update using asyncio.run in a separate thread
        async def async_process_update():
            try:
                logger.info("Processing update asynchronously")

                # Try fresh bot instance first if enabled
                if const.use_fresh_bots:
                    fresh_bot_app = None
                    try:
                        fresh_bot_app = setup_bot()

                        # Initialize the fresh bot instance
                        await fresh_bot_app.initialize()
                        # Set up commands for fresh bot instance
                        await setup_bot_commands(fresh_bot_app)
                        logger.info("Fresh bot instance initialized successfully")

                        # Verify bot is properly initialized by checking if it has a username
                        try:
                            bot_info = await fresh_bot_app.bot.get_me()
                            logger.info(f"Fresh bot verified: @{bot_info.username}")
                        except Exception as verify_error:
                            logger.warning(
                                f"Could not verify fresh bot info: {verify_error}"
                            )

                        # Re-create the Update object with the fresh bot instance
                        # This ensures proper bot reference in command handlers
                        fresh_update = Update.de_json(update_data, fresh_bot_app.bot)
                        logger.info("Created fresh Update object with new bot instance")

                        # Process the update with the fresh instance
                        await fresh_bot_app.process_update(fresh_update)
                        logger.info(
                            "Update processed successfully with fresh bot instance"
                        )
                        return  # Success, exit early

                    except Exception as fresh_bot_error:
                        logger.error(
                            f"Error with fresh bot instance: {fresh_bot_error}",
                            exc_info=True,
                        )
                        # Continue to fallback

                    finally:
                        # Clean up the fresh bot instance after allowing background tasks to complete
                        if fresh_bot_app:
                            try:
                                # Wait for background tasks to complete before shutdown
                                logger.info(
                                    "Waiting for background tasks to complete before bot shutdown..."
                                )
                                await wait_for_background_tasks(
                                    timeout=10
                                )  # Wait up to 10 seconds

                                await fresh_bot_app.shutdown()
                                logger.info("Fresh bot instance shutdown completed")
                            except Exception as shutdown_error:
                                logger.error(
                                    f"Error shutting down fresh bot instance: {shutdown_error}"
                                )

                # Fallback to global bot instance
                logger.info("Using global bot instance")

                # Initialize global bot if not already done
                if not const.bot_app.running:
                    logger.info("Initializing global bot application")
                    await const.bot_app.initialize()
                    # Set up commands for global bot instance
                    await setup_bot_commands(const.bot_app)
                    logger.info("Global bot application initialized successfully")

                # Process the update with global instance (using original update object)
                await const.bot_app.process_update(update)
                logger.info("Update processed successfully with global bot instance")

            except Exception as process_error:
                logger.error(f"Error processing update: {process_error}", exc_info=True)

        def run_async_process():
            try:
                # Add some debugging information about the thread context
                import threading

                current_thread = threading.current_thread()
                logger.info(
                    f"Starting async processing in thread: {current_thread.name} (ID: {current_thread.ident})"
                )

                # Ensure we're in a new thread with no existing event loop
                try:
                    existing_loop = asyncio.get_running_loop()
                    logger.warning(
                        f"Found existing running loop in thread: {id(existing_loop)}"
                    )
                except RuntimeError:
                    # Good, no running loop
                    logger.info("No existing event loop found - creating fresh context")

                # Use asyncio.run() which creates and manages its own event loop
                logger.info("Starting asyncio.run() for update processing")
                asyncio.run(async_process_update())
                logger.info("asyncio.run() completed successfully")

            except RuntimeError as runtime_error:
                # Handle "Event loop is closed" and similar runtime errors
                logger.error(
                    f"Runtime error in asyncio.run: {runtime_error}", exc_info=True
                )
                # Try alternative approach with manual event loop management
                try:
                    logger.info("Attempting fallback with manual event loop management")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        logger.info(f"Created new event loop: {id(loop)}")
                        loop.run_until_complete(async_process_update())
                        logger.info("Fallback event loop succeeded")
                    finally:
                        try:
                            # Cancel any remaining tasks
                            pending = asyncio.all_tasks(loop)
                            if pending:
                                logger.info(f"Cancelling {len(pending)} pending tasks")
                                for task in pending:
                                    task.cancel()
                                loop.run_until_complete(
                                    asyncio.gather(*pending, return_exceptions=True)
                                )
                        except Exception as cancel_error:
                            logger.error(f"Error cancelling tasks: {cancel_error}")
                        finally:
                            loop.close()
                            asyncio.set_event_loop(None)
                            logger.info("Event loop cleanup completed")
                except Exception as fallback_error:
                    logger.error(
                        f"Fallback event loop approach also failed: {fallback_error}",
                        exc_info=True,
                    )
            except Exception as run_error:
                logger.error(f"Error in asyncio.run: {run_error}", exc_info=True)

        try:
            thread = threading.Thread(
                target=run_async_process,
                daemon=True,
                name=f"webhook-{threading.active_count()}",
            )
            thread.start()
            logger.info(f"Update processing thread started: {thread.name}")

            # Reset failure count on successful processing start
            if const.webhook_failures > 0:
                logger.info(
                    f"Resetting failure count from {const.webhook_failures} to 0"
                )
                const.webhook_failures = 0
                const.last_failure_time = None

            # Don't wait for the thread to complete, return immediately
            return "OK", 200

        except Exception as thread_error:
            logger.error(
                f"Error starting processing thread: {thread_error}", exc_info=True
            )
            const.webhook_failures += 1
            const.last_failure_time = datetime.datetime.now()
            return "Error starting processing thread", 500

    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}", exc_info=True)
        const.webhook_failures += 1
        const.last_failure_time = datetime.datetime.now()
        return "Internal server error", 500


@app.route("/expense/summary", methods=["GET", "OPTIONS"])
def expense_summary():
    """Provide yearly expense summary by month"""
    try:
        # Get year parameter from query string, default to spend year
        year = request.args.get("year", type=int)
        if not year:
            current_time = datetime.datetime.now()
            year = current_time.year

        logger.info(f"Yearly expense summary requested for year: {year}")

        # use thread pool to fetch all sheets concurrently
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for month_num in range(1, 13):
                month_name = const.MONTH_NAMES_SHORT[month_num - 1]
                sheet_name = f"{month_num:02d}/{year}"  # Format as "mm/yyyy"

                futures[executor.submit(sheet.get_monthly_expense, sheet_name)] = (
                    month_name
                )

            monthly_expenses = []
            for future in as_completed(futures):
                month_name = futures[future]
                total = 0.0
                try:
                    total = future.result()
                except Exception as fetch_error:
                    logger.error(
                        f"Error fetching expense for {month_name}: {fetch_error}"
                    )

                monthly_expenses.append({"month": month_name, "total": total})

        response_data = {
            "year": year,
            "currency": "VND",
            "monthly_expenses": monthly_expenses,
        }

        logger.info(f"Yearly expense summary completed for {year}")
        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error generating yearly expense summary: {e}", exc_info=True)
        return jsonify({"error": "Error generating summary"}), 500


@app.route("/expense/dashboard", methods=["GET", "OPTIONS"])
async def expense_dashboard():
    """Provide dashboard overview of expenses"""
    try:
        logger.info("Expense dashboard requested")

        now = get_current_time()
        target_month = now.strftime("%m/%Y")
        sheet_name = now.strftime("%m/%Y")

        month_value = await asyncio.to_thread(sheet.get_cached_sheet_data, sheet_name)

        # Get week and daily data concurrently
        week_data_task = sheet.get_week_process_data(now)
        daily_data_task = sheet.get_daily_process_data(now)
        month_budget_task = sheet.get_month_budget(target_month)

        week_data, daily_data, month_budget = await asyncio.gather(
            week_data_task, daily_data_task, month_budget_task
        )

        # Get the worksheet for the target week
        week_expenses = week_data["week_expenses"]
        week_records = week_data["records"]

        # Get today's data
        day_spend = daily_data["total"]
        day_records = daily_data["records"]

        # Summarize records by category concurrently
        month_summary = sheet.get_records_summary_by_cat(
            sheet.convert_values_to_records(month_value)
        )
        week_summary = sheet.get_records_summary_by_cat(week_records)
        day_summary = sheet.get_records_summary_by_cat(day_records)

        today_budget = month_budget / now.day
        week_budget = today_budget * 7

        # spend
        today_spend = day_spend
        month_spend = month_summary["total"]
        week_spend = week_data["total"]

        # income
        month_income = month_budget
        day_income = month_budget / now.day
        week_income = day_income * 7

        # expenses
        week_expenses = week_spend
        month_expenses = month_spend
        day_expenses = day_spend

        # Get categories data
        month_categories = []
        week_categories = []
        day_categories = []

        category_percent = await sheet.get_category_percentages_by_sheet_name(
            sheet_name
        )
        cat_meta = {
            cat: {
                "color": const.CATEGORY_COLORS.get(cat, "#000000"),
                "icon": const.CATEGORY_ICONS.get(cat, "🌟"),
                "name": const.CATEGORY_NAMES.get(cat, "Unknown"),
                "percent": category_percent[cat],
            }
            for cat in category_percent
        }

        # for cat in budgets:
        for cat, meta in cat_meta.items():
            # color
            color = meta["color"]

            # icon
            icon = meta["icon"]

            # category_name
            name = meta["name"]

            # spend
            month_spend_cat = month_summary[cat]
            week_spend_cat = week_summary[cat]
            day_spend_cat = day_summary[cat]

            # total
            budget_percentage = meta["percent"]
            budget = month_budget * (budget_percentage / 100) if month_budget > 0 else 0

            daily_budget = budget / now.day
            week_budget = daily_budget * 7

            # monthly
            month_categories.append(
                {
                    "category": cat,
                    "icon": icon,
                    "color": color,
                    "name": name,
                    "spend": month_spend_cat,
                    "budget": budget,
                }
            )

            # weekly
            week_categories.append(
                {
                    "category": cat,
                    "icon": icon,
                    "color": color,
                    "name": name,
                    "spend": week_spend_cat,
                    "budget": week_budget,
                }
            )

            # daily
            day_categories.append(
                {
                    "category": cat,
                    "icon": icon,
                    "color": color,
                    "name": name,
                    "spend": day_spend_cat,
                    "budget": daily_budget,
                }
            )

        # Fetch data for dashboard
        response_data = {
            "balance": {
                "monthly": {"spend": month_spend, "budget": month_budget},
                "weekly": {"spend": week_spend, "budget": week_budget},
                "daily": {"spend": today_spend, "budget": today_budget},
            },
            "income": {
                "monthly": month_income,
                "weekly": week_income,
                "daily": day_income,
            },
            "expenses": {
                "monthly": month_expenses,
                "weekly": week_expenses,
                "daily": day_expenses,
            },
            "categories": {
                "monthly": month_categories,
                "weekly": week_categories,
                "daily": day_categories,
            },
        }

        logger.info("Expense dashboard data retrieved successfully")
        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error generating expense dashboard: {e}", exc_info=True)
        return jsonify({"error": "Error generating dashboard"}), 500
