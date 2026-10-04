#!/usr/bin/env python3
"""Debug the key fit: what does the pitch-class histogram actually look like?"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pretty_midi

MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def correlate(h, profile, shift):
    a = np.array([h[(i + shift) % 12] for i in range(12)])
    b = np.array(profile)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def variant(name, hist, expect: str, show: bool = True):
    rows = []
    for tonic in range(12):
        for mode, prof in (("major", MAJOR), ("minor", MINOR)):
            rows.append((correlate(hist, prof, tonic), f"{NAMES[tonic]} {mode}"))
    rows.sort(reverse=True)
    if not show:
        return rows
    win = rows[0][1]
    mark = "OK " if win == expect else "MISS"
    print(f"  {mark} {name:34} -> {win:10} (2nd {rows[1][1]:10} {rows[1][0]:.4f})")
    return rows


def main() -> int:
    pm = pretty_midi.PrettyMIDI(sys.argv[1])
    expect = sys.argv[2] if len(sys.argv) > 2 else ""
    notes = sorted((n for i in pm.instruments for n in i.notes), key=lambda n: n.start)
    end = max(n.end for n in notes)

    print(f"{Path(sys.argv[1]).name}  (expected: {expect or '?'})")

    def hist_of(weight):
        h = np.zeros(12)
        for n in notes:
            h[n.pitch % 12] += weight(n)
        return h

    dur = lambda n: max(0.02, n.end - n.start)

    # (a) duration only
    variant("duration", hist_of(dur), expect)
    # (b) onset count only
    variant("onset count", hist_of(lambda n: 1.0), expect)
    # (c) duration x low-register boost (bass carries the tonality)
    variant("duration x bass boost", hist_of(
        lambda n: max(0.02, n.end - n.start) * (1.0 + max(0.0, (72 - n.pitch)) / 24.0)),
        expect)
    # (d) bass line only: the lowest sounding pitch at each onset
    by_onset: dict[float, int] = {}
    for n in notes:
        k = round(n.start, 3)
        by_onset[k] = min(by_onset.get(k, 127), n.pitch)
    h_d = np.zeros(12)
    for p in by_onset.values():
        h_d[p % 12] += 1.0
    variant("bass line (lowest per onset)", h_d, expect)
    # (e) bottom third of notes
    lo = sorted(notes, key=lambda n: n.pitch)[: max(1, len(notes) // 3)]
    h_e = np.zeros(12)
    for n in lo:
        h_e[n.pitch % 12] += dur(n)
    variant("lowest third of notes", h_e, expect)
    # (f) closing harmony root + thirds
    tail = [n for n in notes if n.start > end - 2.0]
    h_f = np.zeros(12)
    for n in tail:
        h_f[n.pitch % 12] += 1.0
    variant("closing 2s", h_f, expect)
    # (g) duration + closing + bass
    h_g = hist_of(dur)
    for n in tail:
        h_g[n.pitch % 12] += 8.0
    for p in by_onset.values():
        h_g[p % 12] += 1.0
    variant("duration + closing + bass", h_g, expect)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
