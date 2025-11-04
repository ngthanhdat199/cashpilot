import asyncio
import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import itertools
from src.track_py.utils.logger import logger
from src.track_py.config import config
from src.track_py.utils.logger import logger
import src.track_py.const as const
import src.track_py.utils.util as util
from src.track_py.utils.category import category_display
from src.track_py.utils.datetime import parse_date_time
import src.track_py.utils.sheet as sheet


# helper to get assets response
async def get_assets_response():
    """Helper to calculate total assets from config"""
    try:
        sheet_name = config["settings"]["assets_sheet_name"]
        logger.info(f"Successfully obtained sheet for {sheet_name}")

        # sort
        try:
            await sort_expenses_by_date(sheet_name)
        except Exception as sort_error:
            logger.error(f"Error sorting assets sheet {sheet_name}: {sort_error}")

        all_values = await asyncio.to_thread(sheet.get_cached_sheet_data, sheet_name)
        records = sheet.convert_values_to_records(all_values)
        assets_summary = get_assets_records_summary(records)
        assets_expenses = assets_summary["expenses"]

        grouped = defaultdict(list)
        for r in assets_expenses:
            date_str = r["Date"]
            grouped[date_str].append(r)

        details_lines = []
        for day, rows in sorted(
            grouped.items(), key=lambda x: datetime.datetime.strptime(x[0], "%d/%m/%Y")
        ):
            date_total = sum(sheet.parse_amount(r["VND"]) for r in rows)
            details_lines.append(f"\n📅 {day}: {date_total:,.0f} VND")
            details_lines.extend(
                sheet.format_expense(r, i) for i, r in enumerate(rows, start=1)
            )

        response = (
            f"{category_display["assets"]} hiện tại: {assets_summary["total"]:,.0f} VND\n"
            f"🏦 Đầu tư dài hạn: \n"
            f"   ├─ 🏅 Vàng → {assets_summary["gold"]:,.0f} VND\n"
            f"   ├─ 🧾 ETF → {assets_summary["etf"]:,.0f} VND\n"
            f"   ├─ 📊 DCDS → {assets_summary["dcds"]:,.0f} VND\n"
            f"   └─ 📈 VESAF → {assets_summary["vesaf"]:,.0f} VND\n"
            f"🌐 Đầu tư cơ hội: \n"
            f"   ├─ ₿ Bitcoin → {assets_summary["bitcoin"]:,.0f} VND\n"
            f"   └─ ✨ Ethereum → {assets_summary["ethereum"]:,.0f} VND\n"
        )

        if details_lines:
            response += "\n📋 Chi tiết:\n"
            response += "\n".join(details_lines)

        return response

    except Exception as e:
        logger.error(f"Error calculating total assets: {e}", exc_info=True)
        return ""


# helper for totals summary
def get_assets_records_summary(records):
    """Helper to get total assets summary from records"""
    summary = {
        "gold": 0,
        "etf": 0,
        "dcds": 0,
        "vesaf": 0,
        "bitcoin": 0,
        "ethereum": 0,
        "total": 0,
        "expenses": [],
        "other": 0,
    }

    for r in records:
        note = r.get("Note", "").lower()
        amount = sheet.parse_amount(r.get("VND", 0))

        if amount == 0:
            continue

        summary["expenses"].append(r)
        summary["total"] += amount

        if sheet.has_keyword(note, ["vàng"]):
            summary["gold"] += amount
        elif sheet.has_keyword(note, ["etf"]):
            summary["etf"] += amount
        elif sheet.has_keyword(note, ["dcds"]):
            summary["dcds"] += amount
        elif sheet.has_keyword(note, ["vesaf"]):
            summary["vesaf"] += amount
        elif sheet.has_keyword(note, ["btc"]):
            summary["bitcoin"] += amount
        elif sheet.has_keyword(note, ["eth"]):
            summary["ethereum"] += amount
        else:
            summary["other"] += amount

    return summary


