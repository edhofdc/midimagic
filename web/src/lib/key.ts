"use client";

/**
 * Key detection from the transcribed notes.
 *
 * Without this the score is engraved as if everything were in C major, so a
 * piece in A minor comes out littered with sharps and flats and the key
 * signature is simply wrong.
 *
 * Krumhansl-Kessler profiles: weight each pitch class by how long it sounds,
 * correlate against the 24 rotated major/minor profiles, take the best fit.
 *
 * The duration weighting is multiplied by a register boost because raw duration
 * is not enough on chromatic repertoire — Rachmaninoff's Op. 39 No. 6 scores
 * 0.9717 for E major against 0.9715 for its actual key, A minor, which is a
 * coin toss. The bass carries the tonality, so low notes get more say. Measured
 * against two pieces with known keys (Op. 39 No. 6 in A minor, Canon in D in D
 * major) this weighting is the one that gets both right; plain duration gets
 * the Rachmaninoff wrong, as do onset count alone, the lowest third of the
 * notes, and the closing harmony alone.
 */

import type { NoteEvent } from "./audio";

const MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88];
const MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17];

const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/** Most keys spell black notes as flats. */
const FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

const SHARP_KEYS = new Set(["G", "D", "A", "E", "B", "F#", "C#"]);

/** Pitch below which bass notes start getting extra weight, and how much. */
const BASS_PIVOT = 72; // C5
const BASS_SPAN = 24; // two octaves
const BASS_MAX = 1.0; // up to 2x at the bottom of the piano

export interface DetectedKey {
  /** VexFlow key spec, e.g. "C", "Am", "F#m", "Bb" */
  vex: string;
  tonic: number; // pitch class
  mode: "major" | "minor";
  label: string; // e.g. "A minor"
  /** correlation of the winning profile, 0..1 */
  confidence: number;
  /** how much the runner-up lost by — small means the key is ambiguous */
  margin: number;
}

function correlate(hist: number[], profile: number[], shift: number): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < 12; i++) {
    const a = hist[(i + shift) % 12];
    const b = profile[i];
    dot += a * b;
    na += a * a;
    nb += b * b;
  }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) + 1e-12);
}

export function pitchClassHistogram(notes: NoteEvent[]): number[] {
  const hist = new Array(12).fill(0);
  for (const n of notes) {
    const midi = Math.round(n.midi);
    const dur = Math.max(0.02, n.end - n.start);
    const bass = 1 + (BASS_MAX * Math.max(0, BASS_PIVOT - midi)) / BASS_SPAN;
    hist[((midi % 12) + 12) % 12] += dur * bass;
  }
  return hist;
}

/** Standard key signatures, for the manual override in the score panel. */
export const KEY_CHOICES: { vex: string; label: string }[] = [
  ["C", "C major"], ["G", "G major"], ["D", "D major"], ["A", "A major"],
  ["E", "E major"], ["B", "B major"], ["F#", "F# major"], ["C#", "C# major"],
  ["F", "F major"], ["Bb", "Bb major"], ["Eb", "Eb major"], ["Ab", "Ab major"],
  ["Db", "Db major"], ["Gb", "Gb major"],
  ["Am", "A minor"], ["Em", "E minor"], ["Bm", "B minor"], ["F#m", "F# minor"],
  ["C#m", "C# minor"], ["G#m", "G# minor"], ["D#m", "D# minor"],
  ["Dm", "D minor"], ["Gm", "G minor"], ["Cm", "C minor"], ["Fm", "F minor"],
  ["Bbm", "Bb minor"], ["Ebm", "Eb minor"], ["Abm", "Ab minor"],
].map(([vex, label]) => ({ vex, label }));

export function keyFromVex(vex: string): DetectedKey {
  const minor = vex.endsWith("m") && vex.length > 1;
  const name = minor ? vex.slice(0, -1) : vex;
  const idx = (minor ? FLAT_NAMES : FLAT_NAMES).indexOf(name);
  const tonic = idx >= 0 ? idx : Math.max(0, NAMES.indexOf(name));
  const label = KEY_CHOICES.find((k) => k.vex === vex)?.label ?? `${name} ${minor ? "minor" : "major"}`;
  return { vex, tonic, mode: minor ? "minor" : "major", label, confidence: 1, margin: 1 };
}

export function detectKey(notes: NoteEvent[]): DetectedKey {
  const hist = pitchClassHistogram(notes);
  const fallback: DetectedKey = {
    vex: "C",
    tonic: 0,
    mode: "major",
    label: "C major",
    confidence: 0,
    margin: 1,
  };
  if (!hist.some((v) => v > 0)) return fallback;

  const scored: { score: number; tonic: number; mode: "major" | "minor" }[] = [];
  for (let tonic = 0; tonic < 12; tonic++) {
    for (const mode of ["major", "minor"] as const) {
      scored.push({
        score: correlate(hist, mode === "major" ? MAJOR : MINOR, tonic),
        tonic,
        mode,
      });
    }
  }
  scored.sort((a, b) => b.score - a.score);

  const top = scored[0];
  const useFlats = top.mode === "major"
    ? !SHARP_KEYS.has(NAMES[top.tonic])
    : !SHARP_KEYS.has(NAMES[(top.tonic + 3) % 12]);
  const name = useFlats ? FLAT_NAMES[top.tonic] : NAMES[top.tonic];

  return {
    vex: top.mode === "minor" ? `${name}m` : name,
    tonic: top.tonic,
    mode: top.mode,
    label: `${name} ${top.mode}`,
    confidence: top.score,
    margin: top.score - scored[1].score,
  };
}
