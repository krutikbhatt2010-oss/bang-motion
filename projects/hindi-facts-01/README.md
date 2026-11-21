# Hindi Facts Short — "19 लोग हर घंटे" (19 people every hour)

A complete YouTube Shorts production built on top of this repository's
**Bang Motion** skill: 1080×1920, 60 fps, 47.8 s, Hindi VO, burned-in
word-synced Devanagari captions, a synthesised cinematic score, a high-CTR
cover, and a launch kit.

**Deliverables are in `out/`:**
`hindi-facts-short-1080x1920.mp4` · `cover-a-do-sach.jpg` · `cover-b-19-only.jpg` ·
`hindi-captions.srt`

---

## 1. Repo audit — what Bang Motion gave us, and what it could not

| Found in the repo | How this project used it |
|---|---|
| `SKILL.md` (v1.19.0) — 8 structural "this is a PPT" rules | Applied literally: one continuous world, a camera rig that always moves, one move per VO beat, a running clock HUD that survives every cut, and the hook's road returning in the payoff. See §3 |
| `assets/starter-explainer-panggung.html`, `references/kartun-panggung.md` | Source of the flat-vector stage language, the 1.08–1.95 camera-zoom floor, and the cut-vs-continuous rule |
| `references/opener-konsep.md`, `techniques.md` | Menu of transitions (whip-pan, push-through, glitch) and the "no fade+scale-bump on every cut" constraint |
| `scripts/export-frames.mjs` + `snap.mjs` | The **frame-by-frame export contract** reused verbatim: `window.OPENER.DURATION`, deterministic `seek(t)`, screenshot each frame, encode with ffmpeg. No dropped frames because nothing is recorded in real time |
| `scripts/serve.py`, `scripts/vo-pauses.html` | Not needed: no local ES modules, and VO boundaries were detected programmatically instead of by hand |
| `assets/fonts` | **Missing** — the repo depends on Google Fonts CDN. See the fix below |

### The setup fix (why this project has its own rasteriser)

This sandbox has **no headless browser** (no Chromium/Playwright, and the
`@sparticuz/chromium` binary needs glibc libs and `libnspr4` that `apt` cannot
fetch here), and **no ffmpeg binary**. Bang Motion's stated prerequisite —
"just a browser" — cannot be met, and rendering 2,868 frames through
`page.screenshot()` would have been slow to iterate on anyway.

So `tools/` reproduces the same contract with a CPU rasteriser:

| Bang Motion (browser) | This pipeline | Same outcome |
|---|---|---|
| GSAP timeline + `seek(t)` | `engine.frame(t)` — pure function of time | deterministic, resumable, parallelisable |
| Three.js / CSS gradients | Skia gradients, shaders, blur masks | identical look, no GPU |
| DOM text + browser shaping | **HarfBuzz shaping → Skia paths** (`textkit.py`) | correct Devanagari conjuncts, matras, ₹ |
| `page.screenshot()` | Skia surface → PNG | lossless frames |
| ffmpeg CLI | `imageio-ffmpeg` binary (pip) | x264 encode |

Dependencies are pinned in `requirements.txt`; `tools/setup_render_env.sh`
documents the one odd bit (a `libGL` stub preload for the `skia-python` wheel,
which links against a system OpenGL that this container lacks).

### Type

No Google Fonts at render time — the fonts are vendored and **subset to what
the video needs** (424 KB total):

- `NotoDeva900/800.ttf` — Devanagari Black / ExtraBold (headlines, captions)
- `NotoDevaLatin900.ttf` — Latin digits, `%`, `:` (Devanagari-only faces have no numerals)
- `ArchivoBlack.ttf` — the "impact" Latin numeral

Both are SIL OFL / Apache, so a Short made with them can be monetised.

---

## 2. Why this topic

The brief asked for Hindi facts using the user's repositories. The user's
public repos are largely mirrors of upstream AI-video projects, so the honest
move was to use the **one repo they own and that this session is built on**
(`bang-motion`) as the production engine, and to make the video about a fact
pattern that actually performs in Hindi Shorts: *national pride + civic shock*.

**Verified facts used (nothing invented):**

| Claim in the video | Source |
|---|---|
| 19 road deaths and 53 crashes **every hour** in India (1,68,491 deaths, 4.61 lakh crashes in 2022) | MoRTH, *Road Accidents in India 2022* |
| India = first country to land near the lunar south pole, 23 Aug 2023 | ISRO / Chandrayaan-3 |
| Mangalyaan = first country to reach Mars on its **first** attempt (24 Sep 2014), ~₹450 crore, cheaper than the film *Gravity* | ISRO; widely reported mission cost |
| 2.3 crore passengers/day on Indian Railways — roughly the population of Australia | Indian Railways |
| 1.55 lakh post offices — world's largest network; Hikkim (4,440 m) is the world's highest | India Post / Guinness |

---

## 3. How the Bang Motion rules were satisfied (mechanically checkable)

