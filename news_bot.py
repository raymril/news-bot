# -*- coding: utf-8 -*-
"""
بوت أخبار حية - يعمل على GitHub Actions كل 10 دقائق
يتابع القنوات الإخبارية ويرسل ملخصات الأخبار العاجلة عبر Telegram
"""
import feedparser, requests, json, os, re, time, tempfile
from datetime import datetime
from google import genai

# ===== المتغيرات من البيئة (GitHub Secrets) =====
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
STATE_FILE     = "news_seen.json"

gemini = genai.Client(api_key=GEMINI_KEY)

# ===== المصادر الإخبارية =====
FEEDS = [
    ("BBC عربي",        "https://feeds.bbci.co.uk/arabic/rss.xml"),
    ("الجزيرة",          "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9"),
    ("RT عربي",         "https://arabic.rt.com/rss/"),
    ("العربية - إيران",   "https://www.alarabiya.net/feed/rss2/ar/iran.xml"),
    ("CNN عربي",        "https://arabic.cnn.com/api/v1/rss/rss.xml"),
    ("AP",              "https://feedx.net/rss/ap.xml"),
]

# ===== الكلمات المفتاحية =====
# كلمات أساسية - أي خبر يذكرها يُرسل مباشرة
PRIMARY_KEYWORDS = [
    # إيران-إسرائيل
    "إيران", "ايران", "الإيراني", "طهران", "خامنئي", "الحرس الثوري",
    "إسرائيل", "اسرائيل", "إسرائيلي", "نتنياهو", "تل أبيب", "الجيش الإسرائيلي",
    "حزب الله", "نصرالله", "نصر الله",
    # فلسطين وغزة
    "غزة", "حماس", "الأقصى", "خان يونس", "رفح", "جنين", "الضفة الغربية",
    # روسيا-أوكرانيا
    "بوتين", "الكرملين", "زيلينسكي", "كييف",
    # أمريكا - سياسة خارجية
    "ترامب", "بايدن", "البنتاغون", "البيت الأبيض",
    # الحوثيون والبحر الأحمر
    "الحوثي", "الحوثيون", "أنصار الله",
]

# كلمات الدول العربية - تُرسل فقط إذا ظهرت مع كلمة صراع/عسكرية
ARAB_COUNTRIES = [
    "السعودية", "الإمارات", "مصر", "الأردن", "سوريا", "العراق",
    "اليمن", "لبنان", "ليبيا", "السودان", "صنعاء", "البحر الأحمر",
    "روسيا", "موسكو", "أوكرانيا", "اوكرانيا", "أمريكا", "امريكا", "واشنطن",
]

CONFLICT_KEYWORDS = [
    "حرب", "هجوم", "صاروخ", "صواريخ", "قصف", "اشتباك", "غارة", "غارات",
    "ضربة", "عملية عسكرية", "تصعيد", "اقتحام", "اغتيال", "عقوبات",
    "نووي", "تطبيع", "محور", "تحالف", "حصار", "درون", "مسيّرة", "مسيرة",
    "إسرائيل", "اسرائيل", "إيران", "ايران", "أمريكا", "امريكا", "روسيا",
    "بوتين", "ترامب", "نتنياهو", "خامنئي", "حزب الله", "حماس",
]

# ===== Helpers =====
def load_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except: return set()
    return set()

def save_seen(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-3000:], f, ensure_ascii=False)

def matches_keywords(text):
    """
    فلتر ذكي:
    - الكلمات الأساسية (PRIMARY) → يُرسل الخبر مباشرة
    - الدول العربية (ARAB) → يُرسل فقط إذا ذُكرت مع كلمة صراع/عسكرية
    """
    text_lower = text.lower()

    # أولاً: فحص الكلمات الأساسية
    for kw in PRIMARY_KEYWORDS:
        if kw.lower() in text_lower:
            return kw

    # ثانياً: الدول العربية + كلمة صراع
    found_country = None
    for kw in ARAB_COUNTRIES:
        if kw.lower() in text_lower:
            found_country = kw
            break

    if found_country:
        for ck in CONFLICT_KEYWORDS:
            if ck.lower() in text_lower:
                return f"{found_country} | {ck}"

    return None

