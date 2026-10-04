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


# ------------------------------------------------------------------- tempo

def detect_tempo(audio_path: Path, fallback: float = 120.0, log: Log | None = None) -> float:
    """Estimate the piece's tempo.

    This is not cosmetic. The MIDI's tempo header is what maps seconds to
    musical time, so a wrong tempo puts every bar line in the wrong place and
    the rendered sheet music becomes unreadable. basic-pitch writes 120 BPM
    unless told otherwise.

    The librosa tempo API has moved twice: `librosa.beat.tempo` (0.10),
    `librosa.feature.rhythm.tempo` (<1.0) and, in 1.0, only
    `librosa.beat.beat_track`. Try them in order rather than pinning one.
    """
    def _fail(msg: str) -> float:
        if log:
            log("preparing", f"tempo: {msg} → pakai {fallback:.0f} BPM")
        return fallback

    try:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=config.ANALYSIS_SR, mono=True)
        if y.size < sr * 3:
            return _fail("audio terlalu pendek")
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
        if onset_env.size == 0 or float(onset_env.max()) <= 0:
            return _fail("tidak ada onset")

        est = None
        errors = []
        rhythm = getattr(getattr(librosa, "feature", None), "rhythm", None)
        if rhythm is not None and hasattr(rhythm, "tempo"):
            try:
                est = rhythm.tempo(onset_envelope=onset_env, sr=sr, hop_length=512,
                                   aggregate=np.median)
            except Exception as exc:                        # noqa: BLE001
                errors.append(f"rhythm.tempo: {exc}")
        if est is None and hasattr(librosa.beat, "tempo"):
            try:
                est = librosa.beat.tempo(onset_envelope=onset_env, sr=sr,
                                         hop_length=512, aggregate=np.median)
            except Exception as exc:                        # noqa: BLE001
                errors.append(f"beat.tempo: {exc}")
        if est is None:
            try:
                est, _beats = librosa.beat.beat_track(
                    onset_envelope=onset_env, sr=sr, hop_length=512
                )
            except Exception as exc:                        # noqa: BLE001
                errors.append(f"beat_track: {exc}")

        if est is None:
            return _fail("; ".join(errors) or "tidak ada API tempo yang cocok")

        bpm = float(np.atleast_1d(np.asarray(est, dtype=float))[0])
        if not np.isfinite(bpm) or bpm <= 0:
            return _fail("hasil tidak valid")
        # fold octave errors into a musically plausible range
        while bpm < 55:
            bpm *= 2
        while bpm > 210:
            bpm /= 2
        return round(bpm, 2)
    except Exception as exc:                                # noqa: BLE001
        return _fail(f"{type(exc).__name__}: {exc}")


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


def transkun_available() -> bool:
    """Is the isolated transkun venv present and importable?"""
    if not config.TRANSKUN_ENABLED:
        return False
    exe = Path(config.TRANSKUN_PYTHON)
    if not exe.exists():
        return False
    try:
        r = subprocess.run([str(exe), "-c", "import transkun"],
                           capture_output=True, text=True, timeout=180)
        return r.returncode == 0
    except Exception:                                        # noqa: BLE001
        return False


def engine_available() -> str:
    """Which engine will be used by default.

    Transkun first: it is a piano specialist (event-based semi-CRF, published
    note onset+offset F1 0.88 on MAPS / 0.98 on Maestro) and it predicts the
    sustain pedal itself. basic-pitch stays for non-piano material — it is
    polyphonic and general, where transkun would only hallucinate a piano.
    """
    if transkun_available():
        return "transkun"
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
        # NEVER drop audio from the timeline here. This used to call
        # librosa.effects.trim(top_db=45), which removed ~1.8s of leading silence
        # from a 199.9s recording. The model then transcribed the trimmed audio, so
        # every note in the MIDI came out shifted earlier by that amount and the
        # transcription no longer lined up with the recording the user was watching
        # (chroma similarity against the original collapsed from 0.92 to 0.58, and a
        # global +1.1s lag was what best re-aligned it). Gate the silence out
        # instead of cutting it — the model still never sees it, but the timeline is
        # preserved exactly.
        y = _gate_silence(y, top_db=45)
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

        # Invariant: the prepared audio must stay on the source timeline, otherwise
        # every downstream timestamp (notes, pedal, score) is silently wrong.
        if y.shape[0] != before:
            log("transcribing",
                f"peringatan: panjang audio berubah {before / sr:.3f}s → "
                f"{y.shape[0] / sr:.3f}s, timestamp bisa bergeser")
            if y.shape[0] < before:
                y = np.pad(y, (0, before - y.shape[0]))
            else:
                y = y[:before]

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


