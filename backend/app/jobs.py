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
from .pipeline import fetch, post, stems as stems_mod, transcribe

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
    opts: dict[str, Any] = job["options"] or {}
    job_dir = config.JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def log(stage: str, message: str) -> None:
        db.log_event(job_id, stage, message)

    # ---------------------------------------------------------- 1. fetch
    _stage(job_id, "fetching", 0.05, "menyiapkan audio sumber")
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
    if opts.get("stems"):
        _stage(job_id, "separating", 0.30, "memisahkan stem dengan AI")
        stem_mode = opts.get("stem_mode", "vocals")
        stem_paths = stems_mod.separate(wav, job_dir, stem_mode, log)
        db.update_job(job_id, stems={k: str(v) for k, v in stem_paths.items()})
        want = opts.get("target", "melody")
        pick = {"melody": "vocals", "vocals": "vocals",
                "instrumental": "instrumental", "mix": None}.get(want, "vocals")
        if pick and pick in stem_paths:
            target_audio = stem_paths[pick]
            log("separating", f"transkripsi akan memakai stem '{pick}'")
        else:
            log("separating", "stem target tidak ada → memakai campuran penuh")

    # ---------------------------------------------------------- 3. transcribe
    _stage(job_id, "transcribing", 0.62, "mengubah audio menjadi MIDI")
    engine = opts.get("engine") or transcribe.engine_available()
    log("transcribing", f"engine: {engine}")
    midi_path = job_dir / "output.mid"
    transcribe.transcribe(
        target_audio, midi_path, engine,
        onset=float(opts.get("onset_threshold", 0.5)),
        frame=float(opts.get("frame_threshold", 0.3)),
        min_note_len=float(opts.get("min_note_length", 0.06)),
        log=log,
    )

    # ---------------------------------------------------------- 4. finalize
    _stage(job_id, "finalizing", 0.90, "membersihkan hasil MIDI")
    summary = post.clean(midi_path, min_note_len=float(opts.get("min_note_length", 0.06)))
    log("finalizing", f"{summary['note_count']} not, pitch {summary['min_pitch']}–{summary['max_pitch']}")

    db.update_job(
        job_id, status="done", stage="done", progress=1.0, message="selesai",
        midi_path=str(midi_path), audio_path=str(wav),
        note_count=int(summary["note_count"]),
        duration=float(summary["duration"] or duration or 0),
        error="",
    )
