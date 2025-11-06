from src.track_py.const import CATEGORY_ICONS, CATEGORY_NAMES, CATEGORY_CELLS
from src.track_py.utils import sheet, util


# Global dictionary to hold category display strings
category_display = {}


def get_categories_display() -> dict:
    rent_display = f"{CATEGORY_ICONS.get('rent')} {CATEGORY_NAMES.get('rent')}"
    support_parent_display = (
        f"{CATEGORY_ICONS.get('support_parent')} {CATEGORY_NAMES.get('support_parent')}"
    )
    dating_display = f"{CATEGORY_ICONS.get('dating')} {CATEGORY_NAMES.get('dating')}"
    long_investment_display = f"{CATEGORY_ICONS.get('long_investment')} {CATEGORY_NAMES.get('long_investment')}"
    opportunity_investment_display = f"{CATEGORY_ICONS.get('opportunity_investment')} {CATEGORY_NAMES.get('opportunity_investment')}"
    other_display = f"{CATEGORY_ICONS.get('other')} {CATEGORY_NAMES.get('other')}"
    food_display = f"{CATEGORY_ICONS.get('food')} {CATEGORY_NAMES.get('food')}"
    gas_display = f"{CATEGORY_ICONS.get('gas')} {CATEGORY_NAMES.get('gas')}"
    investment_display = (
        f"{CATEGORY_ICONS.get('investment')} {CATEGORY_NAMES.get('investment')}"
    )
    food_and_travel_display = f"{CATEGORY_ICONS.get('food_and_travel')} {CATEGORY_NAMES.get('food_and_travel')}"
    summarized_display = (
        f"{CATEGORY_ICONS.get('summarized')} {CATEGORY_NAMES.get('summarized')}"
    )
    spend_display = f"{CATEGORY_ICONS.get('spend')} {CATEGORY_NAMES.get('spend')}"
    income_display = f"{CATEGORY_ICONS.get('income')} {CATEGORY_NAMES.get('income')}"
    transaction_display = (
        f"{CATEGORY_ICONS.get('transaction')} {CATEGORY_NAMES.get('transaction')}"
    )
    detail_display = f"{CATEGORY_ICONS.get('detail')} {CATEGORY_NAMES.get('detail')}"
    estimate_budget_display = f"{CATEGORY_ICONS.get('estimate_budget')} {CATEGORY_NAMES.get('estimate_budget')}"
    actual_spend_display = (
        f"{CATEGORY_ICONS.get('actual_spend')} {CATEGORY_NAMES.get('actual_spend')}"
    )
    sheet_display = f"{CATEGORY_ICONS.get('sheet')} {CATEGORY_NAMES.get('sheet')}"
    compare_display = f"{CATEGORY_ICONS.get('compare')} {CATEGORY_NAMES.get('compare')}"
    categories_display = (
        f"{CATEGORY_ICONS.get('categories')} {CATEGORY_NAMES.get('categories')}"
    )
    total_display = f"{CATEGORY_ICONS.get('total')} {CATEGORY_NAMES.get('total')}"
    balance_display = f"{CATEGORY_ICONS.get('balance')} {CATEGORY_NAMES.get('balance')}"
    sync_display = f"{CATEGORY_ICONS.get('sync')} {CATEGORY_NAMES.get('sync')}"
    keywords_display = (
        f"{CATEGORY_ICONS.get('keywords')} {CATEGORY_NAMES.get('keywords')}"
    )
    asset_display = f"{CATEGORY_ICONS.get('asset')} {CATEGORY_NAMES.get('asset')}"
    migrate_assets_display = (
        f"{CATEGORY_ICONS.get('migrate_assets')} {CATEGORY_NAMES.get('migrate_assets')}"
    )
    sort_display = f"{CATEGORY_ICONS.get('sort')} {CATEGORY_NAMES.get('sort')}"
    salary_display = f"{CATEGORY_ICONS.get('salary')} {CATEGORY_NAMES.get('salary')}"
    freelance_display = (
        f"{CATEGORY_ICONS.get('freelance')} {CATEGORY_NAMES.get('freelance')}"
    )

    category_display = {
        "rent": rent_display,
        "food_and_travel": food_and_travel_display,
        "support_parent": support_parent_display,
        "dating": dating_display,
        "long_investment": long_investment_display,
        "opportunity_investment": opportunity_investment_display,
        "investment": investment_display,
        "food": food_display,
        "gas": gas_display,
        "other": other_display,
        "summarized": summarized_display,
        "spend": spend_display,
        "income": income_display,
        "transaction": transaction_display,
        "detail": detail_display,
        "estimate_budget": estimate_budget_display,
        "actual_spend": actual_spend_display,
        "sheet": sheet_display,
        "compare": compare_display,
        "categories": categories_display,
        "total": total_display,
        "balance": balance_display,
        "sync": sync_display,
        "keywords": keywords_display,
        "assets": asset_display,
        "migrate_assets": migrate_assets_display,
        "sort": sort_display,
        "salary": salary_display,
        "freelance": freelance_display,
    }

    return category_display


# Initialize category_display at module load time
try:
    category_display = get_categories_display()
except Exception as e:
    print(f"⚠️  Failed to get category display: {e}")
    exit(1)


async def get_categories_response() -> str:
    now = sheet.get_current_time()
    target_month = now.strftime("%m")
    year = now.strftime("%Y")
    month_display = util.get_month_display(target_month, year)
    sheet_name = f"{target_month}/{year}"
    category_percent = await sheet.get_category_percentages_by_sheet_name(sheet_name)

    response = f"{category_display['categories']} chi tiêu {month_display}:\n"
    for key in CATEGORY_CELLS.keys():
        icon = CATEGORY_ICONS[key]
        category = CATEGORY_NAMES[key]
        percent = category_percent[key]
        response += f"• {icon} {category}: {percent}%\n"

    return response
