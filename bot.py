# -----------------------------------------------------------------------------
# bot.py - نسخة احترافية (RSI + EMA + MACD + Bollinger + ATR + فلترة السعر + ثقة الإشارة)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
import time
import json
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from binance.client import Client
import pandas as pd

# --- إعدادات التسجيل ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- خادم الويب ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Bot Service (Pro v5) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- إعدادات الاستراتيجية ---
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
EMA_SHORT_PERIOD = 21
EMA_LONG_PERIOD = 50
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60

# --- ملف لحفظ العملات ---
WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    return []

def save_watchlist(coins):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(coins, f)

# --- "ذاكرة" البوت ---
bought_coins = load_watchlist()

# --- دوال المؤشرات ---
def calculate_indicators(df):
    # --- RSI ---
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))

    # --- EMA ---
    df['EMA_SHORT'] = df['close'].ewm(span=EMA_SHORT_PERIOD, adjust=False).mean()
    df['EMA_LONG'] = df['close'].ewm(span=EMA_LONG_PERIOD, adjust=False).mean()

    # --- MACD ---
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()

    # --- Bollinger Bands ---
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['STD20'] = df['close'].rolling(window=20).std()
    df['BOLL_UPPER'] = df['MA20'] + (df['STD20'] * 2)
    df['BOLL_LOWER'] = df['MA20'] - (df['STD20'] * 2)

    # --- ATR ---
    df['H-L'] = df['high'] - df['low']
    df['H-C'] = abs(df['high'] - df['close'].shift())
    df['L-C'] = abs(df['low'] - df['close'].shift())
    df['TR'] = df[['H-L', 'H-C', 'L-C']].max(axis=1)
    df['ATR'] = df['TR'].rolling(window=14).mean()

    return df

# --- فلترة العملات حسب السعر ---
def filter_by_price(client, symbols, max_price=100):
    filtered = []
    for symbol in symbols:
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            if price <= max_price:
                filtered.append(symbol)
        except Exception as e:
            logger.error(f"فشل في جلب سعر {symbol}: {e}")
    return filtered

# --- جلب العملات الأعلى تداول ---
def get_top_usdt_pairs(client, limit=100):
    try:
        all_tickers = client.get_ticker()
        usdt_pairs = [t for t in all_tickers if t['symbol'].endswith('USDT') and 'UP' not in t['symbol'] and 'DOWN' not in t['symbol']]
        return [p['symbol'] for p in sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:limit]]
    except Exception as e:
        logger.error(f"فشل في جلب قائمة العملات: {e}")
        return []

# --- تحليل العملة مع مستوى الثقة ---
def analyze_symbol(client, symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=100)
        if len(klines) < 50: 
            return 'HOLD', None, 0

        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','quote_av','trades','tb_base_av','tb_quote_av','ignore'])
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric)

        df = calculate_indicators(df)
        last = df.iloc[-1]

        confidence_buy = 0
        confidence_sell = 0
        signal = "HOLD"

        # --- شروط الشراء ---
        if last['RSI'] < RSI_OVERSOLD: confidence_buy += 25
        if last['EMA_SHORT'] > last['EMA_LONG']: confidence_buy += 25
        if last['MACD'] > last['MACD_SIGNAL']: confidence_buy += 25
        if last['close'] < last['BOLL_LOWER']: confidence_buy += 25

        if confidence_buy >= 60:
            signal = "BUY"
            confidence = confidence_buy

        # --- شروط البيع ---
        if last['RSI'] > RSI_OVERBOUGHT: confidence_sell += 25
        if last['EMA_SHORT'] < last['EMA_LONG']: confidence_sell += 25
        if last['MACD'] < last['MACD_SIGNAL']: confidence_sell += 25
        if last['close'] > last['BOLL_UPPER']: confidence_sell += 25

        if confidence_sell >= 60:
            signal = "SELL"
            confidence = confidence_sell

        if signal == "HOLD":
            confidence = max(confidence_buy, confidence_sell)

        return signal, last['close'], confidence

    except Exception as e:
        logger.error(f"خطأ أثناء تحليل {symbol}: {e}")
        return "HOLD", None, 0

# --- مهمة الفحص الدوري ---
async def scan_market(context):
    global bought_coins
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']

    # فحص العملات المشتراة
    for symbol in list(bought_coins):
        status, price, confidence = analyze_symbol(client, symbol)
        if status == 'SELL':
            await context.bot.send_message(chat_id=chat_id, text=f"💰 إشارة بيع: {symbol} بسعر {price} (ثقة {confidence}%)", parse_mode='HTML')
            bought_coins.remove(symbol)
            save_watchlist(bought_coins)
        await asyncio.sleep(0.5)

    # فحص السوق
    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    symbols_to_scan = filter_by_price(client, symbols_to_scan, max_price=100)

    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        status, price, confidence = analyze_symbol(client, symbol)
        if status == 'BUY':
            await context.bot.send_message(chat_id=chat_id, text=f"🚨 إشارة شراء: {symbol} بسعر {price} (ثقة {confidence}%)", parse_mode='HTML')
            bought_coins.append(symbol)
            save_watchlist(bought_coins)
        await asyncio.sleep(0.5)

# --- أوامر البوت ---
async def start(update, context):
    user = update.effective_user
    await update.message.reply_html(f"أهلاً {user.mention_html()}!\n\nأنا **بوت الصقر** (Pro v5) وجاهز للعمل.")

async def status(update, context):
    if bought_coins:
        coins_list = "\n".join(bought_coins)
        await update.message.reply_text(f"📊 العملات تحت المراقبة:\n{coins_list}")
    else:
        await update.message.reply_text("لا توجد عملات تحت المراقبة حالياً.")

# --- تشغيل البوت ---
def run_bot():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    BINANCE
