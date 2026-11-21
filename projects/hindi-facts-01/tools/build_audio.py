"""
Hindi Facts Short — audio build.

Layers, all synthesised here (no sample libraries, nothing to license):
  VO     : the 9 generated clips, placed on the cut grid
  BED    : 120 BPM dark cinematic bed in D minor — kick, sub, hats, pad, ticks
  SFX    : whooshes on whip cuts, impacts on push cuts, a riser into the payoff,
           a clock tick under the HUD
  MIX    : sidechain duck of the bed under the VO, then BS.1770 mastering to
           -14 LUFS integrated with a -1 dBTP ceiling (YouTube's target)

Outputs build/audio/mix.wav (48 kHz stereo) and build/audio/mix.m4a.
"""

import json
import math
import os
import subprocess
import wave

import numpy as np

import audio_lab as AL
from engine import SCENES, DURATION, TRANSITION

SR = 48000
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(BASE, "build", "audio")

BEAT = 0.5          # 120 BPM
BAR = BEAT * 4


def t_axis(dur):
    return np.arange(int(dur * SR)) / SR


def env_ad(n, attack, decay, curve=2.0):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.exp(-np.maximum(0, t - attack) * decay) ** curve
    return a * d


def add(dst, src, at):
    i = int(at * SR)
    if i >= len(dst):
        return
    n = min(len(src), len(dst) - i)
    dst[i:i + n] += src[:n]


def kick(gain=1.0, dur=0.34):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 58 * np.exp(-t * 26) + 38
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * env_ad(n, 0.002, 13)
    click = np.random.default_rng(1).normal(0, 1, n) * env_ad(n, 0.0005, 90) * 0.25
    return (body + click) * gain


def hat(gain=1.0, dur=0.06):
    n = int(dur * SR)
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, n)
    # cheap high-pass: difference of consecutive samples
    noise = np.diff(noise, prepend=0)
    return noise * env_ad(n, 0.0004, 70) * gain


def sub(freq, dur, gain=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    a = np.clip(t / 0.02, 0, 1) * np.exp(-t * 2.2)
    return (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t)) * a * gain


def pad(freqs, dur, gain=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    a = np.minimum(1, t / 0.9) * np.minimum(1, (dur - t) / 1.2).clip(0, 1)
    out = np.zeros(n)
    for i, f in enumerate(freqs):
        det = 1 + (i - len(freqs) / 2) * 0.0016
        out += np.sin(2 * np.pi * f * det * t + i) / (i + 2)
        out += 0.4 * np.sin(2 * np.pi * f * 2 * det * t)
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.17 * t)
    return out * a * lfo * gain


def whoosh(dur=0.42, gain=1.0, up=True):
    n = int(dur * SR)
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, n)
    # moving average band-pass whose centre sweeps
    k = int(0.02 * SR)
    smooth = np.convolve(noise, np.ones(k) / k, mode="same")
    band = noise - smooth
    t = np.linspace(0, 1, n)
    amp = (t ** 2.2) if up else ((1 - t) ** 2.2)
    return band * amp * gain


def impact(gain=1.0):
    dur = 1.1
    n = int(dur * SR)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * (44 * np.exp(-t * 6) + 30) * t) * np.exp(-t * 3.4)
    rng = np.random.default_rng(4)
    air = rng.normal(0, 1, n) * np.exp(-t * 12) * 0.25
    return (boom + air) * gain


def tick(gain=1.0):
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    a = np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 220)
    b = np.sin(2 * np.pi * 620 * t) * np.exp(-t * 160) * 0.6
    return (a + b) * gain


def riser(dur, gain=1.0):
    n = int(dur * SR)
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 1, n)
    k = int(0.006 * SR)
    hp = noise - np.convolve(noise, np.ones(k) / k, mode="same")
    t = np.linspace(0, 1, n)
    amp = t ** 3
    tone = np.sin(2 * np.pi * (200 + 900 * t ** 2) * np.arange(n) / SR) * 0.15
    return (hp * 0.5 + tone) * amp * gain


