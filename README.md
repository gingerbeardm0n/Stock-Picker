# 🚀 Momentum Stock Scanner

A Python-based stock scanner with a web dashboard that identifies day trading opportunities based on Ross Cameron's momentum trading strategy.

![Dashboard Preview](https://img.shields.io/badge/Status-Active-success)
![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Flask](https://img.shields.io/badge/Flask-Latest-green)

## 📋 Features

- **Automated Scanning** - Background thread runs every 60 seconds during market hours
- **Real-time Dashboard** - Beautiful web interface showing matching stocks
- **News Detection** - Identifies stocks with recent catalysts
- **Customizable Criteria** - Update scanner parameters via API
- **Ross Cameron Method** - Proven day trading criteria:
  - Price Range: $1-$10
  - Pre-market Volume: 100K+ shares
  - Pre-market Gain: 10%+
  - Relative Volume: 2x+
  - Low Float: Under 50M shares

## 🛠️ Technology Stack

- **Backend**: Python, Flask
- **Frontend**: HTML, CSS, JavaScript
- **Data Source**: Alpaca API (free paper trading)
- **Real-time Updates**: Background scanning thread

## 📁 Project Structure

```
Stock-Picker/
├── backend/
│   ├── scanner.py          # Core scanning logic
│   ├── news_fetcher.py     # Fetch news/catalysts
│   ├── data_feed.py        # Alpaca data connections
│   └── app.py              # Flask web server
├── frontend/
│   ├── index.html          # Dashboard UI
│   ├── style.css           # Styling
│   └── app.js              # Frontend logic
├── config.py               # API keys and settings
├── requirements.txt        # Python dependencies
├── .env                    # API credentials (not in git)
├── .env.example           # Template for .env
└── README.md              # This file
```

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- Alpaca paper trading account (free)
- Modern web browser

### Step 1: Get Alpaca API Keys

1. Go to [Alpaca Markets](https://alpaca.markets/)
2. Sign up for a **paper trading** account (no real money required)
3. Navigate to your dashboard
4. Generate API keys (API Key ID and Secret Key)

### Step 2: Clone and Setup

```bash
# Clone the repository
git clone <repository-url>
cd Stock-Picker

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Configure API Keys

Create a `.env` file in the project root:

```bash
# Copy the example file
cp .env.example .env
```

Edit `.env` and add your Alpaca API credentials:

```
ALPACA_API_KEY=your_alpaca_api_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_key_here
```

**Note:** The `.env` file is already in `.gitignore` to keep your credentials safe.

### Step 4: Run the Application

```bash
# Start the Flask server
python backend/app.py
```

The server will start on `http://localhost:5000`

### Step 5: Open the Dashboard

Open your web browser and navigate to:
```
http://localhost:5000
```

Click "Run Scan Now" to start scanning stocks!

## 📊 Scanner Criteria

The scanner uses the following criteria (Ross Cameron style):

| Criterion | Value |
|-----------|-------|
| Price Range | $1.00 - $10.00 |
| Min Pre-market Volume | 100,000 shares |
| Min Pre-market Gain | 10% |
| Min Relative Volume | 2.0x |
| Max Float | 50M shares |
| Avg Daily Volume | 100K - 5M |

## 🔧 API Endpoints

- `GET /` - Main dashboard
- `GET /api/scan` - Get current scan results
- `POST /api/scan/now` - Trigger manual scan
- `GET /api/stock/<symbol>` - Get details for specific stock
- `GET /api/criteria` - Get scanner criteria
- `POST /api/criteria` - Update scanner criteria

## 🎯 Usage

### Manual Scan

Click the **"Run Scan Now"** button to immediately scan stocks.

### Automatic Scanning

The scanner automatically runs every 60 seconds during market hours (4 AM - 4 PM ET).

### View Results

Stock cards show:
- Symbol and current price
- Pre-market gain percentage
- Volume metrics (PM volume, relative volume, avg volume)
- News/catalyst indicator
- Bid/Ask spread

### Customize Scanning

You can modify scanning criteria in `config.py`:

```python
SCANNER_CRITERIA = {
    'min_price': 1.0,
    'max_price': 10.0,
    'min_premarket_volume': 100000,
    'min_premarket_gain_pct': 10.0,
    'max_float': 50000000,
    'min_relative_volume': 2.0,
    'min_avg_volume': 100000,
    'max_avg_volume': 5000000
}
```

## 🧪 Testing

For initial testing, the scanner uses a small subset of popular symbols:
- AAPL, TSLA, AMD, NVDA, PLTR, SOFI
- NIO, LCID, RIVN, F, GME, AMC
- SPY, QQQ, SQQQ, TQQQ

To scan all active stocks, modify `backend/app.py`:

```python
# Change this line in trigger_scan():
results = scanner.run_scan()  # Scans all active stocks
```

## ⚠️ Important Notes

### Paper Trading Only
This scanner is designed for **paper trading** accounts. Never use it with a live trading account without proper risk management.

### Market Hours
The scanner works best during pre-market (4:00 AM - 9:30 AM ET) and regular market hours (9:30 AM - 4:00 PM ET).

### API Rate Limits
Alpaca's free tier has rate limits. The scanner is designed to work within these limits using test symbols. Scanning all stocks may hit rate limits.

### Risk Warning
⚠️ **Day trading is risky. This tool is for educational purposes only. Past performance does not guarantee future results. Only trade with money you can afford to lose.**

## 🔮 Future Enhancements

- [ ] Add Level 2 quote data integration
- [ ] Build trading algorithm that consumes scanner output
- [ ] Implement automated trade execution with risk management
- [ ] Add backtesting capabilities
- [ ] Implement pattern recognition (bull flags, ABCD patterns)
- [ ] Add email/SMS alerts for matching stocks
- [ ] Database to store historical scan results
- [ ] Advanced filtering and sorting options

## 🐛 Troubleshooting

### "No module named 'alpaca'"
Run: `pip install -r requirements.txt`

### API Key Errors
- Check your `.env` file has the correct keys
- Verify keys are active in your Alpaca dashboard
- Make sure you're using paper trading keys, not live keys

### No Stocks Found
- Check if it's market hours (or pre-market)
- Verify the test symbols are trading
- Check Alpaca API status
- Review logs in the terminal for errors

### Port Already in Use
If port 5000 is already in use, modify `backend/app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5001)  # Change port
```

## 📝 License

This project is for educational purposes only.

## 🙏 Credits

- Scanner strategy based on Ross Cameron's momentum trading method
- Data provided by Alpaca Markets
- Built with Flask, Python, and vanilla JavaScript

## 📧 Support

For issues or questions, please open an issue on GitHub.

---

**Happy Trading! 🚀📈**

*Remember: This is a tool for identifying potential opportunities. Always do your own research and never risk more than you can afford to lose.*
