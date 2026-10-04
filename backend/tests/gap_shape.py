#!/usr/bin/env python3
"""Look at what actually happens in the inter-note gaps of a recording.

A pedalled piano tail decays smoothly from the note's level; a sustained
accompaniment sits at a steady level; a damped note drops to the track floor
within ~150 ms. Printing the normalised decay curve tells us which we have.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import librosa  # noqa: E402
import numpy as np  # noqa: E402
import pretty_midi  # noqa: E402
from app.pipeline import sustain  # noqa: E402


def db(x: float, ref: float) -> float:
    return 20 * np.log10(max(x, 1e-9) / max(ref, 1e-9))


def main() -> int:
    audio, midi = Path(sys.argv[1]), Path(sys.argv[2])
    pm = pretty_midi.PrettyMIDI(str(midi))
    notes = sorted((n for i in pm.instruments for n in i.notes), key=lambda n: n.start)
    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    hop = 512
    fd = hop / sr
    rms = librosa.feature.rms(y=y, hop_length=hop, frame_length=2048)[0]
    nf = rms.shape[0]

    def fr(t):
        return int(round(t / fd))

    floor = float(np.percentile(rms, 5))
    loud = float(np.percentile(rms, 95))
    print(f"track rms: floor(p5) {db(floor, loud):+.1f} dB rel p95   "
          f"median {db(float(np.median(rms)), loud):+.1f} dB")

    onsets = sorted({round(n.start, 4) for n in notes})
    ends = {}
    for n in notes:
        k = round(n.start, 4)
        ends[k] = max(ends.get(k, 0.0), n.end)

    gaps = []
    for i in range(len(onsets) - 1):
        g = onsets[i + 1] - ends[onsets[i]]
        if g > sustain.MIN_GAP:
            gaps.append((onsets[i], ends[onsets[i]], onsets[i + 1], g))
    print(f"gaps > {sustain.MIN_GAP}s : {len(gaps)}")

    # decay shape inside each gap, relative to the preceding note's peak
    shapes = []
    for start, end, nxt, g in gaps:
        a, b = fr(end), fr(nxt)
        if b - a < 2:
            continue
        seg = rms[a:b]
        peak = float(np.percentile(rms[max(0, fr(start)):max(1, fr(end))], 90)) or 1e-9
        curve = [db(float(v), peak) for v in np.percentile(
            seg, [10, 25, 50, 75, 90])]
        shapes.append((g, curve, db(float(seg.mean()), peak),
                       db(float(seg.min()), peak)))

    if not shapes:
        print("no analysable gaps")
        return 0

    # bucket by gap length
    for lo, hi in ((0.03, 0.10), (0.10, 0.25), (0.25, 0.60), (0.60, 5.0)):
        bucket = [s for s in shapes if lo <= s[0] < hi]
        if not bucket:
            continue
        mean_c = np.mean([s[1] for s in bucket], axis=0)
        mins = np.mean([s[3] for s in bucket])
        print(f"gap {lo:.2f}-{hi:.2f}s  n={len(bucket):4d}  "
              f"decay[p10,p25,p50,p75,p90] rel note = "
              + " ".join(f"{v:6.1f}" for v in mean_c)
              + f"   min {mins:6.1f} dB")

    # how far above the track floor does a gap sit?
    rel = [db(float(np.percentile(rms[fr(e):fr(n)], 75)), floor)
           for _, e, n, _ in gaps if fr(n) > fr(e)]
    if rel:
        r = np.array(rel)
        print("gap level above track floor (dB): "
              + " ".join(f"p{p}={np.percentile(r, p):.0f}" for p in (10, 25, 50, 75, 90)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
