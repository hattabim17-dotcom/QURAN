"""
publish.py — ختمة علاء عقل
ينشر 3 فيديوهات يوميًا (10 دقائق لكل واحد تقريبًا) من ملف تلاوة واحد طويل (~25 ساعة)،
يتقدّم تسلسليًا دون قطع أي آية، ويُعيد الدورة من الصفر بعد اكتمال الملف (ختمة جديدة).

يعتمد على:
  • quran_cut.py  — يجد أقرب وقفة طبيعية قرب علامة 10 دقائق (بدل قطع عشوائي)
  • waveform_video.py — يبني فيديو أفقي بخلفية ثابتة + موجة صوتية متحركة
"""
import os
import sys
import json
import time
import logging
import functools
import subprocess
from pathlib import Path

import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from quran_cut import find_cut
from waveform_video import make_waveform_video

# --------------------------------------------------------------------------
# إعدادات — عدّل AUDIO_URL ليشير لرابط تحميل مباشر لملف Release الخاص بك
# --------------------------------------------------------------------------
AUDIO_URL = "https://github.com/hattabim17-dotcom/QURAN/releases/download/v1/Full_QURAN.mp3"

BASE_DIR = Path(__file__).resolve().parent
FONT_PATH = str(BASE_DIR / "assets" / "NotoNaskhArabic-Bold.ttf")
PROGRESS_PATH = BASE_DIR / "quran_progress.json"

TARGET_SECONDS = 600.0     # ~10 دقائق لكل فيديو
CUT_WINDOW = 45.0          # هامش البحث عن أقرب وقفة حول علامة الـ10 دقائق
TITLE_TEXT = "ختمة القرآن الكريم"
RECITER_NAME = "الشيخ علاء عقل"

GROQ_UNUSED = None  # لا حاجة لـ Groq هنا — لا نص مولَّد، فقط رقم جزء ثابت

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
REQUIRED_ENV_VARS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("khatma")


def check_required_env():
    missing = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
    if missing:
        sys.exit(f"❌ متغيرات بيئة ناقصة: {', '.join(missing)} — تحقق من GitHub Secrets.")


def notify_failure(message: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🚨 ختمة علاء عقل: {message}"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"تعذّر إرسال تنبيه Telegram: {e}")


def with_retries(max_attempts=3, base_delay=3.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts:
                        delay = base_delay * (2 ** (attempt - 1))
                        log.warning(f"{func.__name__} فشلت (محاولة {attempt}/{max_attempts}): {e} — إعادة بعد {delay:.0f}s")
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


# --------------------------------------------------------------------------
# التقدّم (quran_progress.json) — ملف صغير جدًا، يُحفظ بعد كل نشر ناجح فقط
# --------------------------------------------------------------------------
def load_progress() -> dict:
    if not PROGRESS_PATH.exists():
        return {"cursor": 0.0, "cycle": 1, "videos": 0, "total_duration": None}
    return json.loads(PROGRESS_PATH.read_text())


def save_progress(progress: dict):
    PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False, indent=2))


@with_retries(max_attempts=3, base_delay=5)
def probe_duration(url: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout.strip()
    return float(out)


@with_retries(max_attempts=3, base_delay=5)
def extract_segment(url: str, start: float, end: float, out_path: str):
    """يقتطع المقطع [start, end] مباشرة من الرابط عبر HTTP Range (لا يحمّل
    الملف كاملاً) ويعيد ترميزه (لا copy، لتفادي قطع غير نظيف عند حدود عشوائية)."""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
        "-i", url, "-vn", "-acodec", "libmp3lame", "-q:a", "4",
        out_path,
    ], check=True, timeout=180)


# --------------------------------------------------------------------------
# يوتيوب
# --------------------------------------------------------------------------
@with_retries(max_attempts=3, base_delay=5)
def upload_to_youtube(video_path: str, title: str, description: str) -> str:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": ["قرآن كريم", "تلاوة", "علاء عقل", "ختمة", "قرآن"],
                "categoryId": "22",
            },
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response["id"]


# --------------------------------------------------------------------------
# التشغيل الرئيسي
# --------------------------------------------------------------------------
def cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            os.remove(p)


def main():
    check_required_env()
    log.info("🚀 بدء تشغيل ختمة علاء عقل...")

    progress = load_progress()
    if progress["total_duration"] is None:
        log.info("⏱️ أول تشغيل — نقيس مدة الملف الكامل...")
        progress["total_duration"] = probe_duration(AUDIO_URL)
        save_progress(progress)
    total = progress["total_duration"]

    cursor = progress["cursor"]
    cut = find_cut(AUDIO_URL, cursor, TARGET_SECONDS, CUT_WINDOW, total)

    segment_path = str(BASE_DIR / "segment.mp3")
    video_path = str(BASE_DIR / "segment.mp4")

    try:
        log.info(f"✂️  استخراج المقطع: {cursor:.1f}s → {cut:.1f}s (المدة {cut - cursor:.1f}s)")
        extract_segment(AUDIO_URL, cursor, cut, segment_path)

        part_number = progress["videos"] + 1
        part_label = f"الجزء رقم {part_number} — الدورة {progress['cycle']}"
        log.info(f"🎬 بناء الفيديو: {part_label}")
        make_waveform_video(segment_path, FONT_PATH, TITLE_TEXT, part_label, video_path)

        title = f"{TITLE_TEXT} — {RECITER_NAME} | الجزء {part_number}"
        description = (
            f"تلاوة متواصلة للقرآن الكريم بصوت {RECITER_NAME}.\n"
            f"الجزء رقم {part_number} — الدورة {progress['cycle']}.\n\n"
            "🔔 اشترك لمتابعة الختمة كاملة، ثلاث مرات يوميًا."
        )
        video_id = upload_to_youtube(video_path, title, description)
        log.info(f"✅ تم النشر: https://youtu.be/{video_id}")

        # يُحفظ التقدّم فقط بعد نجاح الرفع فعليًا
        if cut >= total - 0.5:
            progress["cursor"] = 0.0
            progress["cycle"] += 1
            progress["videos"] = 0
            log.info("🔁 اكتملت الختمة — تبدأ دورة جديدة من البداية.")
        else:
            progress["cursor"] = cut
            progress["videos"] += 1
        save_progress(progress)

    except Exception as e:
        log.error(f"❌ خطأ أوقف التشغيل: {e}")
        notify_failure(f"خطأ في نشر المقطع عند الموضع {cursor:.0f}s: {e}")
        raise
    finally:
        cleanup(segment_path, video_path)


if __name__ == "__main__":
    main()
