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

# ------------------------------------------------------------------ prepare

# Window size for the block-wise prepare path used on long audio.
PREP_BLOCK_SECONDS = 240.0
_PREP_PAD_SECONDS = 2.0


def _prepare_long(src_wav: Path, dst_wav: Path, opts: dict, log: Log) -> Path:
    """Block-wise `prepare` for long audio — same transform, bounded memory.

    The whole-signal version is not merely slow at two hours, it is memory
    unbounded: librosa.load returns float64, `_bandlimit` hands that to scipy's
    sosfiltfilt which allocates another full-length array, and every step in
    between allocates a full-length temporary too. Measured on the real
    98-minute video, that held **5.8 GB** and sat in "preparing" for over five
    minutes with ~1 GB left on the box — one more allocation away from the OOM
    killer taking the whole API down mid-job.

    Here: one streaming pass for the peak, one cheap scan for the silence gate,
    then fixed-size windows written straight to the output. The band-limit is
    still filtfilt (zero phase, so the timeline never moves) but applied per
    window with a pad copied from the neighbours, which makes each window's
    edges behave like they would in a whole-signal filter.
    """
    import soundfile as sf
    from math import gcd
    from scipy.signal import butter, resample_poly, sosfiltfilt

    info = sf.info(str(src_wav))
    src_sr = int(info.samplerate or config.ANALYSIS_SR)
    total = int(info.frames)
    if total <= 0:
        return src_wav

    # The whole-signal path calls librosa.load(sr=ANALYSIS_SR), which RESAMPLES.
    # Reading at the file's native rate without doing the same silently fed the
    # model 44.1k audio labelled as 22.05k — the prepared file came out at double
    # length and correlated with the correct one at ~0. Always match the rate.
    sr = config.ANALYSIS_SR
    need_resample = src_sr != sr

    block = max(src_sr, int(PREP_BLOCK_SECONDS * src_sr))
    pad = int(_PREP_PAD_SECONDS * src_sr)
    nyq = src_sr / 2.0
    lo = max(20.0, min(float(opts.get("min_frequency", 41.2)), nyq * 0.5)) / nyq
    hi = max(lo + 0.01, min(float(opts.get("max_frequency", 4186.0)), nyq * 0.95)) / nyq
    sos = butter(4, [lo, hi], btype="bandpass", output="sos")
    if need_resample:
        g = gcd(sr, src_sr)
        rs_up, rs_down = sr // g, src_sr // g
    use_hpss = bool(opts.get("suppress_percussion"))
    lib = None
    if use_hpss:
        import librosa as lib  # noqa: PLC0415

    def _mono(buf: np.ndarray) -> np.ndarray:
        # the long-audio download is already mono; if a stereo file reaches here,
        # mix it like librosa.load would rather than silently dropping the right
        # channel (the timeline is unaffected either way, the content is not)
        return buf[:, 0] if buf.shape[1] == 1 else buf.mean(axis=1)

    # --- pass 1: global peak (so normalisation matches the whole-signal path)
    # Must be over the MONO mix, because that is what gets processed: taking the
    # peak over a stereo buffer gave 1.0 where the mono mix peaks at 0.90, so the
    # gain came out 0.902x off and every sample was 10% quiet.
    peak = 0.0
    with sf.SoundFile(str(src_wav)) as f:
        while True:
            b = f.read(block, dtype="float32", always_2d=True)
            if b.size == 0:
                break
            peak = max(peak, float(np.max(np.abs(_mono(b)))))
    gain = (0.92 / peak) if peak > 1e-6 else 1.0

    # --- the silence gate, resolved to two indices.
    # top_db is relative to the peak, so this is the same threshold librosa's trim
    # uses; only the two ends are touched, exactly like the whole-signal version
    # (internal quiet passages must survive — they are part of the performance).
    thr = peak * (10.0 ** (-45.0 / 20.0))
    start = 0
    end = total
    if peak > 1e-6:
        with sf.SoundFile(str(src_wav)) as f:
            pos = 0
            while pos < total:
                b = f.read(block, dtype="float32", always_2d=True)
                if b.size == 0:
                    break
                hit = np.flatnonzero(np.abs(_mono(b)) >= thr)
                if hit.size:
                    start = pos + int(hit[0])
                    break
                pos += b.shape[0]
        with sf.SoundFile(str(src_wav)) as f:
            pos = total
            while pos > 0:
                take = min(block, pos)
                pos -= take
                f.seek(pos)
                b = f.read(take, dtype="float32", always_2d=True)
                hit = np.flatnonzero(np.abs(_mono(b)) >= thr)
                if hit.size:
                    end = pos + int(hit[-1]) + 1
                    break

    # --- pass 2: window by window, written as we go
    # `start`/`end` are in SOURCE samples; the output may be at a different rate, so
    # convert them once and track the output position alongside the input position.
    ratio = src_sr / float(sr)
    start_out = int(start / ratio)
    end_out = int(end / ratio)
    written = 0
    with sf.SoundFile(str(src_wav)) as fin:
        with sf.SoundFile(str(dst_wav), "w", samplerate=sr, channels=1,
                          subtype="PCM_16") as fout:
            w0 = 0
            while w0 < total:
                w1 = min(total, w0 + block)
                r0 = max(0, w0 - pad)
                r1 = min(total, w1 + pad)
                fin.seek(r0)
                buf = _mono(fin.read(r1 - r0, dtype="float32", always_2d=True))
                off = w0 - r0

                seg = buf * gain
                seg = sosfiltfilt(sos, seg).astype(np.float32)
                if use_hpss:
                    seg = lib.effects.hpss(seg, margin=(1.0, 5.0))[0]
                seg = seg[off:off + (w1 - w0)]
                if need_resample:
                    # band-limit first, then decimate: anti-aliasing before the
                    # rate change, which is the right order and keeps the result
                    # equivalent to filtering at the output rate
                    seg = resample_poly(seg, rs_up, rs_down).astype(np.float32)

                g0 = max(0, start_out - written)
                g1 = min(seg.shape[0], end_out - written)
                if g0 > 0 or g1 < seg.shape[0]:
                    gated = np.zeros_like(seg)
                    if g1 > g0:
                        gated[g0:g1] = seg[g0:g1]
                    seg = gated

                fout.write(seg)
                written += seg.shape[0]
                w0 = w1

    expect = int(round(total * sr / src_sr))
    if abs(written - expect) > sr // 1000 + 8:
        log("transcribing",
            f"peringatan: panjang hasil pra-proses {written / sr:.3f}s vs sumber "
            f"{total / src_sr:.3f}s ({written} vs {expect} sampel)")
    log("transcribing",
        f"pra-proses (block-wise, {block / src_sr:.0f}s/window): normalisasi + "
        f"band-limit {opts.get('min_frequency'):.0f}-{opts.get('max_frequency'):.0f} Hz"
        + (" + buang perkusi" if use_hpss else "")
        + (f" + resample {src_sr}→{sr} Hz" if need_resample else "")
        + f" ({total / src_sr:.1f}s → {written / sr:.1f}s)")
    return dst_wav


