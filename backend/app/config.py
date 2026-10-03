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
YTDLP_MAX_DURATION = int(os.environ.get("MIDIMAGIC_YT_MAX_SECONDS", "900"))  # 15 min guard
# YouTube extraction needs a JS runtime since yt-dlp 2025.x; node is the one we ship with.
YTDLP_JS_RUNTIME = os.environ.get("MIDIMAGIC_YT_JS_RUNTIME", "node")

# Demucs
DEMUCS_MODEL = os.environ.get("MIDIMAGIC_DEMUCS_MODEL", "htdemucs")
DEMUCS_TWO_STEMS = "vocals"

for _d in (DATA_DIR, JOBS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
