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
    # --- مصادر عربية أساسية ---
    ("BBC عربي",        "https://feeds.bbci.co.uk/arabic/rss.xml"),
    ("الجزيرة",          "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9"),
    ("RT عربي",         "https://arabic.rt.com/rss/"),
    ("العربية - إيران",   "https://www.alarabiya.net/feed/rss2/ar/iran.xml"),
    ("CNN عربي",        "https://arabic.cnn.com/api/v1/rss/rss.xml"),
    ("AP",              "https://feedx.net/rss/ap.xml"),
    # --- وكالات أنباء عالمية (أخبار عاجلة) ---
    ("Reuters",         "https://feedx.net/rss/reuters.xml"),
    ("AFP",             "https://feedx.net/rss/afp.xml"),
    # --- Google News عاجل (بحث مخصص) ---
    ("Google إيران-إسرائيل", "https://news.google.com/rss/search?q=%D8%A5%D9%8A%D8%B1%D8%A7%D9%86+%D8%A5%D8%B3%D8%B1%D8%A7%D8%A6%D9%8A%D9%84&hl=ar&gl=SA&ceid=SA:ar"),
    ("Google غزة",          "https://news.google.com/rss/search?q=%D8%BA%D8%B2%D8%A9+%D8%AD%D8%B1%D8%A8&hl=ar&gl=SA&ceid=SA:ar"),
    ("Google روسيا-أوكرانيا", "https://news.google.com/rss/search?q=%D8%B1%D9%88%D8%B3%D9%8A%D8%A7+%D8%A3%D9%88%D9%83%D8%B1%D8%A7%D9%86%D9%8A%D8%A7&hl=ar&gl=SA&ceid=SA:ar"),
    ("Google ترامب",        "https://news.google.com/rss/search?q=%D8%AA%D8%B1%D8%A7%D9%85%D8%A8&hl=ar&gl=SA&ceid=SA:ar"),
    # --- العربية أقسام إضافية ---
    ("العربية - عاجل",   "https://www.alarabiya.net/feed/rss2/ar.xml"),
    ("سكاي نيوز عربية", "https://www.skynewsarabia.com/web/rss"),
]

