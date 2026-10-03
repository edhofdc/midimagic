#!/usr/bin/env python3
"""Generate a small polyphonic test clip (C-major melody + bass line) as WAV.

Used by tests/smoke_api.py so the smoke test is reproducible without shipping
binary media in the repo.

    .venv/bin/python tests/make_test_audio.py [out.wav]
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100


def voice(freq: float, dur: float, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    y = np.zeros_like(t)
    for i, h in enumerate((1, 0.5, 0.25, 0.12)):
        y += h * np.sin(2 * np.pi * freq * (i + 1) * t)
    env = np.minimum(1, np.arange(len(t)) / (SR * 0.01)) * np.exp(-1.2 * t)
    return amp * y * env / 4


def hz(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/test/melody_stereo.wav")
    out.parent.mkdir(parents=True, exist_ok=True)

    melody = [(60, 0.5), (62, 0.5), (64, 0.5), (65, 0.5),
              (67, 0.5), (69, 0.5), (71, 0.5), (72, 0.75)]
    bass = [(48, 0.5), (52, 0.5), (55, 0.5), (60, 0.5),
            (53, 0.5), (57, 0.5), (60, 0.5), (64, 0.75)]

    buf = np.zeros(int(SR * 0.1))
    for pitch, dur in melody:
        buf = np.concatenate([buf, voice(hz(pitch), dur)])

    mix = buf.copy()
    t0 = 0.0
    for pitch, dur in bass:
        s, e = int(t0 * SR), min(len(mix), int(t0 * SR) + int(dur * SR))
        mix[s:e] += voice(hz(pitch), dur, amp=0.3)[: e - s]
        t0 += dur

    mono = np.clip(mix, -1, 1)
    raw = out.with_suffix(".mono.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mono * 32767 * 0.9).astype("<i2").tobytes())

    # Demucs and the pipeline both expect stereo input
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
         "-ac", "2", "-ar", str(SR), str(out)],
        check=True,
    )
    raw.unlink(missing_ok=True)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
