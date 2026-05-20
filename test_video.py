# -*- coding: utf-8 -*-
"""
سكربت تجريبي لاختبار ميزة ترجمة الفيديو.
يقبل رابط فيديو، ينزّله، يفرّغه، يترجمه، ويرسله للتلقرام.
"""
import os, sys, tempfile, time, requests
from google import genai

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
VIDEO_URL      = os.environ.get("VIDEO_URL", "").strip()
LEADER_NAME    = os.environ.get("LEADER_NAME", "تجريبي").strip()

if not VIDEO_URL:
    print("❌ VIDEO_URL مفقود")
    sys.exit(1)

gemini = genai.Client(api_key=GEMINI_KEY)

def tg_send_text(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=20,
    )

def tg_send_video(path, caption):
    with open(path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"video": f},
            timeout=120,
        )
    return r.status_code == 200, r.json()

def download(url, max_mb=45):
    print(f"⬇️ تنزيل: {url}")
    r = requests.get(url, timeout=120, stream=True)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    total = 0
    for chunk in r.iter_content(chunk_size=65536):
        tmp.write(chunk)
        total += len(chunk)
        if total > max_mb * 1024 * 1024:
            tmp.close()
            os.unlink(tmp.name)
            print(f"  ⊘ تجاوز الحد {max_mb}MB")
            return None
    tmp.close()
    print(f"  ✓ نُزّل ({total/1024/1024:.2f}MB)")
    return tmp.name

def transcribe(path):
    print("🎙 رفع الفيديو لـ Gemini...")
    uploaded = gemini.files.upload(file=path)
    for i in range(60):
        uploaded = gemini.files.get(name=uploaded.name)
        if uploaded.state.name != "PROCESSING":
            break
        print(f"  ⏳ معالجة... ({i*2}s)")
        time.sleep(2)

    if uploaded.state.name == "FAILED":
        print("  ✗ فشلت المعالجة")
        return None

    prompt = """فرّغ الكلام في هذا الفيديو وترجمه إلى العربية الفصحى.

- إذا الفيديو بالعربية، انقل النص بدقة كما قيل.
- إذا بلغة أخرى، ترجمه بأمانة بدون إضافة أو حذف.
- اقتصر على الكلام المنطوق (تجاهل الموسيقى والمؤثرات).
- إذا تعدد المتحدثون، عرّف كل واحد بـ "المتحدث الأول:" أو اسمه.
- اكتب نصاً متواصلاً بفقرات منظمة.
- لا تضف مقدمات."""

    r = gemini.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[uploaded, prompt]
    )
    try:
        gemini.files.delete(name=uploaded.name)
    except: pass
    return r.text.strip()

def main():
    tg_send_text(
        f"🧪 <b>اختبار ترجمة الفيديو</b>\n"
        f"المصدر: <a href=\"{VIDEO_URL}\">{LEADER_NAME}</a>\n"
        f"جارٍ المعالجة..."
    )

    path = download(VIDEO_URL)
    if not path:
        tg_send_text("❌ فشل تنزيل الفيديو (حجم كبير أو رابط غير صالح)")
        return

    translation = transcribe(path)
    if not translation:
        tg_send_text("❌ فشل تفريغ الفيديو")
        os.unlink(path)
        return

    print(f"✓ التفريغ ({len(translation)} حرف)")

    caption = f"🎙 <b>{LEADER_NAME}</b>\nاختبار التفريغ والترجمة عبر Gemini"
    ok, resp = tg_send_video(path, caption)
    os.unlink(path)

    if not ok:
        print(f"  ✗ فشل رفع الفيديو: {resp}")
        tg_send_text("⚠️ فشل رفع الفيديو لتلقرام")

    # إرسال النص مهما حصل
    time.sleep(1)
    # تقسيم النص الطويل
    for i in range(0, len(translation), 4000):
        chunk = translation[i:i+4000]
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": f"📝 <b>التفريغ والترجمة:</b>\n━━━━━━━━━━\n\n{chunk}" if i == 0 else chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        time.sleep(1)

    print("✅ اكتمل الاختبار")

if __name__ == "__main__":
    main()
