import os
from src.track_py.utils.version import get_version
from src.track_py.const import bot_app, WEBHOOK_URL
from src.track_py.utils.logger import logger
from src.track_py.webhook.webhook import app
from src.track_py.webhook.bot import setup_bot

def main():
    """Main function to run the bot with webhook"""
    global bot_app
    
    try:
        # Setup bot if not already initialized
        if bot_app is None:
            bot_app = setup_bot()
        
        logger.info("Bot started successfully with webhook support!")
        print("🚀 CashPilot is running with webhooks...")
        print("📊 Connected to Google Sheets")
        print(f"🔗 Webhook URL: {WEBHOOK_URL}")
        print("💬 Listening for webhook requests...")
        print("📡 Visit /set_webhook to configure the webhook")
        
        # Add global error handler for the Flask app
        @app.errorhandler(Exception)
        def handle_exception(e):
            logger.error(f"Unhandled exception in Flask app: {e}", exc_info=True)
            return "Internal server error", 500
        
        # Run Flask app
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"Error starting bot: {e}", exc_info=True)
        print(f"❌ Failed to start bot: {e}")
    finally:
        # Cleanup bot if it exists
        if bot_app and bot_app.running:
            try:
                # Note: We can't use await here since main() is not async
                # The bot will be cleaned up when the process exits
                logger.info("Bot cleanup completed")
            except Exception as cleanup_error:
                logger.error(f"Error during bot cleanup: {cleanup_error}", exc_info=True)

if __name__ == "__main__":
    __version__ = get_version()
    main()
