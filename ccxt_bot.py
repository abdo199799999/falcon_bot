# -----------------------------------------------------------------------------
# ccxt_bot.py - المحلل الفني الاحترافي v3.0 (متجاوب وغير متزامن)
# -----------------------------------------------------------------------------
import os
import asyncio
import ccxt.async_support as ccxt # <-- استخدام النسخة غير المتزامنة لدعم تعدد المهام
import pandas as pd
import pandas_ta as ta
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- إعداد خادم الويب (للتوافق مع Render) ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Professional Analyzer Bot (v3.0) is Running and Responsive!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- قراءة متغيرات البيئة ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- إعداد المؤشرات ---
RSI_LENGTH = 6
EMA_FAST = 7
EMA_MID = 25
EMA_SLOW = 99
SCAN_INTERVAL_MINUTES = 10 # الفحص كل 10 دقائق

# --- الأوامر (Commands) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start - يرسل رسالة ترحيب ويؤكد أن البوت يعمل"""
    user = update.effective_user
    await update.message.reply_html(
        f"أهلاً بك يا {user.mention_html()}!\n\n"
        f"أنا **بوت المحلل الفني (v3.0)**. أنا أعمل الآن وأستمع لأوامرك.\n"
        f"سأقوم بفحص السوق كل {SCAN_INTERVAL_MINUTES} دقائق."
    )

# --- دوال التحليل (تم تحويلها إلى async) ---
async def fetch_data(exchange, symbol, timeframe="1h", limit=200):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        return df
    except Exception:
        return None

def compute_indicators(df):
    # هذه الدالة لا تحتاج إلى async لأنها تعتمد على pandas فقط
    df[f"ema_{EMA_FAST}"] = ta.ema(df["close"], length=EMA_FAST)
    df[f"ema_{EMA_MID}"]  = ta.ema(df["close"], length=EMA_MID)
    df[f"ema_{EMA_SLOW}"] = ta.ema(df["close"], length=EMA_SLOW)
    df[f"rsi_{RSI_LENGTH}"] = ta.rsi(df["close"], length=RSI_LENGTH)
    stochrsi = ta.stochrsi(df["close"], length=14, rsi_length=14, k=3, d=3)
    if stochrsi is not None and not stochrsi.empty:
        df["stochrsi_k"] = stochrsi.get("STOCHRSIk_14_14_3_3")
    else:
        df["stochrsi_k"] = None
    df["vol_ma_20"] = ta.sma(df["volume"], length=20)
    return df.dropna()

def generate_signal(row):
    try:
        buy_cond = (
            (row["close"] > row[f"ema_{EMA_FAST}"]) and
            (row[f"ema_{EMA_FAST}"] > row[f"ema_{EMA_MID}"]) and
            (row[f"ema_{EMA_MID}"] > row[f"ema_{EMA_SLOW}"]) and
            (60 <= row[f"rsi_{RSI_LENGTH}"] <= 80) and
            (40 <= row["stochrsi_k"] <= 60) and
            (row["volume"] > row["vol_ma_20"]) and
            (row["close"] > row["open"])
        )
        sell_cond = (
            (row[f"rsi_{RSI_LENGTH}"] > 80 or row["stochrsi_k"] > 80) and
            (row["close"] < row["open"])
        )
        if buy_cond: return "BUY"
        elif sell_cond: return "SELL"
        else: return "HOLD"
    except Exception:
        return "HOLD"

# --- المهمة الدورية (Background Job) ---
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """المهمة التي تعمل في الخلفية لفحص السوق"""
    exchange = context.job.data['exchange']
    print("--- [Background Job] بدء جولة فحص جديدة ---")
    
    try:
        markets = await exchange.load_markets()
        spot_pairs = [s for s in markets if s.endswith('/USDT')]

        for symbol in spot_pairs:
            df = await fetch_data(exchange, symbol, "1h")
            if df is None or df.empty: continue
            
            df = compute_indicators(df)
            if df.empty: continue
            
            last = df.iloc[-1]
            signal = generate_signal(last)

            if signal in ["BUY", "SELL"]:
                msg = f"""👀 إشارة Binance (v3.0)

• العملة: {symbol.replace('/', '')}
• السعر الحالي: {round(last['close'], 6)}
• RSI: {round(last[f'rsi_{RSI_LENGTH}'], 2)}
• الإشارة: {signal} ✅
"""
                await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
                print(f"تم إرسال إشارة: {symbol} | {signal}")
            
            await asyncio.sleep(0.5) # انتظار بسيط لمنع إغراق الـ API

    except Exception as e:
        print(f"خطأ عام في المهمة الدورية: {e}")
    finally:
        print("--- [Background Job] انتهاء جولة الفحص ---")


# --- نقطة البداية الرئيسية ---
async def main():
    print("--- بدء تشغيل التطبيق الرئيسي (v3.0) ---")
    
    # إعداد البوت
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # إضافة الأوامر
    application.add_handler(CommandHandler("start", start_command))

    # إعداد وجدولة المهمة الدورية
    job_queue = application.job_queue
    exchange_instance = ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET_KEY,
        "enableRateLimit": True
    })
    job_data = {'exchange': exchange_instance}
    job_queue.run_repeating(monitor_job, interval=SCAN_INTERVAL_MINUTES * 60, first=10, data=job_data)

    print(f"--- البوت جاهز ويستمع. ستبدأ أول جولة فحص بعد 10 ثوانٍ ---")
    
    # تشغيل البوت (وضع الاستماع)
    await application.initialize()
    await application.start()
    await application.updater.start_polling()


if __name__ == "__main__":
    # تشغيل خادم الويب في خيط منفصل
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    print("--- تم تشغيل خادم الويب ---")
    
    # تشغيل الحلقة الرئيسية غير المتزامنة
    asyncio.run(main())