# ===== كلمات الأخبار العاجلة (أولوية عالية) =====
BREAKING_KEYWORDS = [
    "عاجل", "خبر عاجل", "عاجل |", "| عاجل",
    "BREAKING", "Breaking News", "JUST IN",
    "بيان عاجل", "تطور عاجل", "الآن",
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

# فاصل زمني بين دفعات الأخبار اليومية (ساعتين = 7200 ثانية)
REGULAR_INTERVAL = 7200

# ===== Helpers =====
def load_state():
    """تحميل الحالة: الأخبار المرئية + وقت آخر إرسال يومي"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                # دعم الصيغة القديمة (قائمة فقط) والجديدة (dict)
                if isinstance(data, list):
                    return set(data), 0
                return set(data.get("seen", [])), data.get("last_regular", 0)
            except:
                return set(), 0
    return set(), 0

def save_state(seen, last_regular):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "seen": list(seen)[-3000:],
            "last_regular": last_regular,
        }, f, ensure_ascii=False)

def is_breaking(text):
    """هل الخبر عاجل؟"""
    for kw in BREAKING_KEYWORDS:
        if kw.lower() in text.lower():
            return True
    return False

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
    import html as html_mod
    text = text or ""
    text = re.sub(r'<[^>]+>', '', text)       # إزالة تاقات HTML
    text = html_mod.unescape(text)             # تحويل &nbsp; &amp; وغيرها
    text = text.replace('\xa0', ' ')           # مسافات غير قابلة للكسر
    # إزالة اسم المصدر المكرر في نهاية العنوان (مثل " - Anadolu Ajansı")
    text = re.sub(r'\s*[-–—|]\s*[A-Za-zÀ-ɏ\s]{3,30}$', '', text)
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

    for attempt in range(3):
        try:
            r = gemini.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            return r.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = (attempt + 1) * 15
                print(f"  ⏳ Gemini rate limit، انتظار {wait}s...")
                time.sleep(wait)
            else:
                print(f"خطأ Gemini: {e}")
                return description[:500]
    return description[:500]

def tg_api(method, payload=None, files=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
        if files:
            r = requests.post(url, data=payload, files=files, timeout=180)
        else:
            r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200, r.json() if r.text else {}
    except Exception as e:
        print(f"خطأ Telegram ({method}): {e}")
        return False, {}

def send_news(caption, image=None, video=None):
    """إرسال الخبر - الميديا فوق والنص تحت"""
    short_caption = caption[:1020] + "…" if len(caption) > 1020 else caption

    sent_media = False

    # 1) فيديو بـ URL
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

    return sent_media

def send_telegram(text):
    ok, _ = tg_api("sendMessage", {
        "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"
    })
    return ok

# كلمات تدل على خبر عاجل مهم (يستحق تلخيص)
IMPORTANT_BREAKING = [
    "حرب", "هجوم", "قصف", "غارة", "صاروخ", "اجتياح", "اغتيال",
    "نووي", "تصعيد كبير", "إعلان حرب", "وقف إطلاق النار",
    "انسحاب", "اتفاق", "معاهدة", "عقوبات جديدة",
]

def is_important_breaking(title, desc):
    """هل الخبر العاجل مهم بما يكفي للتلخيص؟"""
    text = f"{title} {desc}".lower()
    for kw in IMPORTANT_BREAKING:
        if kw in text:
            return True
    # أي كلمة أساسية من القادة = مهم
    for ldr in ["ترامب", "بوتين", "نتنياهو", "خامنئي", "زيلينسكي", "بايدن"]:
        if ldr in text:
            return True
    return False

# ===== بناء وإرسال خبر =====
def process_and_send(item, is_urgent):
    """معالجة خبر واحد وإرساله"""
    source_name, title, desc, link, image, video = item

    if is_urgent:
        # عاجل عادي: بدون تلخيص، نص أصلي مرتب
        # عاجل مهم: يلخّص عبر Gemini
        if is_important_breaking(title, desc):
            body = rewrite_news(title, desc, source_name)
            print(f"  🔴⭐ عاجل مهم → تلخيص Gemini")
        else:
            # تنظيف النص الأصلي وإرساله مباشر
            body = desc[:600] if desc and desc != title else ""
    else:
        # يومي: دائماً يلخّص عبر Gemini
        body = rewrite_news(title, desc, source_name)

    caption_lines = []
    if is_urgent:
        caption_lines.append("🔴 <b>عاجل</b>")
        caption_lines.append("")
    caption_lines.append(f"<b>{title}</b>")
    if body:
        caption_lines.append("")
        caption_lines.append(body)
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
        video=video,
    )

    if sent:
        tag = "🔴" if is_urgent else "📰"
        if video:
            tag = "🎥"
        elif image:
            tag = "🖼"
        print(f"  ✓ {tag} [{source_name}] {title[:60]}")

    return sent

# ===== المعالج الرئيسي =====
def main():
    now = time.time()
    print(f"📡 بدء فحص الأخبار - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    seen, last_regular = load_state()
    is_first_run = len(seen) == 0

    if is_first_run:
        send_telegram(
            "📡 <b>بوت الأخبار جاهز</b>\n\n"
            "🔴 الأخبار العاجلة: فورية (كل 10 دقائق)\n"
            "📰 الأخبار اليومية: كل ساعتين\n\n"
            "المصادر: BBC • الجزيرة • RT • العربية • CNN • AP • Reuters • AFP • سكاي نيوز • Google News"
        )

    # ===== جمع كل الأخبار الجديدة =====
    breaking_items = []   # أخبار عاجلة → فورية
    regular_items = []    # أخبار يومية → كل ساعتين

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

            kw = matches_keywords(f"{title} {desc}")
            if not kw:
                continue

            image, video = extract_media(entry)
            item = (source_name, title, desc, link, image, video)

            # تصنيف: عاجل أم يومي
            if is_breaking(f"{title} {desc}"):
                breaking_items.append(item)
            else:
                regular_items.append(item)

    # ===== 1) إرسال الأخبار العاجلة فوراً (5 ثوانٍ بين كل خبر) =====
    sent_breaking = 0
    MAX_BREAKING = 10
    if breaking_items:
        print(f"\n🔴 أخبار عاجلة: {len(breaking_items)}")
        for item in breaking_items[:MAX_BREAKING]:
            if process_and_send(item, is_urgent=True):
                sent_breaking += 1
                time.sleep(5)

    # ===== 2) إرسال الأخبار اليومية كل ساعتين (10 ثوانٍ بين كل خبر) =====
    sent_regular = 0
    MAX_REGULAR = 8
    time_since_last = now - last_regular
    regular_due = time_since_last >= REGULAR_INTERVAL or is_first_run

    if regular_items and regular_due:
        print(f"\n📰 أخبار يومية: {len(regular_items)} (آخر دفعة قبل {time_since_last/60:.0f} دقيقة)")
        for item in regular_items[:MAX_REGULAR]:
            if process_and_send(item, is_urgent=False):
                sent_regular += 1
                time.sleep(10)
        last_regular = now  # تحديث وقت آخر دفعة
    elif regular_items:
        remaining = REGULAR_INTERVAL - time_since_last
        print(f"\n📰 {len(regular_items)} خبر يومي محفوظ (الدفعة القادمة بعد {remaining/60:.0f} دقيقة)")

    save_state(seen, last_regular)
    print(f"\n✅ عاجل: {sent_breaking} | يومي: {sent_regular} | المتابعة: {len(seen)}")

if __name__ == "__main__":
    main()
