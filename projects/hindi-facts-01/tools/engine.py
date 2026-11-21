"""
Hindi Facts Short — render engine (Skia + HarfBuzz).

Bang Motion's architecture translated to a headless rasteriser. Its rules that
this file obeys:
  * one continuous world, not slides — a ticking clock HUD runs through every
    shot, and the road from the hook physically returns in the payoff;
  * a camera rig (camera_from/applied in apply_camera) that is always moving,
    one move per VO beat, never a static slide;
  * text lives inside the scene: captions sit in the mobile safe box, headlines
    are part of the composition, and they share the camera, grain and grade;
  * every shot changes state on the VO, not on a timer.

Run:  python tools/engine.py stills 1.2 3 7.5
      python tools/engine.py video [start_frame] [end_frame]
"""

import os
import sys
import math
import json
import random
import numpy as np
import skia

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textkit as T  # noqa: E402

W, H = 1080, 1920
FPS = 60
DURATION = 47.8
SAFE_L, SAFE_R = 84, 996

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# ---------------------------------------------------------------- palette
INKC = 0xFFFFFFFF
DIM = 0xFF9AA3AE
SOFT = 0xFFCBD3DD
RED = 0xFFFF2D2D
AMBER = 0xFFFFC53D
MINT = 0xFF35E0BE
BLUE = 0xFF4D8CFF

SCENES = [
    dict(name="hook", t0=0.0, t1=5.0, vo=0.22, tag="भारत · 2022"),
    dict(name="moon", t0=5.0, t1=10.0, vo=5.10, tag="चंद्रयान-3"),
    dict(name="mars", t0=10.0, t1=15.0, vo=10.10, tag="मंगलयान · 2014"),
    dict(name="cost", t0=15.0, t1=20.5, vo=15.10, tag="₹450 करोड़"),
    dict(name="rail", t0=20.5, t1=26.5, vo=20.58, tag="भारतीय रेल"),
    dict(name="post", t0=26.5, t1=32.5, vo=26.58, tag="डाक विभाग"),
    dict(name="turn", t0=32.5, t1=39.0, vo=32.58, tag="सवाल"),
    dict(name="cost2", t0=39.0, t1=43.8, vo=39.08, tag="हिसाब"),
    dict(name="loop", t0=43.8, t1=47.8, vo=43.86, tag="लूप"),
]
TRANSITION = ["whip", "cut", "push", "whip", "cut", "push", "glitch", "cut"]

TIMING = None


def timing():
    global TIMING
    if TIMING is None:
        p = os.path.join(BASE, "build", "timing.json")
        TIMING = json.load(open(p)) if os.path.exists(p) else {}
    return TIMING


def voice(scene_i):
    """Words of scene i (1-based) as [(word, abs_start, abs_end)]."""
    t = timing().get(str(scene_i))
    if not t:
        return []
    vo = SCENES[scene_i - 1]["vo"]
    return [(w, vo + s, vo + e) for w, s, e in t["words"]]


def word_at(scene_i, needle, default):
    """Absolute time of the first word containing `needle` (for headline beats)."""
    for w, s, e in voice(scene_i):
        if needle in w:
            return s
    return SCENES[scene_i - 1]["t0"] + default


def scene_at(t):
    for i, s in enumerate(SCENES):
        if s["t0"] <= t < s["t1"]:
            return i, t - s["t0"]
    return len(SCENES) - 1, t - SCENES[-1]["t0"]


# ---------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0):
    return a if x < a else (b if x > b else x)


def ease_out(p):
    return 1 - (1 - clamp(p)) ** 3


def ease_in(p):
    return clamp(p) ** 3


def ease_io(p):
    return 0.5 - 0.5 * math.cos(math.pi * clamp(p))


def back_out(p, s=1.7):
    p = clamp(p) - 1
    return p * p * ((s + 1) * p + s) + 1


def ramp(t, a, b):
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def lerp(a, b, p):
    return a + (b - a) * p


# ---------------------------------------------------------------- surfaces
class Pool:
    def __init__(self):
        self.free = []

    def get(self, w=W, h=H):
        if self.free:
            s = self.free.pop()
            if s.width() == w and s.height() == h:
                return s
        return skia.Surface(w, h)

    def put(self, s):
        if len(self.free) < 6:
            self.free.append(s)


POOL = Pool()
RNG = np.random.default_rng(7)
GRAIN = None
VIGNETTE = None
SCAN = None


