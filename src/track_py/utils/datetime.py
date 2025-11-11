import datetime
import src.track_py.utils.sheet as sheet
from src.track_py.utils.logger import logger
import os
from src.track_py.config import PROJECT_ROOT

BUILD_TIME = "BUILD_TIME"


# Sort by date and time
def parse_date_time(row: list[str]) -> datetime.datetime:
    if len(row) < 2 or not row[0]:
        return datetime.datetime.min

    date_str = row[0].strip()
    time_str = row[1].strip() if row[1] else "00:00:00"

    try:
        # Normalize time format first
        time_str = sheet.normalize_time(time_str)

        # Handle date format - check if year is present
        if date_str.count("/") == 1:  # dd/mm format
            # Add current year or infer from context
            current_year = datetime.datetime.now().year
            date_str = f"{date_str}/{current_year}"

        # Parse the complete date and time
        return datetime.datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
    except (ValueError, TypeError) as e:
        logger.debug(f"Failed to parse date/time '{date_str} {time_str}': {e}")
        return datetime.datetime.min


# Get build time
def get_build_time() -> str:
    try:
        build_time_file = os.path.join(PROJECT_ROOT, BUILD_TIME)
        with open(build_time_file) as f:
            return f.read().strip()
    except Exception:
        return "unknown"
