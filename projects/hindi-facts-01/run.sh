#!/usr/bin/env bash
# Render env wrapper: the skia wheel is built against a system libGL that this
# container does not ship, so we preload two no-op GL symbols. Harmless (skia
# only touches them if you ask for a GPU surface; we render into CPU surfaces).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_PRELOAD=/tmp/libglstub.so
export LD_LIBRARY_PATH=/tmp
exec /tmp/venv/bin/python "$@"
