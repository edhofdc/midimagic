#!/usr/bin/env python3
"""Where exactly does the transcription drift from the recording?

The aggregate chroma score hides the shape of the error. This prints:

  1. per-window chroma similarity — which seconds are wrong
  2. the best global lag — a constant offset means the onsets are systematically
     early/late rather than wrong
  3. per-note spectral support — how many emitted notes have energy at their own
     pitch in the recording at that moment (precision of the note events)
  4. per-note timing offset distribution — is the error a shift or noise

usage: diagnose.py <original_audio> <midi>
"""
from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np
import pretty_midi

SR = 22050
HOP = 512
WIN = 10.0


def render_midi(midi_path: Path, duration: float, sr: int = SR) -> np.ndarray:
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    n = int(duration * sr) + sr
    out = np.zeros(n, dtype=np.float32)
    partials = ((1, 1.0), (2, 0.5), (3, 0.28), (4, 0.16), (5, 0.09), (6, 0.05))
    for inst in pm.instruments:
        for note in inst.notes:
            f0 = 440.0 * 2 ** ((note.pitch - 69) / 12)
            i0, i1 = int(note.start * sr), int(note.end * sr)
            if i1 <= i0:
                continue
            i1 = min(i1, n)
            t = np.arange(i1 - i0, dtype=np.float32) / sr
            env = np.exp(-1.8 * t).astype(np.float32)
            rel = int(0.12 * sr)
            if rel and len(env) > rel:
                env[-rel:] *= np.linspace(1, 0, rel, dtype=np.float32)
            seg = np.zeros_like(t)
            for mult, amp in partials:
                f = f0 * mult
                if f < sr / 2:
                    seg += amp * np.sin(2 * np.pi * f * t).astype(np.float32)
            out[i0:i1] += seg * env
    peak = float(np.max(np.abs(out))) or 1.0
    return out / peak


def chroma(y: np.ndarray, sr: int = SR) -> np.ndarray:
    c = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    return c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)


def cos_cols(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    m = min(a.shape[1], b.shape[1])
    a, b = a[:, :m], b[:, :m]
    return np.einsum("ij,ij->j", a, b) / (
        np.linalg.norm(a, axis=0) * np.linalg.norm(b, axis=0) + 1e-9
    )


def main() -> int:
    orig_p, midi_p = Path(sys.argv[1]), Path(sys.argv[2])
    y, _ = librosa.load(str(orig_p), sr=SR, mono=True)
    dur = len(y) / SR
    print(f"original : {orig_p.name}  ({dur:.1f}s)")

    re_y = render_midi(midi_p, dur)
    oc, rc = chroma(y), chroma(re_y)
    sim = cos_cols(oc, rc)
    frames = sim.shape[0]
    fps = SR / HOP
    print(f"overall chroma sim : {float(np.mean(sim)):.3f}")

    # ---- 1. where is it wrong
    print(f"\nper-{WIN:.0f}s window similarity (worst first):")
    step = int(WIN * fps)
    windows = []
    for s in range(0, frames - step, step):
        windows.append((float(np.mean(sim[s:s + step])), s / fps))
    for sc, t in sorted(windows)[:10]:
        bar = "#" * int(max(0.0, sc) * 30)
        print(f"  {t:6.1f}s  {sc:.3f}  {bar}")
    good = sum(1 for sc, _ in windows if sc >= 0.85)
    print(f"  -> {good}/{len(windows)} windows at or above 0.85")

    # ---- 2. global lag (is the whole thing shifted?)
    N = int(2.0 * fps)
    best, best_lag = -1.0, 0
    for lag in range(-N, N + 1):
        a = oc[:, max(0, lag):frames + min(0, lag)]
        b = rc[:, max(0, -lag):frames - max(0, lag)]
        m = min(a.shape[1], b.shape[1])
        if m < 50:
            continue
        v = float(np.mean(np.einsum("ij,ij->j", a[:, :m], b[:, :m])
                          / (np.linalg.norm(a[:, :m], axis=0)
                             * np.linalg.norm(b[:, :m], axis=0) + 1e-9)))
        if v > best:
            best, best_lag = v, lag
    print(f"\nbest global lag    : {best_lag / fps:+.3f}s  (sim {best:.3f})")

    # ---- 3. spectral support per note
    pm = pretty_midi.PrettyMIDI(str(midi_p))
    notes = [n for i in pm.instruments for n in i.notes]
    print(f"\nnote events        : {len(notes)}")

    # chroma of the ORIGINAL only, and the note's own pitch class
    supported = 0
    weak = []
    frame_pitch = np.zeros_like(oc)
    for note in notes:
        f0, f1 = int(note.start * fps), int(note.end * fps)
        if f1 <= f0:
            f1 = f0 + 1
        f0, f1 = max(0, f0), min(frames, f1)
        if f1 <= f0:
            continue
        pc = note.pitch % 12
        here = oc[pc, f0:f1].mean()
        # what the pitch class looks like elsewhere in the piece
        glob = oc[pc].mean()
        if here >= glob * 0.8:
            supported += 1
        else:
            weak.append((here / (glob + 1e-9), note.start, note.pitch))
    print(f"spectrally supported: {supported}/{len(notes)} = "
          f"{supported / max(1, len(notes)):.3f}")
    if weak:
        weak.sort()
        print("  weakest note events (ratio, time, pitch):")
        for r, t, p in weak[:8]:
            print(f"    {r:.3f}  {t:6.2f}s  midi {p}")

    # ---- 4. timing offsets of the strongest onsets
    onset_o = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, units="time")
    onset_m = np.array(sorted({round(n.start, 3) for n in notes}))
    offs = []
    for t in onset_m:
        if len(onset_o):
            j = int(np.argmin(np.abs(onset_o - t)))
            if abs(onset_o[j] - t) <= 0.25:
                offs.append(t - onset_o[j])
    if offs:
        o = np.array(offs)
        print(f"\nonset offset       : median {np.median(o) * 1000:+.0f} ms  "
              f"mean {o.mean() * 1000:+.0f} ms  p10 {np.percentile(o, 10) * 1000:+.0f}  "
              f"p90 {np.percentile(o, 90) * 1000:+.0f}  (n={len(o)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
