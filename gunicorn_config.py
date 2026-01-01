# gunicorn_config.py
from threading import Thread
from bot import run_bot
        
def post_worker_init(worker):
    print("Gunicorn worker is ready. Starting the Telegram bot in a background thread...")
    bot_thread = Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

