import datetime
import pytz
from config import config

# Timezone setup
timezone = pytz.timezone(config["settings"]["timezone"])

def get_current_time():
    """Get current time in the configured timezone"""
    return datetime.datetime.now(timezone)