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


# helper for month response
def get_month_response(
    records: list[sheet.Record],
    current_sheet: gspread.Worksheet,
    time_with_offset: datetime.datetime,
) -> str:
    summary = sheet.get_records_summary_by_cat(records)
    month_expenses = summary["expenses"]
    total = summary["total"]
    food_total = summary["food"]
    dating_total = summary["dating"]
    gas_total = summary["gas"]
    rent_total = summary["rent"]
    other_total = summary["other"]
    long_invest_total = summary["long_investment"]
    opportunity_invest_total = summary["opportunity_investment"]
    investment_total = summary["investment"]
    support_parent_total = summary["support_parent"]
    food_and_travel_total = food_total + gas_total + other_total

    total_income = sheet.get_month_budget_by_sheet(current_sheet)

    category_budget = sheet.get_category_percentages_by_sheet(current_sheet)
    food_and_travel_budget = category_budget[const.FOOD_TRAVEL]
    rent_budget = category_budget[const.RENT]
    long_invest_budget = category_budget[const.LONG_INVEST]
    opportunity_invest_budget = category_budget[const.OPPORTUNITY_INVEST]
    support_parent_budget = category_budget[const.SUPPORT_PARENT]
    dating_budget = category_budget[const.DATING]

    count = len(month_expenses)
    month = time_with_offset.strftime("%m")
    year = time_with_offset.strftime("%Y")
    month_display = util.get_month_display(month, year)

    # Calculate estimated amounts based on percentages and income
    food_and_travel_estimate = (
        total_income * (food_and_travel_budget / 100) if total_income > 0 else 0
    )
    rent_estimate = total_income * (rent_budget / 100) if total_income > 0 else 0
    long_invest_estimate = (
        total_income * (long_invest_budget / 100) if total_income > 0 else 0
    )
    opportunity_invest_estimate = (
        total_income * (opportunity_invest_budget / 100) if total_income > 0 else 0
    )
    support_parent_estimate = (
        total_income * (support_parent_budget / 100) if total_income > 0 else 0
    )
    dating_estimate = total_income * (dating_budget / 100) if total_income > 0 else 0

    response = (
        f"{category_display['summarized']} {month_display}:\n"
        f"{category_display['income']}: {total_income:,.0f} VND\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['balance']}: {total_income - total:,.0f} VND\n\n"
        f"{category_display['estimate_budget']}:\n"
        f"{category_display['rent']}: {rent_budget:.0f}% = {rent_estimate:,.0f} VND\n"
        f"{category_display['food_and_travel']}: {food_and_travel_budget:.0f}% = {food_and_travel_estimate:,.0f} VND\n"
        f"{category_display['support_parent']}: {support_parent_budget:.0f}% = {support_parent_estimate:,.0f} VND\n"
        f"{category_display['dating']}: {dating_budget:.0f}% = {dating_estimate:,.0f} VND\n"
        f"{category_display['long_investment']}: {long_invest_budget:.0f}% = {long_invest_estimate:,.0f} VND\n"
        f"{category_display['opportunity_investment']}: {opportunity_invest_budget:.0f}% = {opportunity_invest_estimate:,.0f} VND\n\n"
        f"{category_display['actual_spend']}:\n"
        f"{category_display['rent']}: {rent_total:,.0f} VND ({rent_estimate - rent_total:+,.0f})\n"
        f"{category_display['food_and_travel']}: {food_and_travel_total:,.0f} VND ({food_and_travel_estimate - food_and_travel_total:+,.0f})\n"
        f"{category_display['support_parent']}: {support_parent_total:,.0f} VND ({support_parent_estimate - support_parent_total:+,.0f})\n"
        f"{category_display['dating']}: {dating_total:,.0f} VND ({dating_estimate - dating_total:+,.0f})\n"
        f"{category_display['long_investment']}: {long_invest_total:,.0f} VND ({long_invest_estimate - long_invest_total:+,.0f})\n"
        f"{category_display['opportunity_investment']}: {opportunity_invest_total:,.0f} VND ({opportunity_invest_estimate - opportunity_invest_total:+,.0f})\n\n"
        f"{category_display['detail']}:\n"
        f"{category_display['rent']}: {rent_total:,.0f} VND\n"
        f"{category_display['food']}: {food_total:,.0f} VND\n"
        f"{category_display['gas']}: {gas_total:,.0f} VND\n"
        f"{category_display['support_parent']}: {support_parent_total:,.0f} VND\n"
        f"{category_display['dating']}: {dating_total:,.0f} VND\n"
        f"{category_display['investment']}: {investment_total:,.0f} VND\n"
        f"{category_display['other']}: {other_total:,.0f} VND\n"
    )

    return response


