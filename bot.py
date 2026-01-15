# -----------------------------------------------------------------------------
# bot.py - نسخة استراتيجية 1 ساعة (مؤشرات جديدة)
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
    return "Falcon Bot Service (Binance - 1H Strategy) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. إعدادات الاستراتيجية ---
RSI_PERIOD = 6
RSI_OVERSOLD = 40
RSI_OVERBOUGHT = 70
SCAN_INTERVAL_SECONDS = 15 * 60 # فحص كل 15 دقيقة
bought_coins = []

# --- دوال التحليل ---
def calculate_indicators(df):
    # RSI(6)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))

    # EMA7 / EMA25 / EMA99
    df['EMA7'] = df['close'].ewm(span=7, adjust=False).mean()
    df['EMA25'] = df['close'].ewm(span=25, adjust=False).mean()
    df['EMA99'] = df['close'].ewm(span=99, adjust=False).mean()

    # Stochastic RSI
    min_close = df['close'].rolling(window=14).min()
    max_close = df['close'].rolling(window=14).max()
    df['StochRSI'] = (df['RSI'] - min_close) / (max_close - min_close + 1e-10) * 100

    # متوسط حجم التداول (Volume MA20)
    df['VolMA20'] = df['volume'].rolling(window=20).mean()

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
        # --- استخدام إطار 1 ساعة ---
        klines_1h = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=100)
        if len(klines_1h) < 50: return 'HOLD', None, None

        df_1h = pd.DataFrame(klines_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df_1h[['close', 'open', 'volume']] = df_1h[['close', 'open', 'volume']].apply(pd.to_numeric)

        df_1h = calculate_indicators(df_1h)

        last_1h = df_1h.iloc[-1]
        prev_1h = df_1h.iloc[-2]
        current_price = last_1h['close']

        # شروط الشراء
        ema_trend_up = last_1h['EMA7'] > last_1h['EMA25'] > last_1h['EMA99']
        rsi_condition = last_1h['RSI'] > 60
        stoch_condition = last_1h['StochRSI'] > 60
        volume_condition = last_1h['volume'] > last_1h['VolMA20']

        buy_signals = sum([ema_trend_up, rsi_condition, stoch_condition, volume_condition])
        if buy_signals >= 3:
            return 'BUY', current_price, None

        # شروط البيع
        rsi_overbought = last_1h['RSI'] > RSI_OVERBOUGHT
        stoch_overbought = last_1h['StochRSI'] > 80
        if rsi_overbought and stoch_overbought:
            return 'SELL', current_price, None

    except Exception as e:
        logger.error(f"[Binance] خطأ أثناء فحص {symbol}: {e}")

    return 'HOLD', None, None

# --- مهمة الفحص الدوري ---
async def scan_market(context):
    global bought_coins
    logger.info("--- [Binance] بدء جولة فحص السوق (استراتيجية 1 ساعة) ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']

    for symbol in list(bought_coins):
        status, price, _ = analyze_symbol(client, symbol)
        if status == 'SELL':
            message = (f"💰 **[Binance] إشارة بيع (1H Strategy)** 💰\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر الحالي:** `{price}`")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins.remove(symbol)
        await asyncio.sleep(1)

    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, current_price, _ = analyze_symbol(client, symbol)
        if status == 'BUY':
            message = (f"🚨 **[Binance] إشارة شراء (1H Strategy)** 🚨\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر الحالي:** `{current_price}`\n")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins.append(symbol)
        await asyncio.sleep(1)

    logger.info(f"--- [Binance] انتهاء جولة الفحص. ---")

# --- أمر /start ---
async def start(update, context):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت التداول الفوري (Binance - استراتيجية 1 ساعة)**.\n"
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
