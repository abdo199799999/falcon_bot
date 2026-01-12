import struct
import socket
from tqdm import tqdm
import time
import os
from threading import Thread
from http.server import SimpleHTTPRequestHandler, HTTPServer

# --- الجزء الجديد: الخادم الصوري لإرضاء Render ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    # إنشاء خادم بسيط لا يفعل شيئًا سوى الاستماع على البورت
    with HTTPServer(("", port), SimpleHTTPRequestHandler) as httpd:
        print(f"--- الخادم الصوري يعمل على البورت {port} ---")
        httpd.serve_forever()

# --- نفس الكود السابق لتوليد وتقسيم الـ IP ---
CLOUDFLARE_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22"
]
IPS_PER_PART = 40000

def generate_ips_from_cidr(cidr):
    try:
        ip, prefix = cidr.split('/')
        prefix = int(prefix)
        start_int = struct.unpack('!I', socket.inet_aton(ip))[0]
        num_addresses = 2**(32 - prefix)
        for i in range(1, num_addresses - 1):
            yield socket.inet_ntoa(struct.pack('!I', start_int + i))
    except Exception:
        return []

def main_task():
    print("--- بدء مهمة التوليد والتقسيم على خادم Render ---")
    all_ips = []
    print("الخطوة 1: توليد قائمة IP الكاملة...")
    for cidr in tqdm(CLOUDFLARE_RANGES, desc="معالجة النطاقات", unit=" range"):
        all_ips.extend(list(generate_ips_from_cidr(cidr)))
    total_ips = len(all_ips)
    if total_ips < 1800000:
        print(f"\nفشل التحقق: تم توليد {total_ips:,} IP فقط.")
        return
    else:
        print(f"\nنجاح: تم توليد {total_ips:,} عنوان IP.")
    print("\nالخطوة 2: بدء تقسيم القائمة إلى ملفات...")
    part_number = 1
    for i in tqdm(range(0, total_ips, IPS_PER_PART), desc="إنشاء الأجزاء", unit=" file"):
        batch = all_ips[i:i + IPS_PER_PART]
        file_name = f"part_{part_number}.txt"
        with open(file_name, "w") as f:
            f.write("\n".join(batch))
        part_number += 1
    print(f"\n--- اكتملت المهمة بنجاح على الخادم! ---")
    print(f"تم إنشاء {part_number - 1} ملفًا.")
    print("الخطوة التالية: استخدم 'Shell' في Render لضغط وتحميل الملفات.")
    print("\nالخادم سيبقى قيد التشغيل لمدة 15 دقيقة...")
    # لا نوقف البرنامج، نتركه يعمل مع الخادم الصوري
    
if __name__ == "__main__":
    # تشغيل الخادم الصوري في خيط منفصل في الخلفية
    server_thread = Thread(target=run_dummy_server)
    server_thread.daemon = True
    server_thread.start()
        
    # تشغيل مهمة التوليد الرئيسية
    main_task()

    # إبقاء البرنامج الرئيسي يعمل طالما الخادم يعمل
    time.sleep(900) # 15 دقيقة
    print("انتهى الوقت. يتم إيقاف الخادم.")

