#!/usr/bin/env python3
"""
Японский фон для роликов GitHub Finder: ночное небо, луна, Фудзи, туман,
пагода, красные тории, ветви сакуры и падающие лепестки (анимация).
Всё рисуется кодом (Pillow), без чужих картинок.
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920


def _vgrad(w, h, stops):
    """Вертикальный градиент: stops = [(доля 0..1, (r,g,b)), …]."""
    im = Image.new("RGB", (1, h))
    px = im.load()
    for y in range(h):
        f = y / (h - 1)
        for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
            if f0 <= f <= f1:
                k = (f - f0) / max(1e-6, f1 - f0)
                px[0, y] = tuple(int(a + (b - a) * k) for a, b in zip(c0, c1))
                break
    return im.resize((w, h))


def _blur_layer(size, draw_fn, radius):
    lay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(lay))
    return lay.filter(ImageFilter.GaussianBlur(radius))


def _pagoda(d, cx, base, scale, color):
    """Силуэт пятиярусной пагоды с загнутыми карнизами."""
    y = base
    tiers = 5
    for i in range(tiers):
        bw = (260 - i * 34) * scale
        th = (78 - i * 4) * scale
        # стена яруса
        d.rectangle((cx - bw * 0.32, y - th, cx + bw * 0.32, y), fill=color)
        # крыша с загнутыми краями
        ry = y - th
        d.polygon([(cx - bw * 0.62, ry + 8 * scale), (cx - bw * 0.5, ry - 4 * scale),
                   (cx - bw * 0.28, ry - 26 * scale), (cx + bw * 0.28, ry - 26 * scale),
                   (cx + bw * 0.5, ry - 4 * scale), (cx + bw * 0.62, ry + 8 * scale),
                   (cx + bw * 0.4, ry + 2 * scale), (cx - bw * 0.4, ry + 2 * scale)], fill=color)
        y = ry - 26 * scale
    # шпиль
    d.rectangle((cx - 5 * scale, y - 120 * scale, cx + 5 * scale, y), fill=color)
    for k in range(5):
        yy = y - 30 * scale - k * 18 * scale
        d.ellipse((cx - 13 * scale, yy - 5 * scale, cx + 13 * scale, yy + 5 * scale), fill=color)


def _torii(d, cx, base, scale, red, dark):
    h = 420 * scale
    pw = 26 * scale
    span = 300 * scale
    for sx in (-1, 1):
        x = cx + sx * span / 2
        d.polygon([(x - pw / 2, base), (x + pw / 2, base), (x + pw / 2 * 0.8, base - h), (x - pw / 2 * 0.8, base - h)], fill=red)
        d.rectangle((x - pw * 0.8, base - 26 * scale, x + pw * 0.8, base), fill=dark)
    # нижняя перекладина (нуки)
    d.rectangle((cx - span / 2 - 40 * scale, base - h * 0.72, cx + span / 2 + 40 * scale, base - h * 0.72 + 22 * scale), fill=red)
    # верхняя (касаги) — изогнутая
    top = base - h
    d.polygon([(cx - span / 2 - 95 * scale, top - 12 * scale), (cx - span / 2 - 70 * scale, top - 46 * scale),
               (cx, top - 36 * scale), (cx + span / 2 + 70 * scale, top - 46 * scale),
               (cx + span / 2 + 95 * scale, top - 12 * scale), (cx, top - 2 * scale)], fill=dark)
    d.rectangle((cx - span / 2 - 55 * scale, top, cx + span / 2 + 55 * scale, top + 24 * scale), fill=red)
    d.rectangle((cx - 12 * scale, top + 24 * scale, cx + 12 * scale, base - h * 0.72), fill=red)


def _branch(d, rnd, x, y, ang, length, width, depth, blossoms):
    if depth == 0 or length < 18:
        return
    x2 = x + math.cos(ang) * length
    y2 = y + math.sin(ang) * length
    d.line((x, y, x2, y2), fill=(48, 28, 36), width=max(2, int(width)))
    if depth <= 3:
        for _ in range(int(6 * (4 - depth))):
            t = rnd.random()
            bx = x + (x2 - x) * t + rnd.uniform(-26, 26)
            by = y + (y2 - y) * t + rnd.uniform(-26, 26)
            blossoms.append((bx, by, rnd.uniform(8, 17)))
    for da in (-0.45, 0.35):
        _branch(d, rnd, x2, y2, ang + da + rnd.uniform(-0.2, 0.2), length * rnd.uniform(0.62, 0.78),
                width * 0.68, depth - 1, blossoms)


def _sakura_corner(size, root, ang, seed):
    rnd = random.Random(seed)
    lay = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    blossoms = []
    _branch(d, rnd, root[0], root[1], ang, 170, 20, 4, blossoms)
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for bx, by, r in blossoms:
        gd.ellipse((bx - r * 1.8, by - r * 1.8, bx + r * 1.8, by + r * 1.8), fill=(255, 150, 190, 60))
    lay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    for bx, by, r in blossoms:
        c = rnd.choice([(255, 183, 206), (255, 201, 219), (246, 160, 192), (255, 222, 233)])
        for k in range(5):
            a = k * 2 * math.pi / 5 + rnd.random()
            px, py = bx + math.cos(a) * r * 0.55, by + math.sin(a) * r * 0.55
            d.ellipse((px - r * 0.55, py - r * 0.55, px + r * 0.55, py + r * 0.55), fill=c + (255,))
        d.ellipse((bx - r * 0.25, by - r * 0.25, bx + r * 0.25, by + r * 0.25), fill=(214, 90, 130, 255))
    return lay


def background():
    sky = _vgrad(W, H, [(0.0, (10, 12, 38)), (0.35, (34, 22, 66)), (0.58, (98, 42, 88)),
                        (0.68, (176, 82, 104)), (0.74, (60, 30, 62)), (1.0, (12, 10, 22))]).convert("RGBA")
    # звёзды
    rnd = random.Random(7)
    st = ImageDraw.Draw(sky)
    for _ in range(160):
        x, y = rnd.randrange(W), rnd.randrange(0, 900)
        r = rnd.choice((1, 1, 1, 2))
        st.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, rnd.randrange(80, 220)))
    # луна со свечением
    mx, my, mr = 760, 470, 165
    sky.alpha_composite(_blur_layer((W, H), lambda d: d.ellipse((mx - mr * 1.9, my - mr * 1.9, mx + mr * 1.9, my + mr * 1.9), fill=(255, 214, 170, 70)), 70))
    md = ImageDraw.Draw(sky)
    md.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(255, 236, 205, 255))
    sky.alpha_composite(_blur_layer((W, H), lambda d: [d.ellipse((mx + dx - r, my + dy - r, mx + dx + r, my + dy + r), fill=(214, 186, 156, a))
                                                       for dx, dy, r, a in ((-50, -30, 34, 90), (40, 50, 22, 80), (-10, 70, 16, 70), (60, -60, 18, 70))], 4))
    # Фудзи
    fuji = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fuji)
    base_y, peak = 1330, 860
    fd.polygon([(-260, base_y), (380, peak + 18), (470, peak), (610, peak), (700, peak + 18), (1340, base_y)], fill=(44, 32, 74, 255))
    fd.polygon([(380, peak + 18), (470, peak), (610, peak), (700, peak + 18), (760, 990), (705, 965), (660, 1005),
                (600, 960), (545, 1010), (490, 962), (430, 1000), (380, 960), (318, 992)], fill=(236, 230, 246, 255))
    sky.alpha_composite(fuji)
    # туман
    sky.alpha_composite(_blur_layer((W, H), lambda d: [d.rectangle((0, y, W, y + 60), fill=(255, 190, 210, 40)) for y in (1150, 1230, 1300)], 40))
    # дальние холмы
    hills = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hills)
    pts = [(0, H)]
    for x in range(0, W + 40, 40):
        pts.append((x, 1330 + 40 * math.sin(x / 140) + 20 * math.sin(x / 47)))
    pts.append((W, H))
    hd.polygon(pts, fill=(28, 20, 46, 255))
    sky.alpha_composite(hills)
    # пагода слева и тории справа
    sil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sil)
    _pagoda(sd, 170, 1420, 0.95, (16, 12, 30, 255))
    _torii(sd, 880, 1560, 0.62, (178, 40, 48, 255), (70, 16, 26, 255))
    sky.alpha_composite(sil)
    # передний план
    ground = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(ground)
    pts = [(0, H)]
    for x in range(0, W + 30, 30):
        pts.append((x, 1520 + 25 * math.sin(x / 90 + 1)))
    pts.append((W, H))
    gd.polygon(pts, fill=(10, 8, 18, 255))
    sky.alpha_composite(ground)
    # сакура в верхних углах
    sky.alpha_composite(_sakura_corner((W, H), (-20, 30), 0.06, 3))
    sky.alpha_composite(_sakura_corner((W, H), (W + 20, 250), math.pi - 0.02, 11))
    # затемнение центра, чтобы читались окна и текст
    dark = Image.new("RGBA", (W, H), (8, 6, 18, 0))
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle((90, 230, W - 90, 1420), radius=220, fill=140)
    dark.putalpha(m.filter(ImageFilter.GaussianBlur(120)))
    sky.alpha_composite(dark)
    return sky


class Petals:
    """Падающие лепестки сакуры: позиция зависит от глобального времени ролика."""

    def __init__(self, n=34, seed=5):
        rnd = random.Random(seed)
        self.p = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(60, 140), rnd.uniform(-60, 20),
                   rnd.uniform(9, 18), rnd.uniform(0, 6.28), rnd.uniform(1.5, 3.5),
                   rnd.choice([(255, 183, 206), (255, 201, 219), (246, 160, 192)])) for _ in range(n)]

    def draw(self, f, t):
        lay = Image.new("RGBA", f.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        for x0, y0, vy, vx, r, ph, sw, c in self.p:
            y = (y0 + vy * t) % (H + 60) - 30
            x = (x0 + vx * t + 40 * math.sin(t * sw * 0.5 + ph)) % (W + 60) - 30
            k = abs(math.cos(t * sw + ph))          # «переворот» лепестка
            rx, ry = r, max(3, r * 0.55 * (0.4 + 0.6 * k))
            d.ellipse((x - rx, y - ry, x + rx, y + ry), fill=c + (215,))
        f.alpha_composite(lay)
