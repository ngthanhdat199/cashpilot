from dateutil.relativedelta import relativedelta
from src.track_py.utils.logger import logger
from src.track_py.utils.logger import logger
import src.track_py.const as const
import src.track_py.utils.util as util
import src.track_py.utils.sheet as sheet
from src.track_py.utils.category import category_display
from collections import defaultdict


def get_investment_response(offset: int) -> str:
    now = sheet.get_current_time() + relativedelta(months=offset)
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
