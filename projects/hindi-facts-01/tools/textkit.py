"""textkit — Devanagari-safe text on a Skia canvas.

Why this exists: Skia's own `drawString` has no Indic shaper, so "प्रत्येक" would
come out as disconnected consonants. Here we shape with HarfBuzz (which does the
full OpenType Devanagari pipeline: reordering, half forms, matra placement), then
draw the resulting glyph ids as Skia paths. Kerning, advances and offsets all come
from HarfBuzz, so the layout is exactly what a browser would produce.

Fonts are registered by role and picked per grapheme cluster:
  display  -> Devanagari Black (headlines)
  body     -> Devanagari ExtraBold (captions, smaller text)
  latin    -> Noto Sans Latin Black (digits, %, :, and Devanagari-less glyphs)
  heavy    -> Archivo Black (Latin "impact" words, numbers in big stat cards)
"""

import os
import re
import functools
import uharfbuzz as hb
import skia

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "..", "assets", "fonts")

ROLE_FILES = {
    "display": "NotoDeva900.ttf",
    "body": "NotoDeva800.ttf",
    "latin": "NotoDevaLatin900.ttf",
    "heavy": "ArchivoBlack.ttf",
    "rupee": "NotoDeva900.ttf",
}

_ANIM_RE = re.compile(r"[\u0900-\u097F\u0A80-\u0AFF]")
_ZWJ = "\u200d"


@functools.lru_cache(maxsize=None)
def _font(role):
    path = os.path.join(FONT_DIR, ROLE_FILES[role])
    tf = skia.Typeface.MakeFromFile(path)
    if tf is None:
        raise RuntimeError(f"cannot load typeface {path}")
    blob = hb.Blob.from_file_path(path)
    face = hb.Face(blob)
    hbfont = hb.Font(face)
    upem = face.upem
    return {"tf": tf, "font": skia.Font(tf, 100), "hb": hbfont, "upem": upem, "face": face}


def typeface(role="display"):
    return _font(role)["tf"]


def clusters(text):
    """Split into rendering runs. A run is (role, substring).

    Devanagari clusters (consonant + optional ZWJ + matra) get `display`; a lone
    ZWJ becomes a no-op; everything else (digits, %, :, ₹, Latin) gets `latin`,
    except ₹ which only exists in the Devanagari face.
    """
    runs = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if _ANIM_RE.match(ch):
            j = i
            while j < n and _ANIM_RE.match(text[j]):
                j += 1
            # keep a trailing ZWJ glued to the cluster before it
            while j < n and text[j] in _ZWJ + "\u200c":
                j += 1
            runs.append(("display", text[i:j]))
            i = j
        elif ch == "\u20b9":
            runs.append(("rupee", ch))
            i += 1
        elif ch in _ZWJ:
            runs.append(("skip", ""))
            i += 1
        else:
            j = i
            while j < n and not _ANIM_RE.match(text[j]) and text[j] != "\u20b9" and text[j] not in _ZWJ:
                j += 1
            runs.append(("latin", text[i:j]))
            i = j
    return [r for r in runs if r[1]]


class Glyph:
    __slots__ = ("path", "x", "y")

    def __init__(self, path, x, y):
        self.path, self.x, self.y = path, x, y


@functools.lru_cache(maxsize=40000)
def _shaped_run(text, role, size_q):
    """Shape one run at one size; returns tuple of (glyph_id, x, y, advance)."""
    f = _font(role)
    size = size_q / 4.0
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(f["hb"], buf)
    s = size / f["upem"]
    out = []
    pen = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append((info.codepoint, pen + pos.x_offset * s, -pos.y_offset * s, pos.x_advance * s))
        pen += pos.x_advance * s
    return tuple(out), pen


