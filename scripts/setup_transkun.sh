#!/usr/bin/env bash
# Install the transkun transcription engine into its own venv.
#
# Transkun is a piano specialist (event-based neural semi-CRF, MIT, Yujia Yan)
# and is now the default engine. It is kept in a SEPARATE venv on purpose: its
# dependency set (mir_eval, ncls, moduleconf, pydub, soxr, audioop-lts) does not
# overlap with Demucs/basic-pitch, and a transkun install must never be able to
# break the environment that already works. The backend calls it as a subprocess.
#
# Two Python 3.13 gotchas this script handles:
#   * pydub imports `audioop`, which PEP 594 REMOVED from the stdlib in 3.13.
#     `audioop-lts` is the backport that restores it. Without it transkun dies
#     with "No module named 'pyaudioop'" the moment it tries to read audio.
#   * `mir_eval` is imported by the model module itself (via Evaluation.py), so
#     it is required at inference time, not just for training metrics.
#
# The heavier training-only deps (seaborn, tensorboard, torch-optimizer, sox)
# are deliberately NOT installed — nothing in the transcription path imports them.
#
# usage: bash scripts/setup_transkun.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$HERE/backend/.venv-transkun"

if [ -x "$VENV/bin/python" ]; then
  echo "transkun venv already exists: $VENV"
else
  echo "==> creating $VENV"
  python3 -m venv "$VENV"
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "==> pip"
"$PIP" install -q --upgrade pip

echo "==> torch + torchaudio (CPU wheels, ~200 MB)"
"$PIP" install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "==> transkun (no-deps) + the runtime deps it actually needs"
"$PIP" install -q --no-deps transkun
"$PIP" install -q ncls moduleconf soxr pydub tqdm pretty_midi scipy numpy soundfile mir_eval audioop-lts

echo "==> verify"
"$PY" - <<'EOF'
import audioop   # noqa: F401  (provided by audioop-lts)
import pydub     # noqa: F401
import torch
import transkun   # noqa: F401
print("ok — torch", torch.__version__, "/ transkun importable")
EOF

echo
echo "done. The backend picks it up automatically:"
echo "  curl -s http://127.0.0.1:8892/api/health | grep -o '\"transcription\": \"[^\"]*\"'"
echo "Override the path with MIDIMAGIC_TRANSKUN_PYTHON, or disable with MIDIMAGIC_TRANSKUN=off."
