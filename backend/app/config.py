"""MidiMagic backend configuration."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
ROOT_DIR = BASE_DIR.parent                                  # midimagic/
DATA_DIR = Path(os.environ.get("MIDIMAGIC_DATA", BASE_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"
MODELS_DIR = DATA_DIR / "models"

DB_PATH = Path(os.environ.get("MIDIMAGIC_DB", DATA_DIR / "midimagic.db"))

HOST = os.environ.get("MIDIMAGIC_HOST", "0.0.0.0")
PORT = int(os.environ.get("MIDIMAGIC_PORT", "8892"))

# Public origin of the web app, used when building share URLs.
PUBLIC_WEB_ORIGIN = os.environ.get("MIDIMAGIC_PUBLIC_ORIGIN", "http://localhost:8891")

# Job execution
MAX_WORKERS = int(os.environ.get("MIDIMAGIC_WORKERS", "1"))   # CPU-bound, keep at 1 on 4-core box
JOB_TTL_HOURS = int(os.environ.get("MIDIMAGIC_JOB_TTL_HOURS", "72"))

# Uploads
MAX_UPLOAD_BYTES = int(os.environ.get("MIDIMAGIC_MAX_UPLOAD_MB", "60")) * 1024 * 1024
ALLOWED_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".webm"}

# yt-dlp
YTDLP_FORMAT = "bestaudio/best"
YTDLP_MAX_DURATION = int(os.environ.get("MIDIMAGIC_YT_MAX_SECONDS", "7200"))  # 2 jam
# Beyond this length the pipeline changes shape: transkun runs in chunks (its
# inference memory grows with input length and this box only has ~5 GB free), and
# the download switches to a mono 22.05k WAV — a 98-minute stereo 44.1k WAV is
# ~1 GB on disk, while the analysis path resamples to 22.05k mono regardless and a
# piano preview gains nothing from stereo.
LONG_AUDIO_SECONDS = int(os.environ.get("MIDIMAGIC_LONG_AUDIO_SECONDS", "600"))
# YouTube extraction needs a JS runtime since yt-dlp 2025.x; node is the one we ship with.
YTDLP_JS_RUNTIME = os.environ.get("MIDIMAGIC_YT_JS_RUNTIME", "node")

# Demucs
DEMUCS_MODEL = os.environ.get("MIDIMAGIC_DEMUCS_MODEL", "htdemucs")
DEMUCS_TWO_STEMS = "vocals"

# Audio analysis (transcription + pedal detection)
ANALYSIS_SR = int(os.environ.get("MIDIMAGIC_ANALYSIS_SR", "22050"))

# Transkun — piano-specialist transcription (MIT, Yujia Yan).
#
# It needs a different dependency set than the main backend venv (torchaudio,
# ncls, moduleconf, pydub, soxr, mir_eval, plus the audioop-lts backport that
# Python 3.13 removed), so it lives in its own isolated venv and is invoked as a
# subprocess. Keeping it separate means a transkun install can never break the
# Demucs/basic-pitch environment that already works.
TRANSKUN_PYTHON = os.environ.get(
    "MIDIMAGIC_TRANSKUN_PYTHON", str(BASE_DIR / ".venv-transkun" / "bin" / "python")
)
TRANSKUN_DEVICE = os.environ.get("MIDIMAGIC_TRANSKUN_DEVICE", "cpu")
TRANSKUN_ENABLED = os.environ.get("MIDIMAGIC_TRANSKUN", "auto").lower() not in ("0", "off", "false", "no")
# Transkun reports key-press durations, not sounding durations, so its output is
# held through the sustain pedal before it reaches the player or the score.
TRANSKUN_MAX_EXTEND = float(os.environ.get("MIDIMAGIC_TRANSKUN_MAX_EXTEND", "6.0"))
# Long audio is transcribed in windows: inference memory grows with input length
# and this box has only ~5 GB free. 4-minute windows with a 6s overlap keep peak
# memory flat and equal to a single short run — the only shape actually measured.
# The overlap exists so a note straddling a boundary is seen whole by at least one
# window; duplicates are merged afterwards.
TRANSKUN_CHUNK_SECONDS = float(os.environ.get("MIDIMAGIC_TRANSKUN_CHUNK", "240"))
TRANSKUN_CHUNK_OVERLAP = float(os.environ.get("MIDIMAGIC_TRANSKUN_OVERLAP", "6"))
# Rough wall-clock cost, measured on this 4-vCPU box (transkun 126s per 200s of
# audio; basic-pitch ~16s per 200s). Used only to show an honest ETA up front.
SPEED_FACTOR = {"transkun": 0.63, "basic-pitch": 0.08, "librosa-pyin": 0.05}

for _d in (DATA_DIR, JOBS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
