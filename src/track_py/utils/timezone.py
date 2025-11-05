import datetime
import pytz
from src.track_py.config import config

# Timezone setup
timezone = pytz.timezone(config["settings"]["timezone"])


def get_current_time() -> datetime.datetime:
    """Get current time in the configured timezone"""
    return datetime.datetime.now(timezone)