def _make_grain(frames=6):
    imgs = []
    for i in range(frames):
        n = RNG.normal(0.5, 0.17, (H // 2, W // 2)).clip(0, 1)
        rgb = np.repeat((n * 255).astype(np.uint8)[..., None], 3, axis=2)
        a = np.full((H // 2, W // 2, 1), 255, np.uint8)
        arr = np.concatenate([rgb, a], axis=2)
        imgs.append(skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType))
    return imgs


def _make_vignette():
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    sh = skia.GradientShader.MakeRadial(
        skia.Point(W * 0.5, H * 0.44), W * 1.05,
        [0x00000000, 0x78000000, 0xEB000000], [0.0, 0.60, 1.0])
    p = skia.Paint(AntiAlias=True)
    p.setShader(sh)
    c.drawRect(skia.Rect.MakeWH(W, H), p)
    return surf.makeImageSnapshot()


def _make_scan():
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    p = skia.Paint(Color=0x2A000000)
    for y in range(0, H, 4):
        c.drawRect(skia.Rect.MakeXYWH(0, y, W, 1), p)
    return surf.makeImageSnapshot()


def init_assets():
    global GRAIN, VIGNETTE, SCAN
    if GRAIN is None:
        GRAIN = _make_grain(6)
        VIGNETTE = _make_vignette()
        SCAN = _make_scan()


def img(canvas, image, x, y, w, h, alpha=1.0, blend=None):
    p = skia.Paint(AntiAlias=True)
    p.setAlphaf(clamp(alpha))
    if blend is not None:
        p.setBlendMode(blend)
    canvas.drawImageRect(image, skia.Rect.MakeXYWH(x, y, w, h), p)


# ---------------------------------------------------------------- primitives
def glow(canvas, cx, cy, r, color, alpha=1.0, blend=skia.BlendMode.kPlus):
    base = color & 0xFFFFFF
    sh = skia.GradientShader.MakeRadial(
        skia.Point(cx, cy), max(1.0, r),
        [(base | (int(190 * alpha) << 24)), (base | (int(52 * alpha) << 24)), (base & 0xFFFFFF)],
        [0.0, 0.52, 1.0])
    p = skia.Paint(AntiAlias=True)
    p.setShader(sh)
    p.setBlendMode(blend)
    canvas.drawRect(skia.Rect.MakeXYWH(cx - r, cy - r, r * 2, r * 2), p)


def rect(canvas, x, y, w, h, color, alpha=1.0, r=0.0):
    p = T.paint(color, alpha)
    if r > 0:
        canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r), p)
    else:
        canvas.drawRect(skia.Rect.MakeXYWH(x, y, w, h), p)


def line(canvas, x1, y1, x2, y2, color, width=3.0, alpha=1.0, cap=skia.Paint.kRound_Cap):
    p = T.paint(color, alpha, stroke=width)
    p.setStrokeCap(cap)
    canvas.drawLine(x1, y1, x2, y2, p)


def text(canvas, s, x, y, size, color=INKC, alpha=1.0, align="left", stroke=None,
         stroke_w=0.0, tracking=0.0, progress=None):
    if alpha <= 0.004:
        return 0.0
    gs, w, a, d = T.layout(s, size, tracking)
    if align == "center":
        x = x - w / 2
    elif align == "right":
        x = x - w
    T.draw_glyphs(canvas, gs, x, y, color=color, alpha=alpha, stroke=stroke,
                  stroke_w=stroke_w, progress=progress)
    return w


def fit_text(canvas, s, x, y, size, maxw, color=INKC, alpha=1.0, align="center",
             stroke=None, stroke_w=0.0):
    gs, w, a, d = T.layout(s, size)
    if w > maxw:
        size *= maxw / w
        gs, w, a, d = T.layout(s, size)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    T.draw_glyphs(canvas, gs, x, y, color=color, alpha=alpha, stroke=stroke, stroke_w=stroke_w)
    return w


def pill(canvas, s, cx, cy, size=34, fg=0xFF05050A, bg=AMBER, alpha=1.0, pad=24):
    gs, w, a, d = T.layout(s, size)
    h = size * 1.9
    rect(canvas, cx - w / 2 - pad, cy - h / 2, w + pad * 2, h, bg, alpha, r=h / 2)
    T.draw_glyphs(canvas, gs, cx - w / 2, cy + size * 0.36, color=fg, alpha=alpha)
    return w + pad * 2


def stamp(canvas, s, cx, cy, size=44, color=RED, alpha=1.0, rot=-8, sc=1.0):
    gs, w, a, d = T.layout(s, size)
    bw, bh = w + 52, size * 1.85
    canvas.save()
    canvas.translate(cx, cy)
    canvas.rotate(rot)
    canvas.scale(sc, sc)
    p = T.paint(color, alpha, stroke=3.5)
    canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-bw / 2, -bh / 2, bw, bh), 8, 8), p)
    T.draw_glyphs(canvas, gs, -w / 2, size * 0.36, color=color, alpha=alpha)
    canvas.restore()


# ---------------------------------------------------------------- HUD
def hud(canvas, t_abs, alpha=1.0, tag=""):
    if alpha <= 0.01:
        return
    secs = (t_abs * 1.7) % 3600
    clock = f"{int(secs // 3600):02d}:{int((secs % 3600) // 60):02d}:{int(secs % 60):02d}"
    rect(canvas, SAFE_L, 176, 4, 56, RED, alpha)
    text(canvas, "इस घंटे", SAFE_L + 20, 216, 28, DIM, alpha)
    text(canvas, clock, SAFE_L + 148, 216, 34, INKC, alpha, tracking=1)
    if tag:
        text(canvas, tag, SAFE_R, 216, 26, DIM, alpha * 0.9, align="right")
    line(canvas, SAFE_L, 246, SAFE_R, 246, 0xFF3A3F47, 1.5, alpha * 0.7)


# ---------------------------------------------------------------- camera
def apply_camera(canvas, zoom, cx, cy, rot=0.0, shake=(0, 0)):
    canvas.translate(W / 2 + shake[0], H / 2 + shake[1])
    canvas.rotate(rot)
    canvas.scale(zoom, zoom)
    canvas.translate(-cx, -cy)


def camera_from(keys, t):
    if t <= keys[0][0]:
        return keys[0][1:]
    for i in range(1, len(keys)):
        if t <= keys[i][0]:
            a, b = keys[i - 1], keys[i]
            p = ease_io(ramp(t, a[0], b[0]))
            return (lerp(a[1], b[1], p), lerp(a[2], b[2], p), lerp(a[3], b[3], p))
    return keys[-1][1:]


