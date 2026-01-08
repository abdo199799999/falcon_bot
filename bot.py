# -----------------------------------------------------------------------------
# bot.py - نسخة v2.2 (MA200 + إشارات متقدمة + نسبة الربح)
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
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. إعداد خادم الويب ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Bot Service (Binance - Advanced Signals v2.2) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 70
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60
MIN_CONFIDENCE_STRONG = 75
MIN_CONFIDENCE_WEAK = 50
bought_coins = {}

# --- دوال التحليل المتقدمة ---
def calculate_indicators(df):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['STD20'] = df['close'].rolling(window=20).std()
    df['BOLL_UPPER'] = df['MA20'] + (df['STD20'] * 2)
    df['BOLL_LOWER'] = df['MA20'] - (df['STD20'] * 2)
    df['MA200'] = df['close'].rolling(window=200).mean()
    return df

def get_top_usdt_pairs(client, limit=150):
    try:
        all_tickers = client.get_ticker()
        usdt_pairs = [t for t in all_tickers if t['symbol'].endswith('USDT') and 'UP' not in t['symbol'] and 'DOWN' not in t['symbol']]
        return [p['symbol'] for p in sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:limit]]
    except Exception as e:
        logger.error(f"[Binance] فشل في جلب قائمة العملات: {e}")
        return []

def analyze_symbol(client, symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=200)
        if len(klines) < 200: return 'HOLD', 0, None, None
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df[['close', 'open', 'high', 'low', 'volume']] = df[['close', 'open', 'high', 'low', 'volume']].apply(pd.to_numeric)
        df = calculate_indicators(df)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = last['close']
        if last['close'] < last['MA200']:
            return 'HOLD', 0, None, current_price
        confidence = 0
        if last['RSI'] < RSI_OVERSOLD: confidence += 25
        if last['close'] <= last['BOLL_LOWER']: confidence += 25
        if (last['close'] > last['open'] and prev['close'] < prev['open'] and last['close'] > prev['open'] and last['open'] < prev['close']):
            confidence += 25
        if last['volume'] > df['volume'].rolling(window=20).mean().iloc[-1]: confidence += 25
        expected_target = last['MA20']
        if confidence >= MIN_CONFIDENCE_STRONG:
            return 'STRONG_BUY', confidence, expected_target, current_price
        if confidence >= MIN_CONFIDENCE_WEAK:
            return 'WEAK_BUY', confidence, expected_target, current_price
    except Exception as e:
        logger.error(f"[Binance] خطأ أثناء فحص {symbol}: {e}")
    return 'HOLD', 0, None, None

# --- مهمة الفحص الدوري ---
async def scan_market(context):
    global bought_coins
    logger.info("--- [Binance] بدء جولة فحص السوق (Advanced Signals v2.2) ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']
    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    logger.info(f"[Binance] Found {len(symbols_to_scan)} symbols to scan.")
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, confidence, target, current_price = analyze_symbol(client, symbol)
        if status == 'STRONG_BUY':
            if current_price > 0 and target > current_price:
                profit_percentage = ((target / current_price) - 1) * 100
                profit_text = f"• **الربح المتوقع:** `~{profit_percentage:.2f}%`\n"
            else:
                profit_text = ""
            message = (f"🚨 **[Binance] إشارة شراء قوية** 🚨\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر الحالي:** `{current_price}`\n"
                       f"• **الهدف المتوقع:** `{target:.4f}`\n"
                       f"{profit_text}"
                       f"• **الثقة:** `{confidence}%`")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins[symbol] = {'buy_price': current_price}
        elif status == 'WEAK_BUY':
            message = (f"👀 **[Binance] إشارة ضعيفة للمراقبة** 👀\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر الحالي:** `{current_price}`\n"
                       f"• **الثقة:** `{confidence}%`")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
        await asyncio.sleep(0.5)
    logger.info(f"--- [Binance] انتهاء جولة الفحص. ---")

# --- أمر /start ---
async def start(update, context):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت التداول الفوري (Binance - نسخة MA200 المتقدمة)**.\n"
               f"<i>صنع بواسطه المطور عبدالرحمن محمد</i>")
    await update.message.reply_html(message)

# --- دالة تشغيل البوت ---
def run_bot():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
    BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_SECRET_KEY]):
        logger.critical("!!! [Binance] فشل: متغيرات البيئة غير كاملة. !!!")
        return
    try:
        binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
    except Exception as e:
        logger.critical(f"فشل الاتصال ببينانس: {e}")
        return
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    job_data = {'binance_client': binance_client, 'chat_id': TELEGRAM_CHAT_ID}
    job_queue = application.job_queue
    job_queue.run_repeating(scan_market, interval=SCAN_INTERVAL_SECONDS, first=10, data=job_data)
    logger.info("--- [Binance] البوت جاهز ويعمل. ---")
    application.run_polling()

# --- نقطة البداية الرئيسية ---
if __name__ == "__main__":
    logger.info("--- [Binance] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [Binance] Web Server has been started. ---")
    run_bot()

