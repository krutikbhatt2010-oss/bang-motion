#!/usr/bin/env bash
# Full render: frames -> H.264 1080x1920 60fps + muxed audio + thumbnail stills.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PAR="${PAR:-4}"
TOTAL=2868
rm -rf build/frames && mkdir -p build/frames
echo "rendering $TOTAL frames across $PAR workers…"
CH=$(( (TOTAL + PAR - 1) / PAR ))
pids=()
for ((w=0; w<PAR; w++)); do
  s=$((w*CH)); e=$(((w+1)*CH)); [ $e -gt $TOTAL ] && e=$TOTAL
  ( ./run.sh tools/engine.py video $s $e > build/log_$w.txt 2>&1 ) &
  pids+=($!)
done
for pid in "${pids[@]}"; do wait "$pid"; done
echo "frames: $(ls build/frames | wc -l)"