def clean_html(text):
    text = re.sub(r'<[^>]+>', '', text or "")
    return re.sub(r'\s+', ' ', text).strip()

def extract_media(entry):
    """استخراج صورة أو فيديو من الـ RSS entry"""
    image = None
    video = None

    # 1. media_content (أكثر المصادر تستخدمه)
    for m in entry.get("media_content", []) or []:
        url_m = m.get("url", "")
        mtype = (m.get("type") or "").lower()
        if "video" in mtype or url_m.endswith((".mp4", ".mov")):
            video = video or url_m
        elif "image" in mtype or url_m.endswith((".jpg", ".jpeg", ".png", ".webp")):
            image = image or url_m

    # 2. media_thumbnail
    if not image:
        for t in entry.get("media_thumbnail", []) or []:
            if t.get("url"):
                image = t["url"]
                break

    # 3. enclosures
    for e in entry.get("enclosures", []) or []:
        url_e = e.get("href") or e.get("url", "")
        etype = (e.get("type") or "").lower()
        if "video" in etype and not video:
            video = url_e
        elif "image" in etype and not image:
            image = url_e

    # 4. استخراج من HTML داخل summary/content
    if not image:
        html = entry.get("summary", "") or entry.get("description", "")
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        if m:
            image = m.group(1)

    return image, video

# قادة مهمون - الفيديو يحتاج ترجمة لو ذُكر اسمهم
LEADERS_FOR_VIDEO = [
    "ترامب", "بوتين", "نتنياهو", "خامنئي", "بزشكيان", "زيلينسكي", "بايدن",
    "محمد بن سلمان", "السيسي", "أردوغان", "ماكرون", "شي جين بينغ",
    "نصرالله", "نصر الله", "السنوار", "هنية", "الحوثي", "الأسد",
    "Trump", "Putin", "Netanyahu", "Khamenei", "Zelensky", "Biden", "Erdogan",
]

def has_leader(text):
    for ldr in LEADERS_FOR_VIDEO:
        if ldr in text:
            return ldr
    return None

def download_video(url, max_mb=45, timeout=60):
    """تنزيل فيديو مع فحص الحجم"""
    try:
        head = requests.head(url, allow_redirects=True, timeout=10)
        size = int(head.headers.get("content-length", 0))
        if size and size > max_mb * 1024 * 1024:
            print(f"  ⊘ فيديو كبير جداً ({size/1024/1024:.1f}MB)")
            return None
    except:
        pass

    try:
        r = requests.get(url, timeout=timeout, stream=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        total = 0
        for chunk in r.iter_content(chunk_size=65536):
            tmp.write(chunk)
            total += len(chunk)
            if total > max_mb * 1024 * 1024:
                tmp.close()
                os.unlink(tmp.name)
                print(f"  ⊘ تجاوز الحد أثناء التنزيل")
                return None
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"  خطأ تنزيل الفيديو: {e}")
        return None

