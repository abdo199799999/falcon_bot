# -----------------------------------------------------------------------------
# bot.py - نسخة v3.2 (MTFA 4H + 15M)
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
    return "Falcon Bot Service (Binance - MTFA 4H+15M Strategy v3.2) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- 2. إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SCAN_INTERVAL_SECONDS = 15 * 60 # فحص كل 15 دقيقة
bought_coins = []

# --- دوال التحليل (مع منطق MTFA) ---
def calculate_indicators(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    # MA20 (للهدف المتوقع)
    df['MA20'] = df['close'].rolling(window=20).mean()
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
        # --- الخطوة 1: التحليل الاستراتيجي على إطار 4 ساعات (الفلتر) ---
        klines_4h = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_4HOUR, limit=201)
        if len(klines_4h) < 200: return 'HOLD', None, None
        
        df_4h = pd.DataFrame(klines_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df_4h['close'] = pd.to_numeric(df_4h['close'])
        df_4h['MA200'] = df_4h['close'].rolling(window=200).mean()
        
        last_4h = df_4h.iloc[-1]
        
        if last_4h['close'] < last_4h['MA200']:
            return 'HOLD', None, None
            
        # --- الخطوة 2: البحث عن نقطة دخول على إطار 15 دقيقة ---
        klines_15m = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=100)
        if len(klines_15m) < 50: return 'HOLD', None, None

        df_15m = pd.DataFrame(klines_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df_15m[['close', 'open']] = df_15m[['close', 'open']].apply(pd.to_numeric)
        
        df_15m = calculate_indicators(df_15m)
        
        last_15m = df_15m.iloc[-1]
        prev_15m = df_15m.iloc[-2]
        current_price = last_15m['close']
        expected_target = last_15m['MA20']

        # شروط الشراء
        rsi_is_oversold = last_15m['RSI'] < RSI_OVERSOLD
        is_bullish_engulfing = (last_15m['close'] > last_15m['open'] and prev_15m['close'] < prev_15m['open'] and last_15m['close'] > prev_15m['open'] and last_15m['open'] < prev_15m['close'])
        macd_is_bullish = last_15m['MACD'] > last_15m['MACD_Signal']

        if rsi_is_oversold and is_bullish_engulfing and macd_is_bullish:
            return 'BUY', current_price, expected_target

        # شروط البيع (على إطار 15 دقيقة)
        rsi_is_overbought = last_15m['RSI'] > RSI_OVERBOUGHT
        macd_is_bearish = last_15m['MACD'] < last_15m['MACD_Signal']
        if rsi_is_overbought and macd_is_bearish:
            return 'SELL', current_price, None

    except Exception as e:
        logger.error(f"[Binance] خطأ أثناء فحص {symbol} (MTFA): {e}")
    
    return 'HOLD', None, None

# --- مهمة الفحص الدوري ---
async def scan_market(context):
    global bought_coins
    logger.info("--- [Binance] بدء جولة فحص السوق (MTFA 4H+15M) ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']
    
    for symbol in list(bought_coins):
        status, price, _ = analyze_symbol(client, symbol)
        if status == 'SELL':
            message = (f"💰 **[Binance] إشارة بيع (MTFA - 15M)** 💰\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر الحالي:** `{price}`")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins.remove(symbol)
        await asyncio.sleep(1)

    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, current_price, target = analyze_symbol(client, symbol)
        if status == 'BUY':
            if current_price > 0 and target > current_price:
                profit_percentage = ((target / current_price) - 1) * 100
                profit_text = f"• **الربح المتوقع:** `~{profit_percentage:.2f}%`\n"
            else:
                profit_text = ""
            
            message = (f"🚨 **[Binance] إشارة شراء MTFA (4H + 15M)** 🚨\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر الحالي:** `{current_price}`\n"
                       f"• **الهدف المتوقع:** `{target:.4f}`\n"
                       f"{profit_text}")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
            bought_coins.append(symbol)
        await asyncio.sleep(1)

    logger.info(f"--- [Binance] انتهاء جولة الفحص. ---")

# --- أمر /start ---
async def start(update, context):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت التداول الفوري (Binance - استراتيجية MTFA 4H+15M)**.\n"
               f"<i>صنع بواسطه المطور عبدالرحمن محمد</i>")
    await update.message.reply_html(message)

# --- دالة تشغيل البوت ---
def run_bot():
    # ... (بقية الكود تبقى كما هي تمامًا) ...
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

