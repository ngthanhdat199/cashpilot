import src.track_py.utils.sheet as sheet
import src.track_py.utils.sheet.process as process
from src.track_py.utils.category import get_categories_response
from ..cli import helper


async def handle_command(cmd: str) -> str:
    # Exact match
    if cmd in command_map:
        command_func = command_map[cmd]
        return await helper.handle_coroutine_command(command_func, cmd)

    # Match by prefix (e.g., "week 1", "month -1")
    base_command = cmd.split()[0]
    if base_command in command_map:
        command_func = command_map[base_command]
        return await helper.handle_coroutine_command(command_func, cmd)

    return f"Unknown command: {cmd}"


async def today() -> str:
    response = await sheet.process_today_summary()
    return response


async def week(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = await sheet.process_week_summary(offset)
    return response


def month(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.process_month_summary(offset)
    return response


def gas(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.process_gas_summary(offset)
    return response


def food(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.process_food_summary(offset)
    return response


def dating(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.process_dating_summary(offset)
    return response


def other(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.process_other_summary(offset)
    return response


def investment(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.get_investment_response(offset)
    return response


def freelance(cmd: str = "") -> str:
    parts = cmd.split()
    # /fl 200 -> offset=0, amount=200
    if len(parts) == 2:
        offset = 0
        amount = int(parts[1])
    # /fl 1 200 -> offset=1, amount=200
    elif len(parts) == 3:
        offset = int(parts[1])
        amount = int(parts[2])
    else:
        print("Usage: /freelance [amount]")
        exit(1)

    response = sheet.process_freelance(offset, amount)
    return response


def salary(cmd: str = "") -> str:
    parts = cmd.split()
    # /sl 200 -> offset=0, amount=200
    if len(parts) == 2:
        offset = 0
        amount = int(parts[1])
    # /sl 1 200 -> offset=1, amount=200
    elif len(parts) == 3:
        offset = int(parts[1])
        amount = int(parts[2])
    else:
        print("Usage: /salary [amount]")
        exit(1)

    response = sheet.process_salary(offset, amount)
    return response


def income(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = sheet.process_income_summary(offset)
    return response


async def sort(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = await sheet.sort_expenses_by_date(offset)
    return response


async def ai(cmd: str = "") -> str:
    offset = helper.get_offset_from_command(cmd)
    response = await sheet.get_ai_analyze_summary(offset)
    return response


async def categories() -> str:
    response = await get_categories_response()
    return response


def sync_config() -> str:
    response = sheet.sync_config_to_sheet()
    return response


def keywords() -> str:
    response = sheet.get_keywords_response()
    return response


async def assets() -> str:
    response = await sheet.get_assets_response()
    return response


def migrate_assets() -> str:
    response = sheet.migrate_assets_data()
    return response


def price() -> str:
    response = sheet.get_price_response()
    return response


async def profit() -> str:
    response = await sheet.get_profit_response()
    return response


async def test() -> str:
    response = ""

    for name, func in test_func.items():
        result = await helper.handle_coroutine_command(func)
        response += f"{name.capitalize()} Test Result:\n{result}\n\n"

    return response


test_func = {
    "today": today,
    "week": week,
    "month": month,
    "investment": investment,
    "sort": sort,
    "categories": categories,
    "keywords": keywords,
    "assets": assets,
    "price": price,
}


command_map = {
    "today": today,
    "week": week,
    "month": month,
    "gas": gas,
    "food": food,
    "dating": dating,
    "other": other,
    "investment": investment,
    "freelance": freelance,
    "salary": salary,
    "income": income,
    "sort": sort,
    "ai": ai,
    "categories": categories,
    "sync_config": sync_config,
    "keywords": keywords,
    "assets": assets,
    "migrate_assets": migrate_assets,
    "price": price,
    "profit": profit,
    "test": test,
}
