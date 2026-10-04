#!/usr/bin/env python3
"""Inspect the gap-energy ratios used for pedal inference (tuning aid)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pretty_midi  # noqa: E402
import librosa  # noqa: E402

from app.pipeline import sustain  # noqa: E402


def main() -> int:
    audio, midi = Path(sys.argv[1]), Path(sys.argv[2])
    pm = pretty_midi.PrettyMIDI(str(midi))
    notes = sorted((n for i in pm.instruments for n in i.notes), key=lambda n: (n.start, n.pitch))
    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    hop = 512
    fd = hop / sr
    rms = librosa.feature.rms(y=y, hop_length=hop, frame_length=2048)[0]
    nf = rms.shape[0]

    def band(t0, t1):
        a, b = max(0, int(round(t0 / fd))), min(nf, int(round(t1 / fd)))
        return float(np.percentile(rms[a:b], 75)) if b > a else 0.0

    starts = sorted({round(n.start, 4) for n in notes})
    level = {}
    for inst in pm.instruments:
        for n in inst.notes:
            k = round(n.start, 4)
            a = n.start + min(0.05, (n.end - n.start) * 0.3)
            level[k] = max(level.get(k, 0.0), band(a, n.end))

    ratios, gaps = [], []
    for i in range(len(starts) - 1):
        cur, nxt = starts[i], starts[i + 1]
        end = sustain._note_end_at(notes, cur)
        gap = nxt - end
        if gap <= sustain.MIN_GAP:
            continue
        lv = level.get(cur, 0.0)
        if lv <= 1e-7:
            continue
        g = band(end + gap * 0.15, nxt - gap * 0.15)
        ratios.append(g / lv)
        gaps.append(gap)

    r = np.array(ratios)
    print(f"gaps analysed : {len(r)}")
    print(f"gap duration  : median {np.median(gaps):.3f}s  p90 {np.percentile(gaps, 90):.3f}s")
    for p in (10, 25, 50, 75, 90, 95):
        print(f"  p{p:<3} ratio {np.percentile(r, p):.4f}")
    for thr in (0.06, 0.12, 0.22, 0.35, 0.5):
        print(f"  thr {thr:.2f} → {float((r >= thr).mean()) * 100:5.1f}% gaps classed as pedalled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
