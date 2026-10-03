"use client";

import { Midi } from "@tonejs/midi";
import type { NoteEvent } from "./audio";

export interface LoadedMidi {
  notes: NoteEvent[];
  duration: number;
  tempo: number;
  trackCount: number;
  name: string;
}

/** Fetch a .mid from the backend and normalise it into a flat note list. */
export async function loadMidi(url: string): Promise<LoadedMidi> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`gagal memuat MIDI (${res.status})`);
  const buf = await res.arrayBuffer();
  return parseMidiBuffer(buf);
}

export function parseMidiBuffer(buf: ArrayBuffer, name = ""): LoadedMidi {
  const midi = new Midi(buf);
  const notes: NoteEvent[] = [];
  for (const track of midi.tracks) {
    for (const n of track.notes) {
      notes.push({
        midi: n.midi,
        start: n.time,
        end: n.time + n.duration,
        velocity: n.velocity > 0 ? n.velocity : 0.75,
      });
    }
  }
  notes.sort((a, b) => a.start - b.start);
  const tempo = midi.header.tempos[0]?.bpm ?? 120;
  return {
    notes,
    duration: midi.duration || Math.max(0, ...notes.map((n) => n.end), 0),
    tempo,
    trackCount: midi.tracks.length,
    name: midi.name || name,
  };
}

/** Trim notes outside the 88-key range and optionally thin out very dense chords. */
export function sanitizeNotes(notes: NoteEvent[], maxChord = 10): NoteEvent[] {
  const inRange = notes.filter((n) => n.midi >= 21 && n.midi <= 108 && n.end > n.start);
  const out: NoteEvent[] = [];
  let i = 0;
  while (i < inRange.length) {
    const onset = inRange[i].start;
    const group: NoteEvent[] = [];
    let j = i;
    while (j < inRange.length && inRange[j].start - onset < 0.035) {
      group.push(inRange[j]);
      j++;
    }
    group.sort((a, b) => b.velocity - a.velocity);
    out.push(...group.slice(0, maxChord).sort((a, b) => a.midi - b.midi));
    i = j;
  }
  return out;
}

export function formatTime(sec: number): string {
  if (!isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
