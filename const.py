from config import config
from utils.version import get_version

# Global variable to store bot application - initialize it immediately
bot_app = None
webhook_failures = 0
last_failure_time = None
use_fresh_bots = True  # Flag to enable/disable fresh bot instances

# Simple circuit breaker for webhook failures
MAX_FAILURES = 10
FAILURE_RESET_TIME = 300  # 5 minutes
TOKEN = config["telegram"]["bot_token"]
WEBHOOK_URL = config["telegram"]["webhook_url"]
PROJECT_HOME = '/home/thanhdat19/track-money'
WSGI_FILE = 'thanhdat19_pythonanywhere_com_wsgi.py'

# Get month name in Vietnamese
MONTH_NAMES = {
    "01": "tháng 1", "02": "tháng 2", "03": "tháng 3", "04": "tháng 4",
    "05": "tháng 5", "06": "tháng 6", "07": "tháng 7", "08": "tháng 8", 
    "09": "tháng 9", "10": "tháng 10", "11": "tháng 11", "12": "tháng 12"
}

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
📖 Hướng dẫn sử dụng Money Tracker Bot

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

💰 Thu nhập:
• /salary [số tiền] → Ghi nhận lương (/sl) 🏢  
• /freelance [số tiền] → Ghi nhận freelance (/fl) 💻  
• /income → Tổng thu nhập (/inc) 💰  

🗑️ Xóa:
• del dd/mm hh:mm  

🤖 Bot tự động sắp xếp theo thời gian!  
📌 Phiên bản: {get_version()}
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
DATING_KEYWORDS = ["hanuri", "matcha", "lẩu", "cá", "ốc", "bingsu", "kem", "phở", "hải sản", "mì cay", "gà rán", "dimsum", "cafe", "xem phim", "cơm gà", "pizza", "hẹn hò", "date"]
TRANSPORT_KEYWORDS = ["grab", "giao hàng", "taxi", "bus", "gửi xe", "xăng"]
LONG_INVEST_KEYWORDS = ["chứng khoán",  "cổ phiếu",  "etf"]
OPPORTUNITY_INVEST_KEYWORDS = ["bitcoin", "eth", "crypto"]
RENT_KEYWORD = ["thuê nhà"]
SUPPORT_PARENT_KEYWORDS = ["gửi mẹ"]
SALARY_CELL = "I2"
FREELANCE_CELL = "J2"
EXPECTED_HEADERS = ["Date", "Time", "VND", "Note", "Total per day", "SALARY", "FREELANCE"]
