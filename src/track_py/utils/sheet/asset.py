import asyncio
import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import itertools
from src.track_py.config import config
from src.track_py.utils.logger import logger
import src.track_py.const as const
import src.track_py.utils.util as util
from src.track_py.utils.category import category_display
import src.track_py.utils.sheet as sheet
import requests
import base64
import json
from typing import TypedDict


class AssetPrices(TypedDict):
    vesaf: float
    dcds: float
    etf: float
    gold: float
    bitcoin: float
    ethereum: float


class Asset(TypedDict):
    vesaf: float
    dcds: float
    etf: float
    gold: float
    updated_at: str


# helper to get assets response
async def get_assets_response() -> str:
    """Helper to calculate total assets from config"""
    try:
        sheet_name = config["settings"]["assets_sheet_name"]
        logger.info(f"Successfully obtained sheet for {sheet_name}")

        # sort
        try:
            await sheet.sort_assets_expenses_by_date()
        except Exception as sort_error:
            logger.error(f"Error sorting assets sheet {sheet_name}: {sort_error}")

        all_values = await asyncio.to_thread(sheet.get_cached_sheet_data, sheet_name)
        records = sheet.convert_values_to_asset_records(all_values)

        # asset
        assets_summary = get_assets_records_summary(records)
        assets_expenses = assets_summary["expenses"]

        # profit
        prices = prepare_prices()
        profit_summary = get_profit_asset_summary(records, prices)

        grouped = defaultdict(list)
        for r in assets_expenses:
            date_str = r["date"]
            grouped[date_str].append(r)

        details_lines = []
        for day, rows in sorted(
            grouped.items(), key=lambda x: datetime.datetime.strptime(x[0], "%d/%m/%Y")
        ):
            date_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
            details_lines.append(f"\n📅 {day}: {date_total:,.0f} VND")
            details_lines.extend(
                "\n" + sheet.format_expense(r, i) for i, r in enumerate(rows, start=1)
            )
            details_lines.append("\n")

        # --- Pre-calculate all value/percent changes ---
        profit_value_change = sheet.process_value_change(
            profit_summary["total"], assets_summary["total"]
        )
        profit_percent_change = sheet.process_percent_change(
            profit_summary["total"], assets_summary["total"]
        )

        gold_value_change = sheet.process_value_change(
            profit_summary["gold"], assets_summary["gold"]
        )
        gold_percent_change = sheet.process_percent_change(
            profit_summary["gold"], assets_summary["gold"]
        )

        etf_value_change = sheet.process_value_change(
            profit_summary["etf"], assets_summary["etf"]
        )
        etf_percent_change = sheet.process_percent_change(
            profit_summary["etf"], assets_summary["etf"]
        )

        dcds_value_change = sheet.process_value_change(
            profit_summary["dcds"], assets_summary["dcds"]
        )
        dcds_percent_change = sheet.process_percent_change(
            profit_summary["dcds"], assets_summary["dcds"]
        )

        vesaf_value_change = sheet.process_value_change(
            profit_summary["vesaf"], assets_summary["vesaf"]
        )
        vesaf_percent_change = sheet.process_percent_change(
            profit_summary["vesaf"], assets_summary["vesaf"]
        )

        bitcoin_value_change = sheet.process_value_change(
            profit_summary["bitcoin"], assets_summary["bitcoin"]
        )
        bitcoin_percent_change = sheet.process_percent_change(
            profit_summary["bitcoin"], assets_summary["bitcoin"]
        )

        ethereum_value_change = sheet.process_value_change(
            profit_summary["ethereum"], assets_summary["ethereum"]
        )
        ethereum_percent_change = sheet.process_percent_change(
            profit_summary["ethereum"], assets_summary["ethereum"]
        )

        long_investment_asset_value = (
            assets_summary["gold"]
            + assets_summary["etf"]
            + assets_summary["dcds"]
            + assets_summary["vesaf"]
        )

        long_investment_profit_value = (
            profit_summary["gold"]
            + profit_summary["etf"]
            + profit_summary["dcds"]
            + profit_summary["vesaf"]
        )

        opportunity_investment_asset_value = (
            assets_summary["bitcoin"] + assets_summary["ethereum"]
        )

        opportunity_investment_profit_value = (
            profit_summary["bitcoin"] + profit_summary["ethereum"]
        )

        long_investment_value_change = sheet.process_value_change(
            long_investment_profit_value,
            long_investment_asset_value,
        )
        long_investment_percent_change = sheet.process_percent_change(
            long_investment_profit_value,
            long_investment_asset_value,
        )

        opportunity_investment_value_change = sheet.process_value_change(
            profit_summary["bitcoin"] + profit_summary["ethereum"],
            assets_summary["bitcoin"] + assets_summary["ethereum"],
        )
        opportunity_investment_percent_change = sheet.process_percent_change(
            profit_summary["bitcoin"] + profit_summary["ethereum"],
            assets_summary["bitcoin"] + assets_summary["ethereum"],
        )

        response = (
            f"{category_display["assets"]}: {assets_summary["total"]:,.0f} VND\n"
            f"{category_display["long_investment"]}: {long_investment_asset_value:,.0f} VND\n"
            f"   ├─ {category_display["gold"]} → {assets_summary["gold"]:,.0f} VND\n"
            f"   ├─ {category_display["etf"]} → {assets_summary["etf"]:,.0f} VND\n"
            f"   ├─ {category_display["dcds"]} → {assets_summary["dcds"]:,.0f} VND\n"
            f"   └─ {category_display["vesaf"]} → {assets_summary["vesaf"]:,.0f} VND\n"
            f"{category_display["opportunity_investment"]}: {opportunity_investment_asset_value:,.0f} VND\n"
            f"   ├─ {category_display["bitcoin"]} → {assets_summary["bitcoin"]:,.0f} VND\n"
            f"   └─ {category_display["ethereum"]} → {assets_summary["ethereum"]:,.0f} VND\n\n"
            f"{category_display["profit"]}: {profit_summary["total"]:,.0f} VND ({profit_value_change}) ({profit_percent_change})\n"
            f"{category_display['long_investment']}: {long_investment_profit_value:,.0f} VND ({long_investment_value_change}) ({long_investment_percent_change}) \n"
            f"   ├─ {category_display['gold']} → {profit_summary['gold']:,.0f} VND ({gold_value_change}) ({gold_percent_change})\n"
            f"   ├─ {category_display['etf']} → {profit_summary['etf']:,.0f} VND ({etf_value_change}) ({etf_percent_change})\n"
            f"   ├─ {category_display['dcds']} → {profit_summary['dcds']:,.0f} VND ({dcds_value_change}) ({dcds_percent_change})\n"
            f"   └─ {category_display['vesaf']} → {profit_summary['vesaf']:,.0f} VND ({vesaf_value_change}) ({vesaf_percent_change})\n"
            f"{category_display['opportunity_investment']}: {opportunity_investment_profit_value:,.0f} VND ({opportunity_investment_value_change}) ({opportunity_investment_percent_change}) \n"
            f"   ├─ {category_display['bitcoin']} → {profit_summary['bitcoin']:,.0f} VND ({bitcoin_value_change}) ({bitcoin_percent_change})\n"
            f"   └─ {category_display['ethereum']} → {profit_summary['ethereum']:,.0f} VND ({ethereum_value_change}) ({ethereum_percent_change})\n"
        )

        if details_lines:
            response += f"\n📝 Chi tiết:{''.join(details_lines)}"

        return response

    except Exception as e:
        logger.error(f"Error calculating total assets: {e}", exc_info=True)
        return ""


