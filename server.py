# server.py - النسخة التشخيصية
    
import os
import requests
from flask import Flask
    
app = Flask(__name__)
    
# اقرأ المتغيرات من البيئة
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    
@app.route('/')
def health_check_and_test_message():
    # سنحاول إرسال رسالة مباشرة باستخدام طلب HTTP بسيط
        
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return "Error: Telegram Token or Chat ID is missing in environment variables.", 500
            
    # تكوين الرسالة والـ URL الخاص بـ Telegram API
    message_text = "✅ Server is alive! This message was sent directly from the web server."
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message_text
    }
        
    try:
        # إرسال الطلب
        response = requests.post(url, json=payload)
        response_json = response.json()
            
        if response.status_code == 200 and response_json.get('ok'):
            # إذا نجح الإرسال
            return "OK! A test message has been successfully sent to your Telegram.", 200
        else:
            # إذا فشل الإرسال
            error_description = response_json.get('description', 'Unknown error')
            return f"Error sending message: {error_description}", 500
                
    except Exception as e:
        # في حالة وجود خطأ في الشبكة
        return f"Failed to connect to Telegram API: {str(e)}", 500

