import src.track_py.utils.sheet as sheet
from src.track_py.utils.logger import logger
import src.track_py.utils.util as util
from collections import defaultdict
from src.track_py.utils.category import category_display


def process_other_summary(month_offset: int) -> str:
    now = sheet.get_current_time() + sheet.relativedelta(months=month_offset)
    target_month = now.strftime("%m/%Y")
    previous_month = (now - sheet.relativedelta(months=1)).strftime("%m/%Y")

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
