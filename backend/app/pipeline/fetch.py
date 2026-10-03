"""Stage 1 — obtain source audio (local upload or YouTube download)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .. import config

Log = Callable[[str, str], None]


class FetchError(RuntimeError):
    pass


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg") or str(config.BASE_DIR / ".venv" / "bin" / "ffmpeg")
    if not shutil.which(exe) and not Path(exe).exists():
        raise FetchError("ffmpeg tidak ditemukan di PATH")
    return exe


def probe_duration(path: Path) -> float:
    """Return media duration in seconds via ffprobe (0.0 when unknown)."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def to_wav(src: Path, dst: Path, sample_rate: int = 44100) -> Path:
    """Normalise any input to mono-ish 44.1k WAV (stereo kept — demucs wants stereo)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-ac", "2", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le", str(dst),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists():
        raise FetchError(f"ffmpeg gagal: {r.stderr.strip()[:400]}")
    return dst


def from_youtube(url: str, job_dir: Path, job_id: str, log: Log) -> tuple[Path, dict]:
    """Download bestaudio from YouTube and normalise to WAV. Returns (wav, meta)."""
    ytdlp = shutil.which("yt-dlp") or str(config.BASE_DIR / ".venv" / "bin" / "yt-dlp")
    if not Path(ytdlp).exists() and not shutil.which("yt-dlp"):
        raise FetchError("yt-dlp tidak terpasang")

    log("fetching", "mengambil metadata YouTube…")
    js_runtime = ["--js-runtimes", config.YTDLP_JS_RUNTIME] if config.YTDLP_JS_RUNTIME else []
    meta: dict = {}
    try:
        r = subprocess.run(
            [ytdlp, *js_runtime, "--no-playlist", "--skip-download", "--dump-single-json",
             "--no-warnings", url],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0 and r.stdout.strip():
            raw = json.loads(r.stdout.strip().splitlines()[-1])
            meta = {
                "title": raw.get("title") or "Untitled",
                "uploader": raw.get("uploader") or "",
                "duration": float(raw.get("duration") or 0),
            }
    except Exception as exc:  # metadata is best-effort
        log("fetching", f"metadata gagal (lanjut): {exc}")

    dur = meta.get("duration") or 0
    if dur and dur > config.YTDLP_MAX_DURATION:
        raise FetchError(
            f"durasi {int(dur)}s melebihi batas {config.YTDLP_MAX_DURATION}s"
        )

    log("fetching", "mengunduh audio dari YouTube…")
    raw_out = job_dir / "source_raw.%(ext)s"
    cmd = [
        ytdlp, *js_runtime, "--no-playlist", "--no-warnings", "--newline",
        "-f", config.YTDLP_FORMAT,
        "--max-filesize", "200M",
        "-x", "--audio-format", "wav", "--audio-quality", "0",
        "--postprocessor-args", "ffmpeg:-ac 2 -ar 44100",
        "-o", str(raw_out), url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise FetchError(f"yt-dlp gagal: {(proc.stderr or proc.stdout).strip()[-500:]}")

    candidates = sorted(job_dir.glob("source_raw.*"))
    wavs = [p for p in candidates if p.suffix == ".wav"]
    if not wavs:
        raise FetchError("yt-dlp selesai tapi tidak ada file WAV dihasilkan")

    final = job_dir / "source.wav"
    if wavs[0] != final:
        shutil.move(str(wavs[0]), str(final))
    for leftover in candidates:
        if leftover != final and leftover.exists():
            leftover.unlink()
    return final, meta
