"""Stage 4 — post-process the MIDI before handing it to the browser.

The model fragments notes: one piano note routinely comes back as two or three
abutting events, which sounds like a stutter and inflates the note count. The
cleanup here merges those back together, trims same-pitch overlaps, and drops
the low-velocity specks that are almost always noise rather than playing.
"""
from __future__ import annotations

from pathlib import Path

import pretty_midi

CC_SUSTAIN = 64


def clean(midi_path: Path, min_note_len: float = 0.05,
          drop_short: bool = True,
          merge_gap: float = 0.055,
          min_velocity: int = 28,
          quantize: float = 0.0) -> dict:
    """Merge fragments, trim overlaps, drop noise, optionally quantise onsets.

    Returns summary: {note_count, duration, min_pitch, max_pitch,
                      instruments, merged, dropped}.
    """
    pm = pretty_midi.PrettyMIDI(str(midi_path))

    total = 0
    merged_total = 0
    dropped_total = 0

    for inst in pm.instruments:
        kept: list[pretty_midi.Note] = []
        last_by_pitch: dict[int, pretty_midi.Note] = {}

        for note in sorted(inst.notes, key=lambda n: (n.start, n.pitch)):
            if note.end <= note.start:
                continue
            if drop_short and (note.end - note.start) < min_note_len:
                dropped_total += 1
                continue
            # a tiny, quiet blip is model noise, not playing
            if note.velocity < min_velocity and (note.end - note.start) < 0.12:
                dropped_total += 1
                continue
            note.velocity = int(max(20, min(127, note.velocity)))

            prev = last_by_pitch.get(note.pitch)
            if prev is not None:
                if prev.end > note.start:
                    prev.end = note.start            # same pitch overlapping
                # fragmented retrigger of one physical note → glue back together
                if -0.001 <= (note.start - prev.end) <= merge_gap:
                    prev.end = note.end
                    prev.velocity = max(prev.velocity, note.velocity)
                    merged_total += 1
                    last_by_pitch[note.pitch] = prev
                    continue
                if prev.end <= prev.start:
                    kept = [k for k in kept if k is not prev]

            if quantize > 0:
                note.start = round(note.start / quantize) * quantize
                note.end = max(note.start + 0.02, round(note.end / quantize) * quantize)

            last_by_pitch[note.pitch] = note
            kept.append(note)

        kept = [n for n in kept if n.end > n.start]
        inst.notes = sorted(kept, key=lambda n: n.start)
        total += len(inst.notes)

    if total == 0:
        raise ValueError("MIDI bersih kosong — tidak ada not tersisa")

    if quantize > 0:
        for inst in pm.instruments:
            for cc in inst.control_changes:
                cc.time = round(cc.time / quantize) * quantize
    pm.write(str(midi_path))

    pitches = [n.pitch for inst in pm.instruments for n in inst.notes]
    return {
        "note_count": total,
        "duration": float(pm.get_end_time()),
        "min_pitch": min(pitches) if pitches else 0,
        "max_pitch": max(pitches) if pitches else 0,
        "instruments": [i.name or f"program-{i.program}" for i in pm.instruments],
        "merged": merged_total,
        "dropped": dropped_total,
    }


def shift(midi_path: Path, out_path: Path, semitones: int = 0,
          tempo_scale: float = 1.0) -> Path:
    """Server-side transpose / tempo change (used by the export endpoint)."""
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    if semitones:
        for inst in pm.instruments:
            for n in inst.notes:
                n.pitch = int(max(0, min(127, n.pitch + semitones)))
    if tempo_scale != 1.0:
        for inst in pm.instruments:
            for n in inst.notes:
                n.start /= tempo_scale
                n.end /= tempo_scale
            # sustain events must move with the notes or the pedal drifts
            for cc in inst.control_changes:
                cc.time /= tempo_scale
            for pb in inst.pitch_bends:
                pb.time /= tempo_scale
        for ts in pm.time_signature_changes:
            ts.time /= tempo_scale
    pm.write(str(out_path))
    return out_path


def pedal_summary(midi_path: Path) -> dict:
    """Read CC64 back out of a MIDI (used by the API to report pedal coverage)."""
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    events = sorted(
        (cc for inst in pm.instruments for cc in inst.control_changes
         if cc.number == CC_SUSTAIN),
        key=lambda c: c.time,
    )
    segments = 0
    pedalled = 0.0
    start: float | None = None
    for cc in events:
        if cc.value >= 64 and start is None:
            start = cc.time
        elif cc.value < 64 and start is not None:
            pedalled += max(0.0, cc.time - start)
            segments += 1
            start = None
    total = float(pm.get_end_time()) or 1.0
    return {
        "segments": segments,
        "pedalled_seconds": round(pedalled, 2),
        "ratio": round(pedalled / total, 3),
    }