def transcribe_translate_video(video_path):
    """رفع الفيديو لـ Gemini وتفريغ الكلام مترجم للعربية"""
    uploaded = None
    try:
        uploaded = gemini.files.upload(file=video_path)
        # انتظار المعالجة
        for _ in range(30):
            uploaded = gemini.files.get(name=uploaded.name)
            if uploaded.state.name != "PROCESSING":
                break
            time.sleep(2)

        if uploaded.state.name == "FAILED":
            print("  ✗ فشلت معالجة الفيديو في Gemini")
            return None

        prompt = """أنت مترجم فوري محترف. فرّغ الكلام في هذا الفيديو وترجمه إلى العربية الفصحى.

التعليمات:
- إذا كان الفيديو بالعربية أصلاً، انقل الكلام بدقة كما قيل.
- إذا كان بلغة أخرى، ترجم بأمانة بدون إضافة أو حذف.
- اقتصر على الكلام المنطوق فقط (تجاهل الموسيقى والمؤثرات).
- إذا تعدد المتحدثون، عرّف كل واحد إن أمكن.
- اكتب نصاً متواصلاً بفقرات منظمة، ليس قائمة.
- لا تضف مقدمات أو تعليقات.
- إذا لم يكن في الفيديو كلام واضح، اكتب: "لا يحتوي الفيديو على كلام منطوق."
"""
        r = gemini.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[uploaded, prompt]
        )
        text = r.text.strip()
        if "لا يحتوي" in text[:50]:
            return None
        return text
    except Exception as e:
        print(f"  خطأ تفريغ الفيديو: {e}")
        return None
    finally:
        if uploaded:
            try: gemini.files.delete(name=uploaded.name)
            except: pass

def rewrite_news(title, description, source):
    """إعادة صياغة الخبر بأسلوب وكالات الأنباء العالمية"""
    prompt = f"""أنت محرر في وكالة أنباء عالمية مثل رويترز أو فرانس برس. أعد صياغة الخبر بالعربية الفصحى بأسلوب احترافي ومحايد.

العنوان الأصلي: {title}
النص الأصلي: {description}
المصدر: {source}

التعليمات:
- اكتب فقرة واحدة متماسكة من 3-5 جمل (ليست قصيرة جداً ولا طويلة).
- ابدأ بأهم معلومة (المكان، الفاعل، الحدث).
- استخدم لغة الصحافة الجادة: محايدة، دقيقة، بدون مبالغة.
- لا تستخدم نقاط أو رموز إيموجي داخل النص.
- لا تضف معلومات غير موجودة في الخبر الأصلي.
- لا تكرر العنوان حرفياً.
- اكتب الخبر مباشرة بدون مقدمات."""

    try:
        r = gemini.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        return r.text.strip()
    except Exception as e:
        print(f"خطأ Gemini: {e}")
        return description[:500]

