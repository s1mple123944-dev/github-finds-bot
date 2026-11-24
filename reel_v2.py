#!/usr/bin/env python3
"""
Ролик v2 «3 находки с GitHub» — в стиле вирусных роликов про AI-инструменты:
ведущий-маскот, смена кадра каждые 2–3 секунды, окна программ в стиле Mac,
телефон с Telegram-каналом в финале, субтитры с цветными ключевыми словами
и звуки на переходах. Озвучка — голос владельца (5 кусков: hook, 1, 2, 3, cta).

    python reel_v2.py voice/script_xxx_v2.json <папка с gf2_*.wav> out.mp4
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

import bot
import mascot
import reel
from reel import (ACCENT, BG, BORDER, CARD, FG, FPS, H, MUTED, W, ease, fade, font,
                  pill, put, text_layer, wrap)

CAPTION_Y = 1330
YELLOW = (255, 214, 102)
LEAD, TAIL = 0.15, 0.35


def spring(t, k=10.0):
    """Пружинка для «выскакивания»: 0→1 с небольшим перелётом."""
    if t <= 0:
        return 0.0
    if t >= 1.2:
        return 1.0
    return 1 - math.exp(-k * t) * math.cos(2.2 * math.pi * t)


def scaled(layer, s):
    if abs(s - 1) < 0.005:
        return layer
    return layer.resize((max(1, int(layer.width * s)), max(1, int(layer.height * s))), Image.BILINEAR)


def put_c(f, layer, cx, cy, a=1.0, s=1.0):
    """Положить слой по центру (cx, cy) с прозрачностью и масштабом."""
    if a <= 0 or s <= 0.02:
        return
    lay = scaled(layer, s)
    put(f, lay, cx - lay.width / 2, cy - lay.height / 2, a)


# ------------------------------------------------------------------ субтитры v2

def parse_marked(text):
    """«*слово*» или «*два слова*» → (слова, флаги выделения). Тире прилипает к предыдущему слову."""
    words, marks, inside = [], [], False
    for raw in text.split():
        core = raw.rstrip(".,!?:;»)")
        starts, ends = raw.startswith("*"), core.endswith("*")
        mark = inside or starts
        if starts and not ends:
            inside = True
        if ends:
            inside = False
        w = raw.replace("*", "")
        if w in ("—", "–", "-") and words:
            words[-1] += " " + w
            continue
        words.append(w)
        marks.append(mark)
    return words, marks


class CaptionsV2:
    """2–4 слова, капслок, белые с обводкой, ключевые слова — зелёные. Как в примерах."""

    def __init__(self, show_text, start, end, size=70):
        words, marks = parse_marked(show_text)
        timings = reel.word_timings(" ".join(words), start, end)
        self.items = [(a, b, w.upper(), m) for (a, b, w), m in zip(timings, marks)]
        self.fnt = font("Black", size)
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.chunks, cur = [], []
        for it in self.items:
            test = " ".join(x[2] for x in cur + [it])
            if cur and (d.textlength(test, font=self.fnt) > 860 or len(cur) >= 3
                        or cur[-1][2][-1:] in ".!?,:"):
                self.chunks.append(cur)
                cur = []
            cur.append(it)
        if cur:
            self.chunks.append(cur)
        self.layers = [self._layer(c) for c in self.chunks]
        self.starts = [c[0][0] for c in self.chunks]

    def _layer(self, chunk):
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        space = d.textlength(" ", font=self.fnt)
        widths = [d.textlength(w, font=self.fnt) for _, _, w, _ in chunk]
        asc, desc = self.fnt.getmetrics()
        im = Image.new("RGBA", (int(sum(widths) + space * (len(chunk) - 1)) + 40, asc + desc + 40), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        x = 20
        for (_, _, w, m), ww in zip(chunk, widths):
            dd.text((x, 16), w, font=self.fnt, fill=ACCENT if m else FG, stroke_width=7, stroke_fill=(0, 0, 0))
            x += ww + space
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sh.putalpha(im.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.6)))
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        out.alpha_composite(sh, (0, 6))
        out.alpha_composite(im)
        return out

    def draw(self, f, t):
        idx = None
        for i, s in enumerate(self.starts):
            end = self.starts[i + 1] if i + 1 < len(self.starts) else self.chunks[i][-1][1] + 0.4
            if s <= t < end:
                idx = i
        if idx is None:
            return
        k = (t - self.starts[idx]) / 0.12
        s = 1.12 - 0.12 * ease(k)
        put_c(f, self.layers[idx], W / 2, CAPTION_Y, 1.0, s)


# ------------------------------------------------------------------ элементы

def mac_window(title, w, h):
    """Рамка окна в стиле macOS (заголовок с тремя точками) — без содержимого."""
    bar = 58
    frame = Image.new("RGBA", (w, h + bar), (0, 0, 0, 0))
    d = ImageDraw.Draw(frame)
    d.rounded_rectangle((0, 0, w - 1, h + bar - 1), radius=28, fill=(22, 27, 34, 255), outline=BORDER + (255,), width=3)
    for i, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((26 + i * 34, 20, 46 + i * 34, 40), fill=c)
    tf = font("Bold", 30)
    tw = d.textlength(title, font=tf)
    d.text(((w - tw) / 2, 12), title, font=tf, fill=FG)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, -30, w - 1, h - 1), radius=26, fill=255)
    return frame, mask, bar


def shadow_for(w, h, r=30, blur=30, alpha=160):
    sh = Image.new("RGBA", (w + 2 * blur * 2, h + 2 * blur * 2), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((blur * 2, blur * 2 + 20, blur * 2 + w, blur * 2 + h + 20), radius=r, fill=(0, 0, 0, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur))


def glow_pill(text, size=46):
    p = pill(text, font("Black", size), BG, ACCENT, pad=(34, 14))
    g = Image.new("RGBA", (p.width + 80, p.height + 80), (0, 0, 0, 0))
    gl = Image.new("RGBA", g.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).rounded_rectangle((40, 40, 40 + p.width, 40 + p.height), radius=p.height // 2, fill=ACCENT + (170,))
    g.alpha_composite(gl.filter(ImageFilter.GaussianBlur(18)))
    g.alpha_composite(p, (40, 40))
    return g


def feature_card(text, w=880):
    h = 132
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=32, fill=(22, 27, 34, 245), outline=BORDER + (255,), width=3)
    d.ellipse((30, 33, 96, 99), fill=ACCENT)
    d.line((48, 68, 60, 80, 80, 52), fill=BG, width=9, joint="curve")
    tf = reel.fit_font(text, "Bold", 46, 32, w - 160)
    asc, desc = tf.getmetrics()
    d.text((124, (h - asc - desc) / 2), text, font=tf, fill=FG)
    return im


class Window:
    """Окно Mac с медиа внутри (картинка с проездом, gif или видео)."""

    def __init__(self, title, media, w=940, h=600):
        self.w, self.h = w, h
        self.frame, self.mask, self.bar = mac_window(title, w, h)
        self.media = media
        self.shadow = shadow_for(w, h + self.bar)

    def render(self, t, zoom=1.0):
        win = self.frame.copy()
        if self.media is not None:
            img = self.media.at(t)
            if img.size != (self.w, self.h):
                img = reel.cover(img, self.w, self.h)
                img = img.crop(((img.width - self.w) // 2, (img.height - self.h) // 2,
                                (img.width - self.w) // 2 + self.w, (img.height - self.h) // 2 + self.h))
            if zoom != 1.0:
                zw, zh = int(self.w / zoom), int(self.h / zoom)
                img = img.crop(((self.w - zw) // 2, (self.h - zh) // 2, (self.w - zw) // 2 + zw, (self.h - zh) // 2 + zh)).resize((self.w, self.h), Image.BILINEAR)
            img = img.convert("RGBA")
            img.putalpha(self.mask)
            win.alpha_composite(img, (0, self.bar))
        return win


def telegram_phone(infos, thumbs, avatar):
    """Телефон с открытым каналом GitHub Finder (макет — для финала)."""
    pw, ph = 520, 1000
    phone = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(phone)
    d.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=78, fill=(10, 10, 12, 255))
    sx, sy, sw, sh = 18, 18, pw - 36, ph - 36
    scr = Image.new("RGBA", (sw, sh), (14, 22, 33, 255))
    s = ImageDraw.Draw(scr)
    s.rectangle((0, 0, sw, 150), fill=(23, 33, 43))
    s.rounded_rectangle((sw / 2 - 70, 14, sw / 2 + 70, 44), radius=15, fill=(0, 0, 0))
    av = avatar.resize((84, 84), Image.LANCZOS)
    m = Image.new("L", (84, 84), 0)
    ImageDraw.Draw(m).ellipse((0, 0, 83, 83), fill=255)
    bgc = Image.new("RGBA", (84, 84), (20, 60, 35, 255))
    bgc.alpha_composite(av)
    bgc.putalpha(m)
    scr.alpha_composite(bgc, (26, 56))
    s.text((128, 62), "GitHub Finder", font=font("Bold", 36), fill=FG)
    s.text((128, 106), "канал · находки с GitHub", font=font("Medium", 24), fill=MUTED)
    y = 178
    for i, (info, th) in enumerate(zip(infos, thumbs)):
        bw, bh = sw - 48, 220
        s.rounded_rectangle((24, y, 24 + bw, y + bh), radius=24, fill=(24, 37, 51))
        if th is not None:
            t = reel.cover(th, 150, 150)
            t = t.crop(((t.width - 150) // 2, (t.height - 150) // 2, (t.width - 150) // 2 + 150, (t.height - 150) // 2 + 150)).convert("RGBA")
            tm = Image.new("L", (150, 150), 0)
            ImageDraw.Draw(tm).rounded_rectangle((0, 0, 149, 149), radius=18, fill=255)
            t.putalpha(tm)
            scr.alpha_composite(t, (42, y + 35))
        nf = font("Bold", 32)
        s.text((210, y + 40), wrap(s, info["name"], nf, bw - 200, 1)[0], font=nf, fill=FG)
        tf = font("Medium", 24)
        for j, line in enumerate(wrap(s, info["tagline"], tf, bw - 200, 3)):
            s.text((210, y + 86 + j * 32), line, font=tf, fill=(170, 190, 205))
        y += bh + 22
    s.rounded_rectangle((24, sh - 104, sw - 24, sh - 34), radius=35, fill=(51, 144, 236))
    jf = font("Bold", 32)
    s.text(((sw - s.textlength("ПОДПИСАТЬСЯ", font=jf)) / 2, sh - 88), "ПОДПИСАТЬСЯ", font=jf, fill=(255, 255, 255))
    sm = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(sm).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=62, fill=255)
    scr.putalpha(sm)
    phone.alpha_composite(scr, (sx, sy))
    return phone


# ------------------------------------------------------------------ сцены

class SceneV2(reel.Scene):
    sfx = ()   # [(время от начала сцены, "whoosh"|"pop")]

    def overlay(self, f, t):
        if self.captions:
            self.captions.draw(f, t)
        return f


class HookV2(SceneV2):
    def __init__(self, base, dur, mas, windows):
        self.base, self.duration, self.mas, self.windows = base, dur, mas, windows
        self.split = max(1.4, dur * 0.42)
        self.t1 = text_layer(["3 НАХОДКИ"], font("Black", 128), ACCENT)
        self.t2 = text_layer(["С GITHUB"], font("Black", 128), FG)
        self.t3 = pill("о которых ты не знал", font("Bold", 44), FG, (33, 38, 45), pad=(30, 14), border=BORDER)
        self.free = glow_pill("БЕСПЛАТНО", 40)
        self.sfx = ((0.0, "pop"), (self.split, "whoosh"), (self.split + 0.25, "pop"), (self.split + 0.4, "pop"), (self.split + 0.55, "pop"))

    def frame(self, t):
        f = self.base.copy()
        if t < self.split:
            p = spring(t / 0.5)
            put_c(f, self.t1, W / 2, 330, min(1, p * 1.5), 0.6 + 0.4 * p)
            put_c(f, self.t2, W / 2, 470, ease((t - 0.15) / 0.3), 1)
            bob = math.sin(t * 6) * 8
            put_c(f, self.mas["surprised"], W / 2, 900 + bob, 1, 0.95 * spring((t - 0.1) / 0.5))
        else:
            tt = t - self.split
            put_c(f, self.free, W / 2, 250, 1, spring(tt / 0.4))
            for i, (win, ang, dx) in enumerate(zip(self.windows, (-9, 0, 9), (-250, 0, 250))):
                k = spring((tt - 0.25 - i * 0.15) / 0.5)
                if k <= 0:
                    continue
                lay = win.render(tt, 1.0).rotate(ang, resample=Image.BICUBIC, expand=True)
                lay = scaled(lay, 0.5)
                put_c(f, scaled(lay, 1.15), W / 2 + dx * min(k, 1.05), 640 + (1 - min(k, 1)) * 500 + abs(dx) * 0.15, 1)
            put_c(f, self.t3, W / 2, 1000, ease((tt - 0.6) / 0.3), 1)
            put_c(f, self.mas["point"], 880, 1150 + math.sin(t * 5) * 6, 1, 0.44 * spring((tt - 0.3) / 0.5))
        return f


class FindV2(SceneV2):
    def __init__(self, base, n, info, media, points, dur, mas):
        self.base, self.duration, self.mas = base, dur, mas
        self.b = [0, dur * 0.2, dur * 0.56, dur * 0.84, dur]
        self.badge = glow_pill(f"НАХОДКА #{n}", 50)
        nf = reel.fit_font(info["name"], "Black", 150, 80, 900)
        self.name = text_layer([info["name"]], nf, FG)
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        tf = font("SemiBold", 44)
        self.tag = text_layer(wrap(d, info["tagline"], tf, 880, 2), tf, MUTED)
        self.win = Window(info["name"], media)
        self.small_badge = pill(f"#{n}  {info['name']}", font("Bold", 38), FG, (33, 38, 45), pad=(26, 12), border=BORDER)
        self.cards = [feature_card(p) for p in points[:3]]
        plats = [p.strip() for p in (info.get("platforms") or "").split("·") if p.strip()]
        self.plats = [pill(p, font("Bold", 40), FG, (33, 38, 45), pad=(28, 14), border=BORDER) for p in plats[:3]]
        self.stars_txt = info.get("stars") or ""
        self.star_lbl = text_layer(["звёзд на GitHub"], font("SemiBold", 42), MUTED)
        sfx = [(0.0, "whoosh"), (0.15, "pop")]
        for bi in (1, 2, 3):
            sfx.append((self.b[bi], "whoosh"))
        for i in range(len(self.cards)):
            sfx.append((self.b[2] + 0.02 + i * self._stagger(), "pop"))
        self.sfx = sfx

    def _stagger(self):
        return max(0.35, (self.b[3] - self.b[2] - 0.6) / max(1, len(self.cards)))

    def frame(self, t):
        f = self.base.copy()
        b = self.b
        if t < b[1]:                                   # 1: бейдж + имя + маскот
            put_c(f, self.badge, W / 2, 290, 1, spring(t / 0.45))
            k = spring((t - 0.12) / 0.5)
            put_c(f, self.name, W / 2, 510, min(1, k * 1.4), 0.7 + 0.3 * k)
            put_c(f, self.tag, W / 2, 665, ease((t - 0.35) / 0.3), 1)
            put_c(f, self.mas["happy"], W / 2, 1010 + math.sin(t * 7) * 10, 1, 0.66 * spring((t - 0.25) / 0.5))
        elif t < b[2]:                                 # 2: окно с продуктом
            tt = t - b[1]
            k = spring(tt / 0.5)
            put_c(f, self.small_badge, W / 2, 210, ease(tt / 0.3), 1)
            zoom = 1.0 + 0.08 * (tt / max(0.1, b[2] - b[1]))
            win = self.win.render(t, zoom)
            put_c(f, self.win.shadow, W / 2, 740 + (1 - min(k, 1)) * 600 + 20, min(1, k))
            put_c(f, win, W / 2, 740 + (1 - min(k, 1)) * 600, 1, 0.92 + 0.1 * min(k, 1))
            put_c(f, self.mas["point"], 150, 1150 + math.sin(t * 5) * 6, 1, 0.36 * spring((tt - 0.4) / 0.5))
        elif t < b[3]:                                 # 3: фишки карточками
            tt = t - b[2]
            put_c(f, self.small_badge, W / 2, 210, 1, 1)
            for i, c in enumerate(self.cards):
                k = spring((tt - 0.02 - i * self._stagger()) / 0.4)
                if k > 0:
                    put_c(f, c, W / 2 + (1 - min(k, 1)) * 400, 440 + i * 180, min(1, k * 1.5), 1.04)
            put_c(f, self.mas["happy"], W / 2, 1060 + math.sin(t * 7) * 8, 1, 0.42 * spring((tt + 0.15) / 0.5))
        else:                                          # 4: платформы + звёзды
            tt = t - b[3]
            if self.stars_txt:
                st = text_layer(["★ " + self.stars_txt], font("Black", 150), YELLOW)
                put_c(f, st, W / 2, 420, 1, spring(tt / 0.45))
                put_c(f, self.star_lbl, W / 2, 545, ease((tt - 0.2) / 0.3), 1)
            x0 = W / 2 - (sum(p.width for p in self.plats) + 24 * (len(self.plats) - 1)) / 2
            for i, p in enumerate(self.plats):
                k = spring((tt - 0.25 - i * 0.12) / 0.4)
                put(f, scaled(p, max(0.01, k)), x0 + p.width * (1 - k) / 2, 660 + p.height * (1 - k) / 2, min(1, k * 1.5))
                x0 += p.width + 24
            put_c(f, self.mas["surprised" if not self.stars_txt else "happy"], W / 2, 1010 + math.sin(t * 7) * 8, 1, 0.56 * spring((tt - 0.1) / 0.5))
        return f


class CtaV2(SceneV2):
    def __init__(self, base, dur, infos, phone, mas):
        self.base, self.duration, self.mas, self.phone = base, dur, mas, phone
        self.split = max(1.8, dur * 0.4)
        self.q = text_layer(["КАКАЯ ЗАШЛА?"], font("Black", 118), FG)
        self.btns = []
        for i, info in enumerate(infos):
            im = Image.new("RGBA", (280, 300), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.ellipse((50, 0, 230, 180), fill=ACCENT)
            nf = font("Black", 110)
            d.text((140 - d.textlength(str(i + 1), font=nf) / 2, 18), str(i + 1), font=nf, fill=BG)
            lf = font("Bold", 38)
            name = wrap(d, info["name"], lf, 270, 1)[0]
            d.text((140 - d.textlength(name, font=lf) / 2, 210), name, font=lf, fill=FG)
            self.btns.append(im)
        self.handle = glow_pill("GITHUB FINDER", 54)
        self.prof = pill("ссылка в профиле", font("Bold", 40), FG, (33, 38, 45), pad=(28, 12), border=BORDER)
        self.sfx = ((0.0, "whoosh"), (0.3, "pop"), (0.45, "pop"), (0.6, "pop"), (self.split, "whoosh"), (self.split + 0.5, "pop"))

    def frame(self, t):
        f = self.base.copy()
        if t < self.split:
            put_c(f, self.q, W / 2, 300, 1, spring(t / 0.45))
            for i, bt in enumerate(self.btns):
                k = spring((t - 0.3 - i * 0.15) / 0.45)
                pulse = 1 + 0.06 * max(0, math.sin((t - 1.0 - i * 0.35) * 6)) if t > 1.0 else 1
                put_c(f, bt, W / 2 + (i - 1) * 310, 560, min(1, k * 1.5), k * pulse)
            put_c(f, self.mas["think"], W / 2, 980 + math.sin(t * 5) * 8, 1, 0.55 * spring((t - 0.2) / 0.5))
        else:
            tt = t - self.split
            k = spring(tt / 0.6)
            put_c(f, self.phone, 640, 800 + (1 - min(k, 1)) * 900, 1, 0.86)
            put_c(f, self.mas["point"], 175, 1060 + math.sin(t * 5) * 8, 1, 0.46 * spring((tt - 0.3) / 0.5))
            put_c(f, self.handle, W / 2, 200, 1, spring((tt - 0.5) / 0.45))
            put_c(f, self.prof, W / 2, 300, ease((tt - 0.8) / 0.3), 1)
        return f


# ------------------------------------------------------------------ звук

def make_sfx(tmp):
    whoosh = os.path.join(tmp, "whoosh.wav")
    pop = os.path.join(tmp, "pop.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=0.38:a=0.6",
                    "-af", "highpass=f=500,lowpass=f=4500,afade=t=in:d=0.16,afade=t=out:st=0.16:d=0.22,"
                           "aecho=0.6:0.4:30:0.3,volume=0.9",
                    "-ar", "48000", "-ac", "2", whoosh], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=620:d=0.09",
                    "-af", "asetrate=48000*1.6,aresample=48000,afade=t=out:st=0.005:d=0.08,volume=0.8",
                    "-ac", "2", pop], check=True)
    return {"whoosh": whoosh, "pop": pop}


# ------------------------------------------------------------------ сборка

def background_v2():
    bg = reel.background()
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(dots)
    for y in range(40, H, 48):
        for x in range(24, W, 48):
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(139, 148, 158, 26))
    vign = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vign).ellipse((-400, 250, W + 400, H + 600), fill=255)
    vign = vign.filter(ImageFilter.GaussianBlur(160))
    dots.putalpha(Image.composite(dots.getchannel("A"), Image.new("L", (W, H), 0), vign))
    bg.alpha_composite(dots)
    return bg


def build(posts, script, voice_dir, out_path, media_loader=reel.load_media):
    tmp = tempfile.mkdtemp(prefix="reel2_")
    try:
        base = reel.chrome(background_v2())
        mas = mascot.all_poses()
        segs = script["segments"]
        infos = [reel.extract(p) for p in posts]
        names = {"hook": "gf2_hook", "1": "gf2_1", "2": "gf2_2", "3": "gf2_3", "cta": "gf2_cta"}
        voiced = []
        for seg in segs:
            wav = os.path.join(tmp, f"v_{seg['id']}.wav")
            speech = reel.prepare_voice(os.path.join(voice_dir, names[seg["id"]] + ".wav"), wav)
            dur = round((LEAD + speech + TAIL) * FPS) / FPS
            voiced.append((wav, speech, dur))
        medias = []
        for i, p in enumerate(posts):
            md = os.path.join(tmp, f"m{i}")
            os.makedirs(md, exist_ok=True)
            medias.append(media_loader(p, md))
        thumbs = [m.at(0.5) if m else None for m in medias]
        scenes = [HookV2(base, voiced[0][2], mas, [Window(info["name"], m, 940, 600) for info, m in zip(infos, medias)])]
        for i in range(3):
            seg = segs[i + 1]
            scenes.append(FindV2(base, i + 1, infos[i], medias[i], seg.get("points") or infos[i]["points"],
                                 voiced[i + 1][2], mas))
        scenes.append(CtaV2(base, voiced[4][2], infos, telegram_phone(infos, thumbs, mas["happy"]), mas))
        for sc, seg, v in zip(scenes, segs, voiced):
            sc.captions = CaptionsV2(seg["show"], LEAD, LEAD + v[1])
        total = sum(s.duration for s in scenes)
        # видео
        parts, t0, sfx_events = [], 0.0, []
        for i, sc in enumerate(scenes):
            path = os.path.join(tmp, f"s{i}.mp4")
            bot.log(f"  сцена {i + 1}/{len(scenes)} ({sc.duration:.1f} с)…")
            reel.render_scene(sc, path, t0, total)
            parts.append(path)
            sfx_events += [(t0 + at, kind) for at, kind in sc.sfx if at < sc.duration]
            t0 += sc.duration
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        video = os.path.join(tmp, "video.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", video], check=True)
        # голос
        alist = os.path.join(tmp, "alist.txt")
        with open(alist, "w") as f:
            for i, (sc, (wav, _, _)) in enumerate(zip(scenes, voiced)):
                padded = os.path.join(tmp, f"a{i}.wav")
                ms = int(LEAD * 1000)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-af",
                                f"adelay={ms}|{ms},apad=whole_dur={sc.duration}", "-t", str(sc.duration),
                                "-ar", "48000", "-ac", "2", padded], check=True)
                f.write(f"file '{padded}'\n")
        voice = os.path.join(tmp, "voice.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", alist, voice], check=True)
        # звуки переходов под голос
        sfx = make_sfx(tmp)
        args, filt, labels = ["ffmpeg", "-v", "error", "-y", "-i", voice], [], []
        for j, (at, kind) in enumerate(sfx_events):
            args += ["-i", sfx[kind]]
            ms = int(at * 1000)
            vol = 0.22 if kind == "whoosh" else 0.16
            filt.append(f"[{j + 1}]adelay={ms}|{ms},volume={vol}[s{j}]")
            labels.append(f"[s{j}]")
        filt.append(f"[0]{''.join(labels)}amix=inputs={len(labels) + 1}:normalize=0:duration=first,"
                    f"loudnorm=I=-14:TP=-1.5:LRA=11[out]")
        audio = os.path.join(tmp, "audio.wav")
        subprocess.run(args + ["-filter_complex", ";".join(filt), "-map", "[out]", "-ar", "48000", audio], check=True)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        part = out_path[:-4] + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", audio, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", part], check=True)
        os.replace(part, out_path)
        return infos, total
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    script_path, voice_dir, out = sys.argv[1:4]
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    posts = []
    for name in sc["posts"]:
        with open(os.path.join(reel.BASE, "sent", name), encoding="utf-8") as f:
            posts.append(json.load(f))
    build(posts, sc, voice_dir, out)