def shake_at(t, amp=4.0, hz=11.0):
    return (math.sin(t * hz) * amp + math.sin(t * hz * 2.3) * amp * 0.4,
            math.cos(t * hz * 0.8) * amp * 0.6)


# ---------------------------------------------------------------- captions
def build_caption_lines(scene_i, max_words=3, max_chars=22):
    """Group the scene's words into caption lines, with absolute timings."""
    words = voice(scene_i)
    lines, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or
                    len(" ".join(x[0] for x in cur + [w])) > max_chars):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def scrim(canvas, alpha=1.0, top=980, bottom=1780, strength=0.80):
    sh = skia.GradientShader.MakeLinear(
        [skia.Point(0, top), skia.Point(0, bottom)],
        [0x00000000, int(255 * strength * 0.55) << 24, int(255 * strength) << 24],
        [0.0, 0.45, 1.0])
    p = skia.Paint()
    p.setShader(sh)
    canvas.drawRect(skia.Rect.MakeXYWH(0, top, W, bottom - top), p)


def captions(canvas, scene_i, t_abs, y=1250, alpha=1.0, scrim_on=True):
    """Word-level captions in the mobile safe box; the spoken word is highlighted."""
    lines = build_caption_lines(scene_i)
    if not lines:
        return
    if scrim_on:
        scrim(canvas, alpha)
    for li, ln in enumerate(lines):
        start = ln[0][1] - 0.08
        nxt = lines[li + 1][0][1] - 0.08 if li + 1 < len(lines) else ln[-1][2] + 0.55
        if not (start <= t_abs < nxt):
            continue
        size = 66
        space = size * 0.28
        widths = []
        for w, s, e in ln:
            ww = T.measure(w, size)[0]
            widths.append(ww)
        # shrink the whole line if it would leave the safe box
        total = sum(widths) + space * (len(ln) - 1)
        if total > SAFE_R - SAFE_L:
            k = (SAFE_R - SAFE_L) / total
            size *= k
            widths = [x * k for x in widths]
            space *= k
            total = sum(widths) + space * (len(ln) - 1)
        x = W / 2 - total / 2
        out = 1 - ramp(t_abs, nxt - 0.16, nxt)
        for i, (word, s, e) in enumerate(ln):
            p = back_out(ramp(t_abs, s - 0.02, s + 0.22))
            spoken = s <= t_abs <= e
            col = AMBER if spoken else INKC
            if p <= 0.002:
                x += widths[i] + space
                continue
            canvas.save()
            canvas.translate(x + widths[i] / 2, y + (1 - p) * 30)
            sc = lerp(0.86, 1.0, p) * (1.06 if spoken else 1.0)
            canvas.scale(sc, sc)
            gs, ww, a, d = T.layout(word, size)
            # dark scrim so captions read on any frame
            if spoken:
                rect(canvas, -ww / 2 - 14, -size * 0.62, ww + 28, size * 0.94,
                     0xFF000000, 0.34 * alpha * out, r=10)
            T.draw_glyphs(canvas, gs, -ww / 2, size * 0.34, color=col,
                          alpha=alpha * out * clamp(p * 1.5))
            canvas.restore()
            x += widths[i] + space


# ================================================================ scenes

def _bg(canvas, c1, c2):
    p = skia.Paint()
    sh = skia.GradientShader.MakeLinear([skia.Point(0, 0), skia.Point(W * 0.35, H)], [c1, c2])
    p.setShader(sh)
    canvas.drawRect(skia.Rect.MakeXYWH(-W * 0.6, -H * 0.35, W * 2.2, H * 2.2), p)


def _stars(canvas, t_abs, seed, n=120, alpha=1.0):
    rnd = random.Random(seed)
    for i in range(n):
        x = rnd.uniform(0, W)
        y = rnd.uniform(0, H)
        r = rnd.uniform(0.6, 2.0)
        tw = 0.30 + 0.70 * abs(math.sin(t_abs * rnd.uniform(0.7, 2.4) + i))
        canvas.drawCircle(x, y, r, T.paint(INKC, 0.50 * tw * alpha))


def _road(canvas, tl, speed=1.7, dash_color=AMBER, dash_alpha=0.55, roadc=0xFF14100F):
    vp = (540, 1010)
    path = skia.Path()
    path.moveTo(vp[0] - 46, vp[1])
    path.lineTo(vp[0] - 780, 2120)
    path.lineTo(vp[0] + 780, 2120)
    path.lineTo(vp[0] + 46, vp[1])
    path.close()
    canvas.drawPath(path, T.paint(roadc, 1.0))
    for side in (-1, 1):
        line(canvas, vp[0] + side * 40, vp[1], vp[0] + side * 660, 2120, 0xFF463B34, 6)
    for i in range(10):
        q = ((i / 10.0) + (tl * speed) % 1.0) % 1.0
        yy = vp[1] + (q ** 2.5) * 1100
        wid = 4 + 30 * q ** 2
        hgt = 8 + 160 * q ** 2
        a = clamp(q * 3) * (1 - clamp((q - 0.94) / 0.06))
        rect(canvas, 540 - wid / 2, yy, wid, hgt, dash_color, dash_alpha * a)


