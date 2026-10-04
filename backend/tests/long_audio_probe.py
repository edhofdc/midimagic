#!/usr/bin/env python3
"""Measure the long-audio path: wall clock and PEAK memory per stage.

The question "can it handle a 98-minute video?" is really a memory question on this
box (~5 GB free) plus an honest time estimate. So this builds a long file by tiling
a recording we already have, runs the chunked transkun path on it, and samples RSS
of every child process while it runs.

usage: python -m tests.long_audio_probe <source.wav> <minutes> [engine]
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.pipeline import transcribe  # noqa: E402


def _sample() -> int:
    """RSS (MB) of every transkun/uvicorn process currently alive."""
    try:
        out = subprocess.run(["ps", "-eo", "rss,args"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return 0
    tot = 0
    for line in out.strip().splitlines()[1:]:
        if "transkun" in line or "uvicorn" in line:
            try:
                tot += int(line.split(None, 1)[0])
            except ValueError:
                pass
    return tot // 1024


def main() -> int:
    src = Path(sys.argv[1])
    minutes = float(sys.argv[2])
    engine = sys.argv[3] if len(sys.argv) > 3 else "transkun"

    data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    TARGET_SR = 22050
    # length must be computed at the rate we WRITE at, not the source rate —
    # mixing them built a 40-minute file when 20 was asked for
    need = int(minutes * 60 * TARGET_SR)
    reps = int(need / len(mono)) + 1
    # np.tile, not list multiplication: tolist() on 20 minutes of audio would build
    # tens of millions of Python floats (~1 GB) just to write them straight back.
    import numpy as np
    long = np.tile(mono, reps)[:need]
    out_wav = Path("/tmp/tk/long_%dm.wav" % int(minutes))
    sf.write(str(out_wav), long, TARGET_SR)
    dur = len(long) / TARGET_SR
    print(f"built {out_wav}  {dur/60:.1f} min @22.05k mono  "
          f"({out_wav.stat().st_size/1e6:.0f} MB)")

    peak = {"mb": 0}
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            peak["mb"] = max(peak["mb"], _sample())
            time.sleep(1.0)

    th = threading.Thread(target=watch, daemon=True)
    th.start()

    midi = Path("/tmp/tk/long_out.mid")
    midi.unlink(missing_ok=True)
    opts = {"tempo": 120.0, "min_note_length": 0.015, "merge_gap": 0.0, "min_velocity": 10}
    t0 = time.time()

    def log(stage: str, msg: str) -> None:
        print(f"  [{time.time()-t0:7.1f}s] {stage}: {msg}", flush=True)

    def prog(frac: float, msg: str) -> None:
        print(f"  [{time.time()-t0:7.1f}s] progress {frac*100:5.1f}%: {msg}", flush=True)

    ok = True
    try:
        transcribe.transcribe(out_wav, midi, engine, opts, log, progress=prog)
    except Exception as exc:
        ok = False
        print(f"  FAILED: {type(exc).__name__}: {exc}")
    elapsed = time.time() - t0
    stop.set()
    th.join(timeout=3)

    print()
    print(f"engine     : {engine}")
    print(f"audio      : {dur/60:.1f} min")
    print(f"wall clock : {elapsed:.0f}s  ({elapsed/dur:.2f}x realtime)")
    print(f"peak RSS   : {peak['mb']} MB  (free on box: check `free -m`)")
    if midi.exists():
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(str(midi))
        n = sum(len(i.notes) for i in pm.instruments)
        cc = sum(len(i.control_changes) for i in pm.instruments)
        end = max((x.end for i in pm.instruments for x in i.notes), default=0)
        print(f"notes      : {n}  ({n/dur*60:.0f} per minute)")
        print(f"CC events  : {cc}")
        print(f"last note  : {end:.0f}s  (audio is {dur:.0f}s)")
        print(f"render     : {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
