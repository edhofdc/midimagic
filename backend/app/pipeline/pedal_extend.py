"""Extend note offsets by the sustain pedal — the standard piano-MIDI convention.

A piano transcription model trained without pedal extension reports how long the
*key* was held, not how long the *note sounded*. On a fast piece that is tens of
milliseconds per note: Rachmaninoff Op. 39 No. 6 came out with a median note of
0.054s, which is honest about the key press but wrong about the music — under the
damper pedal those notes ring for as long as the pedal is down.

This matters well beyond tidiness:
  - playback: short notes sound plucked and choppy, not like a piano
  - scoring: every frame where nothing is sounding drags chroma similarity down
    (measured: 0.842 with raw offsets vs 0.879 for a frame-based model that
    happens to smear its offsets long), so the raw output *looks* worse than it is
  - notation: the score shows staccato everywhere

So hold each note until the pedal is released, subject to three limits: never past
the next onset of the same pitch (a re-strike damps the string), never past the
end of the recording, and never beyond `max_extend` seconds.
"""
from __future__ import annotations

from pathlib import Path

import pretty_midi

CC_SUSTAIN = 64
DEFAULT_MAX_EXTEND = 6.0
# re-strike damping: leave a sliver of silence so repeated notes stay articulated
RESTRIKE_GAP = 0.03


def pedal_segments(pm: pretty_midi.PrettyMIDI, threshold: int = 64) -> list[tuple[float, float]]:
    """Sustain-pedal down/up pairs from CC64, clipped to the piece."""
    events: list[tuple[float, bool]] = []
    for inst in pm.instruments:
        for cc in inst.control_changes:
            if cc.number == CC_SUSTAIN:
                events.append((cc.time, cc.value >= threshold))
    events.sort(key=lambda e: e[0])
    if not events:
        return []

    end_of_piece = pm.get_end_time()
    segments: list[tuple[float, float]] = []
    start: float | None = None
    for t, down in events:
        if down and start is None:
            start = t
        elif not down and start is not None:
            if t > start:
                segments.append((start, t))
            start = None
    if start is not None and end_of_piece > start:
        segments.append((start, end_of_piece))
    return segments


def _segment_end_at(segments: list[tuple[float, float]], t: float) -> float | None:
    """End of the pedal segment containing `t`, if any."""
    for s, e in segments:
        if s <= t < e:
            return e
    return None


def extend_by_pedal(
    midi_path: Path,
    out_path: Path | None = None,
    max_extend: float = DEFAULT_MAX_EXTEND,
    restrike_gap: float = RESTRIKE_GAP,
) -> dict:
    """Write `midi_path` with note offsets held through the sustain pedal.

    Returns a summary: notes seen, notes extended, total seconds added.
    """
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    segments = pedal_segments(pm)
    info = {"notes": 0, "extended": 0, "added_seconds": 0.0, "pedal_segments": len(segments)}
    if not segments:
        info["skipped"] = True
        if out_path and out_path != midi_path:
            pm.write(str(out_path))
        return info

    end_of_piece = pm.get_end_time()
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        # next onset of the same pitch, for re-strike damping
        onsets: dict[int, list[float]] = {}
        for n in inst.notes:
            onsets.setdefault(n.pitch, []).append(n.start)
        for v in onsets.values():
            v.sort()

        for n in inst.notes:
            info["notes"] += 1
            pedal_end = _segment_end_at(segments, n.end)
            if pedal_end is None:
                continue
            target = min(pedal_end, n.start + max_extend, end_of_piece)
            for nxt in onsets[n.pitch]:
                if nxt > n.end + 1e-6:
                    target = min(target, nxt - restrike_gap)
                    break
            if target > n.end + 1e-3:
                info["added_seconds"] += target - n.end
                info["extended"] += 1
                n.end = target

    pm.write(str(out_path or midi_path))
    info["added_seconds"] = round(info["added_seconds"], 2)
    return info


def main() -> int:
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src
    print(extend_by_pedal(src, dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
