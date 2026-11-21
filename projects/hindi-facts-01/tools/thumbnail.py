"""
Thumbnail / Shorts cover generator.

Same Skia + HarfBuzz stack as the video, so the cover is visually the same world
as the short (same grade, same type, same red) — covers that look like a different
video lose the recognition the video just earned.

Two concepts are rendered:
  A "do-sach"  — split frame: Mars mission above, the road below. The tension of
                 the script in one image; the number is the punchline, not the hook.
  B "19-only"  — one object, maximum contrast: 19 in road-light red on black.
                 A pure curiosity gap: the viewer must know what 19 means.

Run: python tools/thumbnail.py
"""
import os
import sys
import random
import math
import skia

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textkit as T
import engine as E

W, H = 1080, 1920
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(BASE, "out")


def radial(canvas, cx, cy, r, stops):
    p = skia.Paint(AntiAlias=True)
    p.setShader(skia.GradientShader.MakeRadial(
        skia.Point(cx, cy), r, [c for c, _ in stops], [o for _, o in stops]))
    canvas.drawRect(skia.Rect.MakeXYWH(cx - r, cy - r, r * 2, r * 2), p)


def cover_b(canvas):
    """B — single subject, hardest contrast, pure curiosity gap."""
    canvas.clear(0xFF050507)
    radial(canvas, 540, 900, 820, [(0x66FF2D2D, 0.0), (0x1EFF2D2D, 0.5), (0x00FF2D2D, 1.0)])
    # road shaft below the number
    vp = (540, 1240)
    path = skia.Path()
    path.moveTo(vp[0] - 30, vp[1])
    path.lineTo(vp[0] - 620, 1980)
    path.lineTo(vp[0] + 620, 1980)
    path.lineTo(vp[0] + 30, vp[1])
    path.close()
    canvas.drawPath(path, T.paint(0xFF0C0A0A))
    for s_ in (-1, 1):
        E.line(canvas, vp[0] + s_ * 26, vp[1], vp[0] + s_ * 540, 1980, 0xFF382B25, 7)
    for i in range(7):
        q = i / 7.0
        yy = vp[1] + (q ** 2.2) * 700
        wid = 5 + 30 * q ** 2
        E.rect(canvas, 540 - wid / 2, yy, wid, 12 + 140 * q ** 2, E.AMBER, 0.42 * q)
    E.text(canvas, "भारत · 2022", 540, 372, 40, 0xFF8E7C7C, 1.0, align="center")
    # the object
    canvas.save()
    canvas.translate(540, 900)
    gs, w, a, d = T.layout("19", 560)
    T.draw_glyphs(canvas, gs, -w / 2, 0, color=E.RED)
    canvas.restore()
    E.text(canvas, "हर घंटे", 540, 1136, 150, 0xFFFFFFFF, 1.0, align="center")
    E.text(canvas, "सड़क पर", 540, 1290, 116, E.AMBER, 1.0, align="center")
    E.rect(canvas, 300, 1352, 480, 8, E.RED, 1.0)


def cover_a(canvas):
    """A — split world: the two Indias, one frame."""
    canvas.clear(0xFF050507)
    p = skia.Paint()
    p.setShader(skia.GradientShader.MakeLinear(
        [skia.Point(0, 0), skia.Point(W, 860)], [0xFF170806, 0xFF43120A]))
    canvas.drawRect(skia.Rect.MakeXYWH(0, 0, W, 880), p)
    random.seed(9)
    for i in range(70):
        canvas.drawCircle(random.uniform(0, W), random.uniform(0, 780),
                          random.uniform(0.7, 1.9), T.paint(0xFFFFE9D6, 0.34))
    E.glow(canvas, 780, 820, 420, 0xFF6B1A08, 0.55)
    planet = skia.Path()
    planet.addCircle(820, 1080, 470)
    pp = T.paint(0xFF000000)
    pp.setShader(skia.GradientShader.MakeLinear(
        [skia.Point(560, 700), skia.Point(1040, 1120)], [0xFFE2602A, 0xFF5E1705]))
    canvas.drawPath(planet, pp)
    lx, ly = 700, 700
    E.rect(canvas, lx - 58, ly - 34, 116, 72, 0xFFDCD6C9, 1.0, r=8)
    E.rect(canvas, lx - 30, ly - 86, 60, 52, 0xFFF0EBE0, 1.0, r=6)
    for s_ in (-1, 1):
        E.line(canvas, lx + s_ * 50, ly + 38, lx + s_ * 92, ly + 92, 0xFFB7B1A4, 8)
    canvas.drawCircle(lx, ly + 6, 8, T.paint(E.RED))
    E.text(canvas, "₹450 करोड़", 88, 300, 104, 0xFFFFFFFF)
    E.text(canvas, "में मंगल मिशन", 90, 394, 56, E.AMBER)
    E.rect(canvas, 88, 440, 260, 6, E.RED, 0.9)

    E.rect(canvas, 0, 880, W, H - 880, 0xFF07070A)
    radial(canvas, 540, 1080, 760, [(0x8C5E0F12, 0.0), (0x005E0F12, 1.0)])
    vp = (540, 1180)
    path = skia.Path()
    path.moveTo(vp[0] - 38, vp[1])
    path.lineTo(vp[0] - 720, 1920)
    path.lineTo(vp[0] + 720, 1920)
    path.lineTo(vp[0] + 38, 1920 - 740)
    path.close()
    canvas.drawPath(path, T.paint(0xFF131010))
    for s_ in (-1, 1):
        E.line(canvas, vp[0] + s_ * 32, vp[1], vp[0] + s_ * 600, 1920, 0xFF463B34, 6)
    for i in range(6):
        q = i / 6.0
        yy = vp[1] + (q ** 2.2) * 700
        wid = 5 + 26 * q ** 2
        E.rect(canvas, 540 - wid / 2, yy, wid, 12 + 130 * q ** 2, E.AMBER, 0.42 * q)
    for s_ in (-1, 1):
        E.glow(canvas, 540 + s_ * 250, 1408, 190, 0xFFDCE9FF, 0.45)
        canvas.drawCircle(540 + s_ * 250, 1408, 20, T.paint(0xFFF2F8FF, 0.90))
    canvas.save()
    canvas.translate(540, 1618)
    gs, w, a, d = T.layout("19", 330)
    T.draw_glyphs(canvas, gs, -w / 2, 0, color=E.RED)
    canvas.restore()
    E.text(canvas, "हर घंटे", 540, 1080, 104, 0xFFFFFFFF, 1.0, align="center")
    E.text(canvas, "सड़क पर मौत", 540, 1186, 62, 0xFFF0B7B7, 1.0, align="center")


def finish(surf, seed=1):
    c = surf.getCanvas()
    E.init_assets()
    E.img(c, E.VIGNETTE, 0, 0, W, H, 0.85)
    E.img(c, E.SCAN, 0, 0, W, H, 0.22)
    return surf


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (("cover-a-do-sach", cover_a), ("cover-b-19-only", cover_b)):
        surf = skia.Surface(W, H)
        fn(surf.getCanvas())
        finish(surf)
        p = os.path.join(OUT, f"{name}.png")
        im = surf.makeImageSnapshot()
        im.save(p, skia.kPNG)
        im.save(p.replace(".png", ".jpg"), skia.kJPEG, 95)
        print("wrote", p)
