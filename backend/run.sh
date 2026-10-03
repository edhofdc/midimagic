#!/usr/bin/env bash
# MidiMagic backend launcher (fast path for local dev / manual runs).
set -euo pipefail
cd "$(dirname "$0")"

export MIDIMAGIC_HOST="${MIDIMAGIC_HOST:-0.0.0.0}"
export MIDIMAGIC_PORT="${MIDIMAGIC_PORT:-8892}"
export MIDIMAGIC_PUBLIC_ORIGIN="${MIDIMAGIC_PUBLIC_ORIGIN:-http://localhost:8891}"

exec .venv/bin/uvicorn app.main:app \
  --host "$MIDIMAGIC_HOST" \
  --port "$MIDIMAGIC_PORT" \
  --log-level "${MIDIMAGIC_LOG_LEVEL:-info}"