def scene_hook(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.42, 540, 780), (1.6, 1.20, 540, 860), (3.4, 1.28, 540, 840), (5.0, 1.10, 540, 940)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF160A0B, 0xFF030202)
    glow(canvas, 540, 1010, 800, 0xFF5E0F12, 0.60)
    glow(canvas, 540, 1010, 260, 0xFFFF3A2E, 0.30)
    _road(canvas, tl)
    # rain
    rnd = random.Random(3)
    for i in range(80):
        x0 = rnd.uniform(-250, 1330)
        y0 = (rnd.uniform(0, 2100) + tl * 1500) % 2100
        line(canvas, x0, y0, x0 - 24, y0 + rnd.uniform(40, 120), 0xFFC3DAFF, 1.5, 0.07 + 0.08 * rnd.random())

    # the number
    p_num = back_out(ramp(tl, 0.14, 0.58)) if tl < 3.4 else back_out(ramp(tl, 4.2, 4.7)) * 0.0 + 1
    canvas.save()
    canvas.translate(540, 700)
    sc = lerp(1.9, 1.0, p_num)
    canvas.scale(sc, sc)
    if tl < 0.6:
        canvas.translate(math.sin(tl * 70) * 4 * (1 - tl / 0.6), 0)
    text(canvas, "19", 0, 150, 460, RED, clamp(p_num * 1.6), align="center")
    canvas.restore()
    text(canvas, "हर घंटे", 540, 380, 92, INKC,
         ease_out(ramp(tl, 0.5, 0.9)) * (1 - ramp(t_abs, 1.02, 1.22)), align="center")
    p2 = ease_out(ramp(tl, 2.15, 2.55))
    if p2 > 0:
        text(canvas, "सड़क पर", 540, 1040, 84, INKC, p2, align="center")
        line(canvas, 540 - 170 * p2, 1078, 540 + 170 * p2, 1078, RED, 4, p2)
    if tl < 0.20:
        rect(canvas, -200, -400, W + 400, H * 2, 0xFFFFFFFF, (1 - tl / 0.20) * 0.30)
    # beat pips: the first three taps land where the VO actually starts
    for bt in (0.22, 1.05, 1.75):
        k = 1 - ramp(tl, bt, bt + 0.42)
        if k > 0:
            canvas.drawCircle(540, 936, 16 * back_out(ramp(tl, bt, bt + 0.10)) * (1 + 0.6 * (1 - k)),
                              T.paint(RED, 0.55 * k, stroke=3))
    canvas.restore()
    hud(canvas, t_abs, ramp(tl, 0.3, 0.7), SCENES[0]["tag"])


def scene_moon(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.06, 540, 900), (2.4, 1.28, 540, 860), (5.0, 1.16, 540, 930)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF070A18, 0xFF010103)
    _stars(canvas, t_abs, 11, 150)
    # Earth, small and far
    ex, ey = 838, 506
    glow(canvas, ex, ey, 130, 0xFF2E7BFF, 0.55)
    canvas.drawCircle(ex, ey, 42, T.paint(0xFF2E7BFF, 0.95))
    canvas.drawCircle(ex, ey - 12, 22, T.paint(0xFF7FD8FF, 0.30))
    canvas.drawCircle(ex, ey, 42, T.paint(0xFF8FD0FF, 0.35, stroke=2))
    # Moon limb
    moon = skia.Path()
    moon.addCircle(540, 1660, 800)
    p = T.paint(0xFF000000)
    p.setShader(skia.GradientShader.MakeLinear([skia.Point(240, 900), skia.Point(860, 1900)],
                                               [0xFFE7E1D5, 0xFF7A756B]))
    canvas.drawPath(moon, p)
    rnd = random.Random(5)
    for i in range(14):
        ang = rnd.uniform(math.pi * 1.08, math.pi * 1.92)
        rr = rnd.uniform(620, 790)
        x = 540 + math.cos(ang) * rr
        y = 1660 + math.sin(ang) * rr
        cr = rnd.uniform(18, 58)
        canvas.drawCircle(x, y, cr, T.paint(0xFF8F8A7F, 0.40))
        canvas.drawCircle(x - cr * 0.15, y - cr * 0.25, cr * 0.75, T.paint(0xFFCFC9BD, 0.30))
    # lander
    land_p = ease_out(ramp(tl, 0.35, 2.9))
    ly = lerp(430, 1000, land_p)
    lx = 540 + math.sin(tl * 1.1) * 5
    if land_p < 0.985:
        for i in range(6):
            canvas.drawCircle(lx + rnd.uniform(-12, 12), ly + 86 + i * 26, 20 + i * 9,
                              T.paint(0xFFFFC98A, 0.26 * (1 - land_p) * (1 - i / 6)))
            canvas.drawCircle(lx, ly + 74 + i * 20, 9 + i * 5, T.paint(0xFF9AD8FF, 0.24 * (1 - land_p)))
    body_c = 0xFFDCD6C9
    rect(canvas, lx - 58, ly - 34, 116, 72, body_c, 1.0, r=8)
    rect(canvas, lx - 58, ly - 34, 116, 20, 0xFF8C877C, 1.0, r=8)
    rect(canvas, lx - 30, ly - 86, 60, 52, 0xFFF0EBE0, 1.0, r=6)
    for s in (-1, 1):
        line(canvas, lx + s * 50, ly + 38, lx + s * 92, ly + 92, 0xFFB7B1A4, 8)
        canvas.drawCircle(lx + s * 94, ly + 96, 12, T.paint(0xFF8B857A))
    canvas.drawCircle(lx, ly + 6, 8, T.paint(RED, 0.95))
    dp = ramp(tl, 2.85, 4.2)
    if 0 < dp < 1:
        for i in range(3):
            canvas.drawCircle(lx, ly + 104, 60 + i * 80 + dp * 160,
                              T.paint(0xFFE8DFCF, 0.22 * (1 - dp) * (1 - i * 0.22), stroke=3))
    # instrument labels
    line(canvas, SAFE_L, 292, SAFE_L + 200, 292, 0xFF6D7688, 2, 0.7)
    text(canvas, "चाँद · दक्षिणी ध्रुव", SAFE_L, 340, 30, 0xFFA9B2C2, 0.95)
    text(canvas, "23 अगस्त 2023", SAFE_L, 384, 26, 0xFF6D7688, 0.9)
    t_h = word_at(2, "चाँद", 1.25)
    if t_abs >= t_h:
        text(canvas, "वहाँ आज तक", 540, 470, 62, INKC, ease_out(ramp(t_abs, t_h, t_h + 0.4)), align="center")
    t_h2 = word_at(2, "इतिहास", 3.0)
    if t_abs >= t_h2:
        text(canvas, "कोई नहीं पहुँचा", 540, 552, 62, AMBER, ease_out(ramp(t_abs, t_h2, t_h2 + 0.4)), align="center")
    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[1]["tag"])


