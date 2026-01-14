# -*- coding: utf-8 -*-
import os
import time
import ccxt
import pandas as pd
import pandas_ta as ta
import requests

# قراءة متغيرات البيئة من Render أو أي سيرفر
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# إعداد Binance عبر ccxt
exchange = ccxt.binance({
    "apiKey": BINANCE_API_KEY,
    "secret": BINANCE_SECRET_KEY,
    "enableRateLimit": True
})

# إعداد المؤشرات
RSI_LENGTH = 6
EMA_FAST = 7
EMA_MID = 25
EMA_SLOW = 99

def send_telegram_message(message):
    """إرسال رسالة عبر Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)

def start_bot():
    """رسالة الترحيب عند بدء البوت"""
    welcome_msg = """👋 أهلا بك أيها المطور
أنا بوت التداول الفوري الاحترافي 🚀"""
    send_telegram_message(welcome_msg)

def fetch_data(symbol, timeframe="1h", limit=200):
    """جلب بيانات الشموع لزوج معين"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        print(f"خطأ في جلب البيانات لـ {symbol}: {e}")
        return None

def compute_indicators(df):
    """حساب المؤشرات الفنية"""
    df[f"ema_{EMA_FAST}"] = ta.ema(df["close"], length=EMA_FAST)
    df[f"ema_{EMA_MID}"]  = ta.ema(df["close"], length=EMA_MID)
    df[f"ema_{EMA_SLOW}"] = ta.ema(df["close"], length=EMA_SLOW)
    df[f"rsi_{RSI_LENGTH}"] = ta.rsi(df["close"], length=RSI_LENGTH)
    stochrsi = ta.stochrsi(df["close"], length=14, rsi_length=14, k=3, d=3)
    df["stochrsi_k"] = stochrsi["STOCHRSIk_14_14_3_3"]
    df["stochrsi_d"] = stochrsi["STOCHRSId_14_14_3_3"]
    df["vol_ma_20"] = ta.sma(df["volume"], length=20)
    return df.dropna()

def generate_signal(row):
    """توليد إشارة شراء أو بيع"""
    buy_cond = (
        (row["close"] > row[f"ema_{EMA_FAST}"] > row[f"ema_{EMA_MID}"] > row[f"ema_{EMA_SLOW}"]) and
        (60 <= row[f"rsi_{RSI_LENGTH}"] <= 80) and
        (40 <= row["stochrsi_k"] <= 60) and
        (row["volume"] > row["vol_ma_20"]) and
        (row["close"] > row["open"])
    )
    sell_cond = (
        (row[f"rsi_{RSI_LENGTH}"] > 80 or row["stochrsi_k"] > 80) and
        (row["close"] < row["open"])
    )
    if buy_cond:
        return "BUY"
    elif sell_cond:
        return "SELL"
    else:
        return "HOLD"

def monitor_all(timeframe="1h"):
    """مراقبة جميع الأزواج الفورية"""
    while True:
        try:
            markets = exchange.load_markets()
            spot_pairs = [s for s in markets if "/USDT" in s]  # نركز على أزواج USDT

            for symbol in spot_pairs:
                df = fetch_data(symbol, timeframe)
                if df is None: 
                    continue
                df = compute_indicators(df)
                last = df.iloc[-1]
                signal = generate_signal(last)

                if signal in ["BUY", "SELL"]:
                    msg = f"""👀 إشارة Binance

• العملة: {symbol.replace('/', '')}
• السعر الحالي: {round(last['close'], 6)}
• RSI: {round(last[f'rsi_{RSI_LENGTH}'], 2)}
• EMA7/25/99: {round(last[f'ema_{EMA_FAST}'],3)} / {round(last[f'ema_{EMA_MID}'],3)} / {round(last[f'ema_{EMA_SLOW}'],3)}
• StochRSI(K): {round(last['stochrsi_k'],2)}
• الحجم: {round(last['volume'],2)}
• الإشارة: {signal} ✅
"""
                    send_telegram_message(msg)
                    print("تم إرسال إشارة:", symbol, signal)

            # الانتظار قبل الدورة التالية (مثلاً كل 10 دقائق)
            time.sleep(600)

        except Exception as e:
            print("خطأ عام:", e)
            time.sleep(60)

if __name__ == "__main__":
    # عند تشغيل البوت لأول مرة يرسل الترحيب
    start_bot()
    # ثم يبدأ المراقبة الكاملة
    monitor_all("1h")
