# -----------------------------------------------------------------------------
# bot.py - نسخة مصححة (مع فحص زمني للبيانات)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
import time # <-- جديد: لاستيراد مكتبة الوقت
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from binance.client import Client
import pandas as pd

# --- إعدادات التسجيل (Logging) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- 1. إعداد خادم الويب ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Falcon Bot Service is Running!", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# --- 2. كل ما يتعلق بالبوت ---

# --- إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60

# --- "ذاكرة" البوت ---
bought_coins = []


# --- دوال التحليل (مع تحديثات حاسمة) ---
def calculate_rsi(df, period=14):
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

def analyze_symbol(client, symbol):
    """
    دالة التحليل المحدثة مع "شرط الأمان الزمني".
    """
    try:
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=RSI_PERIOD + 50)
        if len(klines) < RSI_PERIOD + 2: return 'HOLD', None
        
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        
        # --- !!! الإصلاح الحاسم: التحقق من عمر البيانات !!! ---
        last_candle_close_time_ms = int(df.iloc[-1]['close_time'])
        current_time_ms = int(time.time() * 1000)
        
        # نحسب الفارق الزمني بالدقائق
        time_difference_minutes = (current_time_ms - last_candle_close_time_ms) / (1000 * 60)
        
        # إذا كانت البيانات أقدم من 30 دقيقة، فهي غير صالحة. تجاهلها.
        if time_difference_minutes > 30:
            logger.warning(f"بيانات {symbol} قديمة جدًا ({int(time_difference_minutes)} دقيقة). يتم تجاهلها.")
            return 'HOLD', None
        # --- !!! نهاية الإصلاح الحاسم !!! ---

        df['close'] = pd.to_numeric(df['close'])
        df['open'] = pd.to_numeric(df['open'])
        df['RSI'] = calculate_rsi(df, RSI_PERIOD)
        
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        current_price = last_candle['close']

        # --- منطق الشراء ---
        rsi_is_oversold = last_candle['RSI'] < RSI_OVERSOLD
        is_bullish_engulfing = (last_candle['close'] > last_candle['open'] and prev_candle['close'] < prev_candle['open'] and last_candle['close'] > prev_candle['open'] and last_candle['open'] < prev_candle['close'])
        if rsi_is_oversold and is_bullish_engulfing:
            return 'BUY', current_price

        # --- منطق البيع ---
        rsi_is_overbought = last_candle['RSI'] > RSI_

