"""
waveform_video.py — يبني فيديو أفقي (1920×1080) من مقطع صوتي: خلفية داكنة
بنفس هوية باقي القنوات (كحلي + نجوم + هالة ذهبية) + عنوان ثابت + رقم الجزء +
موجة صوتية متحركة تتفاعل مع الصوت الفعلي.

لا حاجة لمعرفة اسم السورة لكل مقطع — فقط رقم تسلسلي ("الجزء رقم 37")، وهذا
يُبسّط النظام كثيرًا (لا داعٍ لخريطة توقيت السور، فقط تتبّع رقم الجزء).
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import AudioFileClip, VideoClip

WIDTH, HEIGHT = 1920, 1080
FPS = 15  # منخفض بما يكفي لحركة موجة سلسة دون إرهاق وقت الترميز (مُختبر: ~0.57s/ثانية صوت)

# ملاحظة مهمة: هنا نعتمد على raqm المدمج فـ Pillow مباشرة (direction="rtl")
# بدل reshape/bidi يدوي + BASIC layout. السبب: خط AmiriQuran (المخصص لكتابة
# النص القرآني بجمالية خاصة) مبني على تشكيل OpenType ذكي عبر raqm فقط، ولا
# يحتوي أشكال العرض الجاهزة (Presentation Forms) التي ينتجها reshape اليدوي
# — خلطهما ينتج مربعات فارغة مكسورة. بما أننا لا نخلط الطريقتين هنا إطلاقًا
# (raqm فقط، فـ كل الأسطر)، لا تحدث مشكلة "المعالجة المزدوجة" التي واجهناها
# سابقًا مع خطوط أخرى (تلك كانت بسبب الجمع بين الطريقتين، وليس raqm نفسه).


def load_font(path, size, weight=None):
    font = ImageFont.truetype(path, size)
    if weight:
        try:
            axes = font.get_variation_axes()
            if axes:
                font.set_variation_by_axes([weight])
        except Exception:
            pass
    return font


def _draw_stars(draw, w, h, count=140):
    rng = np.random.RandomState(42)
    for _ in range(count):
        x, y = rng.randint(0, w), rng.randint(0, h)
        r = rng.choice([1, 1, 1, 2])
        b = rng.randint(40, 110)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(int(b), int(b), int(b) + 15))


def _centered_text(draw, text, font, y, fill, shadow=False):
    """يرسم سطرًا واحدًا متمركزًا أفقيًا عند الإحداثي y (الحافة العلوية
    المرجعية لـ PIL)، معتمدًا على raqm مباشرة للتشكيل العربي الصحيح.
    يُعيد الحافة السفلية الفعلية للنص (y + bbox[3]) — وليس "ارتفاعًا" مجردًا
    — لأن خطوطًا كـ Amiri Quran لها تشكيل زخرفي يمتد كثيرًا فوق/تحت خط
    الأساس (bbox[1] غير صفري)، فالتكديس يجب أن يعتمد الحافة الحقيقية
    لتفادي تراكب الأسطر، وهو ما حدث فعليًا قبل هذا الإصلاح."""
    bbox = draw.textbbox((0, 0), text, font=font, direction="rtl", language="ar")
    w = bbox[2] - bbox[0]
    x = (WIDTH - w) / 2
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0), direction="rtl", language="ar")
    draw.text((x, y), text, font=font, fill=fill, direction="rtl", language="ar")
    return y + bbox[3]


def _build_base_background(fonts: dict, reciter_name: str) -> Image.Image:
    """التصميم: بسملة + استعاذة في الأعلى (بخط Amiri الأنيق)، "القرآن الكريم"
    كعنوان مركزي كبير (بخط Amiri Quran المخصص للنصوص القرآنية)، اسم الشيخ
    تحته، و"صدقة جارية" في أسفل الإطار كإهداء بسيط."""
    top_color, bottom_color = (15, 10, 30), (5, 5, 10)
    img = Image.new("RGB", (WIDTH, HEIGHT), top_color)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        fill = tuple(int(top_color[i] * (1 - ratio) + bottom_color[i] * ratio) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=fill)

    _draw_stars(draw, WIDTH, HEIGHT)

    # هالة ذهبية خافتة خلف العنوان المركزي
    glow = Image.new("L", (WIDTH, HEIGHT), 0)
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([WIDTH / 2 - 460, HEIGHT / 2 - 280, WIDTH / 2 + 460, HEIGHT / 2 + 280], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    gold_layer = Image.new("RGB", (WIDTH, HEIGHT), (90, 70, 10))
    img = Image.composite(gold_layer, img, glow)
    draw = ImageDraw.Draw(img)

    margin = 30
    draw.rectangle([margin, margin, WIDTH - margin, HEIGHT - margin], outline=(255, 215, 0), width=3)

    # الاستعاذة والبسملة — أعلى الشاشة، بخط Amiri العادي الأنيق (غير عريض،
    # يناسب نصًا طويلاً نسبيًا دون أن يبدو ثقيلاً). التكديس يعتمد الحافة
    # السفلية الفعلية المُعادة من _centered_text (وليس نسب ثابتة) لتفادي أي
    # تراكب، إذ تختلف ارتفاعات الخطوط الزخرفية اختلافًا كبيرًا عن المتوقع.
    istiadhah_font = load_font(fonts["amiri_regular"], 44)
    y = _centered_text(draw, "أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ",
                        istiadhah_font, HEIGHT * 0.06, (210, 205, 190)) + 20

    basmala_font = load_font(fonts["amiri_bold"], 50)
    y = _centered_text(draw, "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ", basmala_font, y, (255, 230, 150)) + 30

    draw.line([(WIDTH / 2 - 90, y), (WIDTH / 2 + 90, y)], fill=(255, 215, 0), width=2)
    y += 70

    # العنوان المركزي الكبير: "القرآن الكريم" — بخط Amiri Quran المخصص
    title_font = load_font(fonts["amiri_quran"], 140)
    y = _centered_text(draw, "الْقُرْآنُ الْكَرِيمُ", title_font, y, (255, 255, 255), shadow=True) + 40

    # اسم الشيخ تحت العنوان مباشرة
    reciter_font = load_font(fonts["amiri_bold"], 56)
    y = _centered_text(draw, reciter_name, reciter_font, y, (255, 215, 0))

    # "صدقة جارية" — إهداء بسيط أسفل الإطار (موضع ثابت، بعيد عن كل ما سبق)
    sadaqah_font = load_font(fonts["amiri_regular"], 40)
    _centered_text(draw, "صَدَقَةٌ جَارِيَةٌ", sadaqah_font, HEIGHT * 0.90, (190, 185, 170))

    # نُعيد الحافة السفلية الفعلية لاسم الشيخ، لتموضع الموجة الصوتية تحتها
    # مباشرة بهامش آمن — بدل رقم ثابت قد يتصادم مع النص حسب طول اسم القارئ
    return img, y


def make_waveform_video(audio_path: str, fonts: dict, reciter_name: str, out_path: str):
    """audio_path: مقطع مُقطَّع مسبقًا (~10 دقائق)، وليس الملف الكامل 25 ساعة."""
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    sr = 4000
    sound_array = audio_clip.to_soundarray(fps=sr)
    mono = sound_array.mean(axis=1) if sound_array.ndim > 1 else sound_array

    base_img, text_bottom_y = _build_base_background(fonts, reciter_name)
    base_arr = np.array(base_img)

    n_bars = 48
    bar_area_w = WIDTH * 0.7
    bar_x0 = (WIDTH - bar_area_w) / 2
    sadaqah_top_y = HEIGHT * 0.90 - 55   # هامش أمان فوق سطر "صدقة جارية"
    bar_y = text_bottom_y + (sadaqah_top_y - text_bottom_y) / 2  # في منتصف المسافة المتبقية
    bar_max_h = min(HEIGHT * 0.12, (sadaqah_top_y - text_bottom_y) / 2 - 20)
    bar_gap = bar_area_w / n_bars

    def get_bar_heights(t):
        center = int(t * sr)
        window = int(sr * 0.05)
        heights = []
        for b in range(n_bars):
            offset = int((b - n_bars / 2) * window * 0.6)
            i0 = max(0, center + offset - window // 2)
            i1 = min(len(mono), center + offset + window // 2)
            if i1 <= i0:
                heights.append(0.0)
                continue
            rms = np.sqrt(np.mean(mono[i0:i1] ** 2))
            heights.append(min(1.0, rms * 6))
        return heights

    def make_frame(t):
        img = Image.fromarray(base_arr.copy())
        draw = ImageDraw.Draw(img)
        for i, h in enumerate(get_bar_heights(t)):
            bh = max(6, h * bar_max_h)
            x = bar_x0 + i * bar_gap + bar_gap * 0.2
            w = bar_gap * 0.6
            draw.rounded_rectangle([x, bar_y - bh, x + w, bar_y + bh], radius=w / 2, fill=(255, 215, 0))
        return np.array(img)

    video = VideoClip(make_frame, duration=duration).with_fps(FPS)
    video = video.with_audio(audio_clip)
    video.write_videofile(
        out_path, fps=FPS, codec="libx264", audio_codec="aac",
        bitrate="4000k", preset="medium", logger=None,
    )
    return out_path
