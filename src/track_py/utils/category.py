from src.track_py.const import CATEGORY_ICONS, CATEGORY_NAMES

# Global dictionary to hold category display strings
category_display = {} 

def get_categories_display():
    rent_display = f"{CATEGORY_ICONS.get('rent')} {CATEGORY_NAMES.get('rent')}"
    support_parent_display = f"{CATEGORY_ICONS.get('support_parent')} {CATEGORY_NAMES.get('support_parent')}"
    dating_display = f"{CATEGORY_ICONS.get('dating')} {CATEGORY_NAMES.get('dating')}"
    long_investment_display = f"{CATEGORY_ICONS.get('long_investment')} {CATEGORY_NAMES.get('long_investment')}"
    opportunity_investment_display = f"{CATEGORY_ICONS.get('opportunity_investment')} {CATEGORY_NAMES.get('opportunity_investment')}"
    other_display = f"{CATEGORY_ICONS.get('other')} {CATEGORY_NAMES.get('other')}"
    food_display = f"{CATEGORY_ICONS.get('food')} {CATEGORY_NAMES.get('food')}"
    gas_display = f"{CATEGORY_ICONS.get('gas')} {CATEGORY_NAMES.get('gas')}"
    investment_display = f"{CATEGORY_ICONS.get('investment')} {CATEGORY_NAMES.get('investment')}"
    food_travel_display = food_display + "/" + gas_display
    summarized_display = f"{CATEGORY_ICONS.get('summarized')} {CATEGORY_NAMES.get('summarized')}"
    spend_display = f"{CATEGORY_ICONS.get('spend')} {CATEGORY_NAMES.get('spend')}"
    income_display = f"{CATEGORY_ICONS.get('income')} {CATEGORY_NAMES.get('income')}"
    transaction_display = f"{CATEGORY_ICONS.get('transaction')} {CATEGORY_NAMES.get('transaction')}"
    detail_display = f"{CATEGORY_ICONS.get('detail')} {CATEGORY_NAMES.get('detail')}"
    estimate_budget_display = f"{CATEGORY_ICONS.get('estimate_budget')} {CATEGORY_NAMES.get('estimate_budget')}"
    actual_spend_display = f"{CATEGORY_ICONS.get('actual_spend')} {CATEGORY_NAMES.get('actual_spend')}"
    sheet_display = f"{CATEGORY_ICONS.get('sheet')} {CATEGORY_NAMES.get('sheet')}"
    compare_display = f"{CATEGORY_ICONS.get('compare')} {CATEGORY_NAMES.get('compare')}"
    categories_display = f"{CATEGORY_ICONS.get('categories')} {CATEGORY_NAMES.get('categories')}"
    total_display = f"{CATEGORY_ICONS.get('total')} {CATEGORY_NAMES.get('total')}"

    category_display = {
        "rent": rent_display,
        "food_travel": food_travel_display,
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
    }

    return category_display

# Initialize category_display at module load time
try:    
    category_display = get_categories_display()
except Exception as e:
    print(f"⚠️  Failed to get category display: {e}")
    exit(1)