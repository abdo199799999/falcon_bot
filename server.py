# server.py
from flask import Flask
    
# هذا هو كل ما يفعله هذا الملف: تشغيل خادم ويب بسيط
app = Flask(__name__)
    
@app.route('/')
def health_check():
    return "Falcon Bot Service is running!", 200

