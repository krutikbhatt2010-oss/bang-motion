#!/usr/bin/env bash
# Bootstrap the render environment for this project.
#
# Why a stub library: the `skia-python` wheel is linked against a system
# OpenGL/EGL that this container does not ship (no libGL.so.1, no libEGL.so.1).
# We never ask Skia for a GPU surface — every surface here is CPU — so two
# no-op symbols are enough to satisfy the dynamic linker:
#     glXGetProcAddress, glXGetCurrentContext
# `run.sh` preloads the stub; nothing else in the pipeline touches GL.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

python3 -m venv /tmp/venv 2>/dev/null || true
/tmp/venv/bin/pip install --quiet -r requirements.txt

if [ ! -f /tmp/libglstub.so ]; then
  cat > /tmp/glstub.c <<'C'
void* glXGetProcAddress(const unsigned char* n){ (void)n; return 0; }
void* glXGetCurrentContext(void){ return 0; }
C
  gcc -shared -fPIC -o /tmp/libglstub.so /tmp/glstub.c
fi

cat > run.sh <<'R'
#!/usr/bin/env bash
set -euo pipefail
export LD_PRELOAD=/tmp/libglstub.so
export LD_LIBRARY_PATH=/tmp
exec /tmp/venv/bin/python "$@"
R
chmod +x run.sh
echo "env ready — try: ./run.sh tools/engine.py stills 1 5 10"
