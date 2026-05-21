# -*- coding: utf-8 -*-
"""
ملخص نهاية اليوم - تصريحات القادة المهمة
يُشغّل مرة واحدة يومياً عند 20:00 UTC (23:00 الرياض)
يجمع أخبار اليوم من المصادر، يستخرج تصريحات الرؤساء والقادة،
ويرسل ملخصاً موحداً يُثبَّت في المحادثة.
"""
import feedparser, requests, os, re
from datetime import datetime, timezone, timedelta
from google import genai

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]

gemini = genai.Client(api_key=GEMINI_KEY)

FEEDS = [
    ("BBC عربي",      "https://feeds.bbci.co.uk/arabic/rss.xml"),
    ("الجزيرة",        "https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9"),
    ("RT عربي",       "https://arabic.rt.com/rss/"),
    ("العربية - إيران", "https://www.alarabiya.net/feed/rss2/ar/iran.xml"),
    ("CNN عربي",      "https://arabic.cnn.com/api/v1/rss/rss.xml"),
    ("AP",            "https://feedx.net/rss/ap.xml"),
]

# القادة المستهدفون
LEADERS = [
    "ترامب", "بوتين", "نتنياهو", "خامنئي", "بزشكيان",
    "زيلينسكي", "بايدن", "محمد بن سلمان", "السيسي",
    "الملك عبدالله", "أردوغان", "ماكرون", "شي جين بينغ",
    "نصرالله", "نصر الله", "السنوار", "هنية",
]

# دلائل وجود تصريح
QUOTE_INDICATORS = [
    "قال", "صرّح", "صرح", "أعلن", "أكد", "هدد", "حذر", "حذّر",
    "رد", "ردّ", "أشار", "وصف", "اتهم", "اتّهم", "دعا", "طالب",
    "يقول", "يؤكد", "يصرح", "يعلن", "يهدد",
]

def clean_html(text):
    text = re.sub(r'<[^>]+>', '', text or "")
    return re.sub(r'\s+', ' ', text).strip()

def is_today(entry, tz_offset_hours=3):
    """فحص إذا الخبر نُشر اليوم (بتوقيت الرياض UTC+3)"""
    pub = entry.get("published_parsed") or entry.get("updated_parsed")
    if not pub:
        return True  # إذا ما فيه تاريخ، نشمله احتياطاً
    try:
        pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
        local = pub_dt + timedelta(hours=tz_offset_hours)
        today = (datetime.now(timezone.utc) + timedelta(hours=tz_offset_hours)).date()
        return local.date() == today
    except:
        return True

def has_leader_quote(text):
    """يحتوي على اسم قائد (يكفي ذكر اسمه)"""
    for ldr in LEADERS:
        if ldr in text:
            return ldr
    return None

def collect_quotes():
    """جمع تصريحات القادة من أخبار اليوم"""
    items = []
    for source_name, url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  ✗ {source_name}: {e}")
            continue

        for entry in feed.entries:
            if not is_today(entry):
                continue
            title = clean_html(entry.get("title", ""))
            desc  = clean_html(entry.get("summary", "") or entry.get("description", ""))
            combined = f"{title} {desc}"
            leader = has_leader_quote(combined)
            if leader:
                items.append({
                    "leader": leader,
                    "title": title,
                    "desc": desc[:400],
                    "source": source_name,
                })
    return items

def build_summary(items):
    """توليد ملخص احترافي بأسلوب وكالات الأنباء"""
    if not items:
        return None

    raw = "\n\n".join([
        f"[{i['source']}] {i['title']}\n{i['desc']}"
        for i in items[:30]
    ])

    prompt = f"""أنت محرر في وكالة أنباء دولية. لخّص أهم تصريحات القادة والرؤساء اليوم من الأخبار التالية.

الأخبار:
{raw}

اكتب الملخص بهذا التنسيق:
- ابدأ بعنوان: 📋 <b>تصريحات اليوم — [التاريخ]</b>
- ثم لكل قائد صدر عنه تصريح مهم اليوم: اسمه بالأبيض الغامق <b></b>، ثم تحته جملة أو جملتين تلخص أبرز ما قاله أو هدّد به أو أعلنه.
- اذكر القائد مرة واحدة فقط حتى لو تكرّر، ودمج تصريحاته في فقرة واحدة موجزة.
- رتّب القادة حسب الأهمية (ترامب، بوتين، نتنياهو، خامنئي، زيلينسكي، ثم البقية).
- استخدم لغة وكالات الأنباء: محايدة، دقيقة، بدون مبالغة.
- لا تضف معلومات من خارج الأخبار.
- لا تستخدم نقاط أو شرطات، اكتب فقرات نظيفة بين كل قائد والثاني فراغ سطر.
- إذا قائد ما عنده تصريح واضح، تجاهله.
- اختم بسطر: <i>المصادر: BBC، الجزيرة، RT، العربية، CNN، AP</i>"""

    try:
        r = gemini.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return r.text.strip()
    except Exception as e:
        print(f"خطأ Gemini: {e}")
        return None

def send_and_pin(text):
    """إرسال الرسالة وتثبيتها"""
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    data = r.json()
    if not data.get("ok"):
        print(f"خطأ الإرسال: {data}")
        return False

    msg_id = data["result"]["message_id"]

    # تثبيت الرسالة
    pin = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/pinChatMessage",
        json={
            "chat_id": CHAT_ID,
            "message_id": msg_id,
            "disable_notification": False,
        },
        timeout=15,
    )
    pin_data = pin.json()
    if not pin_data.get("ok"):
        print(f"⚠️ تعذّر التثبيت: {pin_data}")
    else:
        print(f"📌 تم التثبيت - msg_id={msg_id}")
    return True

def main():
    today_local = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%A %d/%m/%Y")
    print(f"📋 ملخص نهاية اليوم - {today_local}")

    items = collect_quotes()
    print(f"  جُمعت {len(items)} تصريحات")

    summary = build_summary(items)
    if not summary:
        # حتى لو ما فيه تصريحات، نرسل إشعار قصير
        send_and_pin(
            f"📋 <b>تصريحات اليوم — {today_local}</b>\n\n"
            f"لم تصدر تصريحات بارزة من القادة الرئيسيين اليوم."
        )
        return

    # ضمان أن العنوان يحوي التاريخ
    if today_local not in summary:
        summary = summary.replace("[التاريخ]", today_local)

    send_and_pin(summary)
    print("✅ تم إرسال وتثبيت ملخص اليوم")

if __name__ == "__main__":
    main()
