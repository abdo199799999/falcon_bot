# -----------------------------------------------------------------------------
# bot.py - نسخة عبدالرحمن محمد (إطار زمني 15 دقيقة)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
import time
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


# --- دوال التحليل (مع إصلاح بناء الجملة) ---
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
    try:
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=RSI_PERIOD + 50)
        if len(klines) < RSI_PERIOD + 2: return 'HOLD', None
        
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        
        last_candle_close_time_ms = int(df.iloc[-1]['close_time'])
        current_time_ms = int(time.time() * 1000)
        time_difference_minutes = (current_time_ms - last_candle_close_time_ms) / (1000 * 60)
        
        if time_difference_minutes > 30:
            logger.warning(f"بيانات {symbol} قديمة جدًا ({int(time_difference_minutes)} دقيقة). يتم تجاهلها.")
            return 'HOLD', None

        df['close'] = pd.to_numeric(df['close'])
        df['open'] = pd.to_numeric(df['open'])
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
        logger.error(f"خطأ غير متوقع أثناء فحص العملة {symbol}: {e}")
    
    return 'HOLD', None


# --- مهمة الفحص الدوري (لا تغيير هنا) ---
async def scan_market(context):
    global bought_coins
    logger.info("--- بدء جولة فحص السوق (شراء + بيع) - إطار 15 دقيقة ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']
    
    for symbol in list(bought_coins):
        status, price = analyze_symbol(client, symbol)
        if status == 'SELL':
            message = (f"💰 **إشارة بيع (RSI تشبع شرائي)** 💰\n\n"
                       f"• <a href='https://www.binance.com/en/trade/{symbol}'>{symbol}</a>\n"
                       f"• **السعر الحالي:** `{price}`")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML', disable_web_page_preview=True)
            logger.info(f"💰 تم إرسال إشارة بيع للعملة: {symbol}. تتم إزالتها من قائمة المراقبة.")
            bought_coins.remove(symbol)
        await asyncio.sleep(0.5)

    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, price = analyze_symbol(client, symbol)
        if status == 'BUY':
            message = (f"🚨 **إشارة شراء قوية (RSI + ابتلاعية)** 🚨\n\n"
                       f"• <a href='https://www.binance.com/en/trade/{symbol}'>{symbol}</a>\n"
                       f"• **السعر الحالي:** `{price}`")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML', disable_web_page_preview=True)
            logger.info(f"🎯 تم إرسال إشارة شراء للعملة: {symbol}. تتم إضافتها لقائمة المراقبة.")
            bought_coins.append(symbol)
        await asyncio.sleep(0.5)

    logger.info(f"--- انتهاء جولة الفحص. العملات قيد المراقبة حاليًا: {bought_coins} ---")


# --- أمر /start ---
async def start(update, context):
    logger.info(f"--- تم استلام أمر /start من المستخدم: {update.effective_user.id} ---")
    user = update.effective_user
    
    # --- هذا هو النص الجديد ---
    message = (
        f"أهلاً بك يا {user.mention_html()}!\n\n"
        f"أنا **بوت التداول الفوري النسخه الاحترافيه**.\n"
        f"<i>صنع بواسطه المطور عبدالرحمن محمد</i>"
    )
    # --- نهاية النص الجديد ---
    
    await update.message.reply_html(message)


# --- دالة تشغيل البوت ---
def run_bot():
    logger.info("--- بدء تشغيل مكون البوت ---")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
    BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")

    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_SECRET_KEY]):
        logger.critical("!!! فشل: متغيرات البيئة غير كاملة. لا يمكن تشغيل البوت. !!!")
        return

    try:
        binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        binance_client.ping()
        logger.info("--- تم الاتصال والتحقق من واجهة بينانس بنجاح. ---")
    except Exception as e:
        logger.critical(f"فشل الاتصال ببينانس: {e}")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    job_data = {'binance_client': binance_client, 'chat_id': TELEGRAM_CHAT_ID}
    job_queue = application.job_queue
    job_queue.run_repeating(scan_market, interval=SCAN_INTERVAL_SECONDS, first=10, data=job_data)

    logger.info("--- البوت جاهز ويعمل. جدولة فحص السوق كل 15 دقيقة. ---")
    application.run_polling()


# --- 3. نقطة البداية الرئيسية للتطبيق ---
if __name__ == "__main__":
    logger.info("--- Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- Web Server has been started in a background thread ---")
    logger.info("--- Starting Bot in the main thread ---")
    run_bot()

