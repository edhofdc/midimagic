"use client";

/**
 * MIDI → standard notation, rendered with VexFlow as a piano grand staff.
 *
 * Deliberately pragmatic rather than a full engraver, but it has to agree with
 * the recording or the score is useless:
 *
 *  - the quantisation grid is *chosen from the music*, not fixed at a 1/16 —
 *    a fast etude quantised to 1/16 turns sixteenth runs into noise;
 *  - the key signature comes from a Krumhansl fit over the transcribed notes,
 *    so a piece in A minor is not engraved as C major with accidentals on
 *    every other note;
 *  - chords containing a semitone cluster are thinned, because VexFlow cannot
 *    render two noteheads a second apart in one chord.
 */

import {
  Accidental,
  Beam,
  Dot,
  Formatter,
  Renderer,
  Stave,
  StaveNote,
  Voice,
} from "vexflow";
import type { NoteEvent, PedalEvent } from "./audio";
import { detectKey, type DetectedKey } from "./key";
import { midiToName } from "./keys";

const PPQ = 480; // ticks per quarter note
const MEASURE = PPQ * 4; // 4/4
const SPLIT = 60; // C4: the conventional grand-staff division

interface Dur {
  ticks: number;
  code: string;
  dots: number;
}

/** Largest-first so the greedy decomposition uses as few glyphs as possible. */
const DURATIONS: Dur[] = [
  { ticks: 1920, code: "w", dots: 0 },
  { ticks: 1440, code: "h", dots: 1 },
  { ticks: 960, code: "h", dots: 0 },
  { ticks: 720, code: "q", dots: 1 },
  { ticks: 480, code: "q", dots: 0 },
  { ticks: 360, code: "8", dots: 1 },
  { ticks: 240, code: "8", dots: 0 },
  { ticks: 180, code: "16", dots: 1 },
  { ticks: 120, code: "16", dots: 0 },
  { ticks: 90, code: "32", dots: 1 },
  { ticks: 60, code: "32", dots: 0 },
  { ticks: 30, code: "64", dots: 0 },
];

export interface ScoreOptions {
  measuresPerLine?: number;
  maxMeasures?: number;
  tempo?: number;
  key?: DetectedKey;
  /** pedal regions from the recording — engraved as Ped. / * under the bass staff */
  pedal?: PedalEvent[];
}

export interface RenderResult {
  measuresRendered: number;
  totalMeasures: number;
  grid: number;
  key: string;
}

interface Chord {
  tick: number;
  endTick: number;
  pitches: number[];
}

