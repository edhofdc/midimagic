"use client";

/**
 * Tone.js playback engine for a flat note list.
 *
 * Two things separate this from a toy: instruments are real recorded samples
 * (Tone.Sampler over the assets in public/audio), and there is a proper damper
 * model — notes ring for the sample's natural decay, the release envelope is
 * long, and a sustain pedal lets notes ring past their written length exactly
 * like holding the pedal down.
 *
 * The pedal is normally *not* a user setting: it is inferred per-recording on
 * the backend (see pipelines/sustain.py) and arrives as MIDI CC64. "Auto" mode
 * replays that pedal line, which is what makes a transcription sound like the
 * performance it came from. On/Off remain as manual overrides.
 *
 * The visualiser needs a continuous, seekable clock, so the transport is a plain
 * `performance.now()` timeline; notes are pushed into Tone slightly ahead of the
 * cursor (lookahead scheduling) to keep timing tight without a callback per frame.
 */

import * as Tone from "tone";
import { midiToName } from "./keys";
import { presetFor, type InstrumentId } from "./instruments";
import MANIFEST from "./sample-manifest.json";

export type { InstrumentId } from "./instruments";
export { INSTRUMENTS } from "./instruments";

/** Seconds of upcoming notes pushed into Tone ahead of the cursor. */
const LOOKAHEAD = 0.35;
/** How long to wait for sample buffers before starting anyway. */
const SAMPLE_TIMEOUT_MS = 12000;

const SAMPLE_MANIFEST = MANIFEST as Record<string, Record<string, string>>;

export interface NoteEvent {
  midi: number;
  start: number; // seconds
  end: number; // seconds
  velocity: number; // 0..1
}

/** One pedal-down stretch, as decoded from the MIDI's CC64 lane. */
export interface PedalEvent {
  start: number;
  end: number;
}

export type PedalMode = "auto" | "on" | "off";

export interface TickState {
  position: number;
  duration: number;
  playing: boolean;
  activeNotes: Set<number>; // midi numbers currently sounding
  pedal: boolean; // damper pedal down right now
}

type AnyVoice = Tone.Sampler | Tone.PolySynth;

export class MidiPlayer {
  private voice: AnyVoice | null = null;
  private gain!: Tone.Gain;
  private limiter!: Tone.Limiter;
  private reverb!: Tone.Reverb;
  private meter!: Tone.Meter;

  private notes: NoteEvent[] = [];
  private byOnset: NoteEvent[] = [];
  private schedulePtr = 0;

  /* ---- damper pedal ---- */
  private pedalEvents: { time: number; down: boolean }[] = [];
  private pedalPtr = 0;
  private pedalDown = false;
  private pedalFromFile = false;
  pedalMode: PedalMode = "auto";

  private playing = false;
  private position = 0;
  private lastFrame = 0;
  private rafId: number | null = null;

  private instrument: InstrumentId = "grand-piano";
  private voiceKind: "sample" | "synth" = "sample";
  private releaseSec = 1.8;
  private maxPolyphony = 48;
  private held: { note: string; time: number }[] = [];

  private listeners = new Set<(s: TickState) => void>();
  private readyWaiters: (() => void)[] = [];
  private ready = false;

  speed = 1;
  transpose = 0;

  duration = 0;

  constructor() {
    this.gain = new Tone.Gain(0.75);
    this.limiter = new Tone.Limiter(-1);
    this.reverb = new Tone.Reverb({ decay: 2.2, wet: 0.18 });
    this.gain.connect(this.reverb);
    this.reverb.connect(this.limiter);
    this.limiter.toDestination();
    this.meter = new Tone.Meter({ smoothing: 0.85 });
    this.limiter.connect(this.meter);
    this.buildVoice(this.instrument);
  }

  /* ------------------------------------------------------------ instruments */

  private buildVoice(id: InstrumentId) {
    const p = presetFor(id);
    this.releaseHeld(0);
    this.voice?.dispose();
    this.voice = null;
    this.held = [];
    this.instrument = id;
    this.voiceKind = p.kind;
    this.releaseSec = p.release;
    this.maxPolyphony = p.maxPolyphony;
    this.ready = false;

    if (p.kind === "sample") {
      const urls = SAMPLE_MANIFEST[p.asset ?? ""] ?? {};
      if (Object.keys(urls).length === 0) {
        console.warn(`[midimagic] no samples found for "${p.asset}" — run scripts/fetch_samples.py`);
      }
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        this.ready = true;
        this.readyWaiters.splice(0).forEach((fn) => fn());
      };
      const sampler = new Tone.Sampler({
        urls,
        release: p.release,
        attack: 0,
        curve: "linear",
        onload: finish,
        onerror: (err) => {
          console.warn("[midimagic] sample load failed", err);
          finish();
        },
      }).connect(this.gain);
      this.voice = sampler;
      // never let a slow/blocked asset download stall playback forever
      setTimeout(finish, SAMPLE_TIMEOUT_MS);
    } else {
      const ToneAny = Tone as unknown as Record<string, unknown>;
      const voiceCtor = p.voice === "fm" ? Tone.FMSynth : Tone.Synth;
      const built = new (ToneAny.PolySynth as new (
        v: unknown,
        o: Record<string, unknown>
      ) => Tone.PolySynth)(voiceCtor, p.options ?? {}).connect(this.gain);
      built.set(p.options ?? {});
      built.maxPolyphony = p.maxPolyphony;
      this.voice = built;
      this.ready = true;
      this.readyWaiters.splice(0).forEach((fn) => fn());
    }

