# 💰 CashPilot

A Vietnamese Telegram bot for tracking personal expenses and income with Google Sheets integration. This bot helps you log daily expenses, categorize spending, and analyze your financial habits through an intuitive Telegram interface.

## 🌟 Features

### 💸 Expense Tracking
- **Quick Logging**: Log expenses with simple commands like `100 ăn` or `50k xăng`
- **Smart Shortcuts**: Use single letters for common expenses (a → ăn, x → xăng xe, etc.)
- **Auto Categorization**: Automatically categorizes expenses (food, gas, dating, other, investment)
- **Delete Function**: Remove incorrect entries easily

### 📊 Analytics & Reports
- **Daily Summary** (`/today`): View today's expenses
- **Weekly Report** (`/week`): Weekly spending overview  
- **Monthly Report** (`/month`): Complete monthly breakdown
- **Category Totals**: Get totals by category (`/food`, `/gas`, `/dating`, etc.)
- **Investment Tracking** (`/investment`): Track investment expenses
- **Income Management** (`/income`): Monitor salary and freelance income

### 🔧 Smart Features
- **Google Sheets Integration**: All data automatically synced to Google Sheets
- **Webhook Support**: Real-time updates via webhooks
- **Multi-format Support**: Accepts various number formats (100, 100k, 100.000)
- **Time Zone Support**: Vietnam timezone (Asia/Ho_Chi_Minh)
- **Error Handling**: Robust error handling with user-friendly messages

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Telegram Bot Token
- Google Sheets API credentials
- Flask (for webhook support)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd track-py
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup Configuration**
   - Copy and edit `config.json` with your credentials:
   ```json
   {
     "telegram": {
       "bot_token": "YOUR_BOT_TOKEN",
       "webhook_url": "YOUR_WEBHOOK_URL"
     },
     "google_sheets": {
       "spreadsheet_id": "YOUR_SPREADSHEET_ID",
       "credentials_file": "credentials.json"
     }
   }
   ```

4. **Add Google Sheets Credentials**
   - Download service account credentials from Google Cloud Console
   - Save as `credentials.json` in the project root
   - Share your Google Sheet with the service account email

5. **Run the Bot**
   ```bash
   python main.py
   ```

## 📱 Bot Commands

### Basic Commands
- `/start` - Initialize bot and show keyboard
- `/help` - Show help message
- `/today` or `/t` - Today's expenses
- `/week` or `/w` - This week's summary
- `/month` or `/m` - This month's summary

### Expense Categories
- `/gas` or `/g` - Gas/transport expenses
- `/food` or `/f` - Food expenses  
- `/dating` or `/d` - Dating expenses
- `/other` or `/o` - Other expenses
- `/investment` or `/i` - Investment expenses

### Income Tracking
- `/income` or `/inc` - View income summary
- `/salary` or `/sl` - Set/view salary
- `/freelance` or `/fl` - Set/view freelance income

### Utility Commands
- `/sort` or `/s` - Sort current month's data

## 💬 Usage Examples

### Logging Expenses
```
100 ăn          → Log 100k for food
50k xăng        → Log 50k for gas
200 grab        → Log 200k for transportation
a 30            → Quick shortcut: 30k for food (ăn)
x 100           → Quick shortcut: 100k for gas (xăng xe)
```

### Shortcuts
- `a` → ăn (food)
- `s` → ăn sáng (breakfast)
- `t` → ăn trưa (lunch)  
- `o` → ăn tối (dinner)
- `c` → cafe
- `x` → xăng xe (gas)
- `g` → grab
- `b` → xe buýt (bus)
- `n` → thuê nhà (rent)

### Deleting Expenses
```
delete 100 ăn   → Remove expense entry
xóa 50k xăng    → Remove gas expense
```

## 🏗️ Project Structure

```
track-py/
├── main.py              # Main application entry point
├── bot.py               # Bot setup and configuration
├── handlers.py          # Command and message handlers
├── webhook.py           # Flask webhook server
├── config.py            # Configuration management
├── const.py             # Constants and global variables
├── requirements.txt     # Python dependencies
├── config.json          # Bot configuration
├── credentials.json     # Google Sheets credentials
├── utils/
│   ├── logger.py        # Logging utilities
│   ├── sheet.py         # Google Sheets integration
│   ├── timezone.py      # Timezone handling
│   └── version.py       # Version management
└── README.md
```

## 🔧 Configuration

### Environment Variables
- `PORT` - Flask server port (default: 5000)

### Config File (`config.json`)
```json
{
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN",
    "webhook_url": "YOUR_WEBHOOK_URL"
  },
  "google_sheets": {
    "spreadsheet_id": "YOUR_SPREADSHEET_ID",
    "credentials_file": "credentials.json",
    "scopes": [
      "https://spreadsheets.google.com/feeds",
      "https://www.googleapis.com/auth/drive"
    ]
  },
  "settings": {
    "logging_level": "INFO",
    "template_sheet_name": "template",
    "timezone": "Asia/Ho_Chi_Minh"
  },
  "income": {
    "salary": 15849000,
    "freelance": 0
  }
}
```

## 📊 Google Sheets Integration

The bot automatically creates monthly sheets in your Google Spreadsheet with the following structure:
- **Date/Time columns**: Timestamp of each expense
- **Amount**: Expense amount in VND
- **Description**: What you spent money on
- **Category**: Auto-categorized (food, gas, dating, etc.)
- **Monthly summaries**: Automatic totals and categorization

## 🌐 Webhook Deployment

For production deployment with webhooks:

1. Deploy to a hosting service (PythonAnywhere, Heroku, etc.)
2. Set your webhook URL in `config.json`
3. Visit `/set_webhook` endpoint to configure the webhook
4. The bot will receive real-time updates via webhooks

## 🛠️ Development

### Running Locally
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

### Using Makefile
```bash
make run  # Runs the application using .venv/bin/python
```

## 📝 Logging

The bot includes comprehensive logging:
- All user interactions are logged
- Error handling with detailed stack traces
- Google Sheets API calls are monitored
- Webhook events are tracked

Logs help with debugging and monitoring bot usage patterns.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🐛 Troubleshooting

### Common Issues

1. **Google Sheets Connection Error**
   - Ensure `credentials.json` is in the project root
   - Check that the spreadsheet is shared with your service account email
   - Verify the spreadsheet ID in `config.json`

2. **Telegram Bot Not Responding**
   - Verify bot token in `config.json`
   - Check if webhook URL is accessible
   - Review logs for error messages

3. **Webhook Issues**
   - Ensure your server is publicly accessible
   - Check SSL certificate if using HTTPS
   - Visit `/set_webhook` to reconfigure

## 📞 Support

If you encounter any issues or have questions, please:
1. Check the troubleshooting section above
2. Review the logs for error messages
3. Create an issue in the repository
4. Contact the maintainer

---

**Made with ❤️ for personal expense tracking in Vietnam** 🇻🇳