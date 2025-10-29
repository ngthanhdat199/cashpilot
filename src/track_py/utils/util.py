import re
from src.track_py.const import MONTH_NAMES


# Convert markdown → HTML
def markdown_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text


def get_month_display(month: int, year: int) -> str:
    return f"{MONTH_NAMES.get(month, month)}/{year}"
