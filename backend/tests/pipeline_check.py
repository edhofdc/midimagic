#!/usr/bin/env python3
"""Exercise the accuracy + pedal pipeline on a real job's audio, in isolation.

Usage: ./.venv/bin/python tests/pipeline_check.py <source.wav> [--fast]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import post, sustain, transcribe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--preset", default="balanced")
    ap.add_argument("--out", default="/tmp/mm_check")
    args = ap.parse_args()

    src = Path(args.wav)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def log(stage: str, msg: str) -> None:
        print(f"[{stage:>12}] {msg}", flush=True)

    opts = transcribe.resolve_options({"accuracy": args.preset})
    print(f"preset={opts['preset']} onset={opts['onset_threshold']} "
          f"frame={opts['frame_threshold']} minlen={opts['min_note_length']} "
          f"freq={opts['min_frequency']}-{opts['max_frequency']} "
          f"hpss={opts['suppress_percussion']}")

    t0 = time.time()
    prepared = transcribe.prepare(src, out / "prepared.wav", opts, log)
    t_prep = time.time() - t0

    engine = transcribe.engine_available()
    midi = out / "raw.mid"
    t0 = time.time()
    transcribe.transcribe(prepared, midi, engine, opts, log)
    t_tr = time.time() - t0

    t0 = time.time()
    summary = post.clean(midi, min_note_len=float(opts["min_note_length"]))
    t_clean = time.time() - t0

    t0 = time.time()
    pedal = sustain.analyze(prepared, midi, log)
    t_ped = time.time() - t0

    written = post.pedal_summary(midi)
    print()
    print(f"engine        : {engine}")
    print(f"prepare       : {t_prep:.1f}s")
    print(f"transcribe    : {t_tr:.1f}s")
    print(f"clean         : {t_clean:.1f}s  ({summary['merged']} merged, "
          f"{summary['dropped']} dropped)")
    print(f"pedal detect  : {t_ped:.1f}s")
    print(f"notes         : {summary['note_count']}")
    print(f"pitch range   : {summary['min_pitch']}..{summary['max_pitch']}")
    print(f"duration      : {summary['duration']:.1f}s")
    print(f"pedal         : {written['segments']} segmen, "
          f"{written['pedalled_seconds']:.1f}s "
          f"({written['ratio'] * 100:.0f}% durasi)")
    print(f"midi written  : {midi}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
