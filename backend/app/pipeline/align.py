"""Self-alignment: make the transcription sit exactly on the recording's timeline.

Every timestamp the model emits is relative to whatever audio it was handed. Any
upstream edit that changes the length (trimming silence, a stem separator that
pads, a resample) shifts the whole transcription, and nothing downstream notices —
the notes, the score and the pedal all stay internally consistent while quietly
drifting away from the recording the user is comparing against.

So measure it: build a chroma matrix straight from the MIDI note events, build one
from the source audio, sweep the lag that best aligns them, and shift the MIDI by
the negative of it. Costs a couple of seconds on a 3-minute track and removes the
entire class of drift bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pretty_midi

SR = 22050
HOP = 512
MAX_LAG = 4.0
# beyond this the "lag" is far more likely to be a bad chroma match than a real offset
APPLY_THRESHOLD = 0.040


def _chroma_of_audio(path: Path, sr: int = SR) -> np.ndarray:
    import librosa

    y, _ = librosa.load(str(path), sr=sr, mono=True)
    if y.size == 0:
        return np.zeros((12, 0))
    c = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    return c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)


def _chroma_of_midi(pm: pretty_midi.PrettyMIDI, frames: int, sr: int = SR) -> np.ndarray:
    """Chroma built directly from note events — no audio rendering needed."""
    fps = sr / HOP
    m = np.zeros((12, frames), dtype=np.float64)
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            f0 = max(0, int(round(n.start * fps)))
            f1 = min(frames, int(round(n.end * fps)))
            if f1 <= f0:
                f1 = min(frames, f0 + 1)
            if f1 <= f0:
                continue
            m[n.pitch % 12, f0:f1] += 1.0
    return m / (np.linalg.norm(m, axis=0, keepdims=True) + 1e-9)


def estimate_lag(src_wav: Path, midi_path: Path,
                 max_lag: float = MAX_LAG) -> tuple[float, float]:
    """Return (lag_seconds, similarity). Positive lag = MIDI sits late vs the audio."""
    oc = _chroma_of_audio(src_wav)
    if oc.shape[1] == 0:
        return 0.0, 0.0
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    mc = _chroma_of_midi(pm, oc.shape[1])
    fps = SR / HOP
    span = int(max_lag * fps)

    best_sim, best_lag = -1.0, 0
    frames = oc.shape[1]
    for lag in range(-span, span + 1):
        # shifting the MIDI by `lag` means comparing oc[:, lag:] with mc[:, :-lag]
        a0, a1 = max(0, lag), frames + min(0, lag)
        b0, b1 = max(0, -lag), frames - max(0, lag)
        m = min(a1 - a0, b1 - b0)
        if m < int(4 * fps):
            continue
        a = oc[:, a0:a0 + m]
        b = mc[:, b0:b0 + m]
        sim = float(np.mean(np.einsum("ij,ij->j", a, b)))
        if sim > best_sim:
            best_sim, best_lag = sim, lag
    return best_lag / fps, best_sim


def apply_shift(midi_path: Path, out_path: Path, shift: float) -> Path:
    """Move every event in the MIDI by `shift` seconds."""
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    for inst in pm.instruments:
        for n in inst.notes:
            n.start = max(0.0, n.start + shift)
            n.end = max(n.start + 0.01, n.end + shift)
        for cc in inst.control_changes:
            cc.time = max(0.0, cc.time + shift)
    pm.write(str(out_path))
    return out_path


def align(src_wav: Path, midi_path: Path, log=None, max_lag: float = MAX_LAG,
          threshold: float = APPLY_THRESHOLD) -> dict:
    """Measure and correct the offset in place. Returns a summary dict."""
    lag, sim = estimate_lag(src_wav, midi_path, max_lag=max_lag)
    info = {"lag_seconds": lag, "similarity": sim, "applied": False}
    if abs(lag) < threshold:
        if log:
            log("finalizing",
                f"alignment: {lag * 1000:+.0f} ms (sim {sim:.3f}) — tidak perlu digeser")
        return info
    tmp = midi_path.with_suffix(".shifted.mid")
    apply_shift(midi_path, tmp, -lag)
    tmp.replace(midi_path)
    info["applied"] = True
    if log:
        log("finalizing",
            f"alignment: MIDI bergeser {lag * 1000:+.0f} ms (sim {sim:.3f}) → dikoreksi")
    return info


def main() -> int:
    src, mdir = Path(sys.argv[1]), Path(sys.argv[2])
    lag, sim = estimate_lag(src, mdir)
    print(f"lag {lag * 1000:+.0f} ms   sim {sim:.3f}")
    if len(sys.argv) > 3 and sys.argv[3] == "--apply":
        apply_shift(mdir, mdir, -lag)
        print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