def scene_mars(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.26, 540, 840), (2.2, 1.10, 540, 900), (5.0, 1.32, 520, 830)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF180705, 0xFF020101)
    _stars(canvas, t_abs, 21, 100, 0.8)
    glow(canvas, 540, 1620, 950, 0xFF7A1B0C, 0.50)
    planet = skia.Path()
    planet.addCircle(540, 1880, 860)
    p = T.paint(0xFF000000)
    p.setShader(skia.GradientShader.MakeLinear([skia.Point(280, 1060), skia.Point(820, 1880)],
                                               [0xFFE2602A, 0xFF83250A, 0xFF2C0C03]))
    canvas.drawPath(planet, p)
    for i in range(9):
        canvas.drawRect(skia.Rect.MakeXYWH(-100, 1180 + i * 64, W + 200, 9 + i * 3),
                        T.paint(0xFF3A1004, 0.28))
    canvas.drawCircle(540, 1880, 860, T.paint(0xFFFFB07A, 0.18, stroke=2))
    # transfer arc + craft
    op = ease_out(ramp(tl, 0.3, 3.3))
    orbit = skia.Path()
    orbit.addOval(skia.Rect.MakeLTRB(-190, 700, 1270, 1560))
    pp = T.paint(0xFFFF9A5C, 0.50, stroke=2.5)
    pp.setPathEffect(skia.DashPathEffect.Make([16, 14], 0))
    canvas.drawPath(orbit, pp)
    ang = math.pi * 0.97 + op * math.pi * 0.92
    sx = 540 + math.cos(ang) * 730
    sy = 1130 + math.sin(ang) * 430
    glow(canvas, sx, sy, 66, AMBER, 0.50)
    canvas.save()
    canvas.translate(sx, sy)
    canvas.rotate(math.degrees(ang) + 96)
    rect(canvas, -13, -13, 26, 26, 0xFFFFF2DC, 1.0, r=4)
    for s in (-1, 1):
        rect(canvas, s * 24 - (8 if s > 0 else 0), -5, 17, 10, AMBER, 0.95, r=2)
    canvas.restore()
    text(canvas, "मंगलयान", sx + 44, sy - 40, 30, 0xFFFFD7AE, 0.95)
    t_h2 = word_at(3, "पहुँच", 3.8)
    if t_abs >= t_h2:
        a = ease_out(ramp(t_abs, t_h2, t_h2 + 0.35))
        pill(canvas, "पहला प्रयास · सफल", 540, 520, 36, 0xFF05050A, MINT, a)
    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[2]["tag"])


def scene_cost(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.00, 540, 940), (2.2, 1.10, 540, 900), (5.5, 1.13, 540, 950)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF0A100D, 0xFF020302)
    glow(canvas, 540, 820, 720, 0xFF0E5A44, 0.32)
    card_x, card_y, card_w, card_h = SAFE_L, 372, SAFE_R - SAFE_L, 720
    rect(canvas, card_x, card_y, card_w, card_h, 0xFF0D1512, 0.97, r=26)
    rect(canvas, card_x, card_y, card_w, 92, 0xFF16241E, 1.0, r=26)
    text(canvas, "मंगल मिशन · बजट", card_x + 36, card_y + 58, 32, 0xFFA6EBD2)
    text(canvas, "ISRO", card_x + card_w - 36, card_y + 58, 32, 0xFF5F9C88, align="right")
    n = 450 * ease_out(ramp(tl, 0.35, 2.7))
    num = f"{int(round(n))}"
    gs, w, a, d = T.layout(num, 180)
    T.draw_glyphs(canvas, gs, card_x + 40, card_y + 262, color=INKC)
    rgs, rw, _, _ = T.layout("₹", 120)
    T.draw_glyphs(canvas, rgs, card_x + 44 + w + 10, card_y + 262, color=AMBER)
    text(canvas, "करोड़", card_x + 58 + w + rw + 24, card_y + 262, 64, 0xFFB9C7C1)
    line(canvas, card_x + 40, card_y + 310, card_x + card_w - 40, card_y + 310, 0xFF2C3B35, 2)
    bp = ease_out(ramp(tl, 1.8, 3.4))
    base_y = card_y + 470
    rows = [("भारत", 450, MINT, 0.9), ("हॉलीवुड फिल्म", 830, 0xFF7C8B85, 0.5)]
    for i, (label, val, c, alpha_) in enumerate(rows):
        y = base_y + i * 132
        text(canvas, label, card_x + 40, y - 26, 30, DIM)
        barw = (card_w - 230) * (val / 900.0) * bp
        rect(canvas, card_x + 40, y, max(2, barw), 44, c, alpha_, r=8)
        text(canvas, f"₹{val}", card_x + 40 + barw + 16, y + 34, 34, INKC if i == 0 else DIM, clamp(bp * 1.5))
    text(canvas, "* ग्रैविटी (2013) का अनुमानित बजट", card_x + 40, card_y + card_h - 30, 22, 0xFF5F6E68)
    # the line everyone remembers: about four rupees per Indian
    a4 = ease_out(ramp(tl, 2.05, 2.5))
    if a4 > 0:
        canvas.save()
        canvas.translate(540, 1174)
        gs, w, _, _ = T.layout("₹4", 90)
        T.draw_glyphs(canvas, gs, -w / 2 - 128, 32, color=AMBER, alpha=a4)
        text(canvas, "प्रति भारतीय", 56, 32, 48, SOFT, a4)
        line(canvas, -w / 2 - 200, -56, w / 2 + 310, -56, 0xFF3A4A44, 2, a4 * 0.8)
        canvas.restore()
    tp = back_out(ramp(tl, 2.95, 3.4))
    if tp > 0.01:
        canvas.save()
        canvas.translate(250, 1330)
        canvas.rotate(-7)
        canvas.scale(tp, tp)
        rect(canvas, -142, -54, 284, 108, AMBER, 1.0, r=10)
        text(canvas, "सस्ता!", 0, 18, 58, 0xFF05050A, 1.0, align="center")
        canvas.restore()
    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[3]["tag"])


