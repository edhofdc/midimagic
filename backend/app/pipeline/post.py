"""Stage 4 — post-process the MIDI before handing it to the browser."""
from __future__ import annotations

from pathlib import Path

import pretty_midi


def clean(midi_path: Path, min_note_len: float = 0.05,
          drop_short: bool = True) -> dict:
    """Normalise velocity, drop micro-notes, clamp overlapping duplicates.

    Returns summary: {note_count, duration, min_pitch, max_pitch, instruments}.
    """
    pm = pretty_midi.PrettyMIDI(str(midi_path))

    total_notes = 0
    for inst in pm.instruments:
        kept: list[pretty_midi.Note] = []
        last_by_pitch: dict[int, pretty_midi.Note] = {}
        for note in sorted(inst.notes, key=lambda n: (n.start, n.pitch)):
            if note.end <= note.start:
                continue
            if drop_short and (note.end - note.start) < min_note_len:
                continue
            note.velocity = int(max(20, min(127, note.velocity)))
            prev = last_by_pitch.get(note.pitch)
            if prev is not None and prev.end > note.start:
                prev.end = note.start          # trim overlap on same pitch
                if prev.end <= prev.start:
                    continue
            last_by_pitch[note.pitch] = note
            kept.append(note)
        # restore chronological order after the trims above
        for n in kept:
            if n.end <= n.start:
                continue
        inst.notes = sorted(kept, key=lambda n: n.start)
        total_notes += len(inst.notes)

    if total_notes == 0:
        raise ValueError("MIDI bersih kosong — tidak ada not tersisa")

    pm.write(str(midi_path))

    pitches = [n.pitch for inst in pm.instruments for n in inst.notes]
    return {
        "note_count": total_notes,
        "duration": float(pm.get_end_time()),
        "min_pitch": min(pitches) if pitches else 0,
        "max_pitch": max(pitches) if pitches else 0,
        "instruments": [i.name or f"program-{i.program}" for i in pm.instruments],
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
        for ts in pm.time_signature_changes:
            ts.time /= tempo_scale
    pm.write(str(out_path))
    return out_path
