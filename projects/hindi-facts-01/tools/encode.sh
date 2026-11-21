#!/usr/bin/env bash
# Encode the rendered PNG sequence + mastered audio into a YouTube-ready MP4,
# then produce the cover/thumbnail stills from the same render pipeline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PY="${PY:-./run.sh}"
FF=$($PY -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null | tail -1)
[ -x "$FF" ] || { echo "ffmpeg not found (pip install imageio-ffmpeg)"; exit 1; }

OUT=out/hindi-facts-short-1080x1920.mp4
$FF -v error -y -framerate 60 -i build/frames/f%05d.png -i build/audio/mix.wav \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -profile:v high -level 4.2 \
  -x264-params "keyint=120:min-keyint=60:scenecut=0" \
  -c:a aac -b:a 192k -ar 48000 -shortest -movflags +faststart \
  -metadata title="19 Log Har Ghante — Hindi Facts Short" \
  -metadata comment="Produced with Bang Motion (MIT) — Skia rasterizer" \
  "$OUT"
echo "wrote $OUT"
ls -lh "$OUT"
