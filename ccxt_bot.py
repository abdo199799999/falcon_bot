# -----------------------------------------------------------------------------
# ccxt_bot.py - المحلل الفني المتقدم (إصدار خدمة الويب v2.0)
# -----------------------------------------------------------------------------
import os
import time
import ccxt
import pandas as pd
import pandas_ta as ta
import requests
from threading import Thread
from flask import Flask

# --- إعداد خادم الويب (للتوافق مع Render) ---
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Advanced Analyzer Bot (v2.0) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- قراءة متغيرات البيئة ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- إعداد Binance عبر ccxt ---
exchange = ccxt.binance({
    "apiKey": BINANCE_API_KEY,
    "secret": BINANCE_SECRET_KEY,
    "enableRateLimit": True
})

# --- إعداد المؤشرات ---
RSI_LENGTH = 6
EMA_FAST = 7
EMA_MID = 25
EMA_SLOW = 99

# --- دوال التحليل والإرسال ---
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"خطأ في إرسال رسالة تيليجرام: {e}")

def fetch_data(symbol, timeframe="1h", limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        return df
    except Exception:
        return None

def compute_indicators(df):
    df[f"ema_{EMA_FAST}"] = ta.ema(df["close"], length=EMA_FAST)
    df[f"ema_{EMA_MID}"]  = ta.ema(df["close"], length=EMA_MID)
    df[f"ema_{EMA_SLOW}"] = ta.ema(df["close"], length=EMA_SLOW)
    df[f"rsi_{RSI_LENGTH}"] = ta.rsi(df["close"], length=RSI_LENGTH)
    stochrsi = ta.stochrsi(df["close"], length=14, rsi_length=14, k=3, d=3)
    if stochrsi is not None and not stochrsi.empty:
        df["stochrsi_k"] = stochrsi.get("STOCHRSIk_14_14_3_3")
        df["stochrsi_d"] = stochrsi.get("STOCHRSId_14_14_3_3")
    else:
        df["stochrsi_k"] = None
        df["stochrsi_d"] = None
    df["vol_ma_20"] = ta.sma(df["volume"], length=20)
    return df.dropna()

def generate_signal(row):
    try:
        buy_cond = (
            (row["close"] > row[f"ema_{EMA_FAST}"] > row[f"ema_{MID}"] > row[f"ema_{SLOW}"]) and
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

def monitor_all(timeframe="1h"):
    """مراقبة جميع الأزواج الفورية في حلقة لا نهائية"""
    print("--- بدء مهمة المراقبة في الخلفية ---")
    send_telegram_message("🚀 بوت المحلل الفني (v2.0) بدأ العمل الآن.")
    
    while True:
        try:
            print("--- بدء جولة فحص جديدة ---")
            markets = exchange.load_markets()
            spot_pairs = [s for s in markets if s.endswith('/USDT')]

            for symbol in spot_pairs:
                df = fetch_data(symbol, timeframe)
                if df is None or df.empty: 
                    continue
                df = compute_indicators(df)
                if df.empty:
                    continue
                
                last = df.iloc[-1]
                signal = generate_signal(last)

                if signal in ["BUY", "SELL"]:
                    msg = f"""👀 إشارة Binance (v2.0)

• العملة: {symbol.replace('/', '')}
• السعر الحالي: {round(last['close'], 6)}
• RSI: {round(last[f'rsi_{RSI_LENGTH}'], 2)}
• الإشارة: {signal} ✅
"""
                    send_telegram_message(msg)
                    print(f"تم إرسال إشارة: {symbol} | {signal}")
                
                time.sleep(1)

            print(f"--- انتهاء جولة الفحص. الانتظار لمدة 10 دقائق ---")
            time.sleep(600)

        except Exception as e:
            print(f"خطأ عام في حلقة المراقبة: {e}")
            time.sleep(60)

# --- نقطة البداية الرئيسية ---
if __name__ == "__main__":
    print("--- بدء تشغيل التطبيق الرئيسي ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    print("--- تم تشغيل خادم الويب ---")
    
    monitor_all("1h")

