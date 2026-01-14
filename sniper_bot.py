# -----------------------------------------------------------------------------
# sniper_bot.py - Falcon Sniper v1.5 (Clear Coin Names & Start Command)
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
import numpy as np

# --- إعدادات التسجيل وخادم الويب ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)
@app.route('/')
def health_check():
    return "Falcon Sniper Bot v1.5 is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- إعدادات الاستراتيجية ---
TIME_INTERVAL = Client.KLINE_INTERVAL_5MINUTE
VOLUME_THRESHOLD_MULTIPLIER = 10
PRICE_CHANGE_THRESHOLD = 3.0
SCAN_INTERVAL_SECONDS = 5 * 60
bought_coins = {}
coin_info_map = {} # قاموس لتخزين أسماء العملات

# --- أمر /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = (f"أهلاً بك يا {user.mention_html()}!\n\n"
               f"أنا **بوت القنص (Falcon Sniper v1.5)**.\n"
               f"أبحث عن انفجارات سعرية وأرسل لك أسماء العملات الواضحة.")
    await update.message.reply_html(message)

# --- دوال التحليل ---
def initialize_coin_info(client):
    """
    تجلب معلومات كل العملات مرة واحدة عند بدء التشغيل
    وتخزنها في قاموس للترجمة السريعة.
    """
    global coin_info_map
    try:
        logger.info("[Sniper] جارٍ تهيئة قاموس أسماء العملات...")
        exchange_info = client.get_exchange_info()
        for s in exchange_info['symbols']:
            if s['symbol'].endswith('USDT'):
                coin_info_map[s['symbol']] = s['baseAsset']
        logger.info(f"تم تهيئة القاموس بنجاح. تم العثور على {len(coin_info_map)} عملة.")
    except Exception as e:
        logger.error(f"[Sniper] فشل كبير في تهيئة أسماء العملات: {e}")

def get_all_usdt_pairs(client):
    if not coin_info_map:
        return []
    return list(coin_info_map.keys())

def analyze_for_explosion(client, symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval=TIME_INTERVAL, limit=51)
        if len(klines) < 50: return 'HOLD', None
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'])
        df['close'] = pd.to_numeric(df['close']); df['open'] = pd.to_numeric(df['open']); df['volume'] = pd.to_numeric(df['volume'])
        df_historical = df.iloc[:-1]; last_candle = df.iloc[-1]
        average_volume = df_historical['volume'].mean()
        if average_volume == 0: return 'HOLD', None
        volume_is_anomalous = last_candle['volume'] > (average_volume * VOLUME_THRESHOLD_MULTIPLIER)
        price_change = ((last_candle['close'] / last_candle['open']) - 1) * 100
        price_action_is_strong = price_change >= PRICE_CHANGE_THRESHOLD
        if volume_is_anomalous and price_action_is_strong:
            return 'BUY', last_candle['close']
    except Exception: pass
    return 'HOLD', None

# --- مهمة الفحص الدوري ---
async def scan_for_pumps(context):
    global bought_coins
    logger.info("--- [Sniper] بدء جولة البحث عن انفجارات سعرية (v1.5) ---")
    client = context.job.data['binance_client']
    chat_id = context.job.data['chat_id']

    for symbol, targets in list(bought_coins.items()):
        try:
            current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])
            clear_name = coin_info_map.get(symbol, symbol)
            if current_price >= targets['profit_target']:
                message = (f"🎯 *[Sniper] تم تحقيق الهدف ({clear_name})*\n\n"
                           f"• *سعر الشراء:* `{targets['buy_price']}`\n"
                           f"• *سعر البيع:* `{current_price}`\n"
                           f"• *الربح:* `~15%`")
                await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                del bought_coins[symbol]
            elif current_price <= targets['stop_loss']:
                message = (f"🛑 *[Sniper] تم تفعيل وقف الخسارة ({clear_name})*\n\n"
                           f"• *سعر الشراء:* `{targets['buy_price']}`\n"
                           f"• *سعر البيع:* `{current_price}`\n"
                           f"• *الخسارة:* `~-5%`")
                await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                del bought_coins[symbol]
        except Exception as e:
            logger.error(f"[Sniper] خطأ في التحقق من سعر {symbol}: {e}")
        await asyncio.sleep(0.5)

    symbols_to_scan = get_all_usdt_pairs(client)
    for symbol in symbols_to_scan:
        if symbol in bought_coins: continue
        
        status, price = analyze_for_explosion(client, symbol)
        if status == 'BUY':
            buy_price = price
            profit_target = buy_price * 1.15
            stop_loss = buy_price * 0.95
            
            bought_coins[symbol] = {
                'buy_price': buy_price,
                'profit_target': profit_target,
                'stop_loss': stop_loss
            }
            
            clear_name = coin_info_map.get(symbol, symbol)
            trade_link = f"https://www.binance.com/en/trade/{clear_name}_USDT"

            message = (f"🚀 *[Sniper] تم رصد انفجار سعري محتمل*\n\n"
                       f"• *الاسم:* *{clear_name}*\n"
                       f"• *الرمز:* `{symbol}`\n"
                       f"• *السعر الحالي:* `{buy_price}`\n"
                       f"• *الهدف:* `{profit_target:.4f}` `(+15%)`\n"
                       f"• *وقف الخسارة:* `{stop_loss:.4f}` `(-5%)`\n\n"
                       f"🔗 [رابط التداول المباشر]({trade_link})")
            try:
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"فشل إرسال رسالة القنص: {e}")

        await asyncio.sleep(0.2)

    logger.info(f"--- [Sniper] انتهاء جولة الفحص. العملات المراقبة: {list(bought_coins.keys())} ---")

# --- دالة التشغيل الرئيسية ---
def main():
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
    BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")
    
    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_SECRET_KEY]):
        logger.critical("!!! [Sniper] فشل: متغيرات البيئة غير كاملة. !!!")
        return

    try:
        binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        initialize_coin_info(binance_client)
    except Exception as e:
        logger.critical(f"فشل الاتصال ببينانس أو تهيئة الأسماء: {e}")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    job_data = {'binance_client': binance_client, 'chat_id': TELEGRAM_CHAT_ID}
    job_queue = application.job_queue
    job_queue.run_repeating(scan_for_pumps, interval=SCAN_INTERVAL_SECONDS, first=10, data=job_data)
    
    logger.info("--- [Sniper] البوت جاهز وقيد التشغيل. ---")
    application.run_polling()

if __name__ == "__main__":
    logger.info("--- [Sniper] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [Sniper] Web Server has been started. ---")
    main()

