"""
waveform_video.py — يبني فيديو أفقي (1920×1080) من مقطع صوتي: خلفية داكنة
بنفس هوية باقي القنوات (كحلي + نجوم + هالة ذهبية) + عنوان ثابت + رقم الجزء +
موجة صوتية متحركة تتفاعل مع الصوت الفعلي.

لا حاجة لمعرفة اسم السورة لكل مقطع — فقط رقم تسلسلي ("الجزء رقم 37")، وهذا
يُبسّط النظام كثيرًا (لا داعٍ لخريطة توقيت السور، فقط تتبّع رقم الجزء).
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import arabic_reshaper
from bidi.algorithm import get_display
from moviepy import AudioFileClip, VideoClip

WIDTH, HEIGHT = 1920, 1080
FPS = 15  # منخفض بما يكفي لحركة موجة سلسة دون إرهاق وقت الترميز (مُختبر: ~0.57s/ثانية صوت)

try:
    LAYOUT_BASIC = ImageFont.Layout.BASIC
except AttributeError:
    LAYOUT_BASIC = ImageFont.LAYOUT_BASIC


def load_font(path, size, weight=None):
    """BASIC layout يمنع raqm من إعادة تشكيل النص (نقوم بـ reshape/bidi يدويًا
    هنا، وخلط الاثنين يُنتج نصًا مبعثرًا — نفس العلّة التي أصلحناها سابقًا)."""
    font = ImageFont.truetype(path, size, layout_engine=LAYOUT_BASIC)
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


def _build_base_background(font_path: str, title: str, part_label: str) -> Image.Image:
    top_color, bottom_color = (15, 10, 30), (5, 5, 10)
    img = Image.new("RGB", (WIDTH, HEIGHT), top_color)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        fill = tuple(int(top_color[i] * (1 - ratio) + bottom_color[i] * ratio) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=fill)

    _draw_stars(draw, WIDTH, HEIGHT)

    # هالة ذهبية خافتة خلف العنوان
    glow = Image.new("L", (WIDTH, HEIGHT), 0)
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([WIDTH / 2 - 420, HEIGHT / 2 - 260, WIDTH / 2 + 420, HEIGHT / 2 + 260], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    gold_layer = Image.new("RGB", (WIDTH, HEIGHT), (90, 70, 10))
    img = Image.composite(gold_layer, img, glow)
    draw = ImageDraw.Draw(img)

    margin = 30
    draw.rectangle([margin, margin, WIDTH - margin, HEIGHT - margin], outline=(255, 215, 0), width=3)

    title_font = load_font(font_path, 130, weight=700)
    bidi_title = get_display(arabic_reshaper.reshape(title))
    bbox = draw.textbbox((0, 0), bidi_title, font=title_font)
    tw = bbox[2] - bbox[0]
    ty = HEIGHT * 0.38 - (bbox[3] - bbox[1]) / 2
    draw.text(((WIDTH - tw) / 2 + 4, ty + 4), bidi_title, font=title_font, fill=(0, 0, 0))
    draw.text(((WIDTH - tw) / 2, ty), bidi_title, font=title_font, fill=(255, 255, 255))

    part_font = load_font(font_path, 54, weight=700)
    bidi_part = get_display(arabic_reshaper.reshape(part_label))
    bbox2 = draw.textbbox((0, 0), bidi_part, font=part_font)
    pw = bbox2[2] - bbox2[0]
    py = HEIGHT * 0.50
    draw.text(((WIDTH - pw) / 2, py), bidi_part, font=part_font, fill=(255, 215, 0))

    return img


def make_waveform_video(audio_path: str, font_path: str, title: str, part_label: str, out_path: str):
    """audio_path: مقطع مُقطَّع مسبقًا (~10 دقائق)، وليس الملف الكامل 25 ساعة."""
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    sr = 4000
    sound_array = audio_clip.to_soundarray(fps=sr)
    mono = sound_array.mean(axis=1) if sound_array.ndim > 1 else sound_array

    n_bars = 48
    bar_area_w = WIDTH * 0.7
    bar_x0 = (WIDTH - bar_area_w) / 2
    bar_y = HEIGHT * 0.72
    bar_max_h = HEIGHT * 0.16
    bar_gap = bar_area_w / n_bars

    base_img = _build_base_background(font_path, title, part_label)
    base_arr = np.array(base_img)

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
