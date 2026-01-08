# -----------------------------------------------------------------------------
# bot_bingx.py - نسخة العامل الصامت (مع التشخيص وتصحيح متغيرات البيئة)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
import time
from threading import Thread
from flask import Flask
from telegram import Bot
import pandas as pd
import requests
import hmac, hashlib
from urllib.parse import urlencode

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Bot Service (BingX Worker - Diagnostic Mode v2) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SCAN_INTERVAL_SECONDS = 15 * 60
bought_coins = []

API_KEY = os.environ.get("BINGX_API_KEY")
API_SECRET = os.environ.get("BINGX_SECRET_KEY")
BASE_URL = "https://open-api.bingx.com"
session = requests.Session()
session.headers.update({"X-BingX-ApiKey": API_KEY})

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_top_usdt_pairs(limit=100):
    try:
        url = f"{BASE_URL}/openApi/spot/v1/market/ticker"
        r = session.get(url, timeout=10)
        r.raise_for_status()
        all_tickers = r.json().get("data", [])
        usdt_pairs = [t for t in all_tickers if t['symbol'].endswith("-USDT")]
        if not usdt_pairs:
             logger.warning("[DIAGNOSTIC] get_top_usdt_pairs returned an EMPTY list.")
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
        df[['open','close','high','low']] = df[['open','close','high','low']].apply(pd.to_numeric)
        df['RSI'] = calculate_rsi(df, RSI_PERIOD)
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        rsi_is_oversold = last_candle['RSI'] < RSI_OVERSOLD
        is_bullish_engulfing = (last_candle['close'] > last_candle['open'] and prev_candle['close'] < prev_candle['open'] and last_candle['close'] > prev_candle['open'] and last_candle['open'] < prev_candle['close'])
        if last_candle['RSI'] < 40:
            logger.info(f"[DIAGNOSTIC] {symbol} | RSI: {last_candle['RSI']:.2f} | Oversold? {rsi_is_oversold} | Engulfing? {is_bullish_engulfing}")
        if rsi_is_oversold and is_bullish_engulfing:
            logger.info(f"✅✅✅ [BINGX] FOUND A BUY SIGNAL FOR {symbol} ✅✅✅")
            return 'BUY', last_candle['close']
        rsi_is_overbought = last_candle['RSI'] > RSI_OVERBOUGHT
        if rsi_is_overbought:
            return 'SELL', last_candle['close']
    except Exception as e:
        logger.error(f"[BingX] خطأ أثناء فحص {symbol}: {e}")
    return 'HOLD', None

async def scan_market(bot, chat_id):
    global bought_coins
    logger.info("--- [BingX] بدء جولة فحص السوق (Diagnostic Mode v2) ---")
    for symbol in list(bought_coins):
        status, price = analyze_symbol(symbol)
        if status == 'SELL':
            message = f"💰 **[BingX] إشارة بيع** 💰\n\n• {symbol}\n• **السعر الحالي:** `{price}`"
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML', disable_web_page_preview=True)
            bought_coins.remove(symbol)
        await asyncio.sleep(0.5)
    symbols_to_scan = get_top_usdt_pairs(limit=150)
    logger.info(f"[DIAGNOSTIC] Found {len(symbols_to_scan)} symbols to scan.")
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, price = analyze_symbol(symbol)
        if status == 'BUY':
            message = f"🚨 **[BingX] إشارة شراء** 🚨\n\n• {symbol}\n• **السعر الحالي:** `{price}`"
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML', disable_web_page_preview=True)
            bought_coins.append(symbol)
        await asyncio.sleep(0.5)
    logger.info(f"--- [BingX] انتهاء جولة الفحص. ---")

async def main_logic():
    # --- !!! هذا هو التصحيح الحاسم !!! ---
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN_BINGX")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID_BINGX")
    # --- !!! نهاية التصحيح !!! ---
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, API_KEY, API_SECRET]):
        logger.critical("!!! [BingX] فشل: متغيرات البيئة غير كاملة.")
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    logger.info("--- [BingX] العامل جاهز للعمل في الخلفية. ---")
    while True:
        try:
            await scan_market(bot, TELEGRAM_CHAT_ID)
        except Exception as e:
            logger.error(f"[BingX] حدث خطأ في حلقة الفحص الرئيسية: {e}")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    logger.info("--- [BingX] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [BingX] Web Server has been started. ---")
    asyncio.run(main_logic())

