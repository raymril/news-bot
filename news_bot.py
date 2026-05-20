# -*- coding: utf-8 -*-
"""
بوت أخبار حية - يعمل على GitHub Actions كل 10 دقائق
يتابع القنوات الإخبارية ويرسل ملخصات الأخبار العاجلة عبر Telegram
"""
import feedparser, requests, json, os, re, time, sys
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
    # --- الجزيرة (أسرع مصدر عربي) ---
    ("الجزيرة",          "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9"),
    # --- وكالات عالمية ---
    ("Reuters",         "https://feedx.net/rss/reuters.xml"),
    ("AFP",             "https://feedx.net/rss/afp.xml"),
    ("AP",              "https://feedx.net/rss/ap.xml"),
    # --- عربية ---
    ("العربية",          "https://www.alarabiya.net/feed/rss2/ar.xml"),
    ("سكاي نيوز",       "https://www.skynewsarabia.com/web/rss"),
    ("RT",              "https://arabic.rt.com/rss/"),
    ("BBC",             "https://feeds.bbci.co.uk/arabic/rss.xml"),
    ("CNN",             "https://arabic.cnn.com/api/v1/rss/rss.xml"),
    # --- Google News ---
    ("Google News",     "https://news.google.com/rss/search?q=%D8%B9%D8%A7%D8%AC%D9%84+%D8%A5%D9%8A%D8%B1%D8%A7%D9%86+OR+%D8%A5%D8%B3%D8%B1%D8%A7%D8%A6%D9%8A%D9%84+OR+%D8%BA%D8%B2%D8%A9+OR+%D8%AA%D8%B1%D8%A7%D9%85%D8%A8+OR+%D8%A8%D9%88%D8%AA%D9%8A%D9%86&hl=ar&gl=SA&ceid=SA:ar"),
    ("Google News",     "https://news.google.com/rss/search?q=%D8%BA%D8%B2%D8%A9&hl=ar&gl=SA&ceid=SA:ar"),
    ("Google News",     "https://news.google.com/rss/search?q=%D8%A5%D9%8A%D8%B1%D8%A7%D9%86&hl=ar&gl=SA&ceid=SA:ar"),
    ("Google News",     "https://news.google.com/rss/search?q=%D8%AA%D8%B1%D8%A7%D9%85%D8%A8&hl=ar&gl=SA&ceid=SA:ar"),
]

