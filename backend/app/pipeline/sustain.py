"""Stage 3b — infer the sustain pedal (MIDI CC64) from the recording.

A piano pedal is audible, not guessable: when it is down the strings keep
ringing through the gaps between notes instead of being damped. So for every
gap between two consecutive note onsets we measure the RMS of the gap against
the RMS of the note that precedes it. A gap that stays loud is a ringing tail →
pedal down; a gap that falls away to near silence is real damping → pedal up.

Consecutive ringing gaps chain into one pedal region that spans from the first
note of the run to the onset that breaks it — which is how a player actually
uses the pedal, holding it across a phrase rather than stabbing it per note.

The result is written into the MIDI as CC64 events, so the pedal travels with
the file: the player replays it, and so does anyone who exports or shares a .mid.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pretty_midi

CC_SUSTAIN = 64

# A gap counts as "still ringing" when its energy stays above this fraction of
# the preceding note's energy. ~-13 dB: below that a damped piano tail has
# already died away; accompaniment bleed keeps sustained-instrument tracks above
# it, which is the honest answer for a full mix.
RINGING_RATIO = 0.22
MIN_GAP = 0.030          # shorter than this and the notes simply overlap
MIN_PEDAL = 0.060        # drop pedal stabs shorter than this
MERGE_PEDAL = 0.150      # glue regions separated by less than this
MAX_PEDAL = 8.0          # a real player re-presses; also bounds voice build-up
REPRESS = 0.120          # brief lift between re-presses (~6% into a 2s release)
MIN_NOTES = 4            # too few notes to infer anything


def analyze(audio_path: Path, midi_path: Path, log=None) -> dict:
    """Detect pedal regions from `audio_path` and write CC64 into `midi_path`.

    Returns a summary: {segments, pedalled_seconds, ratio}.
    """
    def _log(msg: str) -> None:
        if log:
            log("finalizing", msg)

    empty = {"segments": 0, "pedalled_seconds": 0.0, "ratio": 0.0}

    try:
        import librosa
    except ImportError:                                     # pragma: no cover
        return {**empty, "skipped": True}

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes = sorted((n for inst in pm.instruments for n in inst.notes),
                   key=lambda n: (n.start, n.pitch))
    if len(notes) < MIN_NOTES:
        return {**empty, "skipped": True}

    try:
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    except Exception as exc:                                # noqa: BLE001
        _log(f"pedal: audio tidak terbaca ({exc})")
        return {**empty, "skipped": True}
    if y.size == 0:
        return {**empty, "skipped": True}

    hop = 512
    frame_dur = hop / sr
    rms = librosa.feature.rms(y=y, hop_length=hop, frame_length=2048)[0]
    n_frames = rms.shape[0]

    def band_rms(t0: float, t1: float) -> float:
        a, b = max(0, int(round(t0 / frame_dur))), min(n_frames, int(round(t1 / frame_dur)))
        if b <= a:
            return 0.0
        # a high percentile, not the mean: one ringing overtone is enough
        # evidence, and the mean is dragged down by any quiet frame
        return float(np.percentile(rms[a:b], 75))

    # onsets, with the end of the last note that starts on each
    onsets: list[tuple[float, float]] = []
    seen: set[float] = set()
    ends: dict[float, float] = {}
    for n in notes:
        key = round(n.start, 4)
        seen.add(key)
        ends[key] = max(ends.get(key, 0.0), n.end)
    for key in sorted(seen):
        onsets.append((key, ends[key]))

    # loudness of each note body, skipping the attack transient
    note_level: list[float] = []
    for start, end in onsets:
        span = end - start
        a = start + min(0.05, span * 0.3)
        note_level.append(band_rms(a, end) if span > 0.02 else band_rms(start, end))

    # which inter-note gaps are still ringing?
    ringing: list[bool] = []
    ratios: list[float] = []
    for i in range(len(onsets) - 1):
        gap = onsets[i + 1][0] - onsets[i][1]
        if gap <= MIN_GAP:
            ringing.append(True)                 # notes overlap → pedal down
            ratios.append(1.0)
            continue
        level = note_level[i]
        if level <= 1e-7:
            ringing.append(False)
            continue
        gap_level = band_rms(onsets[i][1] + gap * 0.15, onsets[i + 1][0] - gap * 0.15)
        ratio = gap_level / level
        ratios.append(ratio)
        ringing.append(ratio >= RINGING_RATIO)

    # chain runs of ringing gaps into pedal regions that include the notes
    regions: list[list[float]] = []
    i, n_gaps = 0, len(ringing)
    while i < n_gaps:
        if not ringing[i]:
            i += 1
            continue
        j = i
        while j + 1 < n_gaps and ringing[j + 1]:
            j += 1
        regions.append([onsets[i][0], onsets[j + 1][0]])
        i = j + 1

    # a trailing ring after the last note is also evidence of a held pedal
    last_start, last_end = onsets[-1]
    tail = band_rms(last_end + 0.05, last_end + 0.45)
    if tail > 1e-7 and max(note_level, default=0.0) > 1e-7:
        if tail / max(note_level) >= RINGING_RATIO:
            if regions and abs(regions[-1][1] - last_start) < MERGE_PEDAL:
                regions[-1][1] = last_end + 0.35
            else:
                regions.append([last_start, last_end + 0.35])
    if regions and abs(regions[-1][1] - last_start) < MERGE_PEDAL:
        regions[-1][1] = max(regions[-1][1], last_end)

    regions = _merge(regions, MERGE_PEDAL)
    regions = [(a, b) for a, b in regions if b - a >= MIN_PEDAL]
    regions = _split_long(regions, MAX_PEDAL, REPRESS)

    med = round(float(np.median(ratios)) if ratios else 0.0, 3)
    if not regions:
        _log("pedal: tidak ada sustain terdeteksi (permainan staccato / kering)")
        return {**empty, "ratio": med, "skipped": False, "gaps": len(ratios)}

    _write_cc64(pm, regions, midi_path)
    pedalled = sum(b - a for a, b in regions)
    total = float(pm.get_end_time()) or 1.0
    _log(f"pedal: {len(regions)} segmen, {pedalled / total * 100:.0f}% durasi "
         f"(median rasio jeda {med:.2f}, ambang {RINGING_RATIO:.2f})")
    return {
        "segments": len(regions),
        "pedalled_seconds": round(pedalled, 2),
        "ratio": round(pedalled / total, 3),
        "median_gap_ratio": med,
        "gaps": len(ratios),
        "skipped": False,
    }


# ------------------------------------------------------------------ helpers

def _merge(regions: list[list[float]], gap: float) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(regions):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _note_end_at(notes: list[pretty_midi.Note], start: float) -> float:
    """End of the last note that starts at (or just before) `start`."""
    end = start
    for n in notes:
        if abs(n.start - start) < 1e-3 and n.end > end:
            end = n.end
    return end


def _split_long(regions: list[tuple[float, float]], max_len: float,
                lift: float) -> list[tuple[float, float]]:
    """Break very long pedal holds into re-pressed chunks.

    A continuously pedalled performance (solo piano with the damper held down
    for a whole phrase) comes out as one enormous region. Splitting it with a
    short lift costs nothing audibly — a ~120 ms cut inside a 2 s release tail
    leaves the note at over 90% of its level — but it is how a player actually
    re-presses, and it bounds the number of voices the engine keeps alive.
    """
    if max_len <= 0:
        return regions
    out: list[tuple[float, float]] = []
    for a, b in regions:
        while b - a > max_len:
            out.append((a, a + max_len))
            a = a + max_len + lift
        if b > a:
            out.append((a, b))
    return out


def _write_cc64(pm: pretty_midi.PrettyMIDI, regions: list[tuple[float, float]],
                out_path: Path) -> None:
    if not pm.instruments:
        return
    inst = pm.instruments[0]
    inst.control_changes = [c for c in inst.control_changes if c.number != CC_SUSTAIN]
    for a, b in regions:
        inst.control_changes.append(pretty_midi.ControlChange(CC_SUSTAIN, 127, float(a)))
        inst.control_changes.append(pretty_midi.ControlChange(CC_SUSTAIN, 0, float(b)))
    inst.control_changes.sort(key=lambda c: c.time)
    pm.write(str(out_path))
