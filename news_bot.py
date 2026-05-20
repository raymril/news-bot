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

def summarize_news(title, description, source):
    prompt = f"""أنت محرر أخبار محترف. لخّص الخبر التالي بالعربية في 3 نقاط قصيرة:

العنوان: {title}
التفاصيل: {description}
المصدر: {source}

اكتب بهذا التنسيق:
📌 [النقطة الأساسية في جملة واحدة]
🔍 [السياق والتفاصيل]
💡 [الأهمية أو التأثير]

كن موجزاً ومحايداً ولا تضف معلومات من خارج الخبر."""

    try:
        r = gemini.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return r.text.strip()
    except Exception as e:
        print(f"خطأ Gemini: {e}")
        return f"📌 {description[:300]}"

def send_telegram(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15
        )
        return r.status_code == 200
    except Exception as e:
        print(f"خطأ Telegram: {e}")
        return False

# ===== المعالج الرئيسي =====
def main():
    print(f"📡 بدء فحص الأخبار - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    seen = load_seen()
    is_first_run = len(seen) == 0
    total_sent = 0

    if is_first_run:
        send_telegram(
            "📡 <b>بوت الأخبار بدأ العمل</b>\n\n"
            "سأرسل لك الأخبار العاجلة فور نزولها من 6 قنوات إخبارية:\n"
            "• BBC عربي • الجزيرة • RT عربي\n"
            "• العربية • CNN عربي • AP\n\n"
            "🎯 المواضيع:\n"
            "• الحرب الإيرانية-الإسرائيلية\n"
            "• فلسطين وغزة\n"
            "• روسيا وأوكرانيا\n"
            "• أمريكا والوطن العربي\n\n"
            "⏱ التحديث: كل 10 دقائق على مدار اليوم"
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

            if is_first_run:
                continue

            kw = matches_keywords(f"{title} {desc}")
            if not kw:
                continue

            summary = summarize_news(title, desc, source_name)

            msg = (
                f"📰 <b>{source_name}</b> | 🏷 {kw}\n"
                f"⏰ {datetime.now().strftime('%H:%M %d/%m')}\n"
                f"{'─' * 25}\n\n"
                f"<b>{title}</b>\n\n"
                f"{summary}\n\n"
                f"🔗 <a href=\"{link}\">قراءة الخبر كاملاً</a>"
            )

            if send_telegram(msg):
                total_sent += 1
                print(f"  ✓ [{source_name}] {title[:60]}")
                time.sleep(2)

    save_seen(seen)
    print(f"\n✅ المرسلة: {total_sent} | المتابعة: {len(seen)}")

if __name__ == "__main__":
    main()
