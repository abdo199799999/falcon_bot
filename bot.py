# -----------------------------------------------------------------------------
# bot.py - الصقر الخبير (v6.0) - الذاكرة السحابية + استراتيجية هجينة
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
from tinydb_gist import TinyGistDB
from tinydb import Query

# --- إعدادات التسجيل ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- خادم الويب (لـ Render Health Check) ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Bot Service (v6.0) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60
MIN_CONFIDENCE_BUY = 75
MIN_CONFIDENCE_SELL = 75
PRICE_ACTION_WINDOW = 12 # نافذة حركة السعر (3 ساعات)

# --- قاعدة البيانات السحابية (الذاكرة الخالدة) ---
GIST_ID = os.environ.get("GIST_ID")
GITHUB_PAT = os.environ.get("GITHUB_PAT")
db = TinyGistDB(GIST_ID, GITHUB_PAT, db_filename='db.json')
watchlist_table = db.table('watchlist')
Symbol = Query()

def get_watchlist():
    return [item['symbol'] for item in watchlist_table.all()]

def add_to_watchlist(symbol):
    if not watchlist_table.contains(Symbol.symbol == symbol):
        watchlist_table.insert({'symbol': symbol})

def remove_from_watchlist(symbol):
    watchlist_table.remove(Symbol.symbol == symbol)

# --- دوال المؤشرات ---
def calculate_indicators(df):
    df['EMA_SHORT'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_LONG'] = df['close'].ewm(span=50, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))

    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()

    df['MA20'] = df['close'].rolling(window=20).mean()
    df['STD20'] = df['close'].rolling(window=20).std()
    df['BOLL_UPPER'] = df['MA20'] + (df['STD20'] * 2)
    df['BOLL_LOWER'] = df['MA20'] - (df['STD20'] * 2)
    return df

# --- جلب العملات ---
def get_top_usdt_pairs(client, limit=150):
    try:
        all_tickers = client.get_ticker()
        usdt_pairs = [t['symbol'] for t in all_tickers if t['symbol'].endswith('USDT') and 'UP' not in t['symbol'] and 'DOWN' not in t['symbol']]
        return [p['symbol'] for p in sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:limit]]
    except Exception as e:
        logger.error(f"فشل في جلب قائمة العملات: {e}")
        return []

# --- دالة التحليل الهجينة ---
def analyze_symbol(client, symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=100)
        if len(klines) < 50: return 'HOLD', None, 0

        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','quote_av','trades','tb_base_av','tb_quote_av','ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df[['open','high','low','close']] = df[['open','high','low','close']].apply(pd.to_numeric)

        df = calculate_indicators(df)
        last = df.iloc[-1]

        # --- استراتيجية حركة السعر (الخروج السريع) ---
        recent_high = df['high'].tail(PRICE_ACTION_WINDOW).max()
        recent_low  = df['low'].tail(PRICE_ACTION_WINDOW).min()
        if last['close'] < recent_high and last['close'] <= recent_low:
            return 'SELL', last['close'], 80

        # --- استراتيجية المؤشرات (نقاط الثقة) ---
        confidence_buy = 0
        if last['RSI'] < RSI_OVERSOLD: confidence_buy += 25
        if last['EMA_SHORT'] > last['EMA_LONG']: confidence_buy += 25
        if last['MACD'] > last['MACD_SIGNAL']: confidence_buy += 25
        if last['close'] < last['BOLL_LOWER']: confidence_buy += 25

        confidence_sell = 0
        if last['RSI'] > RSI_OVERBOUGHT: confidence_sell += 25
        if last['EMA_SHORT'] < last['EMA_LONG']: confidence_sell += 25
        if last['MACD'] < last['MACD_SIGNAL']: confidence_sell += 25
        if last['close'] > last['BOLL_UPPER']: confidence_sell += 25

        if confidence_buy >= MIN_CONFIDENCE_BUY:
            return 'BUY', last['close'], confidence_buy
        
        if confidence_sell >= MIN_CONFIDENCE_SELL:
            return 'SELL', last['close'], confidence_sell

    except Exception as e:
        logger.error(f"خطأ أثناء تحليل {symbol}: {e}")
    
    return 'HOLD', None, 0

# --- مهمة الفحص الدوري ---
async def scan_market(context):
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']
    watchlist = get_watchlist()
    logger.info(f"--- بدء جولة الفحص (v6.0). العملات تحت المراقبة: {watchlist} ---")

    for symbol in watchlist:
        status, price, confidence = analyze_symbol(client, symbol)
        if status == 'SELL':
            await context.bot.send_message(chat_id=chat_id, text=f"💰 **إشارة بيع:** `{symbol}`\n**السعر:** `{price}`\n**الثقة:** `{confidence}%`", parse_mode='HTML')
            remove_from_watchlist(symbol)
            logger.info(f"💰 تم إرسال إشارة بيع وإزالة {symbol} من المراقبة.")
        await asyncio.sleep(0.5)

    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    for symbol in symbols_to_scan:
        if symbol in get_watchlist(): continue
        status, price, confidence = analyze_symbol(client, symbol)
        if status == 'BUY':
            await context.bot.send_message(chat_id=chat_id, text=f"🚨 **إشارة شراء:** `{symbol}`\n**السعر:** `{price}`\n**الثقة:** `{confidence}%`", parse_mode='HTML')
            add_to_watchlist(symbol)
            logger.info(f"🎯 تم إرسال إشارة شراء وإضافة {symbol} للمراقبة.")
        await asyncio.sleep(0.5)
    
    logger.info("--- انتهاء جولة الفحص ---")

# --- أوامر البوت ---
async def start(update, context):
    await update.message.reply_html(f"أهلاً {update.effective_user.mention_html()}!\n\nأنا **بوت الصقر** (v6.0) وجاهز للعمل بذاكرة خالدة.")

async def status(update, context):
    watchlist = get_watchlist()
    if watchlist:
        coins_list = "\n".join(f"`{coin}`" for coin in watchlist)
        await update.message.reply_text(f"📊 **العملات تحت المراقبة حالياً:**\n{coins_list}", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("لا توجد عملات تحت المراقبة حالياً.")

# --- تشغيل البوت ---
def run_bot():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