def scene_rail(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.32, 300, 820), (3.0, 1.12, 540, 900), (6.0, 1.24, 760, 940)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF0A0B13, 0xFF020204)
    # carriage windows with passing lights
    for row in range(2):
        for col_ in range(3):
            x = 40 + col_ * 350
            y = 690 + row * 250
            rect(canvas, x, y, 310, 206, 0xFF0C131F, 1.0, r=18)
            canvas.save()
            canvas.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x + 8, y + 8, 294, 190), 12, 12),
                             skia.ClipOp.kIntersect, True)
            glow(canvas, x + 160, y + 120, 170, 0xFF24466F, 0.60)
            for i in range(11):
                q = ((i / 11.0) + (tl * 1.9 + row * 0.17) % 1.0) % 1.0
                xx = x + 300 - q * 380
                hh = 5 + (i % 4) * 8
                canvas.drawRect(skia.Rect.MakeXYWH(xx, y + 22 + (i * 41) % 200, 130, hh),
                                T.paint(AMBER, 0.13 + 0.10 * (i % 3)))
            canvas.restore()
            rect(canvas, x, y, 310, 206, 0xFF2A3448, 0.6, r=18)
    cp = ease_out(ramp(tl, 0.45, 3.0))
    text(canvas, f"{2.31 * cp:.2f}".replace(".", ","), 540, 470, 150, INKC, 1.0, align="center")
    text(canvas, "करोड़ यात्री · हर दिन", 540, 536, 40, AMBER, 1.0, align="center")
    rect(canvas, 0, 1330, W, 3, 0xFF232B3A, 0.9)
    text(canvas, "13,000+ ट्रेनें · रोज़", SAFE_L, 1382, 26, 0xFF5C6B84, 0.9)
    a = ease_out(ramp(tl, word_at(5, "ऑस्ट्रेलिया", 3.6) - 20.5, word_at(5, "ऑस्ट्रेलिया", 3.6) - 20.5 + 0.35))
    if a > 0:
        pill(canvas, "पूरा ऑस्ट्रेलिया", 540, 1252, 34, 0xFF05050A, AMBER, a)
    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[4]["tag"])


def scene_post(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.14, 540, 1010), (2.8, 1.00, 540, 960), (6.0, 1.10, 540, 930)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF0C0805, 0xFF030202)
    rnd = random.Random(41)
    dots = [(90 + gx * 101 + rnd.uniform(-16, 16), 640 + gy * 62 + rnd.uniform(-12, 12), rnd.random())
            for gy in range(5) for gx in range(10)]
    for i, (x, y, r) in enumerate(dots):
        on = ramp(tl, 0.2 + (i / len(dots)) * 2.0, 0.55 + (i / len(dots)) * 2.0)
        if on <= 0:
            continue
        canvas.drawCircle(x, y, 5.5 * on, T.paint(0xFFFF5A3A, 0.85))
        if r > 0.86:
            canvas.drawCircle(x, y, 14 * on, T.paint(0xFFFF5A3A, 0.14 * on))
    for i in range(6):
        k = int((tl * 1.4 + i * 0.37) * 40) % (len(dots) - 1)
        line(canvas, dots[k][0], dots[k][1], dots[(k + 11) % len(dots)][0], dots[(k + 11) % len(dots)][1],
             0xFFFF8A5C, 1.6, 0.16)
    # postbox
    bx, by = 540, 1436
    rect(canvas, bx - 88, by - 116, 176, 190, 0xFFC2171B, 1.0, r=16)
    rect(canvas, bx - 100, by - 138, 200, 42, 0xFF8E0F12, 1.0, r=12)
    rect(canvas, bx - 52, by - 92, 104, 11, 0xFF2A0505, 1.0, r=6)
    text(canvas, "डाक", bx, by + 42, 44, 0xFFF6D9D9, 0.9, align="center")
    # Hikkim altitude tag
    ap = ease_out(ramp(tl, word_at(6, "ऊँचा", 4.4) - 26.5, word_at(6, "ऊँचा", 4.4) - 26.5 + 0.5))
    if ap > 0:
        line(canvas, 792, 620, 792, 620 + 250 * ap, 0xFF6A5A4C, 2, 0.9, skia.Paint.kButt_Cap)
        text(canvas, "4,440 मी", 806, 642, 26, 0xFFBCA996, ap)
        text(canvas, "सबसे ऊँचा डाकघर", 806, 892, 26, 0xFFBCA996, ap)
    text(canvas, "1.55", 540, 442, 168, INKC, ease_out(ramp(tl, 0.6, 1.2)), align="center")
    text(canvas, "लाख डाकघर", 540, 512, 46, AMBER, ease_out(ramp(tl, 0.95, 1.5)), align="center")
    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[5]["tag"])


