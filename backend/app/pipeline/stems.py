"""Stage 2 — optional AI stem separation (Demucs)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .. import config

Log = Callable[[str, str], None]


class StemError(RuntimeError):
    pass


def demucs_bin() -> str:
    exe = config.BASE_DIR / ".venv" / "bin" / "demucs"
    if exe.exists():
        return str(exe)
    found = shutil.which("demucs")
    if not found:
        raise StemError("demucs tidak terpasang")
    return found


def separate(
    src_wav: Path,
    job_dir: Path,
    mode: str,
    log: Log,
) -> dict[str, Path]:
    """Run demucs. mode='vocals' (2-stem, fast) or 'full' (4-stem).

    Returns {'vocals': Path, 'drums':..., 'bass':..., 'other':..., 'instrumental': Path}
    """
    out_dir = job_dir / "stems"
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [demucs_bin(), "-n", config.DEMUCS_MODEL, "-o", str(out_dir)]
    if mode == "vocals":
        cmd += ["--two-stems", config.DEMUCS_TWO_STEMS]
        log("separating", "memisahkan vokal (2-stem, mode cepat)…")
    else:
        log("separating", "memisahkan 4 stem (vokal/drum/bass/instrumen)…")
    cmd.append(str(src_wav))

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise StemError(f"demucs gagal: {(proc.stderr or proc.stdout).strip()[-500:]}")

    root = out_dir / config.DEMUCS_MODEL / src_wav.stem
    if not root.exists():
        found = list(out_dir.rglob("*.wav"))
        if not found:
            raise StemError("demucs selesai tapi tidak ada stem dihasilkan")
        root = found[0].parent

    stems: dict[str, Path] = {}
    for wav in sorted(root.glob("*.wav")):
        stems[wav.stem] = wav

    if "vocals" in stems and "no_vocals" in stems:
        # demucs names the residual "no_vocals" in two-stem mode
        stems["instrumental"] = stems.pop("no_vocals")
    elif mode == "full":
        # synthesise an instrumental bed from everything except vocals
        bed_parts = [stems[k] for k in ("drums", "bass", "other") if k in stems]
        if bed_parts:
            stems["instrumental"] = _mix(bed_parts, job_dir / "stems" / "instrumental.wav")

    log("separating", "stem siap: " + ", ".join(sorted(stems)))
    return stems


def _mix(parts: list[Path], dst: Path) -> Path:
    cmd = [shutil.which("ffmpeg") or "ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", f"amix=inputs={len(parts)}:normalize=0",
            "-c:a", "pcm_s16le", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise StemError(f"gagal mix instrumental: {r.stderr.strip()[:300]}")
    return dst
