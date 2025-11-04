import re
import json
from datetime import datetime
from decimal import Decimal
from src.track_py.const import MONTH_NAMES


# Convert markdown → HTML
def markdown_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text


def get_month_display(month: int, year: int) -> str:
    return f"{MONTH_NAMES.get(month, month)}/{year}"


def to_json(data, indent=2):
    """Safely convert any object to a JSON string with pretty formatting."""

    def default(o):
        if isinstance(o, (datetime, Decimal)):
            return str(o)
        return f"<<non-serializable: {type(o).__name__}>>"

    try:
        return json.dumps(data, indent=indent, ensure_ascii=False, default=default)
    except Exception as e:
        return f"<<JSON encode error: {e}>>"
