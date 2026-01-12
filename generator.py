import struct
import socket
from tqdm import tqdm
import time
import os # استيراد مكتبة os للتحقق من الملفات

# هذا الكود مخصص لملف generator.py
# سيتم تشغيله على خادم Render مخصص ومؤقت

# --- الإعدادات ---
CLOUDFLARE_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22"
]
IPS_PER_PART = 40000

# --- منطق التوليد اليدوي (مضمون للعمل على أي بيئة لينكس) ---
def generate_ips_from_cidr(cidr):
    """
    مولد يدوي ومضمون لعناوين IP من نطاق CIDR.
    """
    try:
        ip, prefix = cidr.split('/')
        prefix = int(prefix)
        start_int = struct.unpack('!I', socket.inet_aton(ip))[0]
        
        # حساب عدد العناوين في النطاق
        num_addresses = 2**(32 - prefix)
        
        # توليد كل عنوان IP في النطاق (باستثناء عنوان الشبكة والبث)
        for i in range(1, num_addresses - 1):
            yield socket.inet_ntoa(struct.pack('!I', start_int + i))
    except Exception as e:
        print(f"خطأ في معالجة النطاق {cidr}: {e}")
        # إرجاع قائمة فارغة في حالة حدوث خطأ لتجنب إيقاف البرنامج
        return []


def main_task():
    print("--- بدء مهمة التوليد والتقسيم على خادم Render ---")
    
    all_ips = []
    print("الخطوة 1: توليد قائمة IP الكاملة (الطريقة اليدوية المضمونة)...")
    
    # استخدام tqdm لإظهار التقدم في سجلات Render
    for cidr in tqdm(CLOUDFLARE_RANGES, desc="معالجة النطاقات", unit=" range"):
        all_ips.extend(list(generate_ips_from_cidr(cidr)))
            
    total_ips = len(all_ips)
    
    # التحقق من أن العدد صحيح
    if total_ips < 1800000:
        print(f"\n\033[91mفشل التحقق:\033[0m تم توليد {total_ips:,} IP فقط. هناك خطأ ما.")
        print("سيتم إيقاف الخادم.")
        return
    else:
        print(f"\n\033[92mنجاح:\033[0m تم توليد {total_ips:,} عنوان IP.")

    print("\nالخطوة 2: بدء تقسيم القائمة إلى ملفات...")
    
    part_number = 1
    for i in tqdm(range(0, total_ips, IPS_PER_PART), desc="إنشاء الأجزاء", unit=" file"):
        batch = all_ips[i:i + IPS_PER_PART]
        file_name = f"part_{part_number}.txt"
        with open(file_name, "w") as f:
            f.write("\n".join(batch))
        part_number += 1
        
    print(f"\n--- \033[92mاكتملت المهمة بنجاح على الخادم!\033[0m ---")
    print(f"تم إنشاء {part_number - 1} ملفًا.")
    print("الخطوة التالية: استخدم 'Shell' في Render لضغط وتحميل الملفات.")
    
    # إبقاء البرنامج يعمل لإعطائك وقتًا للوصول إلى الـ Shell
    print("\nالخادم سيبقى قيد التشغيل لمدة 15 دقيقة...")
    print("يمكنك الآن فتح نافذة Shell والبدء في ضغط الملفات.")
    time.sleep(900) # 15 دقيقة
    print("انتهى الوقت. يتم إيقاف الخادم.")

if __name__ == "__main__":
    main_task()

