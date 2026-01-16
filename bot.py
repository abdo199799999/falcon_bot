# -----------------------------------------------------------------------------
# bot.py - نسخة v6.1 (Patient Bottom Sniper - قناص القيعان الصبور)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
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
    return "Falcon Bot Service (Binance - Patient Bottom Sniper v6.1) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SCAN_INTERVAL_SECONDS = 15 * 60
bought_coins = []

# --- دوال التحليل ---
def calculate_indicators(df):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))
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
        klines_1h = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=100)
        if len(klines_1h) < 50: return 'HOLD', None

        df_1h = pd.DataFrame(klines_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df_1h[['close', 'open']] = df_1h[['close', 'open']].apply(pd.to_numeric)

        df_1h = calculate_indicators(df_1h)
        if df_1h.empty or len(df_1h) < 3:
            return 'HOLD', None

        # --- شروط قنص القاع الجديدة مع التأكيد ---
        last = df_1h.iloc[-1]        # الشمعة الحالية (شمعة التأكيد المحتملة)
        prev = df_1h.iloc[-2]        # الشمعة السابقة (شمعة الابتلاع المحتملة)
        prev_prev = df_1h.iloc[-3]   # الشمعة التي قبلها (شمعة الهبوط)
        current_price = last['close']

        # 1. الشمعة التي قبل السابقة كانت حمراء
        prev_prev_is_bearish = prev_prev['close'] < prev_prev['open']
        # 2. الشمعة السابقة كانت خضراء (ابتلاع)
        prev_is_bullish = prev['close'] > prev['open']
        # 3. الشمعة السابقة ابتلعت الشمعة التي قبلها
        is_bullish_engulfing = prev_is_bullish and prev_prev_is_bearish and prev['close'] > prev_prev['open'] and prev['open'] < prev_prev['close']
        # 4. مؤشر RSI كان في منطقة تشبع بيعي عند شمعة الهبوط
        prev_prev_rsi_oversold = prev_prev['RSI'] < RSI_OVERSOLD
        # 5. الشمعة الحالية (الأخيرة) هي شمعة خضراء (التأكيد)
        confirmation_candle = last['close'] > last['open']

        # الشرط النهائي: إذا حدث ابتلاع بعد تشبع، وجاءت بعده شمعة تأكيد خضراء
        if is_bullish_engulfing and prev_prev_rsi_oversold and confirmation_candle:
            return 'BUY', current_price

        # شروط البيع
        rsi_overbought = last['RSI'] > RSI_OVERBOUGHT
        if rsi_overbought:
            return 'SELL', current_price

    except Exception as e:
        logger.error(f"[Binance] خطأ أثناء فحص {symbol}: {e}")

    return 'HOLD', None

# --- بقية الكود تبقى كما هي تمامًا ---
async def scan_market(context):
    global bought_coins
    logger.info("--- [Binance] بدء جولة فحص (قناص صبور v6.1) ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']
    for symbol in list(bought_coins):
        status, price = analyze_symbol(client, symbol)
        if status == 'SELL':
            message = f"💰 *[Sniper] إشارة بيع*\n\n• *العملة:* `{symbol}`\n• *السعر الحالي:* `{price}`"
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            bought_coins.remove(symbol)
        await asyncio.sleep(1)
    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, current_price = analyze_symbol(client, symbol)
        if status == 'BUY':
            message = f"🎯 *[Patient Sniper] تم رصد قاع مؤكد!*\n\n• *العملة:* `{symbol}`\n• *السعر الحالي:* `{current_price}`"
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            bought_coins.append(symbol)
        await asyncio.sleep(1)
    logger.info(f"--- [Binance] انتهاء جولة الفحص. ---")

async def start(update, context):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت قناص القيعان الصبور (v6.1)**.\n"
               f"<i>صنع بواسطه المطور عبدالرحمن محمد</i>")
    await update.message.reply_html(message)

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

if __name__ == "__main__":
    logger.info("--- [Binance] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [Binance] Web Server has been started. ---")
    run_bot()

