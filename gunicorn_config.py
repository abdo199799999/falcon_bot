# gunicorn_config.py
from threading import Thread
# استيراد دالة تشغيل البوت من ملف bot.py
from bot import run_bot
    
def on_starting(server):
    """
    هذا الخطاف يتم استدعاؤه مرة واحدة فقط عند بدء تشغيل Gunicorn.
    هذا هو المكان المثالي لتشغيل البوت.
    """
    print("Gunicorn is starting. Starting the Telegram bot in a background thread...")
    bot_thread = Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