# helper for totals summary
def get_assets_records_summary(records: list[sheet.Record]) -> dict:
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
        note = r["note"].lower()
        amount = sheet.parse_amount(r["vnd"])

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


def migrate_assets_data() -> str:
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


def get_assets_expenses(sheet_name: str, year: int) -> list[list]:
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


def get_assets_expenses_records(records: list[sheet.Record], year: int) -> list[list]:
    expenses_row = []

    for r in records:
        note = r["note"].lower()
        if (
            sheet.has_keyword(note, ["vàng"])
            or sheet.has_keyword(note, ["etf"])
            or sheet.has_keyword(note, ["dcds"])
            or sheet.has_keyword(note, ["vesaf"])
            or sheet.has_keyword(note, ["btc"])
            or sheet.has_keyword(note, ["eth"])
        ):
            date = r["date"].strip()
            # Check if year is already in date, if not add it
            if date and "/" in date and len(date.split("/")) == 2:
                r["date"] = f"{date}/{year}"

            row = [r["date"], r["time"], sheet.parse_amount(r["vnd"]), r["note"]]
            expenses_row.append(row)

    return expenses_row


def prepare_prices() -> AssetPrices:
    price_worker = get_price_worker()
    usd_to_vnd_rate = get_usd_to_vnd_rate()
    price_btc = get_price_btc(usd_to_vnd_rate)
    price_eth = get_price_eth(usd_to_vnd_rate)

    return AssetPrices(
        vesaf=price_worker["vesaf"],
        dcds=price_worker["dcds"],
        etf=price_worker["etf"],
        gold=price_worker["gold"],
        bitcoin=price_btc,
        ethereum=price_eth,
    )


