# -*- coding: utf-8 -*-
"""
بوت أخبار حية - يعمل على GitHub Actions كل 10 دقائق
يتابع القنوات الإخبارية ويرسل ملخصات الأخبار العاجلة عبر Telegram
"""
import feedparser, requests, json, os, re, time
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
        r = gemini.models.generate_content(model="gemini-2.5-flash", contents=prompt)
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

def send_news(caption, image=None, video=None):
    """إرسال الخبر مع الميديا - الفيديو/الصورة فوق والنص تحت"""
    # Telegram caption limit = 1024 chars
    if len(caption) > 1020:
        caption_short = caption[:1015] + "…"
    else:
        caption_short = caption

    if video:
        ok, _ = tg_api("sendVideo", {
            "chat_id": CHAT_ID, "video": video,
            "caption": caption_short, "parse_mode": "HTML"
        })
        if ok: return True

    if image:
        ok, _ = tg_api("sendPhoto", {
            "chat_id": CHAT_ID, "photo": image,
            "caption": caption_short, "parse_mode": "HTML"
        })
        if ok: return True

    # fallback: نص بدون ميديا
    ok, _ = tg_api("sendMessage", {
        "chat_id": CHAT_ID, "text": caption,
        "parse_mode": "HTML", "disable_web_page_preview": False
    })
    return ok

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

            caption = (
                f"<b>{title}</b>\n\n"
                f"{body}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"<i>{source_name}</i> • {datetime.now().strftime('%H:%M')}\n"
                f"<a href=\"{link}\">التفاصيل الكاملة ↗</a>"
            )

            if send_news(caption, image=image, video=video):
                total_sent += 1
                media_tag = "🎥" if video else ("🖼" if image else "📝")
                print(f"  ✓ {media_tag} [{source_name}] {title[:60]}")
                time.sleep(20)

    save_seen(seen)
    print(f"\n✅ المرسلة: {total_sent} | المتابعة: {len(seen)}")

if __name__ == "__main__":
    main()