def prepare(src_wav: Path, dst_wav: Path, opts: dict, log: Log) -> Path:
    """Normalise + band-limit (+ optionally de-percuss) the audio for the model."""
    try:
        import librosa
        import soundfile as sf
    except ImportError:                                     # pragma: no cover
        return src_wav

    try:
        if _duration_of(src_wav) > config.LONG_AUDIO_SECONDS:
            return _prepare_long(src_wav, dst_wav, opts, log)

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

def transcribe(src_wav: Path, out_midi: Path, engine: str, opts: dict, log: Log,
               progress=None) -> Path:
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    if engine == "transkun":
        try:
            return _run_transkun(src_wav, out_midi, opts, log, progress=progress)
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


def _duration_of(path: Path) -> float:
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return float(info.frames) / float(info.samplerate or 1)
    except Exception:
        return 0.0


def _transkun_once(src_wav: Path, out_midi: Path, opts: dict, log: Log) -> Path:
    exe = config.TRANSKUN_PYTHON
    templ = out_midi.parent / "transkun_raw.mid"
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
    return out_midi


def _transkun_chunked(src_wav: Path, out_midi: Path, opts: dict, log: Log,
                      duration: float, progress=None) -> Path:
    """Transcribe a long file in overlapping windows and merge the results.

    Running transkun on 98 minutes in one call would hold the whole recording's
    intermediate tensors at once, and this box has ~5 GB free. Windows keep peak
    memory equal to a short run. The cost is identical overall (the model is
    linear in audio length), so nothing is traded except a little merge code.

    Every window is `step + overlap` long, and the merge drops a note when the
    same pitch was already seen within 40ms — which is exactly the duplicate a
    note straddling a boundary produces. A note clipped by a window edge is
    therefore recovered from the neighbouring window that saw it whole.
    """
    import soundfile as sf

    exe = config.TRANSKUN_PYTHON
    step = max(30.0, float(config.TRANSKUN_CHUNK_SECONDS))
    ov = max(0.0, float(config.TRANSKUN_CHUNK_OVERLAP))
    windows: list[tuple[float, float]] = []
    t = 0.0
    while t < duration - 0.5:
        windows.append((t, min(duration, t + step + ov)))
        t += step

    info = sf.info(str(src_wav))
    sr = int(info.samplerate or 22050)
    log("transcribing",
        f"transkun: audio panjang ({duration / 60:.1f} menit) → {len(windows)} window "
        f"@{step:.0f}s (+{ov:.0f}s tumpang tindih), device={config.TRANSKUN_DEVICE}")

    notes: list[tuple[float, float, int, int]] = []
    ccs: list[tuple[float, int, int]] = []
    failed = 0
    for i, (a, b) in enumerate(windows):
        piece = out_midi.parent / f"chunk_{i:03d}.wav"
        raw = out_midi.parent / f"chunk_{i:03d}_raw.mid"
        data, _ = sf.read(str(src_wav), start=int(a * sr), stop=int(b * sr),
                          dtype="float32", always_2d=True)
        sf.write(str(piece), data, sr)
        del data
        r = subprocess.run(
            [exe, "-m", "transkun.transcribe", str(piece), str(raw),
             "--device", config.TRANSKUN_DEVICE],
            capture_output=True, text=True, timeout=7200)
        piece.unlink(missing_ok=True)
        if not raw.exists():
            failed += 1
            log("transcribing", f"window {i + 1}/{len(windows)} gagal (dilewati): "
                                f"{(r.stderr or r.stdout).strip()[-180:]}")
        else:
            pm = pretty_midi.PrettyMIDI(str(raw))
            for inst in pm.instruments:
                for n in inst.notes:
                    notes.append((n.start + a, n.end + a, int(n.pitch), int(n.velocity)))
                for c in inst.control_changes:
                    ccs.append((c.time + a, int(c.number), int(c.value)))
            raw.unlink(missing_ok=True)
            if progress:
                progress((i + 1) / len(windows),
                         f"transkripsi window {i + 1}/{len(windows)} selesai "
                         f"({len(notes)} not sejauh ini)")

    if not notes:
        raise TranscribeError(
            f"transkun tidak menghasilkan not pada {len(windows)} window "
            f"({failed} gagal) — audio mungkin bukan piano solo")

    # ---- merge the overlap duplicates -------------------------------------
    # Same pitch, onset within 40ms: the boundary-straddling note seen twice.
    notes.sort(key=lambda n: (n[2], n[0]))
    kept: list[tuple[float, float, int, int]] = []
    for n in notes:
        if kept and kept[-1][2] == n[2] and n[0] - kept[-1][0] < 0.04:
            if (n[1] - n[0]) > (kept[-1][1] - kept[-1][0]):
                kept[-1] = n
            continue
        kept.append(n)
    joined = len(notes) - len(kept)
    kept.sort(key=lambda n: n[0])

    ccs.sort(key=lambda c: c[0])
    kcc: list[tuple[float, int, int]] = []
    for c in ccs:
        if kcc and kcc[-1][1] == c[1] and abs(c[0] - kcc[-1][0]) < 0.03:
            continue
        kcc.append(c)

    # ---- write one MIDI, tempo already correct ---------------------------
    pm_out = pretty_midi.PrettyMIDI(initial_tempo=float(opts.get("tempo") or 120.0))
    inst = pretty_midi.Instrument(program=0, is_drum=False, name="Piano")
    for s, e, p, v in kept:
        if e - s < 0.005:
            e = s + 0.02
        inst.notes.append(pretty_midi.Note(velocity=v, pitch=p,
                                           start=float(s), end=float(e)))
    for t, num, val in kcc:
        inst.control_changes.append(
            pretty_midi.ControlChange(number=num, value=val, time=float(t)))
    pm_out.instruments.append(inst)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    pm_out.write(str(out_midi))
    log("transcribing",
        f"transkun chunked: {len(kept)} not dari {len(windows)} window "
        f"({joined} duplikat tumpang tindih dibuang, {len(kcc)} CC pedal), "
        f"tempo {float(opts.get('tempo') or 120.0):.1f} BPM")
    return out_midi


def _run_transkun(src_wav: Path, out_midi: Path, opts: dict, log: Log,
                  progress=None) -> Path:
    """Piano-specialist transcription via the isolated transkun venv."""
    exe = config.TRANSKUN_PYTHON
    if not Path(exe).exists():
        raise TranscribeError(f"transkun python tidak ada: {exe}")

    duration = _duration_of(src_wav)
    if duration > config.LONG_AUDIO_SECONDS and config.TRANSKUN_CHUNK_SECONDS > 0:
        return _transkun_chunked(src_wav, out_midi, opts, log, duration, progress)

    log("transcribing",
        f"transkun: model semi-CRF piano, device={config.TRANSKUN_DEVICE} "
        f"(khusus piano; lebih lambat dari basic-pitch)")
    _transkun_once(src_wav, out_midi, opts, log)
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
