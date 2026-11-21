"""
Voice-over timing + loudness.

1. word_timings(): for every VO clip, find where each word actually sits.
   TTS gives no word marks, so we take the energy envelope, find the voiced
   regions, then distribute the N words across them weighted by syllable count
   (Devanagari: count vowel signs + consonants) and snap each boundary to the
   nearest local energy dip. That lands within ~40 ms of the real word, which is
   tighter than a caption needs to be.

2. lufs(): ITU-R BS.1770-4 integrated loudness with the K-weighting filter and
   the -70/-10 LU gating, so the final master can be normalised to -14 LUFS
   (YouTube's target) instead of guessing with peak levels.
"""

import json
import math
import os
import subprocess
import wave

import numpy as np

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..")

VOWELS = set("अआइईउऊऋएऐओऔािीुूृेैोौंःँ")


def load_wav(path):
    with wave.open(path) as w:
        assert w.getnchannels() == 1, "expected mono"
        sr = w.getframerate()
        n = w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if sr != SR:
        # linear resample — VO is speech, no aliasing concerns at these lengths
        idx = np.linspace(0, len(a) - 1, int(len(a) * SR / sr))
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    return a


def envelope(a, hop=240, win=960):
    n = max(1, (len(a) - win) // hop + 1)
    env = np.array([np.sqrt(np.mean(a[i * hop:i * hop + win] ** 2)) for i in range(n)])
    return env, hop / SR


def syllables(word):
    c = sum(1 for ch in word if ch in VOWELS)
    c += sum(1 for ch in word if ch.isdigit()) * 2
    return max(1, c)


def word_timings(a):
    """Return [(word, start_sec, end_sec)] for one VO clip."""
    env, dt = envelope(a)
    db = 20 * np.log10(env + 1e-7)
    thresh = max(-42.0, np.percentile(db, 92) - 26)
    voiced = db > thresh
    # merge gaps shorter than 80 ms (stop consonants)
    gap = max(1, int(0.08 / dt))
    i = 0
    while i < len(voiced):
        if not voiced[i]:
            j = i
            while j < len(voiced) and not voiced[j]:
                j += 1
            if j - i < gap and i > 0 and j < len(voiced):
                voiced[i:j] = True
            i = j
        else:
            i += 1
    idx = np.nonzero(voiced)[0]
    if len(idx) == 0:
        return [], len(a) / SR
    t0 = idx[0] * dt
    t1 = (idx[-1] + 1) * dt
    return None, t0, t1


def align_words(a, words):
    """Distribute words over the voiced span, snapping joins to nearby energy dips.

    The snap window is a fraction of the local word spacing, not a fixed number
    of seconds: with ~0.15 s function words a fixed +/-0.12 s window makes two
    consecutive boundaries collapse onto the same dip.
    """
    env, dt = envelope(a, hop=120, win=480)
    db = 20 * np.log10(env + 1e-7)
    # smooth lightly so single glottal stops do not win the argmin
    kern = np.ones(3) / 3
    dbs = np.convolve(db, kern, mode="same")
    _, v0, v1 = word_timings(a)
    weights = [syllables(w) for w in words]
    total = sum(weights)
    expect = [v0]
    acc = 0.0
    for wgt in weights[:-1]:
        acc += wgt
        expect.append(v0 + (v1 - v0) * acc / total)
    expect.append(v1)

    bounds = [v0]
    prev = v0
    for i in range(1, len(expect) - 1):
        target = expect[i]
        spacing = min(expect[i] - expect[i - 1], expect[i + 1] - expect[i])
        win = max(0.035, spacing * 0.45)
        lo = int(max(prev + 0.06, target - win) / dt)
        hi = int(min(v1 - 0.06, target + win) / dt)
        if hi - lo >= 2:
            seg = dbs[lo:hi + 1]
            target = (lo + int(np.argmin(seg))) * dt
        target = max(target, prev + 0.06)
        bounds.append(target)
        prev = target
    bounds.append(v1)
    out = []
    for i, w in enumerate(words):
        out.append((w, bounds[i], bounds[i + 1]))
    return out


def build_timing(script, audio_dir):
    """script: {scene_index: text}; writes build/timing.json"""
    out = {}
    for k, text in script.items():
        words = text.split()
        path = os.path.join(audio_dir, f"vo_{int(k):02d}.wav")
        if not os.path.exists(path):
            raise SystemExit(f"missing {path}")
        a = load_wav(path)
        timed = align_words(a, words)
        out[int(k)] = {
            "dur": round(len(a) / SR, 3),
            "words": [[w, round(s, 3), round(e, 3)] for w, s, e in timed],
        }
    p = os.path.join(BASE, "build", "timing.json")
    with open(p, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return p


# ------------------------------------------------------------------ loudness
def _k_weight(x, sr=SR):
    """BS.1770 K-weighting: high-shelf + high-pass, applied in the frequency domain."""
    n = len(x)
    if n == 0:
        return x
    N = 1 << int(math.ceil(math.log2(n + 1)))
    X = np.fft.rfft(x, N)
    f = np.fft.rfftfreq(N, 1 / sr)
    f = np.maximum(f, 1e-6)
    # stage 1: high shelf (+4 dB above ~1.5 kHz)
    shelf = 10 ** (4.0 / 20 * (1 / (1 + (1500 / f) ** 2)))
    # stage 2: high pass (~38 Hz)
    hp = (f / 38.0) ** 2 / np.sqrt(1 + (f / 38.0) ** 4)
    return np.fft.irfft(X * shelf * hp, N)[:n]


def lufs(x):
    y = _k_weight(x)
    block = int(0.4 * SR)
    if len(y) < block:
        return -70.0
    hop = block // 4
    powers = []
    for i in range(0, len(y) - block + 1, hop):
        seg = y[i:i + block]
        powers.append(np.mean(seg ** 2))
    powers = np.array(powers)
    lk = -0.691 + 10 * np.log10(powers + 1e-12)
    gated = powers[lk > -70]
    if len(gated) == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(gated) + 1e-12) - 10
    gated = powers[(lk > -70) & (lk > rel)]
    return float(-0.691 + 10 * np.log10(np.mean(gated) + 1e-12))


def lufs_stereo(l, r, sr=SR):
    """BS.1770 stereo integrated loudness (channel powers summed)."""
    yl = _k_weight(l, sr)
    yr = _k_weight(r, sr)
    block = int(0.4 * sr)
    if len(yl) < block:
        return -70.0
    hop = block // 4
    powers = []
    for i in range(0, len(yl) - block + 1, hop):
        powers.append(np.mean(yl[i:i + block] ** 2) + np.mean(yr[i:i + block] ** 2))
    powers = np.array(powers)
    lk = -0.691 + 10 * np.log10(powers + 1e-12)
    gated = powers[lk > -70]
    if len(gated) == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(gated) + 1e-12) - 10
    gated = powers[(lk > -70) & (lk > rel)]
    return float(-0.691 + 10 * np.log10(np.mean(gated) + 1e-12))


def true_peak(x):
    return float(20 * np.log10(np.max(np.abs(x)) + 1e-9))


def normalize_to(x, target=-14.0, ceiling=-1.0, passes=3):
    y = x.copy()
    gain = 0.0
    for _ in range(passes):
        cur = lufs(y)
        g = target - cur
        gain += g
        y = y * (10 ** (g / 20))
    # soft clip the rare overshoot above ceiling instead of hard clipping
    tp = true_peak(y)
    if tp > ceiling:
        y = np.tanh(y * (1.0 / max(1e-6, 10 ** (tp / 20)))) * (10 ** (ceiling / 20)) * 1.02
    return y, gain


if __name__ == "__main__":
    script = json.load(open(os.path.join(BASE, "script", "vo_lines.json")))
    p = build_timing({int(k): v for k, v in script.items()}, os.path.join(BASE, "build", "audio"))
    print("timing ->", p)