def scene_turn(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.38, 560, 840), (3.2, 1.10, 540, 950), (6.5, 1.22, 540, 880)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF0A0C14, 0xFF010102)
    glow(canvas, 540, 1010, 720, 0xFF12224A, 0.60)
    _road(canvas, tl, 0.85, 0xFF8FA6C8, 0.26, 0xFF101216)
    # ghost numerals falling like a clock shedding seconds
    rnd3 = random.Random(77)
    for i in range(14):
        gx = rnd3.uniform(60, 1020)
        gy = ((rnd3.uniform(0, 2000) + tl * rnd3.uniform(90, 190)) % 2100) - 200
        a = 0.05 + 0.05 * rnd3.random()
        text(canvas, "19", gx, gy, rnd3.uniform(28, 46), 0xFF9FB4D8, a, align="center")
    hp = ease_out(ramp(tl, 0.2, 6.2))
    for s in (-1, 1):
        x = 540 + s * lerp(80, 300, hp)
        y = lerp(1020, 1290, ease_in(hp))
        glow(canvas, x, y, 80 + hp * 300, 0xFFDCE9FF, 0.30 + 0.35 * hp)
        canvas.drawCircle(x, y, 15 + hp * 24, T.paint(0xFFF2F8FF, 0.85))
    t_q2 = word_at(7, "गर्व", 4.6)
    if t_abs >= t_q2:
        a = ease_out(ramp(t_abs, t_q2, t_q2 + 0.4))
        canvas.save()
        canvas.translate(540, 500)
        canvas.scale(a, a)
        text(canvas, "?", 0, 60, 200, AMBER, a * 0.9, align="center")
        canvas.restore()
    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[6]["tag"])


def scene_cost2(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.02, 540, 940), (2.0, 1.22, 540, 900), (4.8, 1.12, 540, 950)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF130708, 0xFF020101)
    glow(canvas, 540, 900, 800, 0xFF5C0A0D, 0.60)
    rp = ease_out(ramp(tl, 0.15, 1.4))
    canvas.save()
    canvas.translate(540, 748)
    canvas.scale(rp, rp)
    for rr in (232, 320):
        p = T.paint(RED, 0.28, stroke=2)
        p.setPathEffect(skia.DashPathEffect.Make([20, 16], 0))
        canvas.drawCircle(0, 0, rr, p)
    canvas.restore()
    text(canvas, "19", 540, 880, 330, INKC, clamp(ramp(tl, 0.12, 0.45)), align="center")
    t_r = word_at(8, "घंटे", 2.1)
    text(canvas, "इस घंटे भी", 540, 470, 54, RED, ease_out(ramp(t_abs, t_r - 0.2, t_r + 0.2)), align="center")

    canvas.restore()
    hud(canvas, t_abs, 1.0, SCENES[7]["tag"])


def scene_loop(canvas, t_abs, tl):
    zoom, cx, cy = camera_from([(0.0, 1.20, 540, 860), (2.4, 1.02, 540, 960), (4.0, 1.16, 540, 900)], tl)
    canvas.save()
    apply_camera(canvas, zoom, cx, cy)
    _bg(canvas, 0xFF140708, 0xFF000000)
    glow(canvas, 540, 960, 760, 0xFF5A0E10, 0.55)
    p = back_out(ramp(tl, 0.02, 0.45))
    canvas.save()
    canvas.translate(540, 940)
    canvas.scale(p, p)
    text(canvas, "उन्नीस", 0, 70, 148, RED, 1.0, align="center")
    canvas.restore()
    t_a = word_at(9, "अगला", 0.3)
    if t_abs >= t_a:
        text(canvas, "अगला घंटा शुरू", 540, 1120, 46, SOFT, ease_out(ramp(t_abs, t_a, t_a + 0.35)), align="center")
    cp = ease_out(ramp(t_abs, t_a + 0.9, t_a + 1.5))
    text(canvas, "00:00:00", 540, 1224, 54, AMBER, cp, align="center", tracking=4)
    canvas.restore()
    hud(canvas, 0.0, 1.0, SCENES[8]["tag"])


DRAW = {"hook": scene_hook, "moon": scene_moon, "mars": scene_mars, "cost": scene_cost,
        "rail": scene_rail, "post": scene_post, "turn": scene_turn,
        "cost2": scene_cost2, "loop": scene_loop}


# ---------------------------------------------------------------- frame assembly
CAPTION_Y = {"hook": 1250, "moon": 1250, "mars": 1250, "cost": 1420, "rail": 1450,
             "post": 1300, "turn": 1250, "cost2": 1560, "loop": 1460}


