#!/usr/bin/env python3
"""
Маскот канала GitHub Finder — «Файндер», маленький робот-искатель с экраном-лицом
и лупой. Рисуется кодом (Pillow), 5 поз: idle, happy, surprised, think, point.

    python mascot.py   — сохранить PNG всех поз в assets/mascot/
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

S = 2                      # суперсэмплинг
W, H = 600, 680            # итоговый размер PNG

BODY = (46, 160, 67)
BODY_DARK = (26, 110, 44)
BODY_LIGHT = (86, 211, 100)
SCREEN = (13, 17, 23)
GLOW = (126, 231, 135)
WHITE = (240, 246, 252)
LENS = (180, 220, 255)
HANDLE = (139, 94, 60)


def _s(v):
    return [int(x * S) for x in v]


def _capsule(d, p1, p2, r, fill, outline=None):
    """Рука/палка: толстая линия со скруглёнными концами."""
    (x1, y1), (x2, y2) = p1, p2
    d.line(_s((x1, y1, x2, y2)), fill=fill, width=int(r * 2 * S))
    for x, y in (p1, p2):
        d.ellipse(_s((x - r, y - r, x + r, y + r)), fill=fill)


def _magnifier(d, cx, cy, angle_deg=40, r=46):
    a = math.radians(angle_deg)
    hx, hy = cx + math.cos(a) * (r + 6), cy + math.sin(a) * (r + 6)
    ex, ey = cx + math.cos(a) * (r + 70), cy + math.sin(a) * (r + 70)
    _capsule(d, (hx, hy), (ex, ey), 11, HANDLE)
    d.ellipse(_s((cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10)), fill=(60, 66, 74))
    d.ellipse(_s((cx - r, cy - r, cx + r, cy + r)), fill=LENS + (255,))
    d.ellipse(_s((cx - r * 0.55, cy - r * 0.6, cx - r * 0.05, cy - r * 0.2)), fill=(235, 247, 255))


def draw(pose="idle"):
    im = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = 300
    # тень
    d.ellipse(_s((170, 630, 430, 668)), fill=(0, 0, 0, 90))
    # ножки
    for fx in (225, 375):
        d.rounded_rectangle(_s((fx - 42, 560, fx + 42, 640)), radius=30 * S, fill=BODY_DARK)
    # руки (позади корпуса — для idle/think/point; поднятые — поверх)
    arms_back = pose in ("idle", "surprised")
    if arms_back:
        _capsule(d, (140, 400), (92, 520), 30, BODY_DARK)
        _capsule(d, (460, 400), (508, 520), 30, BODY_DARK)
    # антенна
    d.line(_s((cx, 150, cx, 82)), fill=BODY_DARK, width=12 * S)
    d.ellipse(_s((cx - 26, 46, cx + 26, 98)), fill=GLOW)
    d.ellipse(_s((cx - 12, 56, cx + 4, 72)), fill=WHITE)
    # корпус
    d.rounded_rectangle(_s((120, 140, 480, 590)), radius=120 * S, fill=BODY_DARK)
    d.rounded_rectangle(_s((128, 140, 472, 574)), radius=114 * S, fill=BODY)
    # повязка-хатимаки (белая с красным кругом), обрезана по форме головы
    band = Image.new("RGBA", im.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rectangle(_s((110, 166, 490, 206)), fill=(245, 243, 238))
    bd.rectangle(_s((110, 200, 490, 206)), fill=(214, 208, 200))
    bd.ellipse(_s((280, 168, 320, 204)), fill=(214, 40, 40))
    bmask = Image.new("L", im.size, 0)
    ImageDraw.Draw(bmask).rounded_rectangle(_s((128, 140, 472, 574)), radius=114 * S, fill=255)
    im.paste(band, (0, 0), Image.composite(band.getchannel("A"), Image.new("L", im.size, 0), bmask))
    # концы узла развеваются справа
    d.polygon(_s((470, 178, 540, 150, 560, 168, 482, 196)), fill=(245, 243, 238))
    d.polygon(_s((470, 190, 530, 222, 516, 240, 466, 204)), fill=(232, 228, 220))
    d.ellipse(_s((456, 176, 486, 206)), fill=(235, 232, 226))
    # экран-лицо
    d.rounded_rectangle(_s((165, 215, 435, 430)), radius=60 * S, fill=SCREEN)
    # лицо по позе
    ey = 305
    if pose == "happy":
        for ex in (240, 360):
            d.arc(_s((ex - 34, ey - 26, ex + 34, ey + 30)), 200, 340, fill=GLOW, width=13 * S)
        d.chord(_s((262, 340, 338, 400)), 0, 180, fill=GLOW)
    elif pose == "surprised":
        for ex in (240, 360):
            d.ellipse(_s((ex - 36, ey - 40, ex + 36, ey + 32)), fill=GLOW)
            d.ellipse(_s((ex - 14, ey - 18, ex + 6, ey + 2)), fill=WHITE)
        d.ellipse(_s((282, 360, 318, 400)), fill=GLOW)
    elif pose == "think":
        d.ellipse(_s((206, ey - 30, 274, ey + 28)), fill=GLOW)
        d.ellipse(_s((226, ey - 14, 244, ey + 4)), fill=WHITE)
        d.rounded_rectangle(_s((326, ey - 4, 394, ey + 12)), radius=8 * S, fill=GLOW)
        d.line(_s((272, 380, 330, 372)), fill=GLOW, width=10 * S)
    else:  # idle / point
        for ex in (240, 360):
            d.ellipse(_s((ex - 30, ey - 34, ex + 30, ey + 30)), fill=GLOW)
            d.ellipse(_s((ex - 12, ey - 20, ex + 4, ey - 4)), fill=WHITE)
        d.arc(_s((262, 330, 338, 392)), 20, 160, fill=GLOW, width=11 * S)
    # щёчки
    for bx in (198, 402):
        d.ellipse(_s((bx - 16, 368, bx + 16, 384)), fill=(70, 160, 90))
    # руки поверх корпуса
    if pose == "happy":
        _capsule(d, (150, 360), (70, 210), 30, BODY_DARK)
        _capsule(d, (450, 360), (530, 210), 30, BODY_DARK)
    elif pose == "think":
        _capsule(d, (140, 420), (92, 520), 30, BODY_DARK)
        _capsule(d, (450, 470), (370, 440), 30, BODY_DARK)
    elif pose == "point":
        _capsule(d, (140, 420), (92, 520), 30, BODY_DARK)
        _capsule(d, (455, 380), (560, 300), 30, BODY_DARK)
        d.ellipse(_s((548, 280, 590, 322)), fill=BODY_DARK)
    elif pose == "idle":
        pass
    # лупа в правой руке (idle)
    if pose == "idle":
        _magnifier(d, 470, 470, angle_deg=60, r=40)
    if pose == "surprised":
        d.rounded_rectangle(_s((52, 120, 80, 220)), radius=12 * S, fill=(255, 214, 102))
        d.ellipse(_s((52, 236, 80, 264)), fill=(255, 214, 102))
    if pose == "think":
        d.ellipse(_s((490, 110, 570, 190)), fill=WHITE)
        d.ellipse(_s((462, 200, 486, 224)), fill=WHITE)
        d.ellipse(_s((446, 236, 460, 250)), fill=WHITE)
        from PIL import ImageFont
        try:
            f = ImageFont.truetype(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Inter-Black.otf"), 64 * S)
            d.text(_s((513, 113)), "?", font=f, fill=SCREEN)
        except OSError:
            pass
    return im.resize((W, H), Image.LANCZOS)


POSES = ("idle", "happy", "surprised", "think", "point")


def all_poses():
    return {p: draw(p) for p in POSES}


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mascot")
    os.makedirs(out, exist_ok=True)
    for p, im in all_poses().items():
        im.save(os.path.join(out, f"{p}.png"))
    print("сохранено в", out)