def get_price_worker() -> Asset:
    try:
        token = config["worker"]["token"]
        url = f"https://api.github.com/repos/ngthanhdat199/cashpilot-worker/contents/data.json?ref=main"
        logger.info(f"Fetching asset prices from worker URL: {url}")

        headers = {
            "Accept": "application/vnd.github.object",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()

            b64_content = data["content"].replace("\n", "")
            file_content = base64.b64decode(b64_content).decode("utf-8")
            json_data = json.loads(file_content)

            return Asset(
                vesaf=json_data["vesaf"],
                dcds=json_data["dcds"],
                etf=json_data["etf"],
                gold=json_data["gold"],
                updated_at=json_data["updated_at"],
            )

        else:
            logger.error(
                f"Failed to fetch data from worker. Status code: {response.status_code}"
            )
            return Asset(vesaf=0.0, dcds=0.0, etf=0.0, gold=0.0, updated_at="")
    except Exception as e:
        logger.error(f"Error fetching gold price: {e}")


def get_price_response() -> str:
    price_worker = sheet.get_price_worker()
    vesaf = price_worker["vesaf"]
    gold = price_worker["gold"]
    etf = price_worker["etf"]
    dcds = price_worker["dcds"]

    usd_to_vnd_rate = sheet.get_usd_to_vnd_rate()
    btc = sheet.get_price_btc(usd_to_vnd_rate)
    eth = sheet.get_price_eth(usd_to_vnd_rate)

    return (
        f"{category_display['price']}:\n"
        f"{category_display['vnd_to_usd']}: {usd_to_vnd_rate:,.2f} VND\n"
        f"{category_display['gold']}: {gold:,.0f} VND\n"
        f"{category_display['etf']}: {etf:,.0f} VND\n"
        f"{category_display['dcds']}: {dcds:,.0f} VND\n"
        f"{category_display['vesaf']}: {vesaf:,.0f} VND\n"
        f"{category_display['bitcoin']}: {btc:,.0f} VND\n"
        f"{category_display['ethereum']}: {eth:,.0f} VND\n"
    )


def get_price_btc(usd_to_vnd_rate: float) -> float:
    try:
        url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            price_usdt = float(data["data"]["amount"])
            price_vnd = price_usdt * usd_to_vnd_rate
            return price_vnd
        else:
            logger.error(
                f"Failed to fetch BTC price. Status code: {response.status_code}"
            )
            return 0.0
    except Exception as e:
        logger.error(f"Error fetching BTC price: {e}")
        return 0.0


def get_price_eth(usd_to_vnd_rate: float) -> float:
    try:
        url = "https://api.coinbase.com/v2/prices/ETH-USD/spot"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            price_usdt = float(data["data"]["amount"])
            price_vnd = price_usdt * usd_to_vnd_rate
            return price_vnd
        else:
            logger.error(
                f"Failed to fetch ETH price. Status code: {response.status_code}"
            )
            return 0.0
    except Exception as e:
        logger.error(f"Error fetching ETH price: {e}")
        return 0.0


def process_asset_unit(amount: float, price: float) -> float:
    """Process asset amount based on unit (e.g., grams for gold)"""
    try:
        unit = amount / price
        return round(unit, 4)
    except Exception as e:
        logger.error(f"Error processing asset unit: {e}")
        return 0.0


def get_usd_to_vnd_rate() -> float:
    """Fetch current USD to VND exchange rate from an external API"""
    try:
        url = (
            "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=vnd"
        )
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            rate = data["tether"]["vnd"]
            return rate
        else:
            logger.error(
                f"Failed to fetch USD to VND rate. Status code: {response.status_code}"
            )
            return 0.0
    except Exception as e:
        logger.error(f"Error fetching USD to VND rate: {e}")
        return 0.0


def prepare_asset_to_append(expense_data: dict, prices: AssetPrices) -> list:
    amount = int(expense_data["amount"])
    note = expense_data["note"]

    if sheet.has_keyword(note, ["vàng"]):
        price = prices["gold"]
    elif sheet.has_keyword(note, ["etf"]):
        price = prices["etf"]
    elif sheet.has_keyword(note, ["dcds"]):
        price = prices["dcds"]
    elif sheet.has_keyword(note, ["vesaf"]):
        price = prices["vesaf"]
    elif sheet.has_keyword(note, ["btc"]):
        price = prices["bitcoin"]
    elif sheet.has_keyword(note, ["eth"]):
        price = prices["ethereum"]

    unit = process_asset_unit(amount, price)

    asset_row = [
        f"{expense_data['entry_date']}/{expense_data['entry_year']}",
        expense_data["entry_time"],
        amount,
        note,
        unit,
    ]

    return asset_row


# helper to get profit response
async def get_profit_response() -> str:
    """Helper to calculate total assets from config"""
    try:
        sheet_name = config["settings"]["assets_sheet_name"]
        logger.info(f"Successfully obtained sheet for {sheet_name}")

        # sort
        try:
            await sheet.sort_assets_expenses_by_date()
        except Exception as sort_error:
            logger.error(f"Error sorting assets sheet {sheet_name}: {sort_error}")

        all_values = await asyncio.to_thread(sheet.get_cached_sheet_data, sheet_name)
        records = sheet.convert_values_to_asset_records(all_values)

        # asset
        assets_summary = get_assets_records_summary(records)

        # profit
        prices = prepare_prices()
        profit_summary = get_profit_asset_summary(records, prices)

        response = (
            f"{category_display["profit"]}: {profit_summary["total"]:,.0f} VND\n"
            f"🏦 Đầu tư dài hạn: \n"
            f"   ├─ 🏅 Vàng → {profit_summary["gold"]:,.0f} VND\n"
            f"   ├─ 🧾 ETF → {profit_summary["etf"]:,.0f} VND\n"
            f"   ├─ 📊 DCDS → {profit_summary["dcds"]:,.0f} VND\n"
            f"   └─ 📈 VESAF → {profit_summary["vesaf"]:,.0f} VND\n"
            f"🌐 Đầu tư cơ hội: \n"
            f"   ├─ ₿ Bitcoin → {profit_summary["bitcoin"]:,.0f} VND\n"
            f"   └─ ✨ Ethereum → {profit_summary["ethereum"]:,.0f} VND\n\n"
            f"\n📝 Chi tiết:\n"
            f"🏦 Đầu tư dài hạn: \n"
            f"   ├─ 🏅 Vàng → {profit_summary["gold"] - assets_summary["gold"]:,.0f} VND\n"
            f"   ├─ 🧾 ETF → {profit_summary["etf"] - assets_summary["etf"]:,.0f} VND\n"
            f"   ├─ 📊 DCDS → {profit_summary["dcds"] - assets_summary["dcds"]:,.0f} VND\n"
            f"   └─ 📈 VESAF → {profit_summary["vesaf"] - assets_summary["vesaf"]:,.0f} VND\n"
            f"🌐 Đầu tư cơ hội: \n"
            f"   ├─ ₿ Bitcoin → {profit_summary["bitcoin"] - assets_summary["bitcoin"]:,.0f} VND\n"
            f"   └─ ✨ Ethereum → {profit_summary["ethereum"] - assets_summary["ethereum"]:,.0f} VND\n\n"
        )

        return response

    except Exception as e:
        logger.error(f"Error calculating total assets: {e}", exc_info=True)
        return ""


def get_profit_asset_summary(
    records: list[sheet.AssetRecord], prices: AssetPrices
) -> dict:
    """Helper to get profit asset summary from records"""
    summary = {
        "gold": 0,
        "etf": 0,
        "dcds": 0,
        "vesaf": 0,
        "bitcoin": 0,
        "ethereum": 0,
        "expenses": [],
        "total": 0,
    }

    for r in records:
        note = r["note"].lower()
        unit = float(r.get("unit", 0))

        if unit == 0:
            continue

        summary["expenses"].append(r)

        if sheet.has_keyword(note, ["vàng"]):
            summary["gold"] += get_present_value(unit, prices["gold"])
        elif sheet.has_keyword(note, ["etf"]):
            summary["etf"] += get_present_value(unit, prices["etf"])
        elif sheet.has_keyword(note, ["dcds"]):
            summary["dcds"] += get_present_value(unit, prices["dcds"])
        elif sheet.has_keyword(note, ["vesaf"]):
            summary["vesaf"] += get_present_value(unit, prices["vesaf"])
        elif sheet.has_keyword(note, ["btc"]):
            summary["bitcoin"] += get_present_value(unit, prices["bitcoin"])
        elif sheet.has_keyword(note, ["eth"]):
            summary["ethereum"] += get_present_value(unit, prices["ethereum"])

    summary["total"] = (
        summary["gold"]
        + summary["etf"]
        + summary["dcds"]
        + summary["vesaf"]
        + summary["bitcoin"]
        + summary["ethereum"]
    )

    return summary


def get_present_value(unit: float, price: float) -> float:
    """Process total amount based on price"""
    try:
        total = unit * price
        return round(total, 2)
    except Exception as e:
        logger.error(f"Error processing total amount: {e}")
        return 0.0