const keyOf = (midi: number) => {
  const m = /^([A-G][#b]?)(-?\d+)$/.exec(midiToName(midi))!;
  return `${m[1].toLowerCase()}/${m[2]}`;
};

function decompose(ticks: number): Dur[] {
  const out: Dur[] = [];
  let left = ticks;
  for (const d of DURATIONS) {
    while (left >= d.ticks) {
      out.push(d);
      left -= d.ticks;
    }
  }
  return out; // sub-64th residue is dropped
}

/**
 * Choose the quantisation grid from the tempo.
 *
 * Trying to infer it from the onsets does not work on a transcription: the
 * onset times come out of a continuous tracker, so they are not on *any* grid
 * and every candidate looks equally bad — which drove the grid to 1/64 and
 * turned the page into a wall of hemidemisemiquavers. Tempo is the honest
 * proxy: fast music uses shorter note values.
 */
function chooseGrid(bpm: number): number {
  if (bpm >= 132) return 60; // 1/32
  if (bpm >= 76) return 120; // 1/16
  return 240; // 1/8
}

/** VexFlow renders a chord with a semitone cluster badly — keep the top note. */
function thinSemitones(pitches: number[]): number[] {
  const sorted = [...new Set(pitches)].sort((a, b) => a - b);
  const out: number[] = [];
  for (const p of sorted) {
    if (out.length === 0 || p - out[out.length - 1] > 1) out.push(p);
  }
  return out;
}

function chordsFor(
  notes: NoteEvent[],
  secPerTick: number,
  grid: number,
  staff: "treble" | "bass"
): Chord[] {
  const byOnset = new Map<number, Chord>();

  for (const n of notes) {
    if (staff === "treble" ? n.midi < SPLIT : n.midi >= SPLIT) continue;
    const startTick = Math.round(n.start / secPerTick / grid) * grid;
    const endTick = Math.max(startTick + grid, Math.round(n.end / secPerTick / grid) * grid);
    const existing = byOnset.get(startTick);
    if (existing) {
      if (!existing.pitches.includes(n.midi)) existing.pitches.push(n.midi);
      existing.endTick = Math.max(existing.endTick, endTick);
    } else {
      byOnset.set(startTick, { tick: startTick, endTick, pitches: [n.midi] });
    }
  }
  return [...byOnset.values()].sort((a, b) => a.tick - b.tick);
}

function withDots(note: StaveNote, dots: number) {
  if (dots > 0) Dot.buildAndAttach([note], { all: true });
  return note;
}

function noteFor(
  pitches: number[],
  dur: Dur,
  clef: "treble" | "bass",
  accidentalKey: string
): StaveNote {
  const note = new StaveNote({
    keys: pitches.map(keyOf),
    duration: dur.code,
    clef,
    autoStem: true,
  });
  pitches.forEach((p, i) => {
    const name = midiToName(p);
    if (name.includes("#")) note.addModifier(new Accidental("#"), i);
    else if (name.includes("b")) note.addModifier(new Accidental("b"), i);
  });
  void accidentalKey;
  return withDots(note, dur.dots);
}

function restFor(dur: Dur, clef: "treble" | "bass"): StaveNote {
  const key = clef === "treble" ? "b/4" : "d/3";
  return withDots(new StaveNote({ keys: [key], duration: `${dur.code}r`, clef }), dur.dots);
}

/**
 * Write notes (or rests when `pitches` is null) covering [startTick, endTick),
 * splitting at bar lines so every StaveNote lands in the right measure.
 */
function emit(
  measures: StaveNote[][],
  measureCount: number,
  startTick: number,
  endTick: number,
  pitches: number[] | null,
  clef: "treble" | "bass",
  accidentalKey: string
): number {
  let cursor = Math.max(0, startTick);
  const hardEnd = Math.min(endTick, measureCount * MEASURE);
  let guard = 0;

  while (cursor < hardEnd && guard++ < 8192) {
    const m = Math.floor(cursor / MEASURE);
    if (m >= measureCount) break;
    const room = (m + 1) * MEASURE - cursor;
    const parts = decompose(Math.min(hardEnd - cursor, room));
    if (parts.length === 0) break;
    for (const p of parts) {
      const mm = Math.floor(cursor / MEASURE);
      if (mm >= measureCount) break;
      measures[mm].push(
        pitches ? noteFor(pitches, p, clef, accidentalKey) : restFor(p, clef)
      );
      cursor += p.ticks;
    }
  }
  return cursor;
}

function measureNotes(
  chords: Chord[],
  measureCount: number,
  clef: "treble" | "bass",
  accidentalKey: string
): StaveNote[][] {
  const measures: StaveNote[][] = Array.from({ length: measureCount }, () => []);
  const total = measureCount * MEASURE;
  let cursor = 0;

  for (const chord of chords) {
    if (chord.tick >= total) break;
    const pitches = thinSemitones(chord.pitches);
    if (pitches.length === 0) continue;

    if (chord.tick > cursor) {
      cursor = emit(measures, measureCount, cursor, chord.tick, null, clef, accidentalKey);
    }
    if (cursor < chord.tick) cursor = chord.tick;

    // a held note is cut at the bar line (no ties) to keep voices aligned
    const barEnd = (Math.floor(cursor / MEASURE) + 1) * MEASURE;
    const end = Math.min(Math.max(chord.endTick, cursor + 60), barEnd);
    cursor = emit(measures, measureCount, cursor, end, pitches, clef, accidentalKey);
    cursor = Math.max(cursor, end);
  }

  emit(measures, measureCount, cursor, total, null, clef, accidentalKey);
  return measures;
}

export function renderScore(
  host: HTMLDivElement,
  notes: NoteEvent[],
  bpm: number,
  opts: ScoreOptions = {}
): RenderResult {
  host.innerHTML = "";
  if (notes.length === 0) {
    return { measuresRendered: 0, totalMeasures: 0, grid: 120, key: "C" };
  }
  const safeBpm = bpm > 20 && bpm < 320 ? bpm : 120;
  const measuresPerLine = opts.measuresPerLine ?? 4;
  const secPerMeasure = (60 / safeBpm) * 4;
  const secPerTick = 60 / safeBpm / PPQ;

  const key = opts.key ?? detectKey(notes);
  const grid = chooseGrid(safeBpm);
  const pedal = opts.pedal ?? [];

  const totalMeasures = Math.max(
    1,
    Math.ceil((Math.max(...notes.map((n) => n.end)) || secPerMeasure) / secPerMeasure)
  );
  const measureCount = Math.min(totalMeasures, opts.maxMeasures ?? 200);

  const treble = measureNotes(
    chordsFor(notes, secPerTick, grid, "treble"), measureCount, "treble", key.vex
  );
  const bass = measureNotes(
    chordsFor(notes, secPerTick, grid, "bass"), measureCount, "bass", key.vex
  );

  const lineWidth = 1120;
  const staveHeight = 215;
  const lines = Math.ceil(measureCount / measuresPerLine);
  const totalHeight = lines * staveHeight + 40;

  const renderer = new Renderer(host, Renderer.Backends.SVG);
  renderer.resize(lineWidth, totalHeight);
  const ctx = renderer.getContext();

  for (let line = 0; line < lines; line++) {
    const y = 24 + line * staveHeight;
    const first = line * measuresPerLine;
    const count = Math.min(measuresPerLine, measureCount - first);
    if (count <= 0) break;
    const staveWidth = (lineWidth - 40) / count;

    for (let i = 0; i < count; i++) {
      const mIndex = first + i;
      const x = 20 + i * staveWidth;
      const leading = i === 0;

      const trebleStave = new Stave(x, y, staveWidth);
      if (leading) {
        trebleStave.addClef("treble").addKeySignature(key.vex).addTimeSignature("4/4");
      }
      trebleStave.setContext(ctx).draw();

      const bassStave = new Stave(x, y + 88, staveWidth);
      if (leading) bassStave.addClef("bass").addKeySignature(key.vex);
      bassStave.setContext(ctx).draw();

      drawVoice(ctx, trebleStave, treble[mIndex] ?? [], staveWidth, key.vex);
      drawVoice(ctx, bassStave, bass[mIndex] ?? [], staveWidth, key.vex);
      // the pedal markings belong under the bass staff, in the measure where
      // the pedal actually moves — this is the "how it was played" of the score
      drawPedal(ctx, bassStave, bass[mIndex] ?? [], mIndex, pedal, secPerTick);
    }
  }

  ctx.setFont("Arial", 11);
  ctx.fillText(
    `♪ = ${Math.round(opts.tempo ?? safeBpm)}  ·  ${key.label}`,
    lineWidth - 190,
    16
  );

  return { measuresRendered: measureCount, totalMeasures, grid, key: key.vex };
}

function drawPedal(
  ctx: ReturnType<Renderer["getContext"]>,
  stave: Stave,
  tickables: StaveNote[],
  measureIndex: number,
  pedal: PedalEvent[],
  secPerTick: number
) {
  if (pedal.length === 0 || tickables.length === 0) return;

  const baseTick = measureIndex * MEASURE;
  const endTick = baseTick + MEASURE;
  const baseSec = baseTick * secPerTick;
  const endSec = endTick * secPerTick;

  const here = pedal.filter((p) => p.end > baseSec && p.start < endSec);
  if (here.length === 0) return;

  // walk the measure's tickables to get each one's tick position, so a pedal
  // event can be pinned to the note it happens on
  const placed: { tick: number; note: StaveNote }[] = [];
  let cursor = baseTick;
  for (const t of tickables) {
    placed.push({ tick: cursor, note: t });
    cursor += t.getTicks().value();
  }
  const nearestNote = (tick: number) => {
    let best = placed[0];
    for (const p of placed) {
      if (Math.abs(p.tick - tick) < Math.abs(best.tick - tick)) best = p;
    }
    return best.note;
  };

  const y = stave.getYForLine(4) + 20;
  ctx.save();
  ctx.setFont("Arial", 10);
  ctx.fillStyle = "#3b4252";
  ctx.strokeStyle = "#3b4252";
  ctx.setLineWidth(0.8);

  for (const p of here) {
    const onTick = Math.round(p.start / secPerTick);
    const offTick = Math.round(p.end / secPerTick);

    if (p.start >= baseSec && p.start < endSec) {
      const note = nearestNote(onTick);
      const x = note.getAbsoluteX() - 6;
      ctx.fillText("Ped.", x, y);
      // a thin line spanning the pedalled stretch looks like a real score
      const to = offTick < endTick ? nearestNote(offTick).getAbsoluteX() - 4 : stave.getX() + stave.getWidth() - 22;
      ctx.beginPath();
      ctx.moveTo(x + 24, y - 3);
      ctx.lineTo(Math.max(x + 30, to), y - 3);
      ctx.stroke();
    }
    if (p.end >= baseSec && p.end < endSec) {
      const note = nearestNote(offTick);
      ctx.fillText("*", note.getAbsoluteX() - 2, y);
    }
  }
  ctx.restore();
}

function drawVoice(
  ctx: ReturnType<Renderer["getContext"]>,
  stave: Stave,
  tickables: StaveNote[],
  staveWidth: number,
  accidentalKey: string
) {
  if (tickables.length === 0) return;
  const voice = new Voice({ numBeats: 4, beatValue: 4 }).setMode(Voice.Mode.SOFT);
  voice.addTickables(tickables);
  try {
    Accidental.applyAccidentals([voice], accidentalKey);
  } catch {
    /* best-effort: VexFlow occasionally rejects odd accidental stacks */
  }
  try {
    const beams = Beam.generateBeams(tickables.filter((t) => !t.isRest()));
    new Formatter().joinVoices([voice]).format([voice], staveWidth - 45);
    voice.draw(ctx, stave);
    beams.forEach((b) => b.setContext(ctx).draw());
  } catch {
    // fall back to unformatted draw so a single bad bar can't kill the page
    tickables.forEach((t) => t.setStave(stave));
    voice.draw(ctx, stave);
  }
}

/* ------------------------------------------------------------------ PDF */

export async function exportScorePdf(host: HTMLDivElement, title = "midimagic") {
  const svg = host.querySelector("svg");
  if (!svg) throw new Error("skor belum dirender — klik 'Render Partitur' dulu");

  const { jsPDF } = await import("jspdf");
  const { svg2pdf } = await import("svg2pdf.js");

  const vb = svg.getAttribute("viewBox")?.split(/\s+/).map(Number);
  const w = vb?.[2] || svg.clientWidth || 1120;
  const h = vb?.[3] || svg.clientHeight || 800;

  const pdf = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const margin = 26;
  const scale = (pageW - margin * 2) / w;
  const contentH = (pageH - margin * 2) / scale;
  const pages = Math.max(1, Math.ceil(h / contentH));

  for (let p = 0; p < pages; p++) {
    if (p > 0) pdf.addPage();
    pdf.setFontSize(9);
    pdf.text(`${title} — hal. ${p + 1}/${pages}`, margin, margin - 10);

    const slice = svg.cloneNode(true) as SVGSVGElement;
    slice.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    slice.setAttribute("viewBox", `0 ${p * contentH} ${w} ${contentH}`);
    slice.setAttribute("width", String(w));
    slice.setAttribute("height", String(contentH));

    await svg2pdf(slice, pdf, {
      x: margin,
      y: margin,
      width: pageW - margin * 2,
      height: contentH * scale,
    });
  }

  pdf.save(`${title}.pdf`);
}