def migrate_assets_data():
    """Helper to migrate assets data from expenses sheet to assets sheet"""
    try:
        current_time = datetime.datetime.now()
        year = current_time.year

        # use thread pool to fetch all sheets concurrently
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for month_num in range(1, 13):
                month_name = const.MONTH_NAMES_SHORT[month_num - 1]
                sheet_name = f"{month_num:02d}/{year}"  # Format as "mm/yyyy"

                futures[executor.submit(get_assets_expenses, sheet_name, year)] = (
                    month_name
                )

            assets_expenses = []
            for future in as_completed(futures):
                month_name = futures[future]
                try:
                    expenses = future.result()
                except Exception as fetch_error:
                    logger.error(
                        f"Error fetching assets expenses for {month_name}: {fetch_error}",
                        exc_info=True,
                    )
                assets_expenses.append(expenses)

        asset_sheet = sheet.get_cached_worksheet(
            config["settings"]["assets_sheet_name"]
        )
        logger.info(f"Got asset sheet: {asset_sheet.title}")

        flat_expenses = list(itertools.chain.from_iterable(assets_expenses))
        logger.info(
            f"Total flat asset expenses to migrate: {util.to_json(flat_expenses)}"
        )
        sort_expenses = sorted(
            flat_expenses, key=lambda x: datetime.datetime.strptime(x[0], "%d/%m/%Y")
        )
        logger.info(
            f"Total sorted asset expenses to migrate: {util.to_json(sort_expenses)}"
        )

        if len(assets_expenses) == 1:
            asset_sheet.append_row(
                assets_expenses[0], value_input_option="RAW", table_range="A2:D"
            )
        else:
            flat_expenses = list(itertools.chain.from_iterable(assets_expenses))
            logger.info(
                f"Total asset expenses to migrate: {util.to_json(flat_expenses)}"
            )
            asset_sheet.append_rows(
                flat_expenses, value_input_option="RAW", table_range="A2:D"
            )

        return f"{category_display['migrate_assets']} thành công!"

    except Exception as e:
        logger.error(f"Error migrating assets data: {e}", exc_info=True)
        return


def get_assets_expenses(sheet_name, year):
    """Fetch total expense for a given month sheet"""
    try:
        current_sheet = sheet.get_monthly_sheet_if_exists(sheet_name)
        if not current_sheet:
            logger.warning(f"Sheet {sheet_name} does not exist.")
            return []

        all_values = sheet.get_cached_sheet_data(sheet_name)
        records = sheet.convert_values_to_records(all_values)
        assets_expenses = get_assets_expenses_records(records, year)
        return assets_expenses

    except Exception as sheet_error:
        logger.error(f"Error accessing sheet {sheet_name}: {sheet_error}")

    return []


def get_assets_expenses_records(records, year):
    expenses_row = []

    for r in records:
        note = r.get("Note", "").lower()
        if (
            sheet.has_keyword(note, ["vàng"])
            or sheet.has_keyword(note, ["etf"])
            or sheet.has_keyword(note, ["dcds"])
            or sheet.has_keyword(note, ["vesaf"])
            or sheet.has_keyword(note, ["btc"])
            or sheet.has_keyword(note, ["eth"])
        ):
            date = r.get("Date", "").strip()
            # Check if year is already in date, if not add it
            if date and "/" in date and len(date.split("/")) == 2:
                r["Date"] = f"{date}/{year}"

            row = [r["Date"], r["Time"], sheet.parse_amount(r["VND"]), r["Note"]]
            expenses_row.append(row)

    return expenses_row


async def sort_expenses_by_date(sheet_name):
    try:
        logger.info(f"Sorting expenses in sheet {sheet_name}...")
        current_sheet = await asyncio.to_thread(sheet.get_cached_worksheet, sheet_name)

        # Get all data
        all_values = await asyncio.to_thread(sheet.get_cached_sheet_data, sheet_name)

        if len(all_values) > 2:  # More than header + 1 row
            data_rows = all_values[1:]
            sorted_data = sorted(data_rows, key=parse_date_time)

            # format amounts VND
            for row in sorted_data:
                if len(row) >= 3 and row[2]:
                    try:
                        row[2] = int(
                            float(str(row[2]).replace(",", "").replace("₫", "").strip())
                        )
                    except (ValueError, TypeError):
                        pass

            # Update the sorted data
            await asyncio.to_thread(
                lambda: current_sheet.update(
                    f"A2:D{len(sorted_data) + 1}", sorted_data, value_input_option="RAW"
                )
            )

            # Invalidate cache
            sheet.invalidate_sheet_cache(sheet_name)
            logger.info(
                f"Manually sorted {len(sorted_data)} rows in sheet {sheet_name}"
            )
        else:
            logger.info(f"No data to sort in sheet {sheet_name}")

    except Exception as e:
        logger.error(f"Error starting sort for sheet {sheet_name}: {e}", exc_info=True)
