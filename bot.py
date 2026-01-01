# -----------------------------------------------------------------------------
# bot.py - النسخة النهائية المبسطة للعمل مع Gunicorn
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from binance.client import Client

# --- إعداد Flask (يبقى كما هو) ---
# Gunicorn سيجد هذا الكائن 'app' تلقائيًا
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Falcon Bot is alive with Gunicorn!", 200

# --- إعدادات البوت (تبقى كما هي) ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_OVERSOLD = 30
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60

# --- دوال الاستراتيجية والتحليل (لا تتغير) ---
def calculate_rsi(df, period=14):
    import pandas as pd
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_top_usdt_pairs(client, limit=100):
    try:
        all_tickers = client.get_ticker()
        usdt_pairs = [t for t in all_tickers if t['symbol'].endswith('USDT') and 'UP' not in t['symbol'] and 'DOWN' not in t['symbol']]
        return [p['symbol'] for p in sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:limit]]
    except Exception as e:
        logger.error(f"فشل في جلب قائمة العملات: {e}")
        return []

def check_strategy(client, symbol):
    try:
        import pandas as pd
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=RSI_PERIOD + 50)
        if len(klines) < RSI_PERIOD + 2: return False
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df['close'] = pd.to_numeric(df['close'])
        df['open'] = pd.to_numeric(df['open'])
        df['RSI'] = calculate_rsi(df, RSI_PERIOD)
        last_candle, prev_candle = df.iloc[-1], df.iloc[-2]
        rsi_is_oversold = last_candle['RSI'] < RSI_OVERSOLD

