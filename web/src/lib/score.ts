"use client";

/**
 * MIDI → standard notation, rendered with VexFlow as a piano grand staff.
 *
 * Deliberately pragmatic: onsets are quantised to a 1/16 grid, a chord is the
 * set of notes sharing an onset, and every measure is padded with rests so each
 * voice fills its 4/4 bar exactly. Good for reading along, not for engraving.
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
import type { NoteEvent } from "./audio";
import { midiToName } from "./keys";

const PPQ = 480; // ticks per quarter note
const MEASURE = PPQ * 4; // 4/4
const GRID = 120; // 1/16

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
  { ticks: 120, code: "16", dots: 0 },
];

export interface ScoreOptions {
  measuresPerLine?: number;
  maxMeasures?: number;
  tempo?: number;
}

export interface RenderResult {
  measuresRendered: number;
  totalMeasures: number;
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
  return out; // sub-16th residue is dropped
}

function chordsFor(notes: NoteEvent[], bpm: number, staff: "treble" | "bass"): Chord[] {
  const secPerTick = 60 / bpm / PPQ;
  const byOnset = new Map<number, Chord>();

  for (const n of notes) {
    if (staff === "treble" ? n.midi < 60 : n.midi >= 60) continue;
    const startTick = Math.round(n.start / secPerTick / GRID) * GRID;
    const endTick = Math.max(
      startTick + GRID,
      Math.round(n.end / secPerTick / GRID) * GRID
    );
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

function noteFor(pitches: number[], dur: Dur, clef: "treble" | "bass"): StaveNote {
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
  return withDots(note, dur.dots);
}

function restFor(dur: Dur, clef: "treble" | "bass"): StaveNote {
  const key = clef === "treble" ? "b/4" : "d/3";
  return withDots(new StaveNote({ keys: [key], duration: `${dur.code}r`, clef }), dur.dots);
}

/**
 * Write notes (or rests when `pitches` is null) covering [startTick, endTick),
 * splitting at bar lines so every StaveNote lands in the right measure.
 * Returns the tick the cursor reached.
 */
function emit(
  measures: StaveNote[][],
  measureCount: number,
  startTick: number,
  endTick: number,
  pitches: number[] | null,
  clef: "treble" | "bass"
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
      measures[mm].push(pitches ? noteFor(pitches, p, clef) : restFor(p, clef));
      cursor += p.ticks;
    }
  }
  return cursor;
}

function measureNotes(
  chords: Chord[],
  measureCount: number,
  clef: "treble" | "bass"
): StaveNote[][] {
  const measures: StaveNote[][] = Array.from({ length: measureCount }, () => []);
  const total = measureCount * MEASURE;
  let cursor = 0;

  for (const chord of chords) {
    if (chord.tick >= total) break;
    if (chord.tick > cursor) {
      cursor = emit(measures, measureCount, cursor, chord.tick, null, clef);
    }
    if (cursor < chord.tick) cursor = chord.tick;

    // a held note is cut at the bar line (no ties) to keep voices aligned
    const barEnd = (Math.floor(cursor / MEASURE) + 1) * MEASURE;
    const end = Math.min(Math.max(chord.endTick, cursor + GRID), barEnd);
    cursor = emit(measures, measureCount, cursor, end, chord.pitches, clef);
    cursor = Math.max(cursor, end);
  }

  emit(measures, measureCount, cursor, total, null, clef);
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
    return { measuresRendered: 0, totalMeasures: 0 };
  }
  const measuresPerLine = opts.measuresPerLine ?? 4;
  const secPerMeasure = (60 / bpm) * 4;

  const totalMeasures = Math.max(
    1,
    Math.ceil((Math.max(...notes.map((n) => n.end)) || secPerMeasure) / secPerMeasure)
  );
  const measureCount = Math.min(totalMeasures, opts.maxMeasures ?? 160);

  const treble = measureNotes(chordsFor(notes, bpm, "treble"), measureCount, "treble");
  const bass = measureNotes(chordsFor(notes, bpm, "bass"), measureCount, "bass");

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
      if (leading) trebleStave.addClef("treble").addTimeSignature("4/4");
      trebleStave.setContext(ctx).draw();

      const bassStave = new Stave(x, y + 88, staveWidth);
      if (leading) bassStave.addClef("bass");
      bassStave.setContext(ctx).draw();

      drawVoice(ctx, trebleStave, treble[mIndex] ?? [], staveWidth);
      drawVoice(ctx, bassStave, bass[mIndex] ?? [], staveWidth);
    }
  }

  ctx.setFont("Arial", 11);
  ctx.fillText(`♪ = ${Math.round(opts.tempo ?? bpm)}`, lineWidth - 90, 16);

  return { measuresRendered: measureCount, totalMeasures };
}

function drawVoice(
  ctx: ReturnType<Renderer["getContext"]>,
  stave: Stave,
  tickables: StaveNote[],
  staveWidth: number
) {
  if (tickables.length === 0) return;
  const voice = new Voice({ numBeats: 4, beatValue: 4 }).setMode(Voice.Mode.SOFT);
  voice.addTickables(tickables);
  try {
    Accidental.applyAccidentals([voice], "C");
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