async def get_ai_analyze_summary(month_offset) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")

    logger.info(f"Getting month expenses for sheet {target_month}")

    try:
        current_sheet = await asyncio.to_thread(
            sheet.get_cached_worksheet, target_month
        )
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error getting/creating sheet {target_month}: {sheet_error}",
            exc_info=True,
        )
        return

    try:
        all_values = await asyncio.to_thread(sheet.get_cached_sheet_data, target_month)
        logger.info(f"Retrieved {len(all_values)} records from sheet")
    except Exception as records_error:
        logger.error(
            f"Error retrieving records from sheet: {records_error}", exc_info=True
        )
        return

    records = sheet.convert_values_to_records(all_values)
    raw_data = get_month_response(records, current_sheet, now)

    client = InferenceClient(token=const.HUGGING_FACE_TOKEN)
    model = "meta-llama/Llama-3.1-8B-Instruct"

    # Use chat_completion for instruction/chat models
    ai_response = client.chat_completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Bạn là một trợ lý tài chính cá nhân thông minh, phản hồi hoàn toàn bằng tiếng Việt. "
                    "Phân tích dữ liệu chi tiêu hàng tháng (bao gồm thu nhập, ngân sách và chi tiêu thực tế) để đưa ra phân tích và khuyến nghị.\n\n"
                    "⚙️ Quy ước dữ liệu:\n"
                    "- Mỗi dòng chi tiêu có dạng: <Tên hạng mục>: <Chi tiêu thực tế> VND (<Chênh lệch>)\n"
                    "- Giá trị trong ngoặc thể hiện CHÊNH LỆCH giữa chi tiêu thực tế và ngân sách:\n"
                    "    • Dấu (+) nghĩa là chi tiêu ÍT HƠN ngân sách (TIẾT KIỆM)\n"
                    "    • Dấu (-) nghĩa là chi tiêu NHIỀU HƠN ngân sách (VƯỢT CHI)\n"
                    "- Ví dụ: (+1,000,000) = tiết kiệm 1 triệu. (-500,000) = vượt ngân sách 500 nghìn.\n\n"
                    "⚙️ Phân tích yêu cầu:\n"
                    "1️⃣ Xác định các hạng mục chi vượt ngân sách (dấu -) và hạng mục tiết kiệm (dấu +), nêu rõ số tiền chênh lệch.\n"
                    "2️⃣ So sánh tổng chi tiêu và thu nhập để xác định thặng dư hoặc thâm hụt.\n"
                    "3️⃣ Phát hiện 2–3 xu hướng nổi bật trong chi tiêu.\n"
                    "4️⃣ Đưa ra 2–3 khuyến nghị cụ thể giúp cải thiện cân bằng tài chính.\n\n"
                    "📋 Định dạng đầu ra (HTML-friendly cho Telegram):\n"
                    "🧾 <b>Tóm tắt:</b> Một đoạn ngắn mô tả tình hình tài chính tháng.\n"
                    "📊 <b>Phân tích chi tiêu vượt ngân sách:</b> Liệt kê rõ từng mục vượt và tiết kiệm.\n"
                    "📈 <b>Xu hướng chi tiêu:</b> 2–3 xu hướng nổi bật.\n"
                    "💡 <b>Khuyến nghị:</b> 2–3 gợi ý cụ thể.\n\n"
                    "💬 <b>Yêu cầu:</b>\n"
                    "- Giọng văn thân thiện, chuyên nghiệp, có cảm xúc.\n"
                    "- Sử dụng emoji phù hợp (🧾📊📈💡💰✨...) để tăng tính dễ đọc.\n"
                ),
            },
            {"role": "user", "content": f"{raw_data}"},
        ],
        max_tokens=1000,
    )

    summary = markdown_to_html(ai_response["choices"][0]["message"]["content"].strip())
    return summary