| Rule | Evidence in `tools/engine.py` |
|---|---|
| Not a slide deck | `SCENES` are one continuous world; every cut is a **camera move or state change** (`whip`, `push`, `glitch`), never an opacity fade between `<section>`s |
| A subject that persists | the ticking clock HUD (`hud()`) is drawn in **every** shot; the night road from the hook returns in `scene_turn` and the payoff |
| One camera move per beat | `camera_from()` keyframe tables, 0.5 s grid, zoom never below 1.02 |
| Text lives in the scene, max two levels | headlines are part of the composition; captions are UI in the safe box; no eyebrow + title + body stacks |
| No Ken Burns as the only motion | 9 distinct motion languages: rushing lane dashes, falling rain, lander descent + dust ring, drawn transfer arc, rolling counters, growing bars, node pop-in, headlight bloom, reticle push |
| Background motion language | grain (6-frame loop), scanlines, vignette, radial glows — all per-frame, not a static PNG |

`engine.py` also enforces two things the skill only advises:

- **The safe zone is computed, not eyeballed** — captions are drawn *after* the
  camera transform is popped, so a push-in can never shove a caption off screen
  or under the Shorts UI.
- **No dead caption gap** — a caption is visible for 100 % of its VO span
  (`build_caption_lines` groups ≤3 words / ≤22 chars; asserted with a script).

---

## 4. Pipeline (reproducible)

```bash
# 0. environment
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r requirements.txt
bash tools/setup_render_env.sh          # builds the libGL stub, writes run.sh

# 1. voiceover (9 clips, generated with the selected voice)
#    -> build/audio/vo_01..09.{mp3,wav}

# 2. word timings from the VO energy envelope
./run.sh tools/audio_lab.py             # -> build/timing.json

# 3. music + SFX + ducking + LUFS master
./run.sh tools/build_audio.py           # -> build/audio/mix.{wav,m4a}  (-14.0 LUFS)

# 4. frames (2868 = 47.8 s @ 60 fps, rendered 3–4 processes in parallel)
./tools/render.sh                       # -> build/frames/f00000..f02867.png

# 5. encode
./tools/encode.sh                       # -> out/hindi-facts-short-1080x1920.mp4

# 6. cover
./run.sh tools/thumbnail.py             # -> out/cover-a-*.png/.jpg, cover-b-*.jpg
```

**Timings on 4 CPU cores:** frames ≈ 10–11 min, encode ≈ 2.5 min.

### Audio design (`tools/build_audio.py`)

Everything is synthesised — no samples, nothing to license:

- 120 BPM bed in D minor (Dm → B♭ → F → C), kick + sub + detuned pad + hats
- SFX on the cut grid: whoosh (band-swept noise), impact (44 Hz boom), riser,
  clock tick; three **tap-tempo pips** at 0.22 / 1.05 / 1.75 s so the music
  agrees with the VO instead of fighting it
- Sidechain duck: music −5.5 dB, SFX −3.5 dB under the voice
- Master: BS.1770-4 integrated loudness to **−14.0 LUFS**, soft-limited to
  **−1.9 dBTP** (YouTube reference). Measured with the same meter that set it.

### Caption design (`tools/textkit.py`)

HarfBuzz does the full Devanagari pipeline (reordering, half forms, matra
placement), then glyph ids are drawn as Skia paths — so `प्रत्येक`, `क्ष`, `ज्ञ`
and the `₹` glyph render exactly as a browser would, with no tofu and no
detached matras. Word timings come from the VO envelope: voiced regions are
detected, words distributed by syllable weight, and each boundary snapped to
the nearest local energy dip (window scales with local word spacing, so short
function words don't collapse onto one another).

---

## 5. Files

```
projects/hindi-facts-01/
├── out/                       deliverables (video 16 MB, 2 covers, SRT)
├── script/
│   ├── vo_lines.json          the 9 VO lines as spoken
│   └── production-table.md    shot-by-shot / beat-by-beat table
├── docs/viral-seo-kit.md      titles, description, tags, pinned comment,
│                              upload settings, 60-min checklist, thumbnail psychology
├── tools/
│   ├── textkit.py             HarfBuzz → Skia text engine
│   ├── engine.py              the timeline: cameras, scenes, captions, grade
│   ├── audio_lab.py           word timing + BS.1770 loudness meter
│   ├── build_audio.py         score, SFX, ducking, master
│   ├── thumbnail.py           two cover concepts
│   ├── render.sh / encode.sh  parallel frames + x264
│   └── setup_render_env.sh    render env bootstrap
├── assets/fonts/              vendored subsets
└── requirements.txt
```

`build/` (1.3 GB of intermediate PNGs) is git-ignored; `out/` is kept so the
deliverables can be downloaded without re-rendering.

---

## 6. Known limitations (stated, not hidden)

- **No photon-level realism.** The brief asked for hyper-realistic visuals; with
  no image-generation or browser tool in this sandbox, the Short is built as
  **graphic 2D motion design** (flat vector + light) rather than photoreal. It
  is internally consistent and reads as intentional, but it is not live-action
  imagery. Swapping in generated stills is a drop-in change in `engine.py`
  (`img()` already composites images into any scene).
- **No browser render path was exercised**, so `scripts/export-frames.mjs` is
  untouched; the pipeline is parallel but not GPU-accelerated.
- **Voice**: generated by the session TTS voice that was selected in the
  Phase-3 audition. It is synthetic-sounding on long vowel clusters;
  a human-recorded read would raise retention further.