    if (this.playing) {
      this.schedulePtr = this.lowerBound(this.position - 0.001);
    }
  }

  /** Resolves once the current instrument's samples are usable. */
  whenReady(): Promise<void> {
    if (this.ready) return Promise.resolve();
    return new Promise((resolve) => {
      this.readyWaiters.push(resolve);
      setTimeout(resolve, SAMPLE_TIMEOUT_MS);
    });
  }

  isReady() {
    return this.ready;
  }

  setInstrument(id: InstrumentId) {
    if (id === this.instrument && this.voice) return;
    const wasPlaying = this.playing;
    if (wasPlaying) this.pause();
    this.buildVoice(id);
    if (wasPlaying) void this.play();
  }

  getInstrument() {
    return this.instrument;
  }

  getInstrumentKind() {
    return this.voiceKind;
  }

  /** Output level in dB (-Infinity when silent). Used by the VU meter + QA. */
  getLevel(): number {
    const v = this.meter?.getValue();
    return typeof v === "number" ? v : -Infinity;
  }

  /** Small introspection hook — used by the UI loading state and by manual QA. */
  debugInfo() {
    const v = this.voice as unknown as { _activeSources?: unknown } | null;
    const src = v?._activeSources;
    return {
      instrument: this.instrument,
      kind: this.voiceKind,
      ready: this.ready,
      releaseSec: this.releaseSec,
      pedalMode: this.pedalMode,
      pedalDown: this.pedalDown,
      pedalEvents: this.pedalEvents.length,
      pedalFromFile: this.pedalFromFile,
      playing: this.playing,
      position: Number(this.position.toFixed(3)),
      activeVoices: Array.isArray(src) ? src.length : src instanceof Set ? src.size : -1,
      /** notes currently held by the damper pedal (0 when the pedal is up) */
      heldNotes: this.held.length,
      levelDb: Number(this.getLevel().toFixed(1)),
      contextState: Tone.getContext().state,
    };
  }

  setVolume(v: number) {
    this.gain.gain.rampTo(Math.max(0, Math.min(1, v)) * 1.2, 0.05);
  }

  /* ----------------------------------------------------------------- pedal */

  /** True when the MIDI we loaded actually carried a CC64 lane. */
  hasPedalTrack() {
    return this.pedalFromFile;
  }

  setPedalMode(mode: PedalMode) {
    this.pedalMode = mode;
    if (mode === "off") {
      this.pedalDown = false;
      this.releaseHeld();
    } else if (mode === "on") {
      this.pedalDown = true;
    } else {
      this.syncPedalTo(this.position);
    }
    this.emit();
  }

  /** Back-compat shim for callers that only know on/off. */
  setSustain(on: boolean) {
    this.setPedalMode(on ? "on" : "off");
  }

  private effectivePedal() {
    if (this.pedalMode === "on") return true;
    if (this.pedalMode === "off") return false;
    return this.pedalDown;
  }

  /** Replay the CC64 lane up to `pos` so the pedal state is right after a seek. */
  private syncPedalTo(pos: number) {
    this.pedalPtr = 0;
    this.pedalDown = false;
    while (
      this.pedalPtr < this.pedalEvents.length &&
      this.pedalEvents[this.pedalPtr].time <= pos
    ) {
      this.pedalDown = this.pedalEvents[this.pedalPtr].down;
      this.pedalPtr++;
    }
  }

  /* ------------------------------------------------------------- transport */

  load(notes: NoteEvent[], duration?: number, pedal: PedalEvent[] = []) {
    this.stop();
    this.notes = [...notes].sort((a, b) => a.start - b.start);
    this.byOnset = this.notes;
    this.duration = duration ?? Math.max(0, ...this.notes.map((n) => n.end), 0);

    // flatten the pedal intervals into an ordered CC64-style event stream
    const events: { time: number; down: boolean }[] = [];
    for (const p of pedal) {
      if (p.end - p.start < 0.05) continue;
      events.push({ time: p.start, down: true });
      events.push({ time: p.end, down: false });
    }
    events.sort((a, b) => a.time - b.time);
    this.pedalEvents = events;
    this.pedalFromFile = events.length > 0;
    this.pedalPtr = 0;
    this.pedalDown = false;

    this.position = 0;
    this.emit();
  }

  get durationValue() {
    return this.duration;
  }

  get positionSec() {
    return this.position;
  }

  async play(from?: number) {
    if (typeof from === "number") this.position = from;
    if (this.position >= this.duration) this.position = 0;
    // Samples must be decoded before the first note, and Tone.start() only
    // resolves after a real user gesture — never block on either forever.
    await this.whenReady();
    await Promise.race([
      Tone.start().catch(() => undefined),
      new Promise((r) => setTimeout(r, 1200)),
    ]);
    this.schedulePtr = this.lowerBound(this.position - 0.001);
    this.syncPedalTo(this.position);
    if (this.pedalMode === "on") this.pedalDown = true;
    this.playing = true;
    this.lastFrame = performance.now();
    this.loop();
    this.emit();
  }

  pause() {
    this.playing = false;
    this.releaseHeld();
    this.pedalDown = this.pedalMode === "on";
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.emit();
  }

  stop() {
    this.playing = false;
    this.releaseHeld(0);
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.position = 0;
    this.syncPedalTo(0);
    if (this.pedalMode === "on") this.pedalDown = true;
    this.emit();
  }

  seek(sec: number) {
    this.position = Math.max(0, Math.min(this.duration, sec));
    this.releaseHeld();
    this.schedulePtr = this.lowerBound(this.position - 0.001);
    this.syncPedalTo(this.position);
    if (this.pedalMode === "on") this.pedalDown = true;
    if (this.playing) this.lastFrame = performance.now();
    this.emit();
  }

  onTick(cb: (s: TickState) => void) {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  }

  dispose() {
    this.pause();
    this.voice?.dispose();
    this.gain.dispose();
    this.reverb.dispose();
    this.limiter.dispose();
  }

  /* --------------------------------------------------------------- engine */

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
        this.releaseHeld();
        this.playing = false;
        this.emit();
        this.rafId = null;
        return;
      }
      this.pump();
      this.emit();
    }
    this.rafId = requestAnimationFrame(this.loop);
  };

  private noteName(n: NoteEvent) {
    return midiToName(Math.round(n.midi) + this.transpose);
  }

  /**
   * Walk notes and pedal events as one time-ordered stream, so a note is always
   * voiced with the pedal state that actually applied when it sounded.
   */
  private pump() {
    const horizon = this.position + LOOKAHEAD * this.speed;
    for (;;) {
      const nextNote =
        this.schedulePtr < this.byOnset.length ? this.byOnset[this.schedulePtr].start : Infinity;
      const nextPedal =
        this.pedalPtr < this.pedalEvents.length ? this.pedalEvents[this.pedalPtr].time : Infinity;
      const next = Math.min(nextNote, nextPedal);
      if (next > horizon) break;

      if (nextPedal <= nextNote) {
        const ev = this.pedalEvents[this.pedalPtr++];
        const at = Tone.now() + Math.max(0, (ev.time - this.position) / this.speed) + 0.02;
        if (ev.down) {
          this.pedalDown = true;
        } else {
          this.pedalDown = false;
          // lift the damper at exactly this point in the performance
          this.releaseHeld(at);
        }
        // a manual override ignores the recorded lane
        if (this.pedalMode !== "auto") {
          this.pedalDown = this.pedalMode === "on";
        }
      } else {
        const n = this.byOnset[this.schedulePtr++];
        this.voiceNote(n);
      }
    }
  }

  private voiceNote(n: NoteEvent) {
    const startDelay = Math.max(0, (n.start - this.position) / this.speed);
    const when = Tone.now() + startDelay + 0.02;
    const name = this.noteName(n);
    const velocity = Math.max(0.08, Math.min(1, n.velocity));

    if (this.effectivePedal()) {
      // pedal down: strike and leave it ringing until the pedal lifts
      try {
        this.voice?.triggerAttack(name, when, velocity);
      } catch {
        /* pitch outside the loaded range */
      }
      this.held.push({ note: name, time: when });
      while (this.held.length > this.maxPolyphony) {
        const oldest = this.held.shift();
        if (!oldest) break;
        try {
          (this.voice as Tone.Sampler | null)?.triggerRelease(oldest.note, Tone.now());
        } catch {
          /* already gone */
        }
      }
    } else {
      const durSec = Math.max(0.08, (n.end - n.start) / this.speed);
      try {
        this.voice?.triggerAttackRelease(name, durSec, when, velocity);
      } catch {
        /* pitch outside the loaded range */
      }
    }
  }

  private releaseHeld(when?: number) {
    try {
      this.voice?.releaseAll(typeof when === "number" ? when : Tone.now() + 0.03);
    } catch {
      /* voice may already be disposed */
    }
    this.held = [];
  }

  private emit() {
    if (this.listeners.size === 0) return;
    const active = new Set<number>();
    let i = this.lowerBound(this.position - 12);
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
      pedal: this.effectivePedal(),
    };
    for (const cb of this.listeners) cb(state);
  }
}
