import datetime
import asyncio
import threading
from flask import Flask, request, jsonify
from src.track_py.utils.logger import logger
from telegram import Update
from src.track_py.webhook.bot import setup_bot, setup_bot_commands
from src.track_py.const import bot_app, webhook_failures, last_failure_time, use_fresh_bots, MAX_FAILURES, FAILURE_RESET_TIME, WSGI_FILE, MONTH_NAMES_SHORT
from src.track_py.utils.sheet import get_monthly_expense
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_cors import CORS

# Flask app for webhook
app = Flask(__name__)

# Configure CORS with explicit settings
CORS(app, 
    origins=['*'],  # Allow all origins for development
    methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Content-Type', 'Authorization', 'Accept'],
    supports_credentials=True
)

@app.route('/')
def home():
    response = jsonify({"message": "Money Tracker Bot is running with webhooks!"})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

@app.route('/deploy', methods=['POST'])
def deploy():
    """Handle deployment webhook requests"""
    import subprocess
    import os
    
    try:
        logger.info("Deploy webhook request received")
        
        # Change to the project directory (assuming the script is in the project root)
        project_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Execute deployment commands
        wsgi_path = f"/var/www/{WSGI_FILE}"
        commands = [
            ['git', 'pull', 'origin', '--no-ff'],
            ['bash', '-c', 'echo $(git rev-parse --short HEAD) > VERSION'],
            ['touch', wsgi_path]
        ]
        
        results = []
        for cmd in commands:
            try:
                logger.info(f"Executing command: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd, 
                    cwd=project_dir,
                    capture_output=True, 
                    text=True, 
                    timeout=30
                )
                
                if result.returncode == 0:
                    logger.info(f"Command succeeded: {' '.join(cmd)}")
                    results.append(f"✓ {' '.join(cmd)}: Success")
                    if result.stdout:
                        results.append(f"  stdout: {result.stdout.strip()}")
                else:
                    logger.error(f"Command failed: {' '.join(cmd)}, return code: {result.returncode}")
                    results.append(f"✗ {' '.join(cmd)}: Failed (code {result.returncode})")
                    if result.stderr:
                        results.append(f"  stderr: {result.stderr.strip()}")
                        
            except subprocess.TimeoutExpired:
                logger.error(f"Command timed out: {' '.join(cmd)}")
                results.append(f"✗ {' '.join(cmd)}: Timeout")
            except Exception as cmd_error:
                logger.error(f"Error executing command {' '.join(cmd)}: {cmd_error}")
                results.append(f"✗ {' '.join(cmd)}: Error - {str(cmd_error)}")
        
        # Return deployment results
        response_text = "Deployment completed:\n" + "\n".join(results)
        logger.info("Deploy webhook completed")
        return response_text, 200
        
    except Exception as e:
        logger.error(f"Error in deploy webhook: {e}", exc_info=True)
        return f"Deployment failed: {str(e)}", 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests from Telegram"""
    global bot_app, webhook_failures, last_failure_time
    
    try:
        logger.info("Webhook request received")
        
        # Check circuit breaker
        current_time = datetime.datetime.now()
        if webhook_failures >= MAX_FAILURES:
            if last_failure_time and (current_time - last_failure_time).seconds < FAILURE_RESET_TIME:
                logger.warning(f"Circuit breaker open: {webhook_failures} failures, rejecting request")
                return "Service temporarily unavailable", 503
            else:
                # Reset the circuit breaker
                logger.info("Resetting circuit breaker")
                webhook_failures = 0
                last_failure_time = None
        
        # Ensure bot is initialized
        if bot_app is None:
            logger.info("Initializing bot application")
            try:
                bot_app = setup_bot()
            except Exception as setup_error:
                logger.error(f"Failed to setup bot application: {setup_error}", exc_info=True)
                webhook_failures += 1
                last_failure_time = current_time
                return "Bot setup failed", 500
            
        # Get the update from Telegram
        try:
            update_data = request.get_json()
            if not update_data:
                logger.warning("Received empty update data")
                return "Empty update", 400
            logger.info(f"Received update data: {update_data}")
        except Exception as json_error:
            logger.error(f"Error parsing JSON from webhook request: {json_error}", exc_info=True)
            return "Invalid JSON", 400
        
        try:
            # Create Update object
            update = Update.de_json(update_data, bot_app.bot)
            if not update:
                logger.warning("Failed to create Update object from data")
                return "Invalid update data", 400
            logger.info(f"Created Update object for user {update.effective_user.id if update.effective_user else 'unknown'}")
        except Exception as update_error:
            logger.error(f"Error creating Update object: {update_error}", exc_info=True)
            return "Error processing update", 500
        
        # Process the update using asyncio.run in a separate thread
        async def async_process_update():
            try:
                logger.info("Processing update asynchronously")
                
                # Try fresh bot instance first if enabled
                if use_fresh_bots:
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
                            logger.warning(f"Could not verify fresh bot info: {verify_error}")
                        
                        # Re-create the Update object with the fresh bot instance
                        # This ensures proper bot reference in command handlers
                        fresh_update = Update.de_json(update_data, fresh_bot_app.bot)
                        logger.info("Created fresh Update object with new bot instance")
                        
                        # Process the update with the fresh instance
                        await fresh_bot_app.process_update(fresh_update)
                        logger.info("Update processed successfully with fresh bot instance")
                        return  # Success, exit early
                        
                    except Exception as fresh_bot_error:
                        logger.error(f"Error with fresh bot instance: {fresh_bot_error}", exc_info=True)
                        # Continue to fallback
                        
                    finally:
                        # Clean up the fresh bot instance
                        if fresh_bot_app:
                            try:
                                await fresh_bot_app.shutdown()
                                logger.info("Fresh bot instance shutdown completed")
                            except Exception as shutdown_error:
                                logger.error(f"Error shutting down fresh bot instance: {shutdown_error}")
                
                # Fallback to global bot instance
                logger.info("Using global bot instance")
                
                # Initialize global bot if not already done
                if not bot_app.running:
                    logger.info("Initializing global bot application")
                    await bot_app.initialize()
                    # Set up commands for global bot instance
                    await setup_bot_commands(bot_app)
                    logger.info("Global bot application initialized successfully")
                
                # Process the update with global instance (using original update object)
                await bot_app.process_update(update)
                logger.info("Update processed successfully with global bot instance")
                
            except Exception as process_error:
                logger.error(f"Error processing update: {process_error}", exc_info=True)
        
        def run_async_process():
            try:
                # Add some debugging information about the thread context
                import threading
                current_thread = threading.current_thread()
                logger.info(f"Starting async processing in thread: {current_thread.name} (ID: {current_thread.ident})")
                
                # Ensure we're in a new thread with no existing event loop
                try:
                    existing_loop = asyncio.get_running_loop()
                    logger.warning(f"Found existing running loop in thread: {id(existing_loop)}")
                except RuntimeError:
                    # Good, no running loop
                    logger.info("No existing event loop found - creating fresh context")
                
                # Use asyncio.run() which creates and manages its own event loop
                logger.info("Starting asyncio.run() for update processing")
                asyncio.run(async_process_update())
                logger.info("asyncio.run() completed successfully")
                
            except RuntimeError as runtime_error:
                # Handle "Event loop is closed" and similar runtime errors
                logger.error(f"Runtime error in asyncio.run: {runtime_error}", exc_info=True)
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
                                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        except Exception as cancel_error:
                            logger.error(f"Error cancelling tasks: {cancel_error}")
                        finally:
                            loop.close()
                            asyncio.set_event_loop(None)
                            logger.info("Event loop cleanup completed")
                except Exception as fallback_error:
                    logger.error(f"Fallback event loop approach also failed: {fallback_error}", exc_info=True)
            except Exception as run_error:
                logger.error(f"Error in asyncio.run: {run_error}", exc_info=True)
        
        try:
            thread = threading.Thread(target=run_async_process, daemon=True, name=f"webhook-{threading.active_count()}")
            thread.start()
            logger.info(f"Update processing thread started: {thread.name}")
            
            # Reset failure count on successful processing start
            if webhook_failures > 0:
                logger.info(f"Resetting failure count from {webhook_failures} to 0")
                webhook_failures = 0
                last_failure_time = None
            
            # Don't wait for the thread to complete, return immediately
            return "OK", 200
            
        except Exception as thread_error:
            logger.error(f"Error starting processing thread: {thread_error}", exc_info=True)
            webhook_failures += 1
            last_failure_time = datetime.datetime.now()
            return "Error starting processing thread", 500
            
    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}", exc_info=True)
        webhook_failures += 1
        last_failure_time = datetime.datetime.now()
        return "Internal server error", 500

@app.route('/expense/summary', methods=['GET', 'OPTIONS'])
def expense_summary():
    """Provide yearly expense summary by month"""
    try:
        # Get year parameter from query string, default to current year
        year = request.args.get('year', type=int)
        if not year:
            current_time = datetime.datetime.now()
            year = current_time.year
        
        logger.info(f"Yearly expense summary requested for year: {year}")

        # use thread pool to fetch all sheets concurrently
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for month_num in range(1, 13):
                month_name = MONTH_NAMES_SHORT[month_num - 1]
                sheet_name = f"{month_num:02d}/{year}"  # Format as "mm/yyyy"
                
                futures[executor.submit(get_monthly_expense, sheet_name)] = month_name
            
            monthly_expenses = []
            for future in as_completed(futures):
                month_name = futures[future]
                total = 0.0
                try:
                    total = future.result()
                except Exception as fetch_error:
                    logger.error(f"Error fetching expense for {month_name}: {fetch_error}")
                
                monthly_expenses.append({
                    "month": month_name,
                    "total": total
                })


        response_data = {
            "year": year,
            "currency": "VND",
            "monthly_expenses": monthly_expenses
        }
        
        logger.info(f"Yearly expense summary completed for {year}")
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error generating yearly expense summary: {e}", exc_info=True)
        return jsonify({"error": "Error generating summary"}), 500

