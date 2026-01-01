# -----------------------------------------------------------------------------
# bot.py - النسخة النهائية مع خدعة الـ Health Check المصححة لـ Render
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from binance.client import Client

# --- إعداد خادم الويب البسيط (Health Check) ---
# هذا الجزء سيجعل Render تعتقد أن الخدمة حية وتمنعها من التوقف.
app = Flask(__name__)

@app.route('/')
def health_check():
    """هذه هي نقطة النهاية التي ستزورها Render (أو أنت) لإيقاظ الخدمة."""
    return "Falcon Bot is alive and scanning!", 200

def run_web_server():
    """دالة لتشغيل خادم الويب في الخلفية."""
    # Render تحدد المنفذ تلقائيًا عبر متغير بيئة PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- إعدادات البوت (لا تتغير) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_OVERSOLD = 30
TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
SCAN_INTERVAL_SECONDS = 15 * 60

# --- دوال الاستراتيجية والتحليل (لا تتغير) ---
def calculate_rsi(df, period=14):
    # استيراد المكتبات داخل الدالة لضمان التوافق في بيئات مختلفة
    import pandas as pd
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

def check_strategy(client, symbol):
    try:
        # استيراد المكتبات داخل الدالة لضمان التوافق
        import pandas as pd
        
        klines = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=RSI_PERIOD + 50)
        if len(klines) < RSI_PERIOD + 2: return False
        
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df['close'] = pd.to_numeric(df['close'])
        df['open'] = pd.to_numeric(df['open'])
        df['RSI'] = calculate_rsi(df, RSI_PERIOD)
        
        last_candle, prev_candle = df.iloc[-1], df.iloc[-2]
        
        rsi_is_oversold = last_candle['RSI'] < RSI_OVERSOLD
        is_bullish_engulfing = (last_candle['close'] > last_candle['open'] and prev_candle['close'] < prev_candle['open'] and last_candle['close'] > prev_candle['open'] and last_candle['open'] < prev_candle['close'])
        
        if rsi_is_oversold and is_bullish_engulfing:
            logger.info(f"🎯 تم العثور على فرصة! العملة: {symbol}, RSI: {last_candle['RSI']:.2f}")
            return True
    except Exception as e:
        logger.error(f"خطأ غير متوقع أثناء فحص العملة {symbol}: {e}")
    return False

async def scan_market(context):
    logger.info("--- بدء جولة فحص السوق ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']
    symbols_to_scan = get_top_usdt_pairs(client, limit=150)
    if not symbols_to_scan:
        logger.warning("لم يتم العثور على عملات لفحصها.")
        return
    found_signals = []
    for symbol in symbols_to_scan:
        if check_strategy(client, symbol):
            found_signals.append(symbol)
        await asyncio.sleep(0.2)
    if found_signals:
        message = "🚨 **إشارة شراء قوية (RSI + ابتلاعية)** 🚨\n\n"
        for symbol in found_signals:
            message += f"• <a href='https://www.binance.com/en/trade/{symbol}'>{symbol}</a>\n"
        await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML', disable_web_page_preview=True)
    logger.info(f"--- انتهاء جولة الفحص. تم العثور على {len(found_signals)} إشارة. ---")

async def start(update, context):
    user = update.effective_user
    await update.message.reply_html(f"أهلاً بك يا {user.mention_html()}!\n\nأنا **بوت الصقر** وجاهز للعمل.")

def main():
    logger.info("--- بدء تشغيل البوت وخادم الويب ---")
    
    # تشغيل خادم الويب في ثريد منفصل حتى لا يوقف البوت
    web_thread = Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    logger.info("خادم الويب للـ Health Check يعمل في الخلفية.")

    # قراءة متغيرات البيئة
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
    BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")

    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_SECRET_KEY]):
        logger.critical("!!! فشل: متغيرات البيئة غير كاملة. !!!")
        return

    logger.info("--- جميع متغيرات البيئة موجودة. ---")

    # الاتصال بالخدمات
    try:
        binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        binance_client.ping()
        logger.info("تم الاتصال ببينانس بنجاح.")
    except Exception as e:
        logger.critical(f"فشل الاتصال ببينانس: {e}")
        return

    # إعداد البوت
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    job_data = {'binance_client': binance_client, 'chat_id': TELEGRAM_CHAT_ID}
    job_queue = application.job_queue
    job_queue.run_repeating(scan_market, interval=SCAN_INTERVAL_SECONDS, first=10, data=job_data)

    logger.info("--- البوت جاهز ويعمل. جدولة فحص السوق كل 15 دقيقة. ---")
    
    # تشغيل البوت
    application.run_polling()

if __name__ == "__main__":
    main()

