# -----------------------------------------------------------------------------
# bot.py - النسخة النهائية مع تصحيح حلقة الأحداث (Event Loop)
# -----------------------------------------------------------------------------

# ... (كل الكود من البداية حتى دالة run_bot يبقى كما هو تمامًا) ...
# ... (imports, flask app, logging, strategy functions, scan_market, start) ...

# --- الدالة الرئيسية لتشغيل البوت (مع تصحيح حلقة الأحداث) ---
def run_bot():
    logger.info("--- بدء تشغيل مكون البوت ---")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
    BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")

    if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_SECRET_KEY]):
        logger.critical("!!! فشل: متغيرات البيئة غير كاملة. !!!")
        return

    try:
        binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        binance_client.ping()
    except Exception as e:
        logger.critical(f"فشل الاتصال ببينانس: {e}")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    job_data = {'binance_client': binance_client, 'chat_id': TELEGRAM_CHAT_ID}
    job_queue = application.job_queue
    job_queue.run_repeating(scan_market, interval=SCAN_INTERVAL_SECONDS, first=10, data=job_data)

    logger.info("--- البوت جاهز ويعمل. جدولة فحص السوق كل 15 دقيقة. ---")
    
    # --- الجزء الذي تم تعديله ---
    # بدلاً من application.run_polling() مباشرة
    # نقوم بإنشاء حلقة أحداث جديدة خاصة بهذا الثريد
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # الآن نقوم بتشغيل البوت داخل هذه الحلقة
    try:
        loop.run_until_complete(application.initialize())
        if application.post_init:
            loop.run_until_complete(application.post_init())
        loop.run_until_complete(application.updater.start_polling())
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("تلقى إشارة إيقاف، يتم إيقاف البوت...")
    finally:
        if application.updater.is_running:
            loop.run_until_complete(application.updater.stop())
        if application.post_shutdown:
            loop.run_until_complete(application.post_shutdown())
        loop.run_until_complete(application.shutdown())
        loop.close()
        logger.info("تم إيقاف البوت بنجاح.")


