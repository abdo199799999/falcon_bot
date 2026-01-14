# -*- coding: utf-8 -*-
import os
import ccxt
import requests

# قراءة متغيرات البيئة من منصة Render
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

def get_last_price(symbol="GLM/USDT", timeframe="1h"):
    """جلب آخر سعر للزوج المطلوب"""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1)
    last_candle = ohlcv[-1]
    current_price = last_candle[4]  # سعر الإغلاق
    return current_price

def send_telegram_message(message):
    """إرسال رسالة عبر Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(url, data=payload)
    return response.json()

def main():
    symbol = "GLM/USDT"  # يمكنك تغييره لأي زوج آخر
    price = get_last_price(symbol)

    # صياغة الرسالة
    msg = f"""👀 Binance إشارة

• العملة: {symbol.replace('/', '')}
• السعر الحالي: {price}
• الإشارة: شراء ✅
"""
    # إرسال الرسالة
    result = send_telegram_message(msg)
    print("تم إرسال الإشارة:", result)

if __name__ == "__main__":
    main()