def render_scene_surface(idx, tl, t_abs):
    surf = POOL.get()
    c = surf.getCanvas()
    c.clear(skia.ColorBLACK)
    DRAW[SCENES[idx]["name"]](c, t_abs, tl)
    # captions are UI, not scenery: drawn in screen space so the camera never
    # pushes them outside the mobile safe box
    captions(c, idx + 1, t_abs, y=CAPTION_Y[SCENES[idx]["name"]],
             scrim_on=SCENES[idx]["name"] not in ("cost2",))
    return surf


def _blur_draw(canvas, image, dx, dy, copies=5, spread=1.0):
    """Cheap directional motion blur: a chain of translucent offset copies."""
    for k in range(copies, 0, -1):
        p = skia.Paint(AntiAlias=True)
        p.setAlphaf(0.30 / k ** 0.55)
        canvas.save()
        canvas.translate(dx * k * spread, dy * k * spread)
        canvas.drawImage(image, 0, 0, p)
        canvas.restore()


def frame(t, frame_index):
    init_assets()
    idx, tl = scene_at(t)
    surf = render_scene_surface(idx, tl, t)
    sim = surf.makeImageSnapshot()
    out = POOL.get()
    c = out.getCanvas()
    c.clear(skia.ColorBLACK)
    c.drawImage(sim, 0, 0)

    remaining = SCENES[idx]["t1"] - t
    trans = TRANSITION[idx] if idx < len(TRANSITION) else "cut"
    if remaining < 0.34 and trans != "cut":
        p = 1 - remaining / 0.34
        nsurf = render_scene_surface(idx + 1, -0.02, t)
        nim = nsurf.makeImageSnapshot()
        if trans == "whip":
            off = ease_in(p) * (W + 120)
            c.clear(skia.ColorBLACK)
            c.save()
            c.translate(-off, 0)
            c.drawImage(sim, 0, 0)
            c.restore()
            c.save()
            c.translate(W - off, 0)
            _blur_draw(c, nim, 26, 0, 4)
            c.drawImage(nim, 0, 0)
            c.restore()
        elif trans == "push":
            k = ease_in(p)
            sc = lerp(1.0, 1.42, k)
            c.save()
            c.translate(W / 2, H / 2)
            c.scale(sc, sc)
            c.translate(-W / 2, -H / 2)
            c.drawImage(sim, 0, 0)
            c.restore()
            a = clamp(p * 1.7)
            pnt = skia.Paint(AntiAlias=True)
            pnt.setAlphaf(a)
            c.drawImage(nim, 0, 0, pnt)
            if p < 0.85:
                fa = 0.34 * (1 - p / 0.85)
                flash = skia.Paint()
                flash.setShader(skia.GradientShader.MakeRadial(
                    skia.Point(W / 2, H / 2), 520 + 420 * p,
                    [(int(255 * fa) << 24) | 0xFFFFFF, (int(70 * fa) << 24) | 0xFFFFFF,
                     0x00FFFFFF], [0.0, 0.5, 1.0]))
                c.drawRect(skia.Rect.MakeWH(W, H), flash)
        elif trans == "glitch":
            pnt = skia.Paint(AntiAlias=True)
            pnt.setAlphaf(clamp(p * 2))
            c.drawImage(nim, 0, 0, pnt)
            rnd2 = random.Random(int(t * 1000))
            for i in range(10):
                y = rnd2.uniform(0, H)
                hh = rnd2.uniform(10, 90)
                dx = rnd2.uniform(-120, 120) * (1 - p)
                c.save()
                c.clipRect(skia.Rect.MakeXYWH(0, y, W, hh))
                c.translate(dx, 0)
                c.drawImage(nim, 0, 0)
                c.restore()
        POOL.put(nsurf)

    if t < 0.15:
        c.drawRect(skia.Rect.MakeWH(W, H), T.paint(0xFF000000, 1 - t / 0.15))
    if t > DURATION - 0.16:
        c.drawRect(skia.Rect.MakeWH(W, H), T.paint(0xFF000000, (t - (DURATION - 0.16)) / 0.16))

    img(c, VIGNETTE, 0, 0, W, H, 0.95)
    img(c, SCAN, 0, 0, W, H, 0.30)
    img(c, GRAIN[frame_index % len(GRAIN)], 0, 0, W, H, 0.085, skia.BlendMode.kOverlay)
    POOL.put(surf)
    return out


def save_frame(t, frame_index, path, quality=94):
    s = frame(t, frame_index)
    s.makeImageSnapshot().save(path, skia.kJPEG, quality)
    return s


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stills"
    init_assets()
    if cmd == "stills":
        outdir = os.path.join(BASE, "build", "stills")
        os.makedirs(outdir, exist_ok=True)
        times = [float(x) for x in sys.argv[2:]] or [1.0, 3.0, 7.0, 12.0, 17.0, 23.0, 29.0, 35.0, 41.0, 46.0]
        for tt in times:
            p = os.path.join(outdir, f"t{tt:05.2f}.jpg")
            save_frame(tt, int(tt * FPS), p, 92)
            print("wrote", p)
    elif cmd == "video":
        outdir = os.path.join(BASE, "build", "frames")
        os.makedirs(outdir, exist_ok=True)
        total = int(round(DURATION * FPS))
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        end = int(sys.argv[3]) if len(sys.argv) > 3 else total
        for i in range(start, end):
            tt = i / FPS
            s = frame(tt, i)
            s.makeImageSnapshot().save(os.path.join(outdir, f"f{i:05d}.png"), skia.kPNG)
            if i % 60 == 0:
                print(f"{i}/{total}  {tt:.2f}s", flush=True)
        print("done")
