"""In-process job runner. One worker by default — the box is 4 vCPU / no GPU and
demucs/tensorflow are memory hungry."""
from __future__ import annotations

import shutil
import subprocess
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import config, db
from .pipeline import fetch, post, stems as stems_mod, sustain, transcribe

_pool = ThreadPoolExecutor(max_workers=config.MAX_WORKERS, thread_name_prefix="midimagic")


def submit(job_id: str) -> None:
    _pool.submit(_safe_run, job_id)


def _safe_run(job_id: str) -> None:
    try:
        _run(job_id)
    except Exception as exc:                                  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        db.log_event(job_id, "error", detail)
        db.log_event(job_id, "error", traceback.format_exc()[-1500:])
        db.update_job(job_id, status="error", stage="error", error=detail,
                      message="gagal", progress=1.0)


def _stage(job_id: str, stage: str, progress: float, message: str) -> None:
    db.update_job(job_id, status="running", stage=stage, progress=progress, message=message)
    db.log_event(job_id, stage, message)


def _run(job_id: str) -> None:
    job = db.get_job(job_id)
    if not job:
        return
    raw_opts: dict[str, Any] = job["options"] or {}
    opts = transcribe.resolve_options(raw_opts)
    job_dir = config.JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def log(stage: str, message: str) -> None:
        db.log_event(job_id, stage, message)

    db.update_job(job_id, accuracy=opts["preset"])

    # ---------------------------------------------------------- 1. fetch
    _stage(job_id, "fetching", 0.04, "menyiapkan audio sumber")
    if job["source_type"] == "youtube":
        wav, meta = fetch.from_youtube(job["source_ref"], job_dir, job_id, log)
        db.update_job(job_id, title=meta.get("title") or job["title"],
                      duration=float(meta.get("duration") or 0))
    else:
        upload = job_dir / "upload.bin"
        src = Path(job["source_ref"])
        if not src.exists():
            raise FileNotFoundError("file upload hilang dari disk")
        shutil.move(str(src), str(upload))
        wav = fetch.to_wav(upload, job_dir / "source.wav")
        upload.unlink(missing_ok=True)

    duration = fetch.probe_duration(wav)
    if duration:
        db.update_job(job_id, duration=duration)
    log("fetching", f"audio siap ({duration:.1f}s)" if duration else "audio siap")

    # browser-playable preview
    preview = job_dir / "preview.mp3"
    try:
        subprocess.run(
            [shutil.which("ffmpeg") or "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(wav), "-b:a", "128k", str(preview)],
            capture_output=True, text=True, timeout=900, check=False,
        )
    except Exception:
        pass

    # ---------------------------------------------------------- 2. stems (optional)
    stem_paths: dict[str, Path] = {}
    target_audio = wav
    used_stem = False
    if raw_opts.get("stems"):
        _stage(job_id, "separating", 0.28, "memisahkan stem dengan AI")
        stem_mode = raw_opts.get("stem_mode", "vocals")
        stem_paths = stems_mod.separate(wav, job_dir, stem_mode, log)
        db.update_job(job_id, stems={k: str(v) for k, v in stem_paths.items()})
        want = raw_opts.get("target", "melody")
        pick = {"melody": "vocals", "vocals": "vocals",
                "instrumental": "instrumental", "mix": None}.get(want, "vocals")
        if pick and pick in stem_paths:
            target_audio = stem_paths[pick]
            used_stem = True
            log("separating", f"transkripsi akan memakai stem '{pick}'")
        else:
            log("separating", "stem target tidak ada → memakai campuran penuh")

    # ---------------------------------------------------------- 3. prepare
    _stage(job_id, "preparing", 0.45, "membersihkan audio untuk model")
    # Demucs already removes the drums; running HPSS on top of a stem only
    # smears the transients we need for onset detection.
    prep_opts = dict(opts)
    if used_stem:
        prep_opts["suppress_percussion"] = False
    prepared = transcribe.prepare(target_audio, job_dir / "prepared.wav", prep_opts, log)

    # ---------------------------------------------------------- 3b. tempo
    # The tempo header drives every bar line in the rendered score, and
    # basic-pitch writes 120 BPM unless told otherwise.
    tempo = float(raw_opts.get("tempo") or 0) or transcribe.detect_tempo(prepared, log=log)
    opts["tempo"] = tempo
    db.update_job(job_id, tempo=tempo)
    log("preparing", f"tempo: {tempo:.1f} BPM")

    # ---------------------------------------------------------- 4. transcribe
    _stage(job_id, "transcribing", 0.60, "mengubah audio menjadi MIDI")
    engine = raw_opts.get("engine") or transcribe.engine_available()
    log("transcribing", f"engine: {engine}")
    midi_path = job_dir / "output.mid"
    transcribe.transcribe(prepared, midi_path, engine, opts, log)

    # ---------------------------------------------------------- 5. finalize
    _stage(job_id, "finalizing", 0.88, "membersihkan hasil MIDI")
    summary = post.clean(
        midi_path,
        min_note_len=float(opts["min_note_length"]),
        merge_gap=float(raw_opts.get("merge_gap", 0.055)),
        min_velocity=int(raw_opts.get("min_velocity", 28)),
        quantize=float(raw_opts.get("quantize", 0.0) or 0.0),
    )
    log("finalizing",
        f"{summary['note_count']} not, pitch {summary['min_pitch']}–{summary['max_pitch']}"
        + (f", {summary['merged']} fragmen digabung" if summary.get("merged") else "")
        + (f", {summary['dropped']} noise dibuang" if summary.get("dropped") else ""))

    # ---------------------------------------------------------- 6. pedal (CC64)
    _stage(job_id, "sustain", 0.94, "mendeteksi sustain pedal dari rekaman")
    pedal = sustain.analyze(prepared, midi_path, log)
    if not pedal.get("skipped"):
        # report from the file itself so the numbers match what the player reads
        written = post.pedal_summary(midi_path)
        pedal = {**pedal, "segments": written["segments"],
                 "pedalled_seconds": written["pedalled_seconds"],
                 "ratio": written["ratio"]}

    db.update_job(
        job_id, status="done", stage="done", progress=1.0, message="selesai",
        midi_path=str(midi_path), audio_path=str(wav),
        note_count=int(summary["note_count"]),
        duration=float(summary["duration"] or duration or 0),
        tempo=tempo,
        pedal=pedal,
        error="",
    )