def tg_api(method, payload=None, files=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        if files:
            r = requests.post(url, data=payload, files=files, timeout=30)
        else:
            r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200, r.json() if r.text else {}
    except Exception as e:
        print(f"خطأ Telegram ({method}): {e}")
        return False, {}

def send_video_file(path, caption):
    """رفع فيديو محلي إلى تلقرام"""
    try:
        with open(path, "rb") as f:
            files = {"video": f}
            data = {
                "chat_id": CHAT_ID,
                "caption": caption[:1020] if len(caption) > 1020 else caption,
                "parse_mode": "HTML",
            }
            ok, _ = tg_api("sendVideo", payload=data, files=files)
            return ok
    except Exception as e:
        print(f"  خطأ رفع الفيديو: {e}")
        return False

def send_long_text(text):
    """إرسال نص طويل كرسالة منفصلة"""
    # تقسيم على 4000 حرف
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        tg_api("sendMessage", {
            "chat_id": CHAT_ID, "text": chunk,
            "parse_mode": "HTML", "disable_web_page_preview": True
        })
        time.sleep(1)

def send_news(caption, image=None, video=None, video_translation=None, video_local_path=None):
    """إرسال الخبر - الميديا فوق والنص تحت + ترجمة الفيديو إن وجدت"""
    short_caption = caption[:1020] + "…" if len(caption) > 1020 else caption

    sent_media = False

    # 1) فيديو محلي مترجم (نرفعه كملف)
    if video_local_path and os.path.exists(video_local_path):
        sent_media = send_video_file(video_local_path, short_caption)
        try: os.unlink(video_local_path)
        except: pass

    # 2) فيديو بـ URL
    if not sent_media and video:
        ok, _ = tg_api("sendVideo", {
            "chat_id": CHAT_ID, "video": video,
            "caption": short_caption, "parse_mode": "HTML"
        })
        sent_media = ok

    # 3) صورة
    if not sent_media and image:
        ok, _ = tg_api("sendPhoto", {
            "chat_id": CHAT_ID, "photo": image,
            "caption": short_caption, "parse_mode": "HTML"
        })
        sent_media = ok

    # 4) fallback نص بدون ميديا
    if not sent_media:
        ok, _ = tg_api("sendMessage", {
            "chat_id": CHAT_ID, "text": caption,
            "parse_mode": "HTML", "disable_web_page_preview": False
        })
        sent_media = ok

    # ترجمة الفيديو في رسالة منفصلة
    if sent_media and video_translation:
        time.sleep(1)
        send_long_text(
            f"🎙 <b>تفريغ وترجمة الفيديو</b>\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"{video_translation}"
        )

    return sent_media

def send_telegram(text):
    ok, _ = tg_api("sendMessage", {
        "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"
    })
    return ok

# ===== المعالج الرئيسي =====
def main():
    print(f"📡 بدء فحص الأخبار - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    seen = load_seen()
    is_first_run = len(seen) == 0
    total_sent = 0
    MAX_PER_RUN = 8  # سقف الأخبار لكل تشغيل لتجنب الإغراق

    if is_first_run:
        send_telegram(
            "📡 <b>بوت الأخبار جاهز</b>\n\n"
            "تغطية: الصراع الأمريكي-الإسرائيلي-الإيراني-الروسي، غزة وفلسطين، وأخبار الوطن العربي المرتبطة بهذه الملفات.\n\n"
            "المصادر: BBC • الجزيرة • RT • العربية • CNN • AP\n"
            "التحديث: كل 10 دقائق."
        )

    for source_name, url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  ✗ {source_name}: {e}")
            continue

        for entry in feed.entries:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not entry_id or entry_id in seen:
                continue

            title = clean_html(entry.get("title", ""))
            desc  = clean_html(entry.get("summary", "") or entry.get("description", ""))
            link  = entry.get("link", "")

            seen.add(entry_id)

            if total_sent >= MAX_PER_RUN:
                continue

            kw = matches_keywords(f"{title} {desc}")
            if not kw:
                continue

            image, video = extract_media(entry)
            body = rewrite_news(title, desc, source_name)

            # محاولة ترجمة الفيديو إذا فيه تصريح لقائد
            video_local = None
            video_translation = None
            leader = has_leader(f"{title} {desc}")
            if video and leader:
                print(f"  🎙 محاولة تفريغ فيديو ({leader})...")
                video_local = download_video(video)
                if video_local:
                    video_translation = transcribe_translate_video(video_local)
                    if video_translation:
                        print(f"  ✓ ترجمت ({len(video_translation)} حرف)")

            caption_lines = [
                f"<b>{title}</b>",
                "",
                body,
            ]
            if video_translation:
                caption_lines.append("")
                caption_lines.append("🎙 <i>الفيديو مترجم في الرسالة التالية</i>")
            caption_lines.extend([
                "",
                "━━━━━━━━━━━━━━",
                f"<i>{source_name}</i> • {datetime.now().strftime('%H:%M')}",
                f"<a href=\"{link}\">التفاصيل الكاملة ↗</a>",
            ])
            caption = "\n".join(caption_lines)

            sent = send_news(
                caption,
                image=image,
                video=video if not video_local else None,
                video_translation=video_translation,
                video_local_path=video_local,
            )

            if sent:
                total_sent += 1
                if video_translation:
                    media_tag = "🎙"
                elif video:
                    media_tag = "🎥"
                elif image:
                    media_tag = "🖼"
                else:
                    media_tag = "📝"
                print(f"  ✓ {media_tag} [{source_name}] {title[:60]}")
                time.sleep(20)

    save_seen(seen)
    print(f"\n✅ المرسلة: {total_sent} | المتابعة: {len(seen)}")

if __name__ == "__main__":
    main()
