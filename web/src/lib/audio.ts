"use client";

/**
 * Tone.js playback engine for a flat note list.
 *
 * The visualiser needs a continuous, seekable clock, so the transport is a
 * plain `performance.now()` timeline. Notes are pushed into Tone slightly ahead
 * of the cursor (lookahead scheduling) which keeps timing tight without a
 * callback per frame.
 */

import * as Tone from "tone";
import { midiToName } from "./keys";
import { presetFor, type InstrumentId } from "./instruments";

export type { InstrumentId } from "./instruments";
export { INSTRUMENTS } from "./instruments";

/** Seconds of upcoming notes pushed into Tone ahead of the cursor. */
const LOOKAHEAD = 0.35;

export interface NoteEvent {
  midi: number;
  start: number; // seconds
  end: number; // seconds
  velocity: number; // 0..1
}

export interface TickState {
  position: number;
  duration: number;
  playing: boolean;
  activeNotes: Set<number>; // midi numbers currently sounding
}

export class MidiPlayer {
  private synth: Tone.PolySynth | null = null;
  private gain!: Tone.Gain;
  private limiter!: Tone.Limiter;
  private reverb!: Tone.Reverb;

  private notes: NoteEvent[] = [];
  private byOnset: NoteEvent[] = [];
  private schedulePtr = 0;
  private windowStart = 0;

  private playing = false;
  private position = 0;
  private lastFrame = 0;
  private rafId: number | null = null;

  speed = 1;
  transpose = 0;

  private listeners = new Set<(s: TickState) => void>();
  private instrument: InstrumentId = "grand-piano";

  constructor() {
    this.gain = new Tone.Gain(0.75);
    this.limiter = new Tone.Limiter(-1);
    this.reverb = new Tone.Reverb({ decay: 1.8, wet: 0.16 });
    this.gain.connect(this.reverb);
    this.reverb.connect(this.limiter);
    this.limiter.toDestination();
    this.buildSynth(this.instrument);
  }

  private buildSynth(id: InstrumentId) {
    const p = presetFor(id);
    this.synth?.dispose();
    const voice = p.kind === "fm" ? Tone.FMSynth : Tone.Synth;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ToneAny = Tone as any;
    const built = new ToneAny.PolySynth(voice, p.options).connect(this.gain);
    built.set({ ...p.options });
    built.maxPolyphony = p.maxPolyphony ?? 32;
    this.synth = built as Tone.PolySynth;
  }

  setInstrument(id: InstrumentId) {
    this.instrument = id;
    const wasPlaying = this.playing;
    if (wasPlaying) this.stop();
    this.buildSynth(id);
    if (wasPlaying) this.play();
  }

  getInstrument() {
    return this.instrument;
  }

  setVolume(v: number) {
    // v: 0..1
    this.gain.gain.rampTo(Math.max(0, Math.min(1, v)) * 1.2, 0.05);
  }

  load(notes: NoteEvent[], duration?: number) {
    this.stop();
    this.notes = [...notes].sort((a, b) => a.start - b.start);
    this.byOnset = this.notes;
    this.duration = duration ?? Math.max(0, ...this.notes.map((n) => n.end), 0);
    this.position = 0;
    this.emit();
  }

  duration = 0;

  get durationValue() {
    return this.duration;
  }

  async play(from?: number) {
    if (typeof from === "number") this.position = from;
    if (this.position >= this.duration) this.position = 0;
    // Tone.start() only resolves after a real user gesture; never let a
    // suspended AudioContext (or a headless browser) block the transport.
    await Promise.race([
      Tone.start().catch(() => undefined),
      new Promise((r) => setTimeout(r, 1200)),
    ]);
    this.schedulePtr = this.lowerBound(this.position - 0.001);
    this.playing = true;
    this.lastFrame = performance.now();
    this.loop();
    this.emit();
  }

  pause() {
    this.playing = false;
    this.synth?.releaseAll();
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.emit();
  }

  stop() {
    this.playing = false;
    this.synth?.releaseAll();
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.position = 0;
    this.emit();
  }

  seek(sec: number) {
    this.position = Math.max(0, Math.min(this.duration, sec));
    this.synth?.releaseAll();
    this.schedulePtr = this.lowerBound(this.position - 0.001);
    this.windowStart = this.lowerBound(this.position);
    if (this.playing) this.lastFrame = performance.now();
    this.emit();
  }

  onTick(cb: (s: TickState) => void) {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  }

  /** Current cursor position in seconds (used for click-to-seek). */
  get positionSec() {
    return this.position;
  }

  dispose() {
    this.pause();
    this.synth?.dispose();
    this.gain.dispose();
    this.reverb.dispose();
    this.limiter.dispose();
  }

  private lowerBound(t: number) {
    let lo = 0;
    let hi = this.byOnset.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.byOnset[mid].start < t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  private loop = () => {
    const now = performance.now();
    const dt = (now - this.lastFrame) / 1000;
    this.lastFrame = now;
    if (this.playing) {
      this.position += dt * this.speed;
      if (this.position >= this.duration) {
        this.position = this.duration;
        this.synth?.releaseAll();
        this.playing = false;
        this.emit();
        this.rafId = null;
        return;
      }
      this.pump(now);
      this.emit();
    }
    this.rafId = requestAnimationFrame(this.loop);
  };

  private pump(now: number) {
    const horizon = this.position + LOOKAHEAD * this.speed;
    while (
      this.schedulePtr < this.byOnset.length &&
      this.byOnset[this.schedulePtr].start <= horizon
    ) {
      const n = this.byOnset[this.schedulePtr];
      const startDelay = Math.max(0, (n.start - this.position) / this.speed);
      const when = Tone.now() + startDelay + 0.02;
      const durSec = Math.max(0.05, (n.end - n.start) / this.speed);
      const name = midiToName(Math.round(n.midi) + this.transpose);
      try {
        this.synth?.triggerAttackRelease(name, durSec, when, Math.max(0.05, n.velocity));
      } catch {
        /* out-of-range pitch — skip */
      }
      this.schedulePtr++;
    }
  }

  private emit() {
    if (this.listeners.size === 0) return;
    // active notes: everything whose [start,end] straddles the cursor
    const active = new Set<number>();
    let i = this.lowerBound(this.position - 12); // generous back-scan window
    for (; i < this.byOnset.length; i++) {
      const n = this.byOnset[i];
      if (n.start > this.position) break;
      if (n.end >= this.position) active.add(Math.round(n.midi) + this.transpose);
    }
    const state: TickState = {
      position: this.position,
      duration: this.duration,
      playing: this.playing,
      activeNotes: active,
    };
    for (const cb of this.listeners) cb(state);
  }
}
