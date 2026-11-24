#!/usr/bin/env python3
"""
Ролик «3 находки с GitHub» для TikTok / Instagram Reels.

Берёт 3 последних опубликованных поста из sent/ (кроме удалённых),
собирает вертикальное видео 1080×1920 без звука (звук добавляешь
трендовый прямо в TikTok/Instagram) и присылает его владельцу в личку
вместе с готовым описанием.

    python reel.py                 — собрать из 3 последних постов в out/
    python reel.py --send          — собрать и прислать в Telegram
    python reel.py --posts a.json,b.json,c.json   — выбрать посты вручную
    python reel.py --send-file out/x.mp4 [--posts …] — прислать готовый ролик (из Remotion)

Нужны: Python 3.8+, Pillow, ffmpeg.
"""
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence

import bot

BASE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(BASE, "fonts")
OUT = os.path.join(BASE, "out")
OWNER_FILE = os.path.join(BASE, "state", "owner_chat_id.txt")
LAST_REEL = os.path.join(BASE, "state", "last_reel.json")

W, H, FPS = 1080, 1920, 30
BG = (13, 17, 23)
FG = (240, 246, 252)
MUTED = (139, 148, 158)
ACCENT = (63, 185, 80)
CARD = (22, 27, 34)
BORDER = (48, 54, 61)

HOOK_S, FIND_S, CTA_S = 2.6, 7.5, 4.5
MEDIA_W, MEDIA_H = 920, 560
MEDIA_X, MEDIA_Y = (W - MEDIA_W) // 2, 500
TEXT_X, TEXT_R = 80, 960          # правый край текста: справа кнопки TikTok

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def font(weight, size):
    return ImageFont.truetype(os.path.join(FONTS, f"Inter-{weight}.otf"), size)


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    s = EMOJI.sub("", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


# ------------------------------------------------------------------ данные

def extract(post):
    """Короткие тексты для ролика из поста (или из поля post['video'])."""
    title = clean(post.get("title", post["repo"]))
    name, _, tagline = title.partition(" — ")
    text = post.get("text", "")
    points = [clean(l.strip()[1:]) for l in text.split("\n") if l.strip().startswith("•")]
    m = re.search(r"Платформы:\s*(?:</b>)?\s*([^\n]+)", text)
    platforms = clean(m.group(1)) if m else ""
    m = re.search(r"⭐\s*([^·\n]+)", text)
    stars = clean(m.group(1)) if m else ""
    m = re.match(r"[\d.,]+\s*[kKкК]?\+?", stars)
    stars = m.group(0).replace(" ", "") if m else ""
    platforms = re.sub(r"\s*\([^)]*\)", "", platforms)
    points = [re.sub(r"\s*\([^)]*\)", "", p) for p in points]
    v = post.get("video", {})
    return {
        "name": v.get("name", name),
        "tagline": v.get("tagline", tagline),
        "points": v.get("points", points)[:3],
        "platforms": v.get("platforms", platforms),
        "stars": v.get("stars", stars),
        "repo": post["repo"],
    }


def pick_posts(names=None):
    sent = os.path.join(BASE, "sent")
    if names:
        files = names
    else:
        files = sorted(f for f in os.listdir(sent) if f.endswith(".json"))
    posts = []
    for f in files:
        with open(os.path.join(sent, f), encoding="utf-8") as fh:
            p = json.load(fh)
        if not names and p.get("deleted_at"):
            continue
        p["_file"] = f
        posts.append(p)
    return posts[-3:]


# ------------------------------------------------------------------ медиа

def cover(img, w, h, overflow=1.0):
    """Масштаб «cover» с запасом overflow для плавного движения камеры."""
    img = img.convert("RGB")
    s = max(w / img.width, h / img.height) * overflow
    return img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)


