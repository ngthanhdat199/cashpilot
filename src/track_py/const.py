from src.track_py.config import config
from src.track_py.utils.version import get_version, get_build_time

# Global variable to store bot application - initialize it  immediately
bot_app = None
webhook_failures = 0
last_failure_time = None
use_fresh_bots = True  # Flag to enable/disable fresh bot instances

# Simple circuit breaker for webhook failures
MAX_FAILURES = 10
FAILURE_RESET_TIME = 300  # 5 minutes
TELEGRAM_TOKEN = config["telegram"]["bot_token"]
CHAT_ID = config["telegram"]["chat_id"]
WEBHOOK_URL = config["telegram"]["webhook_url"]
WSGI_FILE = "thanhdat19_pythonanywhere_com_wsgi.py"
HUGGING_FACE_TOKEN = config["hugging_face"]["token"]

# Get month name in Vietnamese
MONTH_NAMES = {
    "01": "tháng 1",
    "02": "tháng 2",
    "03": "tháng 3",
    "04": "tháng 4",
    "05": "tháng 5",
    "06": "tháng 6",
    "07": "tháng 7",
    "08": "tháng 8",
    "09": "tháng 9",
    "10": "tháng 10",
    "11": "tháng 11",
    "12": "tháng 12",
}

MONTH_NAMES_SHORT = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

SHORTCUTS = {
    "a": "ăn",
    "s": "ăn sáng",
    "t": "ăn trưa",
    "o": "ăn tối",
    "c": "cafe",
    "x": "xăng xe",
    "g": "grab",
    "b": "xe buýt",
    "n": "thuê nhà",
}


def format_shortcuts():
    lines = []
    for k, v in SHORTCUTS.items():
        lines.append(f"• {k} → {v}")
    return "\n".join(lines)


HELP_MSG = f"""
📖 Hướng dẫn sử dụng CashPilot

⚡ Danh sách shortcut:
{format_shortcuts()}

⏰ Ví dụ nhập nhanh:
• `5 c` → 5000 VND cafe  
• `15 t` → 15000 VND ăn trưa  
• `02/09 5 c` → 02/09 5000 VND cafe  
• `02/09 08:30 15 t` → 02/09 08:30 15000 VND ăn trưa  

📊 Lệnh thống kê:
• /today → Chi tiêu hôm nay (/t) 📅  
• /week → Chi tiêu tuần này (/w) 🗓️  
• /month → Chi tiêu tháng này (/m) 📆  

• /gas → Xăng xe (/g) ⛽  
• /food → Ăn uống (/f) 🍜  
• /dating → Hẹn hò/giải trí (/d) 🎉  
• /other → Khác (/o) 🛒  
• /investment → Đầu tư (/i) 📈  
• /ai → Phân tích chi tiêu (/a) 🤖

💰 Thu nhập:
• /salary [số tiền] → Ghi nhận lương (/sl) 🏢  
• /freelance [số tiền] → Ghi nhận freelance (/fl) 💻  
• /income → Tổng thu nhập (/inc) 💰  

🗑️ Xóa:
• del dd/mm hh:mm  

🤖 Bot tự động sắp xếp theo thời gian!  
📌 Phiên bản: {get_version()}
🕒 Thời gian build: {get_build_time()}
"""

LOG_EXPENSE_MSG = """
❌ Định dạng không đúng!

📖 Cách nhập hợp lệ:

🅰️ Case A: Mặc định (không ngày/giờ)
➡️ `1000 t` → dd:mm hh:mm:ss 1000 VND 

🅱️ Case B: Có ngày (mặc định 00:00:00)
📅 `02/09 5000 c` → 02/09 00:00:00 5000 VND 

🅾️ Case C: Có ngày + giờ
⏰ `02/09 08h30s10 10000 s` → 02/09 08:30:10 10000 VND 
"""

DELETE_EXPENSE_MSG = """
❌ Định dạng xóa không đúng!

🗑️ Cách xóa giao dịch:

🅰️ Case A: Chỉ nhập giờ (mặc định hôm nay)  
⏰ `del 08h30` → Xóa hôm nay lúc 08:30:00

🅱️ Case B: Ngày + Giờ  
📅 `del 14/10 00h11` → Xóa giao dịch ngày 14/10 lúc 00:11:00

🅾️ Case C: Ngày + Giờ + Giây (chính xác tuyệt đối)  
⏱️ `del 08h30s45` → Hôm nay lúc 08:30:45
⏱️ `del 14/10 10h30s45` → Ngày 14/10 lúc 10:30:45
"""

FOOD_KEYWORDS = ["ăn", "cơm", "hủ tiếu", "bánh cuốn", "uống", "nước"]
DATING_KEYWORDS = [
    "hanuri",
    "matcha",
    "lẩu",
    "cá",
    "ốc",
    "bingsu",
    "kem",
    "phở",
    "hải sản",
    "mì cay",
    "gà rán",
    "dimsum",
    "cafe",
    "xem phim",
    "cơm gà",
    "pizza",
    "hẹn hò",
    "date",
]
TRANSPORT_KEYWORDS = ["grab", "giao hàng", "taxi", "bus", "gửi xe", "xăng", "thay nhớt"]
LONG_INVEST_KEYWORDS = [
    "chứng khoán",
    "cổ phiếu",
    "etf",
    "ccq",
    "dcds",
    "vesaf",
    "vàng",
]
OPPORTUNITY_INVEST_KEYWORDS = [
    "crypto",
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
]
RENT_KEYWORD = ["thuê nhà"]
SUPPORT_PARENT_KEYWORDS = ["gửi mẹ"]