def layout(text, size, tracking=0.0):
    """Lay out a string at `size` px. Returns (glyphs, width, ascent, descent)."""
    glyphs = []
    pen = 0.0
    max_up = 0.0
    max_down = 0.0
    role_override = None
    if text.isdigit() or all(c in "0123456789.,:%₹ " for c in text):
        role_override = "latin"
    for role, sub in clusters(text):
        if role_override:
            role = "rupee" if sub == "₹" else role_override
        if role == "skip":
            continue
        f = _font(role)
        shaped, adv = _shaped_run(sub, role, int(round(size * 4)))
        fb = f["font"]
        font_size = size
        path_font = skia.Font(f["tf"], font_size)
        for gid, gx, gy, gadv in shaped:
            p = path_font.getPath(gid)
            if p is not None and not p.isEmpty():
                glyphs.append(Glyph(p, pen + gx, gy))
        cap_up = -font_size * 0.76
        max_up = max(max_up, cap_up)
        max_down = max(max_down, font_size * 0.30)
        pen += adv + tracking
    return glyphs, pen, max_up, max_down


def measure(text, size, tracking=0.0):
    _, w, a, d = layout(text, size, tracking)
    return w, a, d


def fit_size(text, max_width, start, minimum=34, tracking=0.0, step=2):
    """Shrink until the line fits; keeps headlines inside the safe zone."""
    s = start
    while s > minimum:
        w, _, _ = measure(text, s, tracking)
        if w <= max_width:
            return s
        s -= step
    return minimum


def paint(color, alpha=1.0, stroke=0.0, cap_round=True):
    p = skia.Paint(AntiAlias=True, Color=color if alpha >= 1.0 else _with_alpha(color, alpha))
    if stroke > 0:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        p.setStrokeCap(skia.Paint.kRound_Cap if cap_round else skia.Paint.kButt_Cap)
        p.setStrokeJoin(skia.Paint.kRound_Join)
    return p


def _with_alpha(color, alpha):
    a = (color >> 24) & 0xFF
    if a == 0:
        a = 255
    return (int(a * alpha) << 24) | (color & 0xFFFFFF)


def draw_glyphs(canvas, glyphs, x, y, color=0xFFFFFFFF, alpha=1.0,
                stroke=None, stroke_w=0.0, shadow=None, shadow_dx=0, shadow_dy=0,
                shadow_blur=0.0, progress=None):
    """Draw a laid-out run. `progress` < 1 clips the run in from the left (wipe)."""
    if alpha <= 0.001:
        return
    if progress is not None:
        canvas.save()
        if progress <= 0:
            canvas.restore()
            return
        maxw = 0.0
        for g in glyphs:
            b = g.path.getBounds()
            maxw = max(maxw, g.x + b.right())
        canvas.clipRect(skia.Rect.MakeLTRB(-9999, -9999, x + maxw * progress + 2, 9999))
    canvas.save()
    canvas.translate(x, y)
    for g in glyphs:
        canvas.save()
        canvas.translate(g.x, g.y)
        if shadow is not None:
            sp = paint(shadow, alpha * 0.9)
            sp.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, shadow_blur or 8.0))
            canvas.save()
            canvas.translate(shadow_dx, shadow_dy)
            canvas.drawPath(g.path, sp)
            canvas.restore()
        if stroke is not None and stroke_w > 0:
            sp = paint(stroke, alpha, stroke=stroke_w)
            canvas.drawPath(g.path, sp)
        canvas.drawPath(g.path, paint(color, alpha))
        canvas.restore()
    canvas.restore()
    if progress is not None:
        canvas.restore()


def text_sprite(text, size, color, role_override=None, pad=24, stroke=None, stroke_w=0.0,
                tracking=0.0):
    """Rasterise a static string to a Skia image (fast path for repeated draws)."""
    glyphs, w, a, d = layout(text, size, tracking)
    W = int(w + pad * 2 + stroke_w * 2)
    H = int(a + d + pad * 2 + stroke_w * 2)
    surf = skia.Surface(max(4, W), max(4, H))
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    draw_glyphs(c, glyphs, pad + stroke_w, pad - a + stroke_w, color=color,
                stroke=stroke, stroke_w=stroke_w)
    return surf.makeImageSnapshot(), (w, a, d)