def _gate_silence(y: np.ndarray, top_db: float = 45.0) -> np.ndarray:
    """Zero out leading/trailing silence *without* changing the timeline.

    Trimming silence is worth doing — it keeps the model from chewing on dead air —
    but `librosa.effects.trim` returns a shorter array, which shifts every
    timestamp the model produces. Gate instead of cut: same length, same timeline.
    """
    try:
        import librosa

        _trimmed, (start, end) = librosa.effects.trim(y, top_db=top_db)
    except Exception:                                        # noqa: BLE001
        return y
    if start <= 0 and end >= len(y):
        return y
    out = np.zeros_like(y)
    out[start:end] = y[start:end]
    return out


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
    if engine == "transkun":
        try:
            return _run_transkun(src_wav, out_midi, opts, log)
        except TranscribeError as exc:
            log("transcribing", f"transkun gagal → fallback basic-pitch: {exc}")
            engine = "basic-pitch"
    if engine == "basic-pitch":
        try:
            return _run_basic_pitch(src_wav, out_midi, opts, log)
        except TranscribeError as exc:
            log("transcribing", f"basic-pitch gagal → fallback pyin: {exc}")
            engine = "librosa-pyin"
    if engine == "librosa-pyin":
        return _run_pyin(src_wav, out_midi, float(opts.get("min_note_length", 0.06)), log,
                         tempo=float(opts.get("tempo") or 120.0))
    raise TranscribeError(f"engine tidak dikenal / tidak tersedia: {engine}")


def _retempo(src: Path, dst: Path, bpm: float) -> Path:
    """Rewrite a MIDI with a different tempo header, keeping every absolute time.

    pretty_midi stores events in seconds and converts to ticks on write using the
    header tempo, so moving the instruments into a fresh PrettyMIDI that carries
    the right tempo preserves all timings while fixing the bar lines.
    """
    src_pm = pretty_midi.PrettyMIDI(str(src))
    out = pretty_midi.PrettyMIDI(initial_tempo=float(bpm))
    out.instruments = src_pm.instruments
    out.write(str(dst))
    return dst


def _run_transkun(src_wav: Path, out_midi: Path, opts: dict, log: Log) -> Path:
    """Piano-specialist transcription via the isolated transkun venv."""
    exe = config.TRANSKUN_PYTHON
    if not Path(exe).exists():
        raise TranscribeError(f"transkun python tidak ada: {exe}")

    templ = out_midi.parent / "transkun_raw.mid"
    log("transcribing",
        f"transkun: model semi-CRF piano, device={config.TRANSKUN_DEVICE} "
        f"(khusus piano; lebih lambat dari basic-pitch)")
    cmd = [exe, "-m", "transkun.transcribe", str(src_wav), str(templ),
           "--device", config.TRANSKUN_DEVICE]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
    if not templ.exists():
        raise TranscribeError(
            f"transkun exit {r.returncode}: {(r.stderr or r.stdout)[-500:]}")
    if r.returncode != 0:
        log("transcribing", f"transkun exit {r.returncode} tapi menghasilkan MIDI")

    # transkun always writes 120 BPM; without the real tempo every bar line in
    # the rendered score lands wrong (same reason as the basic-pitch path).
    _retempo(templ, out_midi, float(opts.get("tempo") or 120.0))
    templ.unlink(missing_ok=True)
    log("transcribing", f"transkun: MIDI ditulis ({out_midi.name}, tempo "
                        f"{float(opts.get('tempo') or 120.0):.1f} BPM)")
    return out_midi


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
        f"frame={opts['frame_threshold']:.2f} minlen={opts['min_note_length']:.3f}s "
        f"tempo={float(opts.get('tempo') or 120.0):.1f} BPM")
    cmd = [
        exe, str(work), str(src_wav),
        "--onset-threshold", str(opts["onset_threshold"]),
        "--frame-threshold", str(opts["frame_threshold"]),
        "--minimum-note-length", str(opts["min_note_length"]),
        "--minimum-frequency", str(opts["min_frequency"]),
        "--maximum-frequency", str(opts["max_frequency"]),
        # without this the file claims 120 BPM and every bar line lands wrong
        "--midi-tempo", str(float(opts.get("tempo") or 120.0)),
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


def _run_pyin(src_wav: Path, out_midi: Path, min_note_len: float, log: Log,
              tempo: float = 120.0) -> Path:
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

    pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo or 120.0))
    inst = pretty_midi.Instrument(program=0, name="Melody")
    inst.notes = notes
    inst.control_changes.append(pretty_midi.ControlChange(number=7, value=100, time=0))
    pm.instruments.append(inst)
    pm.write(str(out_midi))
    log("transcribing", f"pyin: {len(notes)} not terdeteksi")
    return out_midi
