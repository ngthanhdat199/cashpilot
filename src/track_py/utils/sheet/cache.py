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


# Performance optimization: Cache for sheet data to reduce API calls
_sheet_cache = {}
_worksheet_cache = {}
_asset_sheet_cache = {}
_cache_timeout = 300  # Cache timeout in seconds (5 minutes)
_asset_cache_timeout = 600  # Longer cache for asset sheet (10 minutes)
_today_cache_timeout = 60  # Shorter cache for today's data (1 minute)


def get_cached_worksheet(
    sheet_name: str, force_refresh: bool = False
) -> gspread.Worksheet:
    """Get cached worksheet object or fetch fresh if expired"""
    current_time = time.time()
    cache_key = f"worksheet_{sheet_name}"

    if not force_refresh and cache_key in _worksheet_cache:
        worksheet, timestamp = _worksheet_cache[cache_key]
        if current_time - timestamp < _cache_timeout:
            logger.debug(f"Using cached worksheet for {sheet_name}")
            return worksheet

    # Fetch fresh worksheet
    logger.debug(f"Fetching fresh worksheet for {sheet_name}")
    try:
        worksheet = sheet.get_or_create_monthly_sheet(sheet_name)
        _worksheet_cache[cache_key] = (worksheet, current_time)
        return worksheet
    except Exception as e:
        logger.error(f"Error fetching worksheet for {sheet_name}: {e}")
        # Return cached worksheet if available, even if expired
        if cache_key in _worksheet_cache:
            return _worksheet_cache[cache_key][0]
        raise


def get_cached_sheet_data(
    sheet_name: str, force_refresh: bool = False
) -> list[list[str]]:
    """Get cached sheet data or fetch fresh if expired"""
    current_time = time.time()
    cache_key = f"data_{sheet_name}"

    if not force_refresh and cache_key in _sheet_cache:
        data, timestamp = _sheet_cache[cache_key]
        if current_time - timestamp < _cache_timeout:
            logger.debug(f"Using cached data for sheet {sheet_name}")
            return data

    # Fetch fresh data
    logger.debug(f"Fetching fresh data for sheet {sheet_name}")
    try:
        sheet = get_cached_worksheet(sheet_name)
        # Use get_values instead of get_all_records for better performance
        all_values = sheet.get_values("A:D")
        _sheet_cache[cache_key] = (all_values, current_time)
        return all_values
    except Exception as e:
        logger.error(f"Error fetching sheet data for {sheet_name}: {e}")
        # Return cached data if available, even if expired
        if cache_key in _sheet_cache:
            return _sheet_cache[cache_key][0]
        raise


def get_cached_asset_sheet_data(
    sheet_name: str, force_refresh: bool = False
) -> list[list[str]]:
    """Get cached sheet data or fetch fresh if expired"""
    current_time = time.time()
    cache_key = f"data_{sheet_name}"

    if not force_refresh and cache_key in _asset_sheet_cache:
        data, timestamp = _asset_sheet_cache[cache_key]
        if current_time - timestamp < _asset_cache_timeout:
            logger.debug(f"Using cached data for sheet {sheet_name}")
            return data

    # Fetch fresh data
    logger.debug(f"Fetching fresh data for sheet {sheet_name}")
    try:
        sheet = get_cached_worksheet(sheet_name)
        # Use get_values instead of get_all_records for better performance
        all_values = sheet.get_values("A:E")
        _asset_sheet_cache[cache_key] = (all_values, current_time)
        return all_values
    except Exception as e:
        logger.error(f"Error fetching sheet data for {sheet_name}: {e}")
        # Return cached data if available, even if expired
        if cache_key in _asset_sheet_cache:
            return _asset_sheet_cache[cache_key][0]
        raise


def get_cached_today_data(
    sheet_name: str, today_str: str, force_refresh: bool = False
) -> list[list[str]]:
    """Get cached today's data with shorter cache timeout for better freshness"""
    current_time = time.time()
    cache_key = f"today_data_{sheet_name}_{today_str}"

    if not force_refresh and cache_key in _sheet_cache:
        data, timestamp = _sheet_cache[cache_key]
        if current_time - timestamp < _today_cache_timeout:
            logger.info(
                f"Using cached today data for {today_str} in sheet {sheet_name}"
            )
            return data

    # Fetch fresh data - try to get a smaller range first
    logger.info(f"Fetching fresh today data for {today_str} in sheet {sheet_name}")
    try:
        sheet = get_cached_worksheet(sheet_name)

        # First attempt: Try to get the sheet's actual used range to optimize further
        try:
            # Get the actual last row with data to avoid fetching empty rows
            all_values_meta = sheet.get_values(
                "A:A"
            )  # Just get column A to find last row
            if all_values_meta:
                last_row = len(all_values_meta)
                # Add some buffer but cap at reasonable limit
                fetch_range = f"A2:D{min(last_row + 10, 1000)}"
                logger.info(f"Optimizing fetch range to: {fetch_range}")
                logger.info(
                    f"Optimized fetch range: {fetch_range} (detected {last_row} rows)"
                )
                all_values = sheet.get_values(fetch_range)
                # logger.info(f"Fetched {all_values} rows for today data")
            else:
                all_values = []
        except Exception as range_error:
            logger.debug(
                f"Range optimization failed, using default range: {range_error}"
            )
            # Fallback to fixed range
            all_values = sheet.get_values("A2:D1000")

        # Add header row for consistency with existing code
        if all_values:
            all_values.insert(0, ["Date", "Time", "VND", "Note"])
        else:
            all_values = [["Date", "Time", "VND", "Note"]]

        _sheet_cache[cache_key] = (all_values, current_time)
        return all_values
    except Exception as e:
        logger.error(f"Error fetching today's sheet data for {sheet_name}: {e}")
        # Fallback to full sheet data if range fetch fails
        try:
            return get_cached_sheet_data(sheet_name, force_refresh)
        except Exception as fallback_error:
            logger.error(f"Fallback fetch also failed: {fallback_error}")
            # Return cached data if available, even if expired
            if cache_key in _sheet_cache:
                return _sheet_cache[cache_key][0]
            raise


def invalidate_sheet_cache(sheet_name: str):
    """Invalidate cache for a specific sheet"""
    data_key = f"data_{sheet_name}"
    worksheet_key = f"worksheet_{sheet_name}"

    if data_key in _sheet_cache:
        del _sheet_cache[data_key]
        logger.debug(f"Invalidated data cache for sheet {sheet_name}")

    if data_key in _asset_sheet_cache:
        del _asset_sheet_cache[data_key]
        logger.debug(f"Invalidated asset data cache for sheet {sheet_name}")

    if worksheet_key in _worksheet_cache:
        del _worksheet_cache[worksheet_key]
        logger.debug(f"Invalidated worksheet cache for sheet {sheet_name}")

    # Also invalidate today's data cache for this sheet
    today_keys_to_remove = [
        key
        for key in _sheet_cache.keys()
        if key.startswith(f"today_data_{sheet_name}_")
    ]
    for key in today_keys_to_remove:
        del _sheet_cache[key]
        logger.debug(f"Invalidated today cache: {key}")