class Media:
    """Кадр медиа по времени: картинка с плавным проездом, гифка или видео."""

    def __init__(self, kind, data, tmp):
        self.frames, self.still = None, None
        if kind == "video":
            src = os.path.join(tmp, "src.mp4")
            with open(src, "wb") as f:
                f.write(data)
            d = os.path.join(tmp, "vf")
            os.makedirs(d, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", src, "-t", str(FIND_S),
                            "-vf", f"fps={FPS},scale={MEDIA_W}:{MEDIA_H}:force_original_aspect_ratio=increase,"
                                   f"crop={MEDIA_W}:{MEDIA_H}",
                            "-q:v", "3", os.path.join(d, "%04d.jpg")], check=True)
            self.frames = [os.path.join(d, f) for f in sorted(os.listdir(d))]
            if not self.frames:
                raise ValueError("видео без кадров")
            self.fps = FPS
        else:
            im = Image.open(io.BytesIO(data))
            n = getattr(im, "n_frames", 1)
            if n > 1:
                self.frames = [cover(fr.copy(), MEDIA_W, MEDIA_H) for _, fr in
                               zip(range(240), ImageSequence.Iterator(im))]
                dur = im.info.get("duration", 80) or 80
                self.fps = 1000 / dur
            else:
                self.still = cover(im, MEDIA_W, MEDIA_H, overflow=1.12)

    def at(self, t):
        if self.frames:
            i = int(t * self.fps) % len(self.frames)
            fr = self.frames[i]
            if isinstance(fr, str):
                return Image.open(fr).convert("RGB")
            return fr.crop(((fr.width - MEDIA_W) // 2, (fr.height - MEDIA_H) // 2,
                            (fr.width - MEDIA_W) // 2 + MEDIA_W, (fr.height - MEDIA_H) // 2 + MEDIA_H))
        p = ease(t / FIND_S) if t < FIND_S else 1
        dx, dy = self.still.width - MEDIA_W, self.still.height - MEDIA_H
        x, y = round(dx * p), round(dy * 0.5)
        return self.still.crop((x, y, x + MEDIA_W, y + MEDIA_H))


def load_media(post, tmp):
    for item in post.get("media", []):
        try:
            _, data, _ = bot.download(item["url"])
            size = bot.media_size(data)
            if not size or size[0] < bot.MIN_W or size[1] < bot.MIN_H:
                continue
            return Media(item.get("type", "photo"), data, tmp)
        except Exception as e:
            bot.log("  медиа для ролика не подошло:", item.get("url"), e)
    if post.get("fallback_image"):
        try:
            _, data, _ = bot.download(post["fallback_image"])
            return Media("photo", data, tmp)
        except Exception as e:
            bot.log("  превью не скачалось:", e)
    return None


# ------------------------------------------------------------------ рисование

def wrap(draw, text, fnt, width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=fnt) > width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def text_layer(lines, fnt, color, spacing=1.18):
    """Готовый RGBA-слой с текстом (рисуется один раз)."""
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    asc, desc = fnt.getmetrics()
    lh = round((asc + desc) * spacing)
    w = max((tmp.textlength(l, font=fnt) for l in lines), default=1)
    im = Image.new("RGBA", (int(w) + 4, lh * len(lines) + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((0, i * lh), l, font=fnt, fill=color)
    return im


def fit_font(text, weight, size, min_size, width):
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while size > min_size and d.textlength(text, font=font(weight, size)) > width:
        size -= 2
    return font(weight, size)


def pill(text, fnt, fg, bg, pad=(26, 12), border=None):
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = d.textlength(text, font=fnt)
    asc, desc = fnt.getmetrics()
    w, h = int(tw + pad[0] * 2), asc + desc + pad[1] * 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=bg, outline=border, width=2 if border else 0)
    dd.text((pad[0], pad[1]), text, font=fnt, fill=fg)
    return im


def fade(layer, a):
    if a >= 1:
        return layer
    out = layer.copy()
    out.putalpha(out.getchannel("A").point([int(v * max(0.0, a)) for v in range(256)]))
    return out


def put(frame, layer, x, y, a=1.0):
    if a <= 0:
        return
    frame.alpha_composite(fade(layer, a), (int(x), int(y)))


def background():
    bg = Image.new("RGB", (W, H), BG)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((-300, -400, W + 300, 900), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    tint = Image.new("RGB", (W, H), (20, 60, 35))
    bg = Image.composite(tint, bg, glow)
    return bg.convert("RGBA")


def chrome(bg):
    """Надпись канала сверху — на всех кадрах."""
    lay = text_layer(["GitHub Finder · Telegram"], font("SemiBold", 30), MUTED)
    bg = bg.copy()
    put(bg, lay, (W - lay.width) // 2, 70)
    return bg


def progress(frame, t_global, total):
    d = ImageDraw.Draw(frame)
    d.rectangle((0, 0, W, 9), fill=(33, 38, 45, 255))
    d.rectangle((0, 0, int(W * t_global / total), 9), fill=ACCENT + (255,))


# ------------------------------------------------------------------ субтитры

def word_timings(text, start, end):
    """Раскладывает слова по времени речи пропорционально длине (+ паузы на знаках)."""
    words = []
    for w in text.split():
        if w in ("—", "–", "-") and words:
            words[-1] += " " + w          # тире не отдельным словом
        else:
            words.append(w)
    weights = []
    for w in words:
        wt = len(w.strip("«»—-,.!?:")) + 2
        if w[-1:] in ".!?":
            wt += 6
        elif w[-1:] in ",:—" or w == "—":
            wt += 3
        weights.append(wt)
    total, t, out = sum(weights) or 1, start, []
    for w, wt in zip(words, weights):
        d = (end - start) * wt / total
        out.append((t, t + d, w))
        t += d
    return out


class Captions:
    """Крупные субтитры по 2–4 слова, текущее слово подсвечено."""

    def __init__(self, timings, size=66, max_w=None):
        self.timings = timings
        self.fnt = font("Black", size)
        self.max_w = max_w or (TEXT_R - TEXT_X)
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.chunks, cur = [], []
        for i, (a, b, w) in enumerate(timings):
            test = " ".join(x[2] for x in cur + [(a, b, w)])
            if cur and (d.textlength(test, font=self.fnt) > self.max_w or len(cur) >= 4
                        or cur[-1][2][-1:] in ".!?,:"):
                self.chunks.append(cur)
                cur = []
            cur.append((a, b, w))
        if cur:
            self.chunks.append(cur)
        self.cache = {}

    def layer(self, ci, wi):
        key = (ci, wi)
        if key not in self.cache:
            chunk = self.chunks[ci]
            d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            space = d.textlength(" ", font=self.fnt) * 1.8
            widths = [d.textlength(w, font=self.fnt) for _, _, w in chunk]
            asc, desc = self.fnt.getmetrics()
            wtot = int(sum(widths) + space * (len(chunk) - 1)) + 40
            im = Image.new("RGBA", (wtot, asc + desc + 30), (0, 0, 0, 0))
            dd = ImageDraw.Draw(im)
            x = 20
            for j, ((_, _, w), ww) in enumerate(zip(chunk, widths)):
                if j == wi:
                    dd.rounded_rectangle((x - 12, 6, x + ww + 12, asc + desc + 22), radius=16, fill=ACCENT + (255,))
                    dd.text((x, 12), w, font=self.fnt, fill=BG)
                else:
                    dd.text((x, 12), w, font=self.fnt, fill=FG, stroke_width=4, stroke_fill=(0, 0, 0, 200))
                x += ww + space
            self.cache[key] = im
        return self.cache[key]

    def draw(self, f, t, cy):
        for ci, chunk in enumerate(self.chunks):
            if chunk[0][0] <= t < (self.chunks[ci + 1][0][0] if ci + 1 < len(self.chunks) else chunk[-1][1] + 0.3):
                wi = max(j for j, (a, _, _) in enumerate(chunk) if a <= t or j == 0)
                lay = self.layer(ci, wi)
                f.alpha_composite(lay, (int((W - lay.width) / 2), int(cy - lay.height / 2)))
                return


# ------------------------------------------------------------------ сцены

class Scene:
    duration = 1.0
    captions = None
    caption_y = 1560

    def with_voice(self, dur, captions, caption_y=None):
        self.duration, self.captions = dur, captions
        if caption_y:
            self.caption_y = caption_y
        return self

    def overlay(self, f, t):
        if self.captions:
            self.captions.draw(f, t, self.caption_y)
        return f

    def frame(self, t):
        raise NotImplementedError


class Hook(Scene):
    duration = HOOK_S

    def __init__(self, base):
        self.base = base
        big = font("Black", 112)
        self.lines = [text_layer([l], big, c) for l, c in (
            ("3 находки", ACCENT), ("с GitHub,", FG), ("о которых", FG), ("ты не знал", FG))]
        self.tag = pill("бесплатно · open source", font("SemiBold", 38), FG, (33, 38, 45), border=BORDER)
        self.save = text_layer(["досмотри до конца ↓"], font("Medium", 38), MUTED)

    def frame(self, t):
        f = self.base.copy()
        y = 470
        for i, lay in enumerate(self.lines):
            p = ease((t - i * 0.12) / 0.35)
            put(f, lay, TEXT_X, y + (1 - p) * 60, p)
            y += 140
        p = ease((t - 0.7) / 0.4)
        put(f, self.tag, TEXT_X, y + 40 + (1 - p) * 30, p)
        put(f, self.save, TEXT_X, y + 170, ease((t - 1.2) / 0.4))
        return f


class Find(Scene):
    duration = FIND_S

    def __init__(self, base, n, info, media):
        self.base, self.media = base, media
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.num = pill(f"{n} / 3", font("Bold", 40), BG, ACCENT, pad=(28, 10))
        nf = fit_font(info["name"], "Black", 92, 56, TEXT_R - TEXT_X)
        self.name = text_layer(wrap(d, info["name"], nf, TEXT_R - TEXT_X, 1), nf, FG)
        tf = font("Medium", 40)
        self.tagline = text_layer(wrap(d, info["tagline"], tf, TEXT_R - TEXT_X, 2), tf, MUTED)
        pf = font("SemiBold", 40)
        self.points = []
        for p in info["points"]:
            self.points.append(text_layer(wrap(d, p, pf, TEXT_R - TEXT_X - 70, 2), pf, FG))
        check = Image.new("RGBA", (46, 46), (0, 0, 0, 0))
        cd = ImageDraw.Draw(check)
        cd.ellipse((0, 0, 45, 45), fill=ACCENT)
        cd.line((12, 24, 20, 32, 34, 15), fill=BG, width=6, joint="curve")
        self.check = check
        self.plat = None
        if info["platforms"]:
            pfz = fit_font(info["platforms"], "SemiBold", 34, 24, TEXT_R - TEXT_X - 60)
            self.plat = pill(info["platforms"], pfz, FG, (33, 38, 45), border=BORDER)
        self.stars = pill("★ " + info["stars"], font("Bold", 34), (255, 214, 102), (33, 38, 45),
                          border=BORDER) if info["stars"] else None
        self.media_y = max(MEDIA_Y, 240 + self.name.height + 6 + self.tagline.height + 34)
        # тень и маска карточки
        self.mask = Image.new("L", (MEDIA_W, MEDIA_H), 0)
        ImageDraw.Draw(self.mask).rounded_rectangle((0, 0, MEDIA_W - 1, MEDIA_H - 1), radius=30, fill=255)
        sh = Image.new("RGBA", (MEDIA_W + 120, MEDIA_H + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((60, 75, MEDIA_W + 60, MEDIA_H + 75), radius=34, fill=(0, 0, 0, 150))
        self.shadow = sh.filter(ImageFilter.GaussianBlur(28))
        self.frame_border = Image.new("RGBA", (MEDIA_W, MEDIA_H), (0, 0, 0, 0))
        ImageDraw.Draw(self.frame_border).rounded_rectangle(
            (0, 0, MEDIA_W - 1, MEDIA_H - 1), radius=30, outline=BORDER + (255,), width=3)
        if media is None:
            ph = Image.new("RGB", (MEDIA_W, MEDIA_H), CARD)
            lay = text_layer([info["repo"]], font("Bold", 54), FG)
            ph = ph.convert("RGBA")
            put(ph, lay, (MEDIA_W - lay.width) // 2, (MEDIA_H - lay.height) // 2)
            self.placeholder = ph.convert("RGB")

    def frame(self, t):
        f = self.base.copy()
        p = ease(t / 0.35)
        dx = (1 - p) * 120
        put(f, self.num, TEXT_X + dx, 150, p)
        if self.stars:
            put(f, self.stars, TEXT_X + self.num.width + 18 + dx, 150 + (self.num.height - self.stars.height) // 2, p)
        put(f, self.name, TEXT_X + dx, 240, p)
        put(f, self.tagline, TEXT_X + dx, 240 + self.name.height + 6, ease((t - 0.15) / 0.35))
        # карточка с медиа
        mp = ease((t - 0.2) / 0.45)
        if mp > 0:
            img = self.media.at(t) if self.media else self.placeholder
            card = img.convert("RGBA")
            card.putalpha(self.mask)
            card.alpha_composite(self.frame_border)
            y = self.media_y + (1 - mp) * 80
            put(f, self.shadow, MEDIA_X - 60, y - 60, mp)
            put(f, card, MEDIA_X, y, mp)
        # пункты (с озвучкой их заменяют субтитры)
        y = self.media_y + MEDIA_H + 56
        if self.captions:
            if self.plat:
                a = ease((t - 0.6) / 0.35)
                put(f, self.plat, TEXT_X, y + (1 - a) * 30, a)
            return f
        for i, lay in enumerate(self.points):
            a = ease((t - 1.0 - i * 0.7) / 0.35)
            off = (1 - a) * 40
            put(f, self.check, TEXT_X, y + 4 + off, a)
            put(f, lay, TEXT_X + 70, y + off, a)
            y += lay.height + 22
        if self.plat:
            a = ease((t - 1.0 - len(self.points) * 0.7) / 0.35)
            put(f, self.plat, TEXT_X, y + 14 + (1 - a) * 30, a)
        return f


class Cta(Scene):
    duration = CTA_S

    def __init__(self, base, infos, tg_line="Все ссылки — в Telegram"):
        self.base = base
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.q = text_layer(["Какая зашла?"], font("Black", 104), FG)
        self.q2 = text_layer(["Пиши 1, 2 или 3 в комментах"], font("SemiBold", 44), ACCENT)
        self.rows = []
        nf = font("Bold", 46)
        for i, info in enumerate(infos):
            row = Image.new("RGBA", (TEXT_R - TEXT_X, 100), (0, 0, 0, 0))
            rd = ImageDraw.Draw(row)
            rd.rounded_rectangle((0, 0, row.width - 1, 99), radius=24, fill=CARD + (255,), outline=BORDER + (255,), width=2)
            rd.ellipse((22, 22, 78, 78), fill=ACCENT)
            num = str(i + 1)
            rd.text((50 - rd.textlength(num, font=nf) / 2, 22), num, font=nf, fill=BG)
            label = wrap(rd, info["name"], nf, row.width - 130, 1)[0]
            rd.text((104, 22), label, font=nf, fill=FG)
            self.rows.append(row)
        self.tg1 = text_layer([tg_line], font("SemiBold", 46), MUTED)
        self.tg2 = pill("GitHub Finder", font("Black", 64), BG, ACCENT, pad=(40, 18))
        self.save = text_layer(["Сохрани, чтобы не потерять"], font("Medium", 40), MUTED)

    def frame(self, t):
        f = self.base.copy()
        p = ease(t / 0.35)
        put(f, self.q, TEXT_X, 300 + (1 - p) * 50, p)
        put(f, self.q2, TEXT_X, 440, ease((t - 0.2) / 0.35))
        y = 560
        for i, row in enumerate(self.rows):
            a = ease((t - 0.4 - i * 0.15) / 0.3)
            put(f, row, TEXT_X + (1 - a) * 100, y, a)
            y += 124
        a = ease((t - 1.1) / 0.4)
        put(f, self.tg1, TEXT_X, y + 70, a)
        pulse = 1 + 0.04 * abs(((t * 1.6) % 2) - 1) if t > 1.5 else 1
        tg2 = self.tg2 if pulse == 1 else self.tg2.resize(
            (int(self.tg2.width * pulse), int(self.tg2.height * pulse)), Image.LANCZOS)
        put(f, tg2, TEXT_X - (tg2.width - self.tg2.width) / 2, y + 150 - (tg2.height - self.tg2.height) / 2,
            ease((t - 1.3) / 0.4))
        put(f, self.save, TEXT_X, y + 330, ease((t - 1.8) / 0.4))
        return f


# ------------------------------------------------------------------ рендер

def render_scene(scene, path, t0, total):
    tmp_path = path[:-4] + ".part.mp4"
    n = round(scene.duration * FPS)
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", "-r", str(FPS), tmp_path], stdin=subprocess.PIPE)
    for i in range(n):
        t = i / FPS
        fr = scene.overlay(scene.frame(t), t)
        progress(fr, t0 + t, total)
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg не смог закодировать сцену")
    os.replace(tmp_path, path)


def build(posts, out_path, media_loader=load_media):
    tmp = tempfile.mkdtemp(prefix="reel_")
    try:
        base = chrome(background())
        infos = [extract(p) for p in posts]
        scenes = [Hook(base)]
        for i, (p, info) in enumerate(zip(posts, infos)):
            md = os.path.join(tmp, f"m{i}")
            os.makedirs(md, exist_ok=True)
            scenes.append(Find(base, i + 1, info, media_loader(p, md)))
        scenes.append(Cta(base, infos))
        total = sum(s.duration for s in scenes)
        parts, t0 = [], 0.0
        for i, s in enumerate(scenes):
            path = os.path.join(tmp, f"s{i}.mp4")
            bot.log(f"  сцена {i + 1}/{len(scenes)}…")
            render_scene(s, path, t0, total)
            parts.append(path)
            t0 += s.duration
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        part = out_path[:-4] + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", "-movflags", "+faststart", part], check=True)
        os.replace(part, out_path)
        return infos, total
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def prepare_voice(src, dst):
    """Обрезает тишину по краям, 48 кГц стерео."""
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
            "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", trim, "-ar", "48000", "-ac", "2", dst], check=True)
    return _dur(dst)


def build_voiced(posts, segments, out_path, cta_line, media_loader=load_media):
    """segments: [{"show": текст для субтитров, "audio": путь к озвучке}] — hook, 1, 2, 3, cta."""
    LEAD, TAIL = 0.15, 0.35
    tmp = tempfile.mkdtemp(prefix="reelv_")
    try:
        base = chrome(background())
        infos = [extract(p) for p in posts]
        voiced = []
        for i, seg in enumerate(segments):
            wav = os.path.join(tmp, f"v{i}.wav")
            speech = prepare_voice(seg["audio"], wav)
            dur = round((LEAD + speech + TAIL) * FPS) / FPS
            voiced.append((wav, speech, dur, word_timings(seg["show"], LEAD, LEAD + speech)))
        scenes = []
        hook = Hook(base)
        scenes.append(hook.with_voice(max(voiced[0][2], 2.0), Captions(voiced[0][3]), 1380))
        for i, (p, info) in enumerate(zip(posts, infos)):
            md = os.path.join(tmp, f"m{i}")
            os.makedirs(md, exist_ok=True)
            fs = Find(base, i + 1, info, media_loader(p, md))
            v = voiced[i + 1]
            scenes.append(fs.with_voice(v[2], Captions(v[3]), fs.media_y + MEDIA_H + 230))
        cta = Cta(base, infos, cta_line)
        scenes.append(cta.with_voice(max(voiced[4][2], 3.0), Captions(voiced[4][3]), 1440))
        total = sum(sc.duration for sc in scenes)
        # видео
        parts, t0 = [], 0.0
        for i, sc in enumerate(scenes):
            path = os.path.join(tmp, f"s{i}.mp4")
            bot.log(f"  сцена {i + 1}/{len(scenes)} ({sc.duration:.1f} с)…")
            render_scene(sc, path, t0, total)
            parts.append(path)
            t0 += sc.duration
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        video = os.path.join(tmp, "video.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", video], check=True)
        # звук: каждая озвучка ровно на длину своей сцены
        alist = os.path.join(tmp, "alist.txt")
        with open(alist, "w") as f:
            for i, (sc, (wav, _, _, _)) in enumerate(zip(scenes, voiced)):
                padded = os.path.join(tmp, f"a{i}.wav")
                ms = int(LEAD * 1000)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-af",
                                f"adelay={ms}|{ms},apad=whole_dur={sc.duration}", "-t", str(sc.duration),
                                "-ar", "48000", "-ac", "2", padded], check=True)
                f.write(f"file '{padded}'\n")
        audio = os.path.join(tmp, "audio.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", alist,
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", audio], check=True)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        part = out_path[:-4] + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", audio, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        "-movflags", "+faststart", part], check=True)
        os.replace(part, out_path)
        return infos, total
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def caption(infos, channel_link=None):
    lines = ["3 полезные находки с GitHub 🔥", ""]
    for i, info in enumerate(infos, 1):
        lines.append(f"{i}. {info['name']} — {info['tagline']}" if info["tagline"] else f"{i}. {info['name']}")
    lines += ["", "Какая зашла? Пиши номер в комментах 👇",
              "Все ссылки — в Telegram-канале «GitHub Finder»" + (f": {channel_link}" if channel_link else " (ссылка в профиле)"),
              "", "#github #полезныепрограммы #айти #программы #нейросети #лайфхаки #компьютер #opensource"]
    return "\n".join(lines)


def send_file(path, posts, total=None):
    """Отправляет готовый ролик (например, из Remotion) владельцу с описанием."""
    cfg = bot.load_config()
    owner = os.environ.get("TG_OWNER_ID") or (open(OWNER_FILE).read().strip() if os.path.exists(OWNER_FILE) else "")
    if not owner:
        sys.exit("Не знаю, кому слать ролик: нет state/owner_chat_id.txt")
    infos = [extract(p) for p in posts]
    with open(path, "rb") as f:
        data = f.read()
    fields = {"chat_id": owner, "width": W, "height": H, "supports_streaming": "true",
              "caption": "🎬 Ролик для TikTok / Reels готов. Описание — следующим сообщением."}
    if total:
        fields["duration"] = round(total)
    msg = bot.tg(cfg, "sendVideo", fields,
                 files={"video": (os.path.basename(path), data, "video/mp4")}, timeout=300)
    bot.tg(cfg, "sendMessage", {"chat_id": owner, "text": caption(infos),
                                "reply_parameters": json.dumps({"message_id": msg["message_id"]})})
    bot.log("Ролик отправлен владельцу:", path)


def main():
    names = None
    if "--posts" in sys.argv:
        names = sys.argv[sys.argv.index("--posts") + 1].split(",")
    posts = pick_posts(names)
    if "--send-file" in sys.argv:
        return send_file(sys.argv[sys.argv.index("--send-file") + 1], posts)
    if len(posts) < 3:
        sys.exit(f"Для ролика нужно 3 поста, есть {len(posts)} — пропускаю.")
    key = [p["_file"] for p in posts]
    if "--send" in sys.argv and not names and os.path.exists(LAST_REEL):
        with open(LAST_REEL, encoding="utf-8") as f:
            if json.load(f).get("posts") == key:
                sys.exit("Ролик из этих постов уже был — пропускаю.")
    out = os.path.join(OUT, time.strftime("reel_%Y%m%d_%H%M.mp4"))
    bot.log("Собираю ролик:", ", ".join(p["repo"] for p in posts))
    infos, total = build(posts, out)
    bot.log(f"Готово: {out} ({os.path.getsize(out) // 1024} КБ, {total:.1f} с)")
    if "--send" not in sys.argv:
        return
    cfg = bot.load_config()
    owner = os.environ.get("TG_OWNER_ID") or (open(OWNER_FILE).read().strip() if os.path.exists(OWNER_FILE) else "")
    if not owner:
        sys.exit("Не знаю, кому слать ролик: нет state/owner_chat_id.txt")
    link = None
    try:
        chan = open(bot.CHAT_FILE).read().strip()
        info = bot.tg(cfg, "getChat", {"chat_id": chan})
        if info.get("username"):
            link = f"https://t.me/{info['username']}"
    except Exception:
        pass
    with open(out, "rb") as f:
        data = f.read()
    msg = bot.tg(cfg, "sendVideo", {
        "chat_id": owner, "width": W, "height": H, "duration": round(total),
        "supports_streaming": "true",
        "caption": "🎬 Ролик для TikTok / Reels готов. Описание — следующим сообщением, звук добавь трендовый в приложении."},
        files={"video": (os.path.basename(out), data, "video/mp4")}, timeout=300)
    bot.tg(cfg, "sendMessage", {"chat_id": owner, "text": caption(infos, link),
                                "reply_parameters": json.dumps({"message_id": msg["message_id"]})})
    os.makedirs(os.path.dirname(LAST_REEL), exist_ok=True)
    with open(LAST_REEL, "w", encoding="utf-8") as f:
        json.dump({"posts": key, "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, ensure_ascii=False)
    os.remove(out)
    bot.log("Ролик отправлен владельцу.")


if __name__ == "__main__":
    main()