# ------------------------------------------------------------------ build
def build():
    total = int(DURATION * SR) + SR
    music = np.zeros(total)
    sfx = np.zeros(total)
    vo = np.zeros(total)

    # ---------- VO placement
    timing = json.load(open(os.path.join(BASE, "build", "timing.json")))
    for i, s in enumerate(SCENES, start=1):
        path = os.path.join(OUT, f"vo_{i:02d}.wav")
        a = AL.load_wav(path)
        # trim the tail silence so cuts are tight
        idx = np.nonzero(np.abs(a) > 0.02)[0]
        if len(idx):
            a = a[max(0, idx[0] - int(0.01 * SR)):min(len(a), idx[-1] + int(0.09 * SR))]
        add(vo, a * 1.0, s["vo"])
        # keep the per-scene timing consistent with what was trimmed
        shift = max(0, (idx[0] - int(0.01 * SR))) / SR if len(idx) else 0
        s["vo_trim"] = shift

    # ---------- bed
    chords = [
        (73.42, [146.83, 220.00, 349.23]),   # Dm
        (58.27, [116.54, 174.61, 293.66]),   # Bb
        (87.31, [174.61, 261.63, 349.23]),   # F
        (65.41, [130.81, 196.00, 329.63]),   # C
    ]
    bars = int(math.ceil(DURATION / BAR)) + 1
    for b in range(bars):
        t0 = b * BAR
        root, tones = chords[(b // 2) % len(chords)]
        add(music, sub(root, BAR * 1.02, 0.30), t0)
        add(music, pad(tones, BAR * 1.05, 0.085), t0)
    # drums — half-time in the hook, four-on-floor from the moon shot on
    beat = 0.0
    while beat < DURATION:
        idx = int(beat / BEAT)
        section = 0
        for i, s in enumerate(SCENES):
            if s["t0"] <= beat:
                section = i
        if section == 0:
            if idx % 4 == 0:
                add(music, kick(0.55), beat)
        else:
            add(music, kick(0.55 if idx % 2 else 0.68), beat)
        add(music, hat(0.10 + 0.05 * (idx % 2)), beat + BEAT / 2)
        if section >= 1:
            add(music, hat(0.045), beat + BEAT * 0.25)
        # clock ticks under the HUD tension shots
        if section in (0, 6, 7, 8) and idx % 2 == 0:
            add(sfx, tick(0.075), beat)
        beat += BEAT

    # ---------- SFX on the cut grid
    for i, s in enumerate(SCENES[:-1]):
        cut = s["t1"]
        kind = TRANSITION[i]
        if kind == "whip":
            add(sfx, whoosh(0.40, 0.30, up=True), cut - 0.28)
        elif kind == "push":
            add(sfx, impact(0.42), cut - 0.02)
            add(sfx, whoosh(0.30, 0.18, up=False), cut - 0.26)
        elif kind == "glitch":
            add(sfx, impact(0.55), cut - 0.02)
    # riser into the payoff and into the loop seam
    add(sfx, riser(2.4, 0.30), SCENES[7]["t0"] - 2.4)
    add(sfx, riser(1.4, 0.22), SCENES[8]["t0"] - 1.4)
    add(sfx, impact(0.60), SCENES[8]["t0"])       # loop slam
    for bt in (0.22, 1.05, 1.75):                 # tap-tempo pips with the beat grid
        add(sfx, tick(0.22), bt)

    # ---------- ducking
    win = int(0.05 * SR)
    v_env = np.abs(vo)
    kernel = np.ones(win) / win
    v_env = np.convolve(v_env, kernel, mode="same")
    v_env = np.clip(v_env / (np.percentile(v_env, 99) + 1e-9), 0, 1)
    duck = 1.0 - 0.55 * np.clip(v_env * 2.2, 0, 1)
    music *= duck
    sfx *= 1.0 - 0.35 * np.clip(v_env * 2.2, 0, 1)

    mix = vo * 1.0 + music * 0.85 + sfx * 0.8
    mix = mix[:int(DURATION * SR)]

    # gentle top-end air + mono-safe width: slight stereo widening of the bed
    vo = vo[:len(mix)]
    sfx = sfx[:len(mix)]
    bed_l = (music * 0.85)[:len(mix)]
    bed_r = np.roll(music * 0.85, int(0.004 * SR))[:len(mix)] * 0.98
    left = vo + bed_l + sfx * 0.8
    right = vo + bed_r + sfx * 0.8

    # ---------- master: -14 LUFS integrated, -1 dBTP ceiling
    L, R = left.copy(), right.copy()
    ceil = 10 ** (-1.0 / 20)
    for _ in range(6):
        cur = AL.lufs_stereo(L, R)
        err = -14.0 - cur
        if abs(err) < 0.15:
            break
        L *= 10 ** (err / 20)
        R *= 10 ** (err / 20)
        # transparent soft limiter, only the last ~2 dB gets shaped
        pk = max(np.max(np.abs(L)), np.max(np.abs(R)))
        if pk > ceil:
            L = np.tanh(L / ceil) * ceil
            R = np.tanh(R / ceil) * ceil
        stereo = np.stack([L, R], axis=1)
    pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
    wav_path = os.path.join(OUT, "mix.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    stats = {
        "lufs_integrated": round(AL.lufs_stereo(L, R), 2),
        "true_peak_db": round(20 * np.log10(np.max(np.abs(stereo)) + 1e-9), 2),
        "duration": round(len(L) / SR, 3),
    }
    print(json.dumps(stats))
    json.dump(stats, open(os.path.join(BASE, "build", "audio_stats.json"), "w"), indent=1)
    return wav_path


if __name__ == "__main__":
    p = build()
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    m4a = os.path.join(OUT, "mix.m4a")
    subprocess.run([ff, "-v", "error", "-y", "-i", p, "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", m4a], check=True)
    print("wrote", p, m4a)
