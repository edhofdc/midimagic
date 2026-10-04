#!/usr/bin/env python3
"""Side-by-side accuracy for two (or more) transcription engines against a recording.

Same metrics for every engine, measured against the SOURCE audio — not the
pre-processed copy, which already shares the MIDI's timeline and hides offsets:

  notes      number of note events
  chroma     mean frame-wise cosine similarity of the chroma
  windows    how many 10s windows reach 0.85 similarity
  lag        best global lag (0 = the notes sit on the recording's timeline)
  support    fraction of emitted notes with spectral energy at their own pitch
             at that moment — the number that says whether the notes are real

usage: compare_engines.py source.wav label1=out1.mid [label2=out2.mid ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np
import pretty_midi

sys.path.insert(0, str(Path(__file__).parent))
from diagnose import cos_cols, render_midi  # noqa: E402

SR = 22050
HOP = 512
WIN = 10.0


def chroma_matrix(y: np.ndarray, sr: int = SR) -> np.ndarray:
    c = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    return c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)


def best_lag(oc: np.ndarray, rc: np.ndarray, fps: float,
             span_s: float = 2.0) -> tuple[float, float]:
    span = int(span_s * fps)
    frames = oc.shape[1]
    best, arg = -1.0, 0
    for lag in range(-span, span + 1):
        a0, a1 = max(0, lag), frames + min(0, lag)
        b0, b1 = max(0, -lag), frames - max(0, lag)
        m = min(a1 - a0, b1 - b0)
        if m < 40:
            continue
        v = float(np.mean(np.einsum("ij,ij->j", oc[:, a0:a0 + m], rc[:, b0:b0 + m])))
        if v > best:
            best, arg = v, lag
    return arg / fps, best


def onset_prf(src: Path, midi: Path, tol: float = 0.05) -> tuple[float, float, float, int, int, int]:
    """Onset precision/recall/F1 of the MIDI vs the recording's own onsets.

    Both engines are scored against the SAME reference, so even though a simple
    spectral onset detector is a weak absolute reference on dense polyphony, the
    comparison between them is meaningful. Read recall as the ceiling (how much of
    the playing was found) and precision as over-generation.
    """
    import librosa

    y, _ = librosa.load(str(src), sr=SR, mono=True)
    ref = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, units="time")
    pm = pretty_midi.PrettyMIDI(str(midi))
    est = np.array(sorted({round(n.start, 3) for i in pm.instruments
                           if not i.is_drum for n in i.notes}))
    if len(ref) == 0 or len(est) == 0:
        return 0.0, 0.0, 0.0, 0, 0, 0
    used = np.zeros(len(ref), dtype=bool)
    tp = 0
    for t in est:
        j = int(np.argmin(np.abs(ref - t)))
        if abs(ref[j] - t) <= tol and not used[j]:
            used[j] = True
            tp += 1
    fp = len(est) - tp
    fn = len(ref) - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, tp, fp, fn


def evaluate(src: Path, midi: Path) -> dict:
    y, _ = librosa.load(str(src), sr=SR, mono=True)
    dur = len(y) / SR
    oc = chroma_matrix(y)
    rc = chroma_matrix(render_midi(midi, dur))
    sim = cos_cols(oc, rc)
    fps = SR / HOP

    step = int(WIN * fps)
    wins = [float(np.mean(sim[s:s + step])) for s in range(0, sim.shape[0] - step, step)]
    good = sum(1 for w in wins if w >= 0.85)

    pm = pretty_midi.PrettyMIDI(str(midi))
    notes = [n for i in pm.instruments if not i.is_drum for n in i.notes]
    n_frames = sim.shape[0]
    supported = 0
    counted = 0
    for n in notes:
        f0, f1 = int(n.start * fps), int(n.end * fps)
        if f1 <= f0:
            f1 = f0 + 1
        f0, f1 = max(0, f0), min(n_frames, f1)
        if f1 <= f0:
            continue
        counted += 1
        pc = n.pitch % 12
        if oc[pc, f0:f1].mean() >= oc[pc].mean() * 0.8:
            supported += 1

    lag, lag_sim = best_lag(oc, rc, fps)
    prec, rec, f1, tp, fp, fn = onset_prf(src, midi)
    dur_notes = np.array([n.end - n.start for n in notes]) if notes else np.array([0.0])
    return {
        "notes": len(notes),
        "chroma": float(np.mean(sim)),
        "windows": f"{good}/{len(wins)}",
        "lag_ms": int(round(lag * 1000)),
        "lag_sim": lag_sim,
        "support": supported / max(1, counted),
        "onset_p": prec,
        "onset_r": rec,
        "onset_f1": f1,
        "onset_tp": tp,
        "onset_fp": fp,
        "onset_fn": fn,
        "median_note_s": float(np.median(dur_notes)),
        "duration": dur,
        "has_pedal": any(cc.number == 64 for i in pm.instruments
                         for cc in i.control_changes),
    }


def main() -> int:
    src = Path(sys.argv[1])
    rows = []
    for spec in sys.argv[2:]:
        label, _, path = spec.partition("=")
        m = Path(path)
        if not m.exists():
            print(f"{label}: MISSING {m}")
            continue
        rows.append((label, evaluate(src, m)))

    if rows:
        print(f"source: {src.name}  ({rows[0][1]['duration']:.1f}s)\n")
    hdr = (f"{'engine':15} {'notes':>6} {'chroma':>7} {'win>=.85':>9} {'lag ms':>7} "
           f"{'support':>8} {'onP':>6} {'onR':>6} {'onF1':>6} {'med note':>9} {'pedal':>6}")
    print(hdr)
    print("-" * len(hdr))
    for label, r in rows:
        print(f"{label:15} {r['notes']:6} {r['chroma']:7.3f} {r['windows']:>9} "
              f"{r['lag_ms']:7} {r['support'] * 100:7.1f}% {r['onset_p']:6.3f} "
              f"{r['onset_r']:6.3f} {r['onset_f1']:6.3f} {r['median_note_s']:8.3f}s "
              f"{'yes' if r['has_pedal'] else 'no':>6}")
    print("\nonset detail (tp/fp/fn):")
    for label, r in rows:
        print(f"  {label:15} {r['onset_tp']}/{r['onset_fp']}/{r['onset_fn']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
