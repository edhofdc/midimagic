#!/usr/bin/env python3
"""Objective accuracy check: does the transcribed MIDI actually reproduce the recording?

Renders the MIDI to audio with a simple harmonic synth, then compares chroma
(pitch-class energy over time) between the render and the original recording.

  - `chroma_sim`  frame-wise cosine similarity of chroma, time-aligned (0..1)
  - `dtw_sim`     same but after DTW alignment, so timing errors do not hide
                  pitch errors (and vice-versa)
  - `pitch_hist`  cosine similarity of the global pitch-class distribution

A transcription that "nada-nya pas" scores above ~0.75 aligned; a wrong-key or
wrong-chord transcription drops well below 0.5.

Usage: ./.venv/bin/python tests/accuracy_report.py ORIGINAL.wav RENDER.mid
"""
from __future__ import annotations

import sys
from pathlib import Path

import librosa
import numpy as np
import pretty_midi
import soundfile as sf


def render_midi(midi_path: Path, sr: int = 22050) -> np.ndarray:
    """Additive-synthesis render — enough for chroma, no fluidsynth needed."""
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    dur = float(pm.get_end_time()) + 1.0
    out = np.zeros(int(dur * sr), dtype=np.float32)

    # partials of a piano-ish tone; amplitudes fall off like a real string
    partials = [(1, 1.0), (2, 0.5), (3, 0.28), (4, 0.16), (5, 0.09)]

    for inst in pm.instruments:
        for n in inst.notes:
            f0 = pretty_midi.note_number_to_hz(n.pitch)
            if f0 <= 0 or f0 > sr / 2.2:
                continue
            a = int(n.start * sr)
            length = int(max(0.05, (n.end - n.start)) * sr)
            b = min(len(out), a + length)
            if b <= a:
                continue

            t = np.arange(b - a, dtype=np.float32) / sr
            # percussive attack, exponential decay, plus a short release tail
            env = np.exp(-3.2 * t) * (1.0 - np.exp(-260.0 * t))
            tail = int(0.35 * sr)
            ta = b
            tb = min(len(out), b + tail)
            wave = np.zeros(b - a + max(0, tb - ta), dtype=np.float32)
            for mult, amp in partials:
                f = f0 * mult
                if f > sr / 2.2:
                    break
                seg = amp * np.sin(2 * np.pi * f * t)
                wave[: len(seg)] += seg
                if tb > ta:
                    tt = np.arange(tb - ta, dtype=np.float32) / sr
                    dec = np.exp(-3.2 * (t[-1] + tt)) * np.exp(-6.0 * tt)
                    wave[len(seg): len(seg) + len(tt)] += amp * np.sin(
                        2 * np.pi * f * (t[-1] + tt)) * dec
            out[a:tb] += wave[: tb - a] * (n.velocity / 127.0) * 0.09

    peak = float(np.max(np.abs(out))) or 1.0
    return out / peak * 0.9


def chroma_of(y: np.ndarray, sr: int, hop: int = 512) -> np.ndarray:
    c = librosa.feature.chroma_cens(y=y, sr=sr, hop_length=hop)
    c = c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)
    return c


def aligned_sim(a: np.ndarray, b: np.ndarray) -> float:
    n = min(a.shape[1], b.shape[1])
    if n == 0:
        return 0.0
    x, y = a[:, :n], b[:, :n]
    return float(np.mean(np.sum(x * y, axis=0)))


def dtw_sim(a: np.ndarray, b: np.ndarray) -> float:
    try:
        _c, wp = librosa.sequence.dtw(X=a, Y=b, metric="cosine", subseq=False)
    except Exception as exc:                                # noqa: BLE001
        print(f"  (dtw skipped: {type(exc).__name__}: {exc})")
        return float("nan")
    wp = np.array(wp)[::-1]                                  # (i, j) in order
    return float(np.mean(np.sum(a[:, wp[:, 0]] * b[:, wp[:, 1]], axis=0)))


def onset_scores(orig_path: Path, midi_path: Path, sr: int = 22050,
                 tol: float = 0.05) -> tuple[int, int, int, float]:
    """Onset precision/recall vs the recording's own onsets (50 ms tolerance).

    This is the rhythm check: it says whether the transcription fires when the
    performer actually strikes a key, independent of which pitches were chosen.
    """
    y, _ = librosa.load(str(orig_path), sr=sr, mono=True)
    det = librosa.onset.onset_detect(y=y, sr=sr, hop_length=512, units="time",
                                     backtrack=True)
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    onsets = sorted({round(n.start, 3) for i in pm.instruments for n in i.notes})
    if len(det) == 0 or len(onsets) == 0:
        return 0, 0, 0, 0.0

    det = np.asarray(det)
    ons = np.asarray(onsets)

    def matched(a: np.ndarray, b: np.ndarray) -> int:
        if a.size == 0 or b.size == 0:
            return 0
        idx = np.searchsorted(b, a)
        best = np.full(a.shape, np.inf)
        for shift in (-1, 0):
            j = np.clip(idx + shift, 0, b.size - 1)
            best = np.minimum(best, np.abs(a - b[j]))
        return int((best <= tol).sum())

    tp = matched(ons, det)
    fp = len(ons) - tp
    fn = len(det) - matched(det, ons)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return tp, fp, fn, f1


def main() -> int:
    orig_path, midi_path = Path(sys.argv[1]), Path(sys.argv[2])
    sr = 22050

    y_orig, _ = librosa.load(str(orig_path), sr=sr, mono=True)
    y_rend = render_midi(midi_path, sr)
    if y_rend.size < sr:
        print("render failed")
        return 1

    n = min(y_orig.size, y_rend.size)
    y_orig, y_rend = y_orig[:n], y_rend[:n]

    co = chroma_of(y_orig, sr)
    cr = chroma_of(y_rend, sr)

    a_sim = aligned_sim(co, cr)
    d_sim = dtw_sim(co[:, ::4], cr[:, ::4])                  # subsample: DTW is O(n^2)

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes = [n for i in pm.instruments for n in i.notes]

    h_orig = np.zeros(12)
    for p in np.argmax(librosa.feature.chroma_stft(y=y_orig, sr=sr), axis=0):
        h_orig[p] += 1
    h_rend = np.zeros(12)
    for nt in notes:
        h_rend[nt.pitch % 12] += 1
    h_orig /= np.linalg.norm(h_orig) + 1e-9
    h_rend /= np.linalg.norm(h_rend) + 1e-9

    print(f"file            : {orig_path.name}  ({len(y_orig) / sr:.1f}s)")
    print(f"notes           : {len(notes)}")
    print(f"pitch range     : {min(n.pitch for n in notes)}..{max(n.pitch for n in notes)}"
          if notes else "no notes")
    print(f"chroma sim      : {a_sim:.3f}   (time-aligned, 0..1)")
    print(f"chroma sim DTW  : {d_sim:.3f}   (timing-free)")
    print(f"pitch hist sim  : {float(np.sum(h_orig * h_rend)):.3f}")

    tp, fp, fn, f1 = onset_scores(orig_path, midi_path)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    print(f"onset P/R/F1    : {prec:.3f} / {rec:.3f} / {f1:.3f}   "
          f"(tp={tp} fp={fp} fn={fn}, tol=50ms)")

    print(f"tempo in MIDI   : {pm.get_tempo_changes()[1][:1]}")
    print(f"median note len : {np.median([n.end - n.start for n in notes]):.3f}s"
          if notes else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