# ===== كشف الأخبار العاجلة الحقيقية =====
# فقط لو المصدر نفسه كتب "عاجل" أو "BREAKING" بالعنوان
BREAKING_PATTERNS = [
    r'^عاجل\s*[:|]',       # يبدأ بـ "عاجل:" أو "عاجل |"
    r'^\|\s*عاجل',          # يبدأ بـ "| عاجل"
    r'^BREAKING\s*[:|]',    # BREAKING: أو BREAKING |
    r'^JUST IN\s*[:|]',     # JUST IN:
    r'خبر عاجل',            # "خبر عاجل" في أي مكان
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

def is_breaking(title):
    """هل الخبر عاجل؟ فقط إذا المصدر نفسه وسمه عاجل بالعنوان"""
    for pat in BREAKING_PATTERNS:
        if re.search(pat, title, re.IGNORECASE):
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
    text = re.sub(r'<[^>]+>', '', text)
    text = html_mod.unescape(text)
    text = text.replace('\xa0', ' ')
    # إزالة اسم المصدر من النهاية (لاتيني أو عربي مع -)
    text = re.sub(r'\s*[-–—|]\s*[A-Za-zÀ-ɏ\s\.]{2,40}$', '', text)
    text = re.sub(r'\s*[-–—|]\s*[؀-ۿ\s\.]{2,30}$', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def clean_breaking_title(title):
    """تنظيف عنوان عاجل: إزالة كلمة عاجل المكررة والمصدر"""
    # إزالة "عاجل" و"عاجل:" و"عاجل |" من بداية العنوان
    t = re.sub(r'^[\s]*(?:عاجل\s*[:||\-–]\s*)+', '', title)
    t = re.sub(r'^[\s]*(?:BREAKING\s*[:|]\s*)+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^[\s]*(?:JUST IN\s*[:|]\s*)+', '', t, flags=re.IGNORECASE)
    return t.strip()

def normalize_title(title):
    """تطبيع العنوان لكشف التكرار"""
    t = re.sub(r'[^\w\s]', '', title.lower())
    # إزالة كلمات شائعة
    stop = {"في", "من", "إلى", "على", "عن", "أن", "هل", "بعد", "قبل", "بين", "مع", "هذا", "هذه", "التي", "الذي", "ان"}
    words = [w for w in t.split() if w not in stop and len(w) > 2]
    return set(words)

def is_duplicate_title(new_title, existing_titles):
    """هل العنوان مكرر (تشابه 50%+ مع عنوان سابق)؟"""
    new_words = normalize_title(new_title)
    if len(new_words) < 2:
        return False
    for existing in existing_titles:
        ex_words = normalize_title(existing)
        if not ex_words:
            continue
        common = new_words & ex_words
        similarity = len(common) / min(len(new_words), len(ex_words))
        if similarity >= 0.5:
            return True
    return False

def extract_media(entry):
    """استخراج صورة أو فيديو فقط إذا المصدر حطها بالـ RSS"""
    image = None
    video = None

    # 1. media_content
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

    return image, video


def shorten_headline(title, description):
    """اختصار العنوان الطويل لسطر واحد بأسلوب الجزيرة"""
    # إذا العنوان قصير كفاية (أقل من 120 حرف) نرجعه كما هو
    if len(title) <= 120:
        return title

    # العنوان طويل → نستخدم Gemini لاختصاره
    prompt = f"""اختصر هذا الخبر بجملة واحدة فقط (سطر واحد، أقل من 100 حرف) بأسلوب قناة الجزيرة العاجل.

القواعد:
- جملة واحدة مختصرة وقوية
- ابدأ بالفاعل الرسمي إن وُجد (البيت الأبيض، الكرملين، حزب الله...)
- بدون إيموجي، بدون نقاط، بدون علامات تعجب
- اكتب الجملة مباشرة بدون أي مقدمة

الخبر:
{title}
{description[:200]}"""

    try:
        r = gemini.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        result = r.text.strip().strip('"').strip("'")
        # تأكد إنه سطر واحد
        result = result.split('\n')[0]
        return result if result else title
    except Exception as e:
        print(f"  ⚠ Gemini: {str(e)[:80]}")
        # fallback: قص العنوان
        return title[:120]

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

# ===== بناء وإرسال خبر =====
def process_and_send(item, is_urgent):
    """معالجة خبر واحد وإرساله - بأسلوب قناة الجزيرة"""
    source_name, title, desc, link, image, video = item

    clean_title = clean_breaking_title(title)
    headline = shorten_headline(clean_title, desc)

    if is_urgent:
        # عاجل | الخبر
        caption = f"عاجل | {headline}"
    else:
        # المصدر | الخبر
        caption = f"{source_name} | {headline}"

    sent = send_news(
        caption,
        image=image,
        video=video,
    )

    if sent:
        tag = "🔴" if is_urgent else "📰"
        print(f"  ✓ {tag} [{source_name}] {title[:50]}")

    return sent

# ===== المعالج الرئيسي =====
def main():
    now = time.time()
    print(f"📡 بدء فحص الأخبار - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    seen, last_regular = load_state()
    is_first_run = len(seen) == 0

    # ===== جمع كل الأخبار الجديدة =====
    breaking_items = []   # أخبار عاجلة → فورية
    regular_items = []    # أخبار يومية → كل تشغيلة
    sent_titles = []      # عناوين مُرسلة لكشف التكرار
    source_count = {}     # عدد الأخبار لكل مصدر (تنويع)
    MAX_PER_SOURCE = 2    # أقصى خبرين من نفس المصدر لكل تشغيلة

    for source_name, url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  ✗ {source_name}: {e}")
            continue

        for entry in feed.entries:
          try:
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not entry_id or entry_id in seen:
                continue

            title = clean_html(entry.get("title", ""))
            desc  = clean_html(entry.get("summary", "") or entry.get("description", ""))
            link  = entry.get("link", "")

            seen.add(entry_id)

            # Google News: استخراج اسم المصدر الحقيقي
            if source_name == "Google News":
                real_source = entry.get("source", {})
                if hasattr(real_source, "get"):
                    source_name_actual = real_source.get("title") or real_source.get("value") or source_name
                elif hasattr(entry, "source") and hasattr(entry.source, "title"):
                    source_name_actual = entry.source.title
                else:
                    source_name_actual = source_name
            else:
                source_name_actual = source_name

            kw = matches_keywords(f"{title} {desc}")
            if not kw:
                continue

            # كشف التكرار: نفس الخبر من مصادر مختلفة
            if is_duplicate_title(title, sent_titles):
                print(f"  ⊘ مكرر: {title[:50]}")
                continue
            sent_titles.append(title)

            # حد أقصى لكل مصدر (تنويع المصادر)
            sc = source_count.get(source_name_actual, 0)
            if sc >= MAX_PER_SOURCE:
                print(f"  ⊘ تجاوز حد المصدر: [{source_name_actual}] {title[:40]}")
                continue
            source_count[source_name_actual] = sc + 1

            image, video = extract_media(entry)
            item = (source_name_actual, title, desc, link, image, video)

            # تصنيف: عاجل أم يومي
            if is_breaking(title):
                breaking_items.append(item)
            else:
                regular_items.append(item)
          except Exception as e:
            print(f"  ⚠ خطأ بمعالجة خبر [{source_name}]: {str(e)[:60]}")
            continue

    # ===== 1) إرسال الأخبار العاجلة فوراً (5 ثوانٍ بين كل خبر) =====
    sent_breaking = 0
    MAX_BREAKING = 15
    if breaking_items:
        print(f"\n🔴 أخبار عاجلة: {len(breaking_items)}")
        for i, item in enumerate(breaking_items[:MAX_BREAKING]):
            if process_and_send(item, is_urgent=True):
                sent_breaking += 1
            if i < len(breaking_items[:MAX_BREAKING]) - 1:
                time.sleep(5)

    # ===== 2) إرسال الأخبار اليومية - كل تشغيلة أقصى 3 أخبار (10 ثوانٍ بين كل خبر) =====
    sent_regular = 0
    MAX_REGULAR_PER_RUN = 3

    if regular_items:
        print(f"\n📰 أخبار يومية: {len(regular_items)} (يُرسل {min(len(regular_items), MAX_REGULAR_PER_RUN)})")
        for i, item in enumerate(regular_items[:MAX_REGULAR_PER_RUN]):
            if process_and_send(item, is_urgent=False):
                sent_regular += 1
            if i < min(len(regular_items), MAX_REGULAR_PER_RUN) - 1:
                time.sleep(10)

    save_state(seen, now)
    print(f"\n✅ عاجل: {sent_breaking} | يومي: {sent_regular} | المتابعة: {len(seen)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # لا يفشل أبداً - GitHub Actions يوقف الـ cron لو فشل كثير
        print(f"❌ خطأ عام: {e}")
        # حاول إرسال تنبيه
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": f"⚠️ خطأ في البوت: {str(e)[:200]}"},
                timeout=10,
            )
        except:
            pass
    # دائماً exit 0 حتى ما يتوقف الـ cron
    sys.exit(0)
