"""Stage 3 — audio to MIDI transcription.

Primary engine: Spotify `basic-pitch` (polyphonic, AMT).
Fallback engine: `librosa.pyin` monophonic melody tracker (always available,
needed when basic-pitch/TensorFlow is not importable in this environment).
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


class TranscribeError(RuntimeError):
    pass


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


def transcribe(
    src_wav: Path,
    out_midi: Path,
    engine: str,
    onset: float,
    frame: float,
    min_note_len: float,
    log: Log,
) -> Path:
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    if engine == "basic-pitch":
        try:
            return _run_basic_pitch(src_wav, out_midi, onset, frame, min_note_len, log)
        except TranscribeError as exc:
            log("transcribing", f"basic-pitch gagal → fallback pyin: {exc}")
            engine = "librosa-pyin"
    if engine == "librosa-pyin":
        return _run_pyin(src_wav, out_midi, min_note_len, log)
    raise TranscribeError(f"engine tidak dikenal / tidak tersedia: {engine}")


def _run_basic_pitch(src_wav: Path, out_midi: Path, onset: float, frame: float,
                     min_note_len: float, log: Log) -> Path:
    exe = _basic_pitch_bin()
    if not exe:
        raise TranscribeError("basic-pitch binary tidak ditemukan")
    work = out_midi.parent / "_bp"
    work.mkdir(parents=True, exist_ok=True)
    log("transcribing", "basic-pitch: transkripsi polifonik (bisa beberapa menit)…")
    cmd = [
        exe, str(work), str(src_wav),
        "--onset-threshold", str(onset),
        "--frame-threshold", str(frame),
        "--minimum-note-length", str(min_note_len),
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