def process_income_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting income summary for sheet {target_month}")

    try:
        current_sheet = sheet.get_cached_worksheet(target_month)
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error getting/creating sheet {target_month}: {sheet_error}",
            exc_info=True,
        )
        exit(1)

    try:
        previous_sheet = sheet.get_cached_worksheet(previous_month)
        logger.info(f"Successfully obtained sheet for {previous_month}")
    except Exception as prev_sheet_error:
        logger.error(
            f"Error getting/creating sheet {previous_month}: {prev_sheet_error}",
            exc_info=True,
        )
        exit(1)

    # Get income from current month's sheet
    freelance_income = current_sheet.acell(const.FREELANCE_CELL).value
    salary_income = current_sheet.acell(const.SALARY_CELL).value

    if not freelance_income or freelance_income.strip() == "":
        logger.info("Freelance income cell is empty, using config fallback")
        exit(1)

    if not salary_income or salary_income.strip() == "":
        logger.info("Salary income cell is empty, using config fallback")
        exit(1)

    freelance_income = sheet.safe_int(freelance_income)
    salary_income = sheet.safe_int(salary_income)

    # Get income from previous month's sheet for comparison
    prev_freelance_income = previous_sheet.acell(const.FREELANCE_CELL).value
    prev_salary_income = previous_sheet.acell(const.SALARY_CELL).value

    if not prev_freelance_income or prev_freelance_income.strip() == "":
        logger.info("Previous freelance income cell is empty, using config fallback")
        prev_freelance_income = 0

    if not prev_salary_income or prev_salary_income.strip() == "":
        logger.info("Previous salary income cell is empty, using config fallback")
        prev_salary_income = 0

    prev_freelance_income = sheet.safe_int(prev_freelance_income)
    prev_salary_income = sheet.safe_int(prev_salary_income)

    prev_total_income = prev_freelance_income + prev_salary_income
    total_income = freelance_income + salary_income

    # Calculate percentage change
    if prev_total_income > 0:
        percentage_change = (
            (total_income - prev_total_income) / prev_total_income
        ) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    summary = (
        f"{category_display['income']} {month_display}:\n"
        f"{category_display['salary']}: {salary_income:,.0f} VND\n"
        f"{category_display['freelance']}: {freelance_income:,.0f} VND\n"
        f"{category_display['total']}: {total_income:,.0f} VND\n"
        f"{category_display['compare']} {previous_month}: {total_income - prev_total_income:+,.0f} VND {percentage_text}\n"
    )

    return summary