SALARY_CELL = "I2"
FREELANCE_CELL = "J2"
TOTAL_EXPENSE_CELL = "G2"
EXPECTED_HEADERS = [
    "Date",
    "Time",
    "VND",
    "Note",
    "Total per day",
    "SALARY",
    "FREELANCE",
]

# Category mappings with icons
FOOD_TRAVEL = "food_and_travel"
LONG_INVEST = "long_investment"
RENT = "rent"
OPPORTUNITY_INVEST = "opportunity_investment"
SUPPORT_PARENT = "support_parent"
DATING = "dating"

# Keywords mapping for categories
LIST_KEYWORDS = {
    FOOD_TRAVEL: FOOD_KEYWORDS,
    DATING: DATING_KEYWORDS,
    LONG_INVEST: LONG_INVEST_KEYWORDS,
    OPPORTUNITY_INVEST: OPPORTUNITY_INVEST_KEYWORDS,
    RENT: RENT_KEYWORD,
    SUPPORT_PARENT: SUPPORT_PARENT_KEYWORDS,
}

CATEGORY_ICONS = {
    FOOD_TRAVEL: "🍔/⛽",
    DATING: "💖",
    LONG_INVEST: "📈",
    OPPORTUNITY_INVEST: "🚀",
    RENT: "🏠",
    SUPPORT_PARENT: "👨‍👩‍👧‍👦",
    "food": "🍔",
    "gas": "⛽",
    "investment": "💹",
    "other": "🌟",
    "summarized": "📊",
    "spend": "💸",
    "income": "💵",
    "balance": "💰",
    "transaction": "📝",
    "detail": "🔍",
    "estimate_budget": "📌",
    "actual_spend": "🛒",
    "sheet": "📋",
    "compare": "⚖️",
    "start": "🚀",
    "help": "❓",
    "today": "📅",
    "week": "🗓️",
    "month": "📆",
    "freelance": "👨‍💻",
    "salary": "🏢",
    "sort": "🗂️",
    "ai": "🤖",
    "stats": "📊",
    "categories": "🗂",
    "total": "💲",
    "sync": "🔄",
    "keywords": "🔑",
    "asset": "💎",
    "migrate_assets": "🚚",
    "profit": "💰",
    "gold": "🏅",
    "etf": "🧾",
    "dcds": "📊",
    "vesaf": "📈",
    "bitcoin": "₿",
    "ethereum": "✨",
    "price": "💲",
    "vnd_to_usd": "💱",
}

CATEGORY_NAMES = {
    FOOD_TRAVEL: "Ăn uống & Đi lại",
    DATING: "Hẹn hò & Giải trí",
    LONG_INVEST: "Đầu tư dài hạn",
    OPPORTUNITY_INVEST: "Đầu tư cơ hội",
    RENT: "Thuê nhà",
    SUPPORT_PARENT: "Hỗ trợ ba mẹ",
    "food": "Ăn uống",
    "gas": "Xăng / Đi lại",
    "investment": "Đầu tư",
    "other": "Khác",
    "summarized": "Tổng kết",
    "spend": "Chi tiêu",
    "income": "Thu nhập",
    "transaction": "Giao dịch",
    "detail": "Chi tiết",
    "estimate_budget": "Ngân sách dự kiến (% thu nhập)",
    "actual_spend": "Chi tiêu thực tế",
    "sheet": "Bảng tính",
    "compare": "So sánh",
    "salary": "Lương",
    "freelance": "Làm thêm",
    "categories": "Danh mục",
    "total": "Tổng cộng",
    "balance": "Tiết kiệm",
    "sync": "Đồng bộ",
    "keywords": "Từ khoá",
    "asset": "Tài sản",
    "migrate_assets": "Di chuyển tài sản",
    "sort": "Sắp xếp",
    "profit": "Lợi nhuận",
    "gold": "Vàng",
    "etf": "ETF",
    "dcds": "DCDS",
    "vesaf": "VESAF",
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
    "price": "Giá",
    "vnd_to_usd": "Tỷ giá VND/USD",
}

CATEGORY_COLORS = {
    FOOD_TRAVEL: "#F59E0B",  # Warm orange
    RENT: "#10B981",  # Teal green
    LONG_INVEST: "#2563EB",  # Deep blue
    OPPORTUNITY_INVEST: "#8B5CF6",  # Violet / Indigo
    SUPPORT_PARENT: "#F9A8D4",  # Soft pink
    DATING: "#EC4899",  # Bright pink / coral
}

CATEGORY_CELLS = {
    FOOD_TRAVEL: "L2",
    RENT: "M2",
    LONG_INVEST: "N2",
    OPPORTUNITY_INVEST: "O2",
    SUPPORT_PARENT: "P2",
    DATING: "Q2",
}

LOG_ACTION = "lưu chi tiêu"
DELETE_ACTION = "xoá chi tiêu"
