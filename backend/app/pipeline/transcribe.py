"""Stage 3 — audio to MIDI transcription.

Primary engine: Spotify `basic-pitch` (polyphonic, AMT).
Fallback engine: `librosa.pyin` monophonic melody tracker (always available).

Accuracy notes
--------------
Raw uploads and YouTube rips vary wildly in loudness and carry rumble below the
piano range; both make the model hallucinate notes. Every input is therefore
peak-normalised and band-limited before it reaches the model. Percussive
material (drum hits) is the other big source of ghost notes, so harmonic/
percussive separation is applied by default — Demucs stems do this better, but
they cost minutes, and this costs seconds.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np
import pretty_midi

from .. import config

Log = Callable[[str, str], None]

# Accuracy presets: (onset_threshold, frame_threshold, min_note_length,
#                    min_frequency, max_frequency)
#
# Lower onset threshold = more sensitive (catches quiet notes, also more junk).
# Higher frame threshold = a note must be sustained more confidently to count.
PRESETS: dict[str, dict] = {
    "fast": {
        "onset_threshold": 0.60, "frame_threshold": 0.35, "min_note_length": 0.090,
        "min_frequency": 55.0, "max_frequency": 3520.0,
        "suppress_percussion": False,
    },
    "balanced": {
        "onset_threshold": 0.50, "frame_threshold": 0.30, "min_note_length": 0.058,
        "min_frequency": 41.2, "max_frequency": 4186.0,
        "suppress_percussion": True,
    },
    "precise": {
        "onset_threshold": 0.38, "frame_threshold": 0.22, "min_note_length": 0.042,
        "min_frequency": 32.7, "max_frequency": 4978.0,
        "suppress_percussion": True,
    },
}

DEFAULT_PRESET = "balanced"


class TranscribeError(RuntimeError):
    pass


def resolve_options(opts: dict) -> dict:
    """Merge a preset with any explicit per-job overrides."""
    name = str(opts.get("accuracy") or DEFAULT_PRESET).lower()
    merged = dict(PRESETS.get(name) or PRESETS[DEFAULT_PRESET])
    for key in ("onset_threshold", "frame_threshold", "min_note_length",
                "min_frequency", "max_frequency"):
        if opts.get(key) is not None:
            try:
                merged[key] = float(opts[key])
            except (TypeError, ValueError):
                pass
    for key in ("suppress_percussion",):
        if opts.get(key) is not None:
            merged[key] = str(opts[key]).lower() in ("1", "true", "yes", "on")
    merged["preset"] = name if name in PRESETS else DEFAULT_PRESET
    return merged


def engine_available() -> str:
    """Report which transcription engine will be used."""
    exe = _basic_pitch_bin()
    if exe:
        try:
            r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                return "basic-pitch"
        except Exception:
            pass
    if importlib.util.find_spec("librosa"):
        return "librosa-pyin"
    return "none"


def _basic_pitch_bin() -> str | None:
    cand = config.BASE_DIR / ".venv" / "bin" / "basic-pitch"
    if cand.exists():
        return str(cand)
    return shutil.which("basic-pitch")


# --------------------------------------------------------------------- prepare

def prepare(src_wav: Path, dst_wav: Path, opts: dict, log: Log) -> Path:
    """Normalise + band-limit (+ optionally de-percuss) the audio for the model."""
    try:
        import librosa
        import soundfile as sf
    except ImportError:                                     # pragma: no cover
        return src_wav

    try:
        y, sr = librosa.load(str(src_wav), sr=config.ANALYSIS_SR, mono=True)
        if y.size == 0:
            return src_wav

        before = y.shape[0]
        # drop digital silence
        y, _ = librosa.effects.trim(y, top_db=45)
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak > 1e-6:
            y = (y / peak) * 0.92                       # peak normalise

        y = _bandlimit(y, sr, float(opts.get("min_frequency", 41.2)),
                       float(opts.get("max_frequency", 4186.0)))

        if opts.get("suppress_percussion"):
            left = librosa.effects.hpss(y, margin=(1.0, 5.0))
            y = left[0]                                  # harmonic only

        if y.size < sr:                                  # <1s of content left
            y, sr = librosa.load(str(src_wav), sr=config.ANALYSIS_SR, mono=True)

        sf.write(str(dst_wav), y.astype(np.float32), sr, subtype="PCM_16")
        log("transcribing",
            f"pra-proses: normalisasi + band-limit {opts.get('min_frequency'):.0f}-"
            f"{opts.get('max_frequency'):.0f} Hz"
            + (" + buang perkusi" if opts.get("suppress_percussion") else "")
            + f" ({before / sr:.1f}s → {y.shape[0] / sr:.1f}s)")
        return dst_wav
    except Exception as exc:                                # noqa: BLE001
        log("transcribing", f"pra-proses dilewati ({exc})")
        return src_wav


def _bandlimit(y: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt

    nyq = sr / 2.0
    lo = max(20.0, min(low, nyq * 0.5)) / nyq
    hi = max(lo + 0.01, min(high, nyq * 0.95)) / nyq
    sos = butter(4, [lo, hi], btype="bandpass", output="sos")
    out = sosfiltfilt(sos, y).astype(np.float32)
    return out if out.size else y


# ------------------------------------------------------------------ transcribe

def transcribe(src_wav: Path, out_midi: Path, engine: str, opts: dict, log: Log) -> Path:
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    if engine == "basic-pitch":
        try:
            return _run_basic_pitch(src_wav, out_midi, opts, log)
        except TranscribeError as exc:
            log("transcribing", f"basic-pitch gagal → fallback pyin: {exc}")
            engine = "librosa-pyin"
    if engine == "librosa-pyin":
        return _run_pyin(src_wav, out_midi, float(opts.get("min_note_length", 0.06)), log)
    raise TranscribeError(f"engine tidak dikenal / tidak tersedia: {engine}")


def _run_basic_pitch(src_wav: Path, out_midi: Path, opts: dict, log: Log) -> Path:
    exe = _basic_pitch_bin()
    if not exe:
        raise TranscribeError("basic-pitch binary tidak ditemukan")
    work = out_midi.parent / "_bp"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    log("transcribing",
        f"basic-pitch [{opts.get('preset')}]: onset={opts['onset_threshold']:.2f} "
        f"frame={opts['frame_threshold']:.2f} minlen={opts['min_note_length']:.3f}s")
    cmd = [
        exe, str(work), str(src_wav),
        "--onset-threshold", str(opts["onset_threshold"]),
        "--frame-threshold", str(opts["frame_threshold"]),
        "--minimum-note-length", str(opts["min_note_length"]),
        "--minimum-frequency", str(opts["min_frequency"]),
        "--maximum-frequency", str(opts["max_frequency"]),
        "--no-melodia",          # melodia is the slow legacy path
        "--save-midi",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    produced = sorted(work.glob("*.mid")) + sorted(work.glob("*.midi"))
    if r.returncode != 0 and not produced:
        raise TranscribeError(f"basic-pitch exit {r.returncode}: {(r.stderr or r.stdout)[-400:]}")
    if not produced:
        raise TranscribeError("basic-pitch tidak menghasilkan file MIDI")
    shutil.move(str(produced[0]), str(out_midi))
    shutil.rmtree(work, ignore_errors=True)
    return out_midi


def _run_pyin(src_wav: Path, out_midi: Path, min_note_len: float, log: Log) -> Path:
    """Monophonic fallback: f0 tracking → note segmentation → pretty_midi."""
    import librosa

    log("transcribing", "pyin: melacak melodi monofonik…")
    y, sr = librosa.load(str(src_wav), sr=22050, mono=True)
    if y.size == 0:
        raise TranscribeError("audio kosong")

    hop = 512
    f0, voiced, prob = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
        sr=sr, hop_length=hop, frame_length=2048, fill_na=np.nan,
    )

    times = librosa.times_like(f0, sr=sr, hop_length=hop)
    conf = np.nan_to_num(prob, nan=0.0)
    active = voiced & np.isfinite(f0) & (conf > 0.25)

    notes: list[pretty_midi.Note] = []
    vel_base = 84
    i = 0
    n = len(active)
    frame_dur = hop / sr
    while i < n:
        if not active[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and active[j + 1]:
            j += 1
        dur = (j - i + 1) * frame_dur
        if dur >= min_note_len:
            midi_pitch = int(round(librosa.hz_to_midi(float(np.nanmedian(f0[i:j + 1])))))
            if 21 <= midi_pitch <= 108:
                amp = float(np.mean(conf[i:j + 1]))
                vel = int(np.clip(vel_base * (0.55 + 0.55 * amp), 30, 127))
                notes.append(pretty_midi.Note(
                    velocity=vel, pitch=midi_pitch,
                    start=float(times[i]), end=float(times[j] + frame_dur),
                ))
        i = j + 1

    if not notes:
        raise TranscribeError("tidak ada not terdeteksi dari audio")

    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, name="Melody")
    inst.notes = notes
    inst.control_changes.append(pretty_midi.ControlChange(number=7, value=100, time=0))
    pm.instruments.append(inst)
    pm.write(str(out_midi))
    log("transcribing", f"pyin: {len(notes)} not terdeteksi")
    return out_midi