def process_salary(month_offset: int, amount: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    target_year = now.strftime("%Y")
    month_display = util.get_month_display(target_month, target_year)
    current_sheet = sheet.get_cached_worksheet(target_month)

    amount = amount * 1000
    current_sheet.update_acell(const.SALARY_CELL, amount)

    if month_offset == 0:
        # Update config
        config["income"]["salary"] = amount
        save_config()

    response = f"✅ Đã ghi nhận thu nhập lương {month_display}: {amount:,.0f} VND"
    return response


def process_freelance(month_offset: int, amount: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    target_year = now.strftime("%Y")
    month_display = util.get_month_display(target_month, target_year)
    current_sheet = sheet.get_cached_worksheet(target_month)

    amount = amount * 1000
    current_sheet.update_acell(const.FREELANCE_CELL, amount)

    # Update config
    if month_offset == 0:
        config["income"]["freelance"] = amount
        save_config()

    response = f"✅ Đã ghi nhận thu nhập freelance {month_display}: {amount:,.0f} VND"
    return response


def process_other_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting other expenses for sheet {target_month}")

    other_expenses, total = sheet.get_other_total(target_month)
    count = len(other_expenses)
    logger.info(f"Found {count} other expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in other_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += sheet.format_expense(r, i) + "\n"

    _, previous_total = sheet.get_other_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['other']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_dating_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting dating expenses for sheet {target_month}")

    dating_expenses, total = sheet.get_dating_total(target_month)
    count = len(dating_expenses)
    logger.info(f"Found {count} dating expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in dating_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += sheet.format_expense(r, i) + "\n"

    _, previous_total = sheet.get_dating_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['dating']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_food_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting food expenses for sheet {target_month}")

    food_expenses, total = sheet.get_food_total(target_month)
    count = len(food_expenses)
    logger.info(f"Found {count} food expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in food_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += sheet.format_expense(r, i) + "\n"

    _, previous_total = sheet.get_food_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['food']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_gas_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting gas expenses for sheet {target_month}")

    gas_expenses, total = sheet.get_gas_total(target_month)
    count = len(gas_expenses)
    logger.info(f"Found {count} gas expenses for this month with total {total} VND")

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in gas_expenses:
        grouped[r.get("Date", "")].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += sheet.format_expense(r, i) + "\n"

    _, previous_total = sheet.get_gas_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    summary = (
        f"{category_display['gas']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n"
    )

    if details:
        summary += f"\n📝 Chi tiết:{details}"

    return summary


def process_month_summary(month_offset: int) -> str:
    now = get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")

    logger.info(f"Getting month expenses for sheet {target_month}")

    try:
        current_sheet = sheet.get_cached_worksheet(target_month)
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error obtaining sheet for {target_month}: {sheet_error}",
            exc_info=True,
        )
        exit(1)

    try:
        all_values = sheet.get_cached_sheet_data(target_month)
        logger.info(f"Retrieved {len(all_values)} records from sheet")
    except Exception as records_error:
        logger.error(
            f"Error retrieving records from sheet: {records_error}",
            exc_info=True,
        )
        exit(1)

    records = sheet.convert_values_to_records(all_values)
    response = get_month_response(records, current_sheet, now)
    return response


async def process_week_summary(week_offset: int) -> str:
    now = get_current_time() + datetime.timedelta(weeks=week_offset)
    week_data = await sheet.get_week_process_data(now)
    total = week_data["total"]
    week_expenses = week_data["week_expenses"]
    count = len(week_expenses)
    week_start = week_data["week_start"]
    week_end = week_data["week_end"]

    grouped = defaultdict(list)
    for r in week_expenses:
        date_str = r["expense_date"].strftime("%d/%m/%Y")
        grouped[date_str].append(r)

    details_lines = []
    for day, rows in sorted(
        grouped.items(),
        key=lambda d: datetime.datetime.strptime(d[0], "%d/%m/%Y"),
    ):
        day_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
        details_lines.append(f"\n📅 {day}: {day_total:,.0f} VND")
        details_lines.extend(
            "\n" + sheet.format_expense(r, i) for i, r in enumerate(rows, start=1)
        )
        details_lines.append("\n")

    summay = (
        f"{category_display['summarized']} tuần này ({week_start:%d/%m} - {week_end:%d/%m}):\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
    )

    if details_lines:
        summay += f"\n📝 Chi tiết:{''.join(details_lines)}"

    return summay


async def process_today_summary() -> str:
    now = get_current_time()
    today_data = await sheet.get_daily_process_data(now)
    total = today_data["total"]
    today_expenses = today_data["today_expenses"]
    count = len(today_expenses)
    today_str = today_data["date_str"]

    summary = (
        f"{category_display['summarized']} hôm nay ({today_str}):\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
    )

    if today_expenses:
        details = "\n".join(
            sheet.format_expense(r, i + 1) for i, r in enumerate(today_expenses)
        )
        summary += f"\n📝 Chi tiết:\n{details}"

    return summary


def get_investment_response(month_offset: int) -> str:
    now = sheet.get_current_time() + relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - relativedelta(months=1)).strftime("%m/%Y")

    logger.info(f"Getting investment expenses for sheet {target_month}")

    try:
        current_sheet = sheet.get_cached_worksheet(target_month)
        logger.info(f"Successfully obtained sheet for {target_month}")
    except Exception as sheet_error:
        logger.error(
            f"Error getting/creating sheet {target_month}: {sheet_error}",
            exc_info=True,
        )
        exit(1)

    investment_expenses, total = sheet.get_investment_total(target_month)
    count = len(investment_expenses)
    logger.info(
        f"Found {count} investment expenses for this month with total {total} VND"
    )

    current_month = now.strftime("%m")
    current_year = now.strftime("%Y")
    month_display = util.get_month_display(current_month, current_year)

    grouped = defaultdict(list)
    for r in investment_expenses:
        date_str = r["date"]
        grouped[date_str].append(r)

    details = ""
    for day, rows in sorted(grouped.items()):
        day_total = sum(sheet.parse_amount(r["vnd"]) for r in rows)
        details += f"\n📅 {day}: {day_total:,.0f} VND\n"
        for i, r in enumerate(rows, start=1):
            details += sheet.format_expense(r, i) + "\n"

    _, previous_total = sheet.get_investment_total(previous_month)

    # Calculate percentage change
    if previous_total > 0:
        percentage_change = ((total - previous_total) / previous_total) * 100
        change_symbol = (
            "📈" if percentage_change > 0 else "📉" if percentage_change < 0 else "➡️"
        )
        percentage_text = f" ({change_symbol} {percentage_change:+.1f}%)"
    else:
        percentage_text = ""

    # Get income from sheet
    total_income = sheet.get_total_income(current_sheet)
    long_invest_budget = sheet.get_category_percentage(current_sheet, const.LONG_INVEST)
    opportunity_invest_budget = sheet.get_category_percentage(
        current_sheet, const.OPPORTUNITY_INVEST
    )
    long_invest_estimate = total_income * long_invest_budget if total_income > 0 else 0
    opportunity_invest_estimate = (
        total_income * opportunity_invest_budget if total_income > 0 else 0
    )

    response = (
        f"{category_display['investment']} {month_display}:\n"
        f"{category_display['spend']}: {total:,.0f} VND\n"
        f"{category_display['transaction']}: {count}\n"
        f"{category_display['compare']} {previous_month}: {total - previous_total:+,.0f} VND {percentage_text}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 Phân bổ danh mục\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Danh mục đầu tư\n\n"
        f"🏦 Đầu tư dài hạn (CCQ): {long_invest_estimate:,.0f} VND\n"
        f"   ├─ 📊 DCDS (50%) → {long_invest_estimate * 0.5:,.0f} VND\n"
        f"   └─ 📈 VESAF (50%) → {long_invest_estimate * 0.5:,.0f} VND\n\n"
        f"🌐 Đầu tư cơ hội (Crypto): {opportunity_invest_estimate:,.0f} VND\n"
        f"   ├─ ₿ Bitcoin (70%) → {opportunity_invest_estimate * 0.7:,.0f} VND\n"
        f"   └─ ✨ Ethereum (30%) → {opportunity_invest_estimate * 0.3:,.0f} VND\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 Lịch sử giao dịch\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if details:
        response += details

    return response


def get_keywords_response() -> str:
    keywords = const.LIST_KEYWORDS
    message_lines = [f"{category_display['keywords']}\n"]

    for category, words in keywords.items():
        icon = const.CATEGORY_ICONS.get(category, "🏷️")
        category_name = const.CATEGORY_NAMES.get(category, category)

        # Category header
        message_lines.append(f"{icon} {category_name}")
        message_lines.append("-" * 35)

        # Format keywords in 2–3 columns
        per_line = 3
        for i in range(0, len(words), per_line):
            chunk = " • ".join(words[i : i + per_line])
            message_lines.append(f"   {chunk}")

        message_lines.append("")  # Add spacing between categories

    # Wrap entire message in a Telegram code block
    response = "```\n" + "\n".join(message_lines) + "\n```"

    return response
