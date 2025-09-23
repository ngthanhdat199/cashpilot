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

HELP_MSG = f"""
📖 Hướng dẫn sử dụng Money Tracker Bot:

⚡ ULTRA-FAST TYPING MODES:
• 5 → Hiện buttons: Cafe/Ăn/Xăng/Grab
• 15 → Chọn 1 click, xong!
• 200 → Tự động nhân 1000 nếu cần

⚡ Mode 2: SIÊU NGẮN (1-2 ký tự)
• 5 c → 5000 VND cafe
• 15 s → 15000 VND ăn sang  
• 30 t → 30000 VND ăn trưa
• 50 o → 50000 VND ăn tối
• 200 x → 200000 VND xăng xe
• 2m g → 2000000 VND grab

⚡ Mode 3: EMOJI SHORTCUTS
• 5 ☕ → 5000 VND cafe
• 15 🍽️ → 15000 VND ăn
• 200 ⛽ → 200000 VND xăng xe
• 50 🚗 → 50000 VND grab

⏰ Với ngày/giờ:
• 02/09 5 c → 02/09 5000 VND cafe
• 02/09 08:30 15 t → 02/09 08:30 15000 VND ăn trưa

📊 Lệnh thống kê:
• /today - Chi tiêu hôm nay (/t) 📅
• /week - Chi tiêu tuần này  (/w) 🗓️
• /month - Chi tiêu tháng này (/m) 📆

• /gas - Chi tiêu xăng xe tháng này (/g) ⛽
• /food - Chi tiêu ăn uống tháng này (/f) 🍜
• /dating - Chi tiêu hẹn hò/giải trí tháng này (/d) 🎉
• /other - Chi tiêu khác tháng này (/o) 🛒
• /investment - Chi tiêu đầu tư tháng này (/i) 📈

• /freelance [amount] - Ghi nhận thu nhập freelance (/fl [số tiền]) 💻
• /income - Hiện tổng thu nhập tháng này (/inc) 💰


🗑️ Xóa: del dd/mm hh:mm

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

🔑 Shortcuts:  
☕ c = cafe  
🍽️ a = ăn  
🥐 s = ăn sáng  
🍱 t = ăn trưa  
🍲 o = ăn tối  
⛽ x = xăng 
🚗 g = grab  
🚌 b = bus
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