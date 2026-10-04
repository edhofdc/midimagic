"""MidiMagic backend — FastAPI service.

Runs the heavy Python side (yt-dlp, Demucs, basic-pitch) that cannot live in the
browser. The Next.js app calls this over HTTP and does all rendering/playback.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from . import config, db, jobs
from .pipeline import fetch, post, stems as stems_mod, transcribe

app = FastAPI(title="MidiMagic API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SHARES_DIR = config.DATA_DIR / "shares"
SHARES_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def _startup() -> None:
    db.init()


# ------------------------------------------------------------------ helpers

def _tool(name: str, venv_rel: str | None = None) -> str | None:
    if venv_rel:
        cand = config.BASE_DIR / ".venv" / "bin" / venv_rel
        if cand.exists():
            return str(cand)
    return shutil.which(name)


def _range_response(path: Path, request: Request, media_type: str,
                     filename: str, as_attachment: bool) -> Response:
    """FileResponse with HTTP Range support so the browser can seek audio."""
    if not path.exists():
        raise HTTPException(404, "file tidak ditemukan")
    size = path.stat().st_size
    range_header = request.headers.get("range")
    ext = path.suffix.lstrip(".")

    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if as_attachment:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    if not range_header:
        return FileResponse(path, media_type=media_type, headers=headers)

    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        return FileResponse(path, media_type=media_type, headers=headers)
    start = int(m.group(1)) if m.group(1) else 0
    end = int(m.group(2)) if m.group(2) else size - 1
    end = min(end, size - 1)
    if start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1

    def _iter(chunk: int = 256 * 1024):
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                data = fh.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)
    return StreamingResponse(_iter(), status_code=206, media_type=media_type, headers=headers)


def _job_or_404(job_id: str) -> dict:
    job = db.get_job(job_id, with_events=True)
    if not job:
        raise HTTPException(404, "job tidak ditemukan")
    return job


# ------------------------------------------------------------------ meta

@app.get("/api/health")
def health() -> dict:
    demucs_ok = bool(_tool("demucs", "demucs"))
    ytdlp_ok = bool(_tool("yt-dlp", "yt-dlp"))
    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    return {
        "status": "ok",
        "time": time.time(),
        "engines": {
            "transcription": transcribe.engine_available(),
            "basic_pitch": bool(transcribe._basic_pitch_bin()),
            "librosa": bool(importlib.util.find_spec("librosa")),
            "demucs": demucs_ok,
            "yt_dlp": ytdlp_ok,
            "ffmpeg": ffmpeg_ok,
        },
        "config": {
            "demucs_model": config.DEMUCS_MODEL,
            "workers": config.MAX_WORKERS,
            "yt_max_seconds": config.YTDLP_MAX_DURATION,
            "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
            "accuracy_presets": list(transcribe.PRESETS.keys()),
            "default_accuracy": transcribe.DEFAULT_PRESET,
        },
        "stats": db.stats(),
    }


# ------------------------------------------------------------------ jobs

@app.post("/api/jobs", status_code=202)
async def create_job(request: Request) -> dict:
    ctype = (request.headers.get("content-type") or "").lower()
    opts: dict = {}
    source_type = "upload"
    source_ref = ""
    raw_name = ""
    title = ""

    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        # NOTE: fastapi.UploadFile subclasses starlette's; the value returned by
        # request.form() is the Starlette class, so duck-type instead.
        filename = getattr(upload, "filename", None)
        if upload is None or not filename:
            raise HTTPException(400, "field 'file' wajib diisi")
        raw_name = Path(filename).name
        ext = Path(raw_name).suffix.lower()
        if ext not in config.ALLOWED_EXT:
            raise HTTPException(400, f"format {ext or '?'} tidak didukung")
        for key in ("stems", "stem_mode", "target", "engine", "accuracy"):
            if form.get(key) is not None:
                opts[key] = str(form.get(key))
        for key in ("onset_threshold", "frame_threshold", "min_note_length",
                    "min_frequency", "max_frequency", "merge_gap", "quantize"):
            if form.get(key) is not None:
                try:
                    opts[key] = float(str(form.get(key)))
                except ValueError:
                    pass
        if form.get("min_velocity") is not None:
            try:
                opts["min_velocity"] = int(float(str(form.get("min_velocity"))))
            except ValueError:
                pass
        for key in ("stems", "suppress_percussion"):
            if form.get(key) is not None:
                opts[key] = str(form.get(key)).lower() in ("1", "true", "yes", "on")
        jid = db.create_job("upload", "", opts, title=Path(raw_name).stem)
        job_dir = config.JOBS_DIR / jid
        job_dir.mkdir(parents=True, exist_ok=True)
        dest = job_dir / f"upload{ext}"
        size = 0
        with dest.open("wb") as fh:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    fh.close()
                    shutil.rmtree(job_dir, ignore_errors=True)
                    raise HTTPException(413, "file melebihi batas ukuran")
                fh.write(chunk)
        db.update_job(jid, source_ref=str(dest))
        jobs.submit(jid)
        return {"job_id": jid, "status": "queued"}

    # JSON body → YouTube URL
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, f"body tidak valid: {exc}") from exc

    url = (body.get("youtube_url") or "").strip()
    if not url:
        raise HTTPException(400, "kirim multipart 'file' atau JSON 'youtube_url'")
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "URL harus dimulai dengan http(s)://")
    opts = {k: v for k, v in (body.get("options") or {}).items()}
    title = (body.get("title") or "").strip()
    jid = db.create_job("youtube", url, opts, title=title)
    jobs.submit(jid)
    return {"job_id": jid, "status": "queued"}


@app.get("/api/jobs")
def list_jobs(limit: int = 30) -> dict:
    return {"jobs": db.list_jobs(limit=min(max(limit, 1), 200)), "stats": db.stats()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _job_or_404(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    _job_or_404(job_id)
    shutil.rmtree(config.JOBS_DIR / job_id, ignore_errors=True)
    db.update_job(job_id, status="deleted", midi_path=None, audio_path=None)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/midi")
def job_midi(request: Request, job_id: str, download: int = 0,
             semitones: int = 0, tempo: float = 1.0) -> Response:
    job = _job_or_404(job_id)
    if job["status"] != "done" or not job.get("midi_path"):
        raise HTTPException(409, "job belum selesai")
    src = Path(job["midi_path"])
    if not src.exists():
        raise HTTPException(404, "MIDI sudah dibersihkan")
    safe = re.sub(r"[^\w\-. ]+", "_", job.get("title") or job_id)[:60] or job_id

    if semitones or tempo != 1.0:
        out = src.parent / f"export_{semitones}_{tempo}.mid"
        post.shift(src, out, semitones=int(semitones), tempo_scale=float(tempo))
        src = out
        safe = f"{safe}_transposed"

    return _range_response(src, request, "audio/midi", f"{safe}.mid", bool(download))


@app.get("/api/jobs/{job_id}/audio")
def job_audio(request: Request, job_id: str) -> Response:
    job = _job_or_404(job_id)
    preview = config.JOBS_DIR / job_id / "preview.mp3"
    src = preview if preview.exists() else Path(job.get("audio_path") or "")
    if not src or not Path(src).exists():
        raise HTTPException(404, "audio sumber tidak tersedia")
    media = "audio/mpeg" if src.suffix == ".mp3" else "audio/wav"
    return _range_response(Path(src), request, media, f"{job_id}{src.suffix}", False)


# ------------------------------------------------------------------ shares

@app.post("/api/shares")
async def create_share(request: Request) -> dict:
    body = await request.json()
    job_id = (body.get("job_id") or "").strip()
    job = _job_or_404(job_id)
    if job["status"] != "done" or not job.get("midi_path"):
        raise HTTPException(409, "job belum selesai")
    src = Path(job["midi_path"])
    if not src.exists():
        raise HTTPException(404, "MIDI sudah dibersihkan")

    title = (body.get("title") or job.get("title") or "Untitled").strip()[:120]
    dst = SHARES_DIR / f"{job_id}.mid"
    shutil.copy2(src, dst)
    slug = db.create_share(job_id, title, str(dst),
                           note_count=int(job.get("note_count") or 0),
                           duration=float(job.get("duration") or 0))
    return {
        "slug": slug,
        "url": f"{config.PUBLIC_WEB_ORIGIN.rstrip('/')}/share/{slug}",
        "title": title,
        "note_count": job.get("note_count") or 0,
        "duration": job.get("duration") or 0,
    }


@app.get("/api/shares")
def list_shares(limit: int = 30) -> dict:
    return {"shares": db.list_shares(limit=min(max(limit, 1), 200))}


@app.get("/api/shares/{slug}")
def get_share(slug: str) -> dict:
    sh = db.get_share(slug, count_hit=True)
    if not sh:
        raise HTTPException(404, "share tidak ditemukan")
    return {
        "slug": sh["slug"],
        "title": sh["title"],
        "note_count": sh["note_count"],
        "duration": sh["duration"],
        "created_at": sh["created_at"],
        "hits": sh["hits"],
        "midi_url": f"/api/shares/{slug}/midi",
    }


@app.get("/api/shares/{slug}/midi")
def share_midi(request: Request, slug: str, download: int = 0) -> Response:
    sh = db.get_share(slug)
    if not sh:
        raise HTTPException(404, "share tidak ditemukan")
    path = Path(sh["midi_path"])
    if not path.exists():
        raise HTTPException(404, "MIDI share hilang")
    safe = re.sub(r"[^\w\-. ]+", "_", sh["title"] or slug)[:60] or slug
    return _range_response(path, request, "audio/midi", f"{safe}.mid", bool(download))


# ------------------------------------------------------------------ misc

@app.get("/")
def root() -> JSONResponse:
    return JSONResponse({"service": "midimagic-api",
                         "web": config.PUBLIC_WEB_ORIGIN,
                         "health": "/api/health"})
