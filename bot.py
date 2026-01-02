# -----------------------------------------------------------------------------
# bot.py - النسخة النهائية المبسطة (متوافقة 100% مع Render)
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from binance.client import Client

# --- إعدادات التسجيل (Logging) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- 1. إعداد خادم الويب (لإبقاء Render سعيدة) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    """هذه الصفحة هي التي تزورها Render للتأكد من أن الخدمة حية."""
    return "Falcon Bot Service is Running!", 200

def run_server():
    """هذه الدالة تقوم بتشغيل خادم الويب."""
    # Render توفر متغير PORT تلقائيًا. نستخدم 10000 كقيمة افتراضية.
    port = int(os.environ.get("PORT", 10000))
    # نشغل الخادم ليكون متاحًا خارجيًا.
    app.run(host='0.0.0.0', port=port)


# --- 2. كل ما يتعلق بالبوت (الاستراتيجية، الأوامر، إلخ) ---

# إعدادات الاستراتيجية
RSI_PERIOD = 14
RSI_OVERSOLD = 30
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60

# دوال التحليل
def calculate_rsi(df, period=14):
    import pandas as pd
    delta = df['close'].diff()
    gain =

