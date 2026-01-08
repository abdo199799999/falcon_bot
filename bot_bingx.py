# -----------------------------------------------------------------------------
# bot_bingx.py - نسخة العودة إلى البساطة (استراتيجية RSI + Engulfing الفعالة)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
import time
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import pandas as pd
import requests
import hmac, hashlib
from urllib.parse import urlencode

# --- إعدادات التسجيل (Logging) ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. إعداد خادم الويب ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Bot Service (BingX - Simple & Effective) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. كل ما يتعلق بالبوت ---

# --- إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SCAN_INTERVAL_SECONDS = 15 * 60
bought_coins = []

# --- إعدادات BingX ---
API_KEY = os.environ.get("BINGX_API_KEY")
API_SECRET = os.environ.get("BINGX_SECRET_KEY")
BASE_URL = "https://open-api.bingx.com"
session = requests.Session()
session.headers.update({"X-BingX-ApiKey": API_KEY})

# --- دوال التحليل ---
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def get_top_usdt_pairs(limit=150):
    try:
        url = f"{BASE_URL}/openApi/spot/v1/market/ticker"
        r = session.get(url, timeout=10)
        r.raise_for_status()
        all_tickers = r.json().get("data", [])
        usdt_pairs = [t for t in all_tickers if t['symbol'].endswith("USDT")]
        return [p['symbol'] for p in sorted(usdt_pairs, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)[:limit]]
    except Exception as e:
        logger.error(f"[BingX] فشل في جلب قائمة العملات: {e}")
        return []

def get_klines(symbol, interval="15m", limit=100):
    try:
        url = f"{BASE_URL}/openApi/spot/v1/market/kline"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = session.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error(f"[BingX] فشل في جلب الشموع لـ {symbol}: {e}")
        return []

def analyze_symbol(symbol):
    try:
        klines = get_klines(symbol, interval="15m", limit=RSI_PERIOD + 50)
        if len(klines) < RSI_PERIOD + 2: return 'HOLD', None
        df = pd.DataFrame(klines, columns=['open','close','high','low','volume','timestamp'])
        df[['open','close']] = df[['open','close']].apply(pd.to_numeric)
        df['RSI'] = calculate_rsi(df, RSI_PERIOD)
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        current_price = last_candle['close']
        rsi_is_oversold = last_candle['RSI'] < RSI_OVERSOLD
        is_bullish_engulfing = (last_candle['close'] > last_candle['open'] and prev_candle['close'] < prev_candle['open'] and last_candle['close'] > prev_candle['open'] and last_candle['open'] < prev_candle['close'])
        if rsi_is_oversold and is_bullish_engulfing:
            return 'BUY', current_price
        rsi_is_overbought = last_candle['RSI'] > RSI_OVERBOUGHT
        if rsi_is_overbought:
            return 'SELL', current_price
    except Exception as e:
        logger.error(f"[BingX] خطأ أثناء فحص {symbol}: {e}")
    return 'HOLD', None

# --- مهمة الفحص الدوري ---
async def scan_market(context):
    global bought_coins
    logger.info("--- [BingX] بدء جولة فحص السوق (Simple & Effective) ---")
    chat_id = context.job.data['chat_id']
    symbols_to_scan = get_top_usdt_pairs(limit=150)
    logger.info(f"[BingX] Found {len(symbols_to_scan)} symbols to scan.")
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, price = analyze_symbol(symbol)
        if status == 'BUY':
            message = f"🚨 **[BingX] إشارة شراء (RSI + Engulfing)** 🚨\n\n• **العملة:** `{symbol}`\n• **السعر الحالي:** `{price}`"
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins.append(symbol)
        await asyncio.sleep(0.5)
    for symbol in list(bought_coins):
        status, price = analyze_symbol(symbol)
        if status == 'SELL':
            message = f"💰 **[BingX] إشارة بيع (RSI Overbought)** 💰\n\n• **العملة:** `{symbol}`\n• **السعر الحالي:** `{price}`"
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins.remove(symbol)
        await asyncio.sleep(0.5)
    logger.info(f"--- [BingX] انتهاء جولة الفحص. ---")

# --- أمر /start ---
async def start(update, context):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت التداول الفوري (BingX - نسخة بسيطة وفعالة)**.\n"
               f"<i>صنع بواسطه المطور عبدالرحمن محمد</i>")
    await update.message.reply_html(message)

# --- دالة تشغيل البوت ---
def run_bot():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, API_KEY, API_SECRET]):
        logger.critical("!!! [BingX] فشل: متغيرات البيئة غير كاملة.")
        return
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    job_data = {'chat_id': TELEGRAM_CHAT_ID}
    job_queue = application.job_queue
    job_queue.run_repeating(scan_market, interval=SCAN_INTERVAL_SECONDS, first=10, data=job_data)
    logger.info("--- [BingX] البوت جاهز ويعمل. ---")
    application.run_polling()

# --- نقطة البداية الرئيسية ---
if __name__ == "__main__":
    logger.info("--- [BingX] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [BingX] Web Server has been started. ---")
    run_bot()

