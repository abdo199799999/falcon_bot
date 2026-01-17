# -----------------------------------------------------------------------------
# bot.py - نسخة v7.1 (Hybrid Sniper + News Watcher)
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
import requests

# --- إعدادات التسجيل ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. إعداد خادم الويب ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Bot Service (Binance - Hybrid Sniper v7.1) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SCAN_INTERVAL_SECONDS = 15 * 60
bought_coins = []

# --- دوال التحليل الفني ---
def calculate_indicators(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))

    # EMA
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA25'] = df['close'].ewm(span=25, adjust=False).mean()

    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    return df

def get_top_usdt_pairs(client, limit=100):
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

        df = pd.DataFrame(klines_1h, columns=['timestamp','open','high','low','close','volume','close_time','quote_av','trades','tb_base_av','tb_quote_av','ignore'])
        df[['close','open','volume']] = df[['close','open','volume']].apply(pd.to_numeric)

        df = calculate_indicators(df)
        last = df.iloc[-1]
        current_price = last['close']

        # شروط الشراء
        buy_signal = (
            last['RSI'] < RSI_OVERSOLD and
            last['MACD'] > last['Signal'] and
            last['EMA9'] > last['EMA25'] and
            last['volume'] > df['volume'].mean() * 1.5
        )

        # شروط البيع
        sell_signal = (
            last['RSI'] > RSI_OVERBOUGHT and
            last['MACD'] < last['Signal'] and
            last['EMA9'] < last['EMA25']
        )

        if buy_signal:
            return 'BUY', current_price
        elif sell_signal:
            return 'SELL', current_price

    except Exception as e:
        logger.error(f"[Binance] خطأ أثناء فحص {symbol}: {e}")

    return 'HOLD', None

# --- دوال الأخبار ---
def check_coinmarketcal():
    url = "https://api.coinmarketcal.com/v1/events"
    # يجب الحصول على مفتاح API من CoinMarketCal وإضافته كمتغير بيئة
    api_key = os.getenv("COINMARKETCAL_API_KEY")
    if not api_key:
        return []
    headers = {"Accept": "application/json", "x-api-key": api_key}
    params = {"sortBy": "created_desc", "max": 5} # أحدث 5 أحداث
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get("body", [])
    except Exception as e:
        logger.error(f"[News] خطأ CoinMarketCal: {e}")
    return []

def check_binance_announcements():
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageSize=5&page=1"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json().get("data", {}).get("articles", [])
    except Exception as e:
        logger.error(f"[News] خطأ Binance Announcements: {e}")
    return []

# --- فحص السوق ---
async def scan_market(context):
    global bought_coins
    logger.info("--- [Binance] بدء جولة فحص (Hybrid Sniper v7.1) ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']

    # فحص العملات المشتراة
    for symbol in list(bought_coins):
        status, price = analyze_symbol(client, symbol)
        if status == 'SELL':
            message = f"💰 *[Sniper] إشارة بيع*\n\n• العملة: `{symbol}`\n• السعر الحالي: `{price}`"
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            bought_coins.remove(symbol)
        await asyncio.sleep(1)

    # فحص السوق
    symbols_to_scan = get_top_usdt_pairs(client, limit=100)
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, current_price = analyze_symbol(client, symbol)
        if status == 'BUY':
            message = f"🎯 *[Hybrid Sniper] إشارة شراء مؤكدة!*\n\n• العملة: `{symbol}`\n• السعر الحالي: `{current_price}`"
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            bought_coins.append(symbol)
        await asyncio.sleep(1)

    # الأخبار
    news_events = check_coinmarketcal()
    for event in news_events:
        msg = f"📰 *[News]* حدث مهم:\n\n• {event.get('title','')}\n• التاريخ: {event.get('date_event','')}"
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

    binance_news = check_binance_announcements()
    for article in binance_news:
        msg = f"📢 *[Binance]* إعلان جديد:\n\n• {article.get('title','')}"
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

    logger.info("--- [Binance] انتهاء جولة الفحص. ---")

# --- أوامر البوت ---
async def start(update, context):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت Hybrid Sniper v7.1**.\n"
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

# --- نقطة البداية الرئيسية (تم الإصلاح هنا) ---
if __name__ == "__main__":
    logger.info("--- [Hybrid Sniper] Starting Main Application ---")
    
    # الخطوة 1: تشغيل خادم الويب في الخلفية
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [Hybrid Sniper] Web Server has been started. ---")
    
    # الخطوة 2: تشغيل بوت التليجرام الرئيسي
    run_bot()

