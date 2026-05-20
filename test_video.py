# -*- coding: utf-8 -*-
"""
اختبار: تنزيل فيديو، توليد ترجمة SRT بالعربية عبر Gemini،
حرق الترجمة على الفيديو عبر ffmpeg، وإرساله للتلقرام.
"""
import os, sys, tempfile, time, subprocess, requests, re
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
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML",
                  "supports_streaming": "true"},
            files={"video": f},
            timeout=180,
        )
    return r.status_code == 200, r.json()

def download(url, max_mb=45):
    print(f"⬇️ تنزيل: {url}")
    r = requests.get(url, timeout=120, stream=True,
                     headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        print(f"  ✗ HTTP {r.status_code}")
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    total = 0
    for chunk in r.iter_content(chunk_size=65536):
        tmp.write(chunk)
        total += len(chunk)
        if total > max_mb * 1024 * 1024:
            tmp.close()
            os.unlink(tmp.name)
            print(f"  ⊘ تجاوز {max_mb}MB")
            return None
    tmp.close()
    print(f"  ✓ نُزّل ({total/1024/1024:.2f}MB)")
    return tmp.name

def gen_srt(video_path):
    """توليد ملف SRT مع توقيتات وترجمة عربية"""
    print("🎙 رفع الفيديو لـ Gemini...")
    uploaded = gemini.files.upload(file=video_path)
    for i in range(60):
        uploaded = gemini.files.get(name=uploaded.name)
        if uploaded.state.name != "PROCESSING":
            break
        print(f"  ⏳ معالجة... ({i*2}s)")
        time.sleep(2)
    if uploaded.state.name == "FAILED":
        print("  ✗ فشلت معالجة الفيديو")
        return None

    prompt = """أنشئ ترجمة عربية كاملة لهذا الفيديو بصيغة SRT.

التعليمات الصارمة:
- اقتصر على الكلام المنطوق (تجاهل الموسيقى).
- ترجم بأمانة إلى العربية الفصحى الواضحة.
- كل مقطع ترجمة 2-4 ثوانٍ كحد أقصى.
- استخدم توقيتات دقيقة بصيغة HH:MM:SS,mmm
- لا تكتب أي تعليق أو شرح، فقط ملف SRT خام.

الصيغة المطلوبة بالضبط (لا تستخدم backticks ولا أكواد markdown):

1
00:00:00,500 --> 00:00:03,200
النص العربي هنا

2
00:00:03,300 --> 00:00:06,000
النص الثاني هنا

ابدأ مباشرة بالرقم 1."""

    r = gemini.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[uploaded, prompt]
    )
    try: gemini.files.delete(name=uploaded.name)
    except: pass

    srt = r.text.strip()
    # تنظيف: إزالة backticks إن وُجدت
    srt = re.sub(r'^```\w*\s*', '', srt)
    srt = re.sub(r'\s*```\s*$', '', srt)
    return srt

def burn_subtitles(video_path, srt_path, out_path):
    """حرق الترجمة على الفيديو عبر ffmpeg"""
    print("🔥 حرق الترجمة على الفيديو...")
    style = (
        "FontName=Noto Sans Arabic,"
        "FontSize=20,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=25"
    )
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles={srt_path}:force_style='{style}'",
        "-c:a", "copy",
        "-preset", "ultrafast",
        "-crf", "28",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        print(f"  ✗ ffmpeg فشل:\n{proc.stderr[-1500:]}")
        return False
    print(f"  ✓ تم الحرق ({os.path.getsize(out_path)/1024/1024:.2f}MB)")
    return True

def main():
    tg_send_text(
        f"🧪 <b>اختبار الترجمة المدمجة</b>\n"
        f"<a href=\"{VIDEO_URL}\">{LEADER_NAME}</a>\n"
        f"جارٍ التنزيل والمعالجة..."
    )

    src = download(VIDEO_URL)
    if not src:
        tg_send_text("❌ فشل تنزيل الفيديو")
        return

    srt_text = gen_srt(src)
    if not srt_text or "-->" not in srt_text:
        tg_send_text("❌ تعذّر توليد الترجمة")
        os.unlink(src)
        return
    print(f"📝 SRT ({len(srt_text)} حرف)")

    srt_file = tempfile.NamedTemporaryFile(suffix=".srt", delete=False,
                                            mode="w", encoding="utf-8")
    srt_file.write(srt_text)
    srt_file.close()

    out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    out.close()

    if not burn_subtitles(src, srt_file.name, out.name):
        tg_send_text("⚠️ فشل حرق الترجمة، إرسال الفيديو الأصلي")
        path_to_send = src
    else:
        path_to_send = out.name
        os.unlink(src)

    os.unlink(srt_file.name)

    caption = f"🎙 <b>{LEADER_NAME}</b>\n<i>ترجمة عربية مدمجة عبر Gemini</i>"
    ok, resp = tg_send_video(path_to_send, caption)
    try: os.unlink(path_to_send)
    except: pass

    if ok:
        print("✅ اكتمل")
    else:
        print(f"  ✗ فشل الإرسال: {resp}")
        tg_send_text(f"⚠️ فشل الإرسال للتلقرام")

if __name__ == "__main__":
    main()
