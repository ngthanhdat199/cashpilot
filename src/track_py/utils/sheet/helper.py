import os
import gspread
import time
import re
import asyncio
import datetime
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials
from gspread.utils import a1_to_rowcol
from src.track_py.utils.logger import logger
from src.track_py.utils.timezone import get_current_time
from src.track_py.config import config, PROJECT_ROOT
from src.track_py.utils.logger import logger
import src.track_py.const as const
import src.track_py.utils.util as util
from src.track_py.utils.category import category_display
from src.track_py.utils.datetime import parse_date_time
from typing import TypedDict
from huggingface_hub import InferenceClient
from src.track_py.utils.util import markdown_to_html
from src.track_py.config import config, save_config
from collections import defaultdict
import src.track_py.utils.sheet as sheet


class AssetRecord(TypedDict):
    date: str
    time: str
    vnd: int
    note: str
    unit: float


def parse_amount(value: int | float | str) -> int:
    """
    Convert an amount from int/float/str into a float (VND).
    Handles commas, dots, '₫', 'VND', etc.
    Returns 0 if parsing fails.
    """
    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        # Remove everything except digits
        cleaned = re.sub(r"[^\d]", "", value)
        if cleaned.isdigit():
            return int(cleaned)

    logger.warning(f"Invalid amount format '{value}' in today summary")
    return 0


def normalize_date(date_str: str) -> str:
    """
    Normalize a date like '4/9' or '4/10' into '04/09' or '04/10'.
    Keeps only day/month (no year).
    """
    try:
        day, month = date_str.split("/")
        return f"{day.zfill(2)}/{month.zfill(2)}"
    except ValueError:
        return date_str.strip()


def normalize_time(time_str: str) -> str:
    """
    Normalize time formats:
    - '10h'       -> '10:00:00'
    - '01h'       -> '01:00:00'
    - '10h30'     -> '10:30:00'
    - '10h5'      -> '10:05:00'
    - '10h30s45'  -> '10:30:45'
    - '10:05'     -> '10:05:00'
    - '10:05:30'  -> '10:05:30' (unchanged)
    """
    time_str = time_str.strip().lower().replace(" ", "")

    if "h" in time_str:
        # Split by 'h' first
        h_parts = time_str.split("h")
        hour = h_parts[0].zfill(2) if h_parts[0] else "00"

        # Check if there's minute/second part after 'h'
        if len(h_parts) > 1 and h_parts[1]:
            remaining = h_parts[1]

            # Check if there's 's' for seconds
            if "s" in remaining:
                s_parts = remaining.split("s")
                minute = s_parts[0].zfill(2) if s_parts[0] else "00"
                second = (
                    s_parts[1].zfill(2) if len(s_parts) > 1 and s_parts[1] else "00"
                )
            else:
                minute = remaining.zfill(2)
                second = "00"
        else:
            minute = "00"
            second = "00"

        return f"{hour}:{minute}:{second}"

    # Already colon format - add seconds if missing
    if time_str.count(":") == 1:
        return f"{time_str}:00"

    return time_str


def has_keyword(note: str, keywords: list[str]) -> bool:
    """
    Check if a note contains any of the specified keywords.

    This function performs case-insensitive keyword matching with different strategies:
    - For multi-word keywords (containing spaces): searches for exact substring match
    - For single-word keywords: searches for exact word match in tokenized text

    Args:
        note (str): The text to search for keywords
        keywords (list[str]): List of keywords to search for in the note

    Returns:
        bool: True if any keyword is found in the note, False otherwise

    Note:
        The function tokenizes the note using regex pattern r"[^\\s]+" which splits
        on whitespace. Single-word keywords must match complete tokens to avoid
        partial word matches (e.g., "cat" won't match "category").
    """
    note = note.lower()
    tokens = re.findall(r"[^\s]+", note)

    for k in keywords:
        k = k.lower()
        if " " in k:  # multi-word keyword
            if k in note:
                return True
        else:  # single-word keyword
            if k in tokens:
                return True
    return False


def safe_int(value: str) -> int:
    """Convert a string value to int safely, removing non-digit characters"""
    if not value:
        return 0

    text = str(value).strip()
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text.isdigit() else 0


def convert_values_to_records(all_values: list[list[str]]) -> list[sheet.Record]:
    """Convert raw sheet values to record format (list of dicts) with optimization"""
    if not all_values or len(all_values) < 2:  # Need at least header + 1 data row
        return []

    records = []
    for row in all_values[1:]:  # Skip header
        # Create record with proper error handling
        record = sheet.Record(
            {
                "date": (row[0] if len(row) > 0 else "").strip(),
                "time": (row[1] if len(row) > 1 else "").strip(),
                "vnd": row[2] if len(row) > 2 else 0,
                "note": (row[3] if len(row) > 3 else "").strip(),
            }
        )

        # Only add records that have at least a date or amount
        if record["date"] or record["vnd"]:
            records.append(record)

    return records


def convert_values_to_asset_records(
    all_values: list[list[str]],
) -> list[AssetRecord]:
    """Convert raw sheet values to record format (list of dicts) with optimization"""
    if not all_values or len(all_values) < 2:  # Need at least header + 1 data row
        return []

    records = []
    for row in all_values[1:]:  # Skip header
        # Create record with proper error handling
        record = AssetRecord(
            {
                "date": (row[0] if len(row) > 0 else "").strip(),
                "time": (row[1] if len(row) > 1 else "").strip(),
                "vnd": row[2] if len(row) > 2 else 0,
                "note": (row[3] if len(row) > 3 else "").strip(),
                "unit": float(row[4]) if len(row) > 4 and row[4] else 0.0,
            }
        )

        # Only add records that have at least a date or amount
        if record["date"] or record["vnd"] or record["unit"]:
            records.append(record)

    return records


def format_expense(r: sheet.Record, index=None):
    """Format an expense record into a readable string"""
    time_str = r["time"] or "—"
    amount_str = f"{parse_amount(r['vnd']):,.0f} VND"
    note_str = r["note"].lower() or ""

    if has_keyword(note_str, const.FOOD_KEYWORDS):
        note_icon = const.CATEGORY_ICONS["food"]
    elif has_keyword(note_str, const.TRANSPORT_KEYWORDS):
        note_icon = const.CATEGORY_ICONS["gas"]
    elif has_keyword(note_str, const.DATING_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.DATING]
    elif has_keyword(note_str, const.LONG_INVEST_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.LONG_INVEST]
    elif has_keyword(note_str, const.OPPORTUNITY_INVEST_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.OPPORTUNITY_INVEST]
    elif has_keyword(note_str, const.SUPPORT_PARENT_KEYWORDS):
        note_icon = const.CATEGORY_ICONS[const.SUPPORT_PARENT]
    elif has_keyword(note_str, const.RENT_KEYWORD):
        note_icon = const.CATEGORY_ICONS[const.RENT]
    else:
        note_icon = "📝"

    prefix = f"{index}. " if index is not None else ""
    return f"{prefix}⏰ {time_str} | 💰 {amount_str} | {note_icon} {note_str}"


def process_percent_change(new_value, original_value) -> str:
    percent = (
        (new_value - original_value) / original_value * 100
        if original_value != 0
        else 0
    )
    change_symbol = get_change_symbol(percent)
    return f"{change_symbol}{abs(percent):.2f}%"


def process_value_change(new_value, original_value) -> str:
    change = new_value - original_value
    change_symbol = get_change_symbol(change)
    return f"{change_symbol}{abs(change):,.0f}"


def get_change_symbol(value: float) -> str:
    """Get the change symbol (+/-) based on the percent value"""
    return "+" if value >= 0 else "-"
