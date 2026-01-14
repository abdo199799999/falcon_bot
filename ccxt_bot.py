# -----------------------------------------------------------------------------
# bot_webhook.py - نسخة v5.0 (MTFA 1H, EMA+RSI+StochRSI+Volume, Webhook + Flask)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from binance.client import Client
import pandas as pd

# --- إعدادات التسجيل ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- إعداد Flask ---
app = Flask(__name__)

# --- إعدادات الاستراتيجية ---
SCAN_INTERVAL_SECONDS = 60 * 60   # فحص كل ساعة
bought_coins = []

# --- دوال التحليل (مؤشرات جديدة) ---
def calculate_indicators(df):
    df['EMA7'] = df['close'].ewm(span=7, adjust=False).mean()
    df['EMA25'] = df['close'].ewm(span=25, adjust=False).mean()
    df['EMA99'] = df['close'].ewm(span=99, adjust=False).mean()

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/6, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/6, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    df['RSI6'] = 100 - (100 / (1 + rs))

    rsi_min = df['RSI6'].rolling(window=14).min()
    rsi_max = df['RSI6'].rolling(window=14).max()
    df['StochRSI'] = (df['RSI6'] - rsi_min) / (rsi_max - rsi_min)

    df['VolMA20'] = df['volume'].rolling(window=20).mean()
    return df.dropna()

def analyze_symbol(client, symbol):
    try:
        klines_1h = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=120)
        if len(klines_1h) < 100: 
            return 'HOLD', None

        df_1h = pd.DataFrame(klines_1h, columns=['timestamp','open','high','low','close','volume','close_time','quote_av','trades','tb_base_av','tb_quote_av','ignore'])
        df_1h[['close','open','volume']] = df_1h[['close','open','volume']].apply(pd.to_numeric)
        df_1h = calculate_indicators(df_1h)

        last = df_1h.iloc[-1]
        current_price = last['close']

        ema_trend_up = last['close'] > last['EMA7'] > last['EMA25'] > last['EMA99']
        rsi_ok = 60 <= last['RSI6'] <= 80
        stoch_mid = 0.4 <= last['StochRSI'] <= 0.6
        volume_ok = last['volume'] > last['VolMA20']
        bullish_candle = last['close'] > last['open']

        if ema_trend_up and rsi_ok and stoch_mid and volume_ok and bullish_candle:
            return 'BUY', current_price

        rsi_high = last['RSI6'] > 80
        stoch_high = last['StochRSI'] > 0.8
        bearish_candle = last['close'] < last['open']

        if (rsi_high or stoch_high) and bearish_candle:
            return 'SELL', current_price

    except Exception as e:
        logger.error(f"[Binance] خطأ أثناء فحص {symbol}: {e}")

    return 'HOLD', None

# --- أمر /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = (f"👋 أهلاً بك يا {user.mention_html()}!<br><br>"
               f"أنا <b>بوت التداول الفوري (Binance - استراتيجية MTFA 1H)</b>.<br>"
               f"<i>صنع بواسطه المطور عبدالرحمن محمد</i>")
    await update.message.reply_html(message)

# --- إعداد Webhook ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")

application = Application.builder().token(TELEGRAM_TOKEN).build()
application.add_handler(CommandHandler("start", start))

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put_nowait(update)
    return "ok", 200

@app.route("/")
def index():
    return "Falcon Bot Webhook Service is Running!", 200

# --- نقطة البداية ---
if __name__ == "__main__":
    logger.info("--- [Binance] Starting Webhook Application ---")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
