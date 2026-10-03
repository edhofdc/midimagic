#!/usr/bin/env python3
"""Download real instrument samples into web/public/audio/.

- Grand piano: Salamander Grand Piano (Alexander Holm, CC-BY 3.0), the sample set
  Tone.js itself ships in its examples. 30 notes spanning A0..C8.
- Everything else: MusyngKite soundfonts (gleitz/midi-js-soundfonts). We keep every
  third semitone — Tone.Sampler pitch-shifts +/-1.5 semitones transparently, so this
  is ~30 files per instrument instead of 88 with no audible penalty.

Run once after cloning:    python3 scripts/fetch_samples.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "audio"

SALAMANDER = "https://tonejs.github.io/audio/salamander/{file}.mp3"
SALAMANDER_NOTES = [
    "A0", "C1", "D#1", "F#1", "A1", "C2", "D#2", "F#2", "A2", "C3",
    "D#3", "F#3", "A3", "C4", "D#4", "F#4", "A4", "C5", "D#5", "F#5",
    "A5", "C6", "D#6", "F#6", "A6", "C7", "D#7", "F#7", "A7", "C8",
]


def salamander_file(note: str) -> str:
    """The Salamander set spells sharps with an 's' (Ds1.mp3), not a '#'."""
    return f"{note.replace('#', 's')}.mp3"

SF_BASE = "https://gleitz.github.io/midi-js-soundfonts/MusyngKite/{inst}-mp3.js"
SOUNDFONTS = {
    "electric-piano": "electric_piano_1",
    "guitar": "acoustic_guitar_nylon",
    "strings": "string_ensemble_1",
}

PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi_of(name: str) -> int:
    m = re.match(r"^([A-G])([b#]?)(-?\d+)$", name)
    if not m:
        return -1
    pc = PITCH_CLASS[m.group(1)]
    if m.group(2) == "b":
        pc -= 1
    elif m.group(2) == "#":
        pc += 1
    return (int(m.group(3)) + 1) * 12 + pc


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "midimagic-sampler"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_salamander() -> dict[str, str]:
    dest = OUT / "salamander"
    dest.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = {}
    total = 0
    for i, note in enumerate(SALAMANDER_NOTES, 1):
        fname = salamander_file(note)
        path = dest / fname
        if not path.exists():
            path.write_bytes(fetch(SALAMANDER.format(file=fname[:-4])))
        urls[note] = f"/audio/salamander/{fname}"
        total += path.stat().st_size
        print(f"  [{i:2}/{len(SALAMANDER_NOTES)}] {note:<4} {path.stat().st_size/1024:7.1f} KB", flush=True)
    print(f"  salamander total: {total/1024/1024:.1f} MB")
    return urls


def download_soundfont(inst_id: str, sf_name: str) -> dict[str, str]:
    dest = OUT / inst_id
    dest.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {sf_name}-mp3.js …", flush=True)
    text = fetch(SF_BASE.format(inst=sf_name), timeout=180).decode("utf-8", "replace")

    pairs = re.findall(r'"([A-G][b#]?-?\d+)"\s*:\s*"data:audio/mp3;base64,([A-Za-z0-9+/=]+)"', text)
    if not pairs:
        raise RuntimeError(f"tidak ada sample ter-parse dari {sf_name}")

    urls: dict[str, str] = {}
    total = 0
    for note, b64 in pairs:
        # keep every third semitone (C, D#, F# …) plus the lowest A
        if midi_of(note) % 3 != 0 and note != "A0":
            continue
        fname = f"{note.replace('#', 's')}.mp3"
        path = dest / fname
        if not path.exists():
            path.write_bytes(base64.b64decode(b64))
        urls[note] = f"/audio/{inst_id}/{fname}"
        total += path.stat().st_size
    print(f"  {inst_id}: {len(urls)} sample, {total/1024/1024:.1f} MB")
    return urls


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict[str, str]] = {}

    print("grand piano — Salamander (CC-BY 3.0, Alexander Holm)")
    index["grand-piano"] = download_salamander()

    for inst_id, sf in SOUNDFONTS.items():
        print(f"{inst_id} — MusyngKite / {sf}")
        index[inst_id] = download_soundfont(inst_id, sf)

    manifest = ROOT / "web" / "src" / "lib" / "sample-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")

    total = sum(p.stat().st_size for p in OUT.rglob("*.mp3"))
    print(f"\nwrote {manifest.relative_to(ROOT)}")
    print(f"total samples: {total/1024/1024:.1f} MB in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
