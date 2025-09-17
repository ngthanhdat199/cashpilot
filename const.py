from config import config

# Global variable to store bot application - initialize it immediately
bot_app = None

# Simple circuit breaker for webhook failures
webhook_failures = 0
last_failure_time = None
MAX_FAILURES = 10
FAILURE_RESET_TIME = 300  # 5 minutes
use_fresh_bots = True  # Flag to enable/disable fresh bot instances

TOKEN = config["telegram"]["bot_token"]
WEBHOOK_URL = config["telegram"]["webhook_url"]