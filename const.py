from config import config
from utils.version import get_version

# Global variable to store bot application - initialize it immediately
bot_app = None

# Simple circuit breaker for webhook failures
webhook_failures = 0
last_failure_time = None
MAX_FAILURES = 10
FAILURE_RESET_TIME = 300  # 5 minutes
use_fresh_bots = True  # Flag to enable/disable fresh bot instances

TOKEN = config["telegram"]["bot_token"]
WEBHOOK_URL = config["telegram"]["webhook_url"]
PROJECT_HOME = '/home/thanhdat19/track-money'

# Get month name in Vietnamese
month_names = {
    "01": "Tháng 1", "02": "Tháng 2", "03": "Tháng 3", "04": "Tháng 4",
    "05": "Tháng 5", "06": "Tháng 6", "07": "Tháng 7", "08": "Tháng 8", 
    "09": "Tháng 9", "10": "Tháng 10", "11": "Tháng 11", "12": "Tháng 12"
}

help_msg = f"""
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
• /today - Chi tiêu hôm nay
• /week - Chi tiêu tuần này  
• /month - Chi tiêu tháng này
• /gas - Chi tiêu xăng xe tháng này

🗑️ Xóa: del dd/mm hh:mm

🤖 Bot tự động sắp xếp theo thời gian!
📌 Phiên bản: {get_version()}
"""

log_expense_msg = """
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

delete_expense_msg = """
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