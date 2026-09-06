import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
ALLOWED_CHAT_IDS = [int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x]

# Exchange (Binance USDT-M Futures)
EXCHANGE_NAME = "binance"
EXCHANGE_TYPE = "future"
DEFAULT_SYMBOL = "BTC/USDT:USDT"
DEFAULT_TIMEFRAME = "15m"

# Polling intervals (seconds)
PRICE_POLL_INTERVAL = 5

# Orderbook depth to fetch
ORDERBOOK_LIMIT = 500

# Tier thresholds (configurable)
ORDERBOOK_WALL_RATIO = 3.5
VOLUME_SPIKE_RATIO = 1.5
VWAP_DEVIATION_BAND = 0.002

DATA_FILE = "data/alerts.json"