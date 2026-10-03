/**
 * Instrument definitions, kept free of any Tone.js import so components can use
 * them during SSR without pulling the audio engine into the server bundle.
 */

export type InstrumentId =
  | "grand-piano"
  | "electric-piano"
  | "synth-lead"
  | "guitar"
  | "chiptune"
  | "strings";

export interface InstrumentDef {
  id: InstrumentId;
  label: string;
  hint: string;
}

export const INSTRUMENTS: InstrumentDef[] = [
  { id: "grand-piano", label: "Grand Piano", hint: "Akustik hangat" },
  { id: "electric-piano", label: "Electric Piano", hint: "FM Rhodes" },
  { id: "synth-lead", label: "Analog Synth", hint: "Sawtooth tajam" },
  { id: "guitar", label: "Guitar", hint: "Plucked string" },
  { id: "chiptune", label: "8-bit Chiptune", hint: "Square wave retro" },
  { id: "strings", label: "Strings Pad", hint: "Pad lembut" },
];

/** Which Tone voice class the preset is built on. */
export type VoiceKind = "synth" | "fm";

export interface Preset {
  kind: VoiceKind;
  options: Record<string, unknown>;
  maxPolyphony: number;
}

export function presetFor(id: InstrumentId): Preset {
  switch (id) {
    case "electric-piano":
      return {
        kind: "fm",
        options: {
          harmonicity: 3.01,
          modulationIndex: 12,
          oscillator: { type: "sine" },
          envelope: { attack: 0.004, decay: 0.9, sustain: 0.12, release: 1.1 },
          modulation: { type: "sine" },
          modulationEnvelope: {
            attack: 0.002, decay: 0.35, sustain: 0.02, release: 0.25,
          },
        },
        maxPolyphony: 40,
      };
    case "synth-lead":
      return {
        kind: "synth",
        options: {
          oscillator: { type: "sawtooth" },
          envelope: { attack: 0.02, decay: 0.25, sustain: 0.5, release: 0.6 },
          filter: { Q: 2, type: "lowpass", rolloff: -24 },
          filterEnvelope: {
            attack: 0.02, decay: 0.3, sustain: 0.4, release: 0.5,
            baseFrequency: 220, octaves: 3,
          },
        },
        maxPolyphony: 24,
      };
    case "guitar":
      return {
        kind: "synth",
        options: {
          oscillator: { type: "triangle8" },
          envelope: { attack: 0.003, decay: 0.75, sustain: 0.03, release: 0.5 },
        },
        maxPolyphony: 24,
      };
    case "chiptune":
      return {
        kind: "synth",
        options: {
          oscillator: { type: "square" },
          envelope: { attack: 0.001, decay: 0.06, sustain: 0.72, release: 0.05 },
        },
        maxPolyphony: 20,
      };
    case "strings":
      return {
        kind: "synth",
        options: {
          oscillator: { type: "sine" },
          envelope: { attack: 0.35, decay: 0.4, sustain: 0.75, release: 1.6 },
        },
        maxPolyphony: 32,
      };
    case "grand-piano":
    default:
      return {
        kind: "synth",
        options: {
          oscillator: { type: "triangle" },
          envelope: { attack: 0.004, decay: 1.15, sustain: 0.05, release: 1.25 },
          filter: { Q: 1, type: "lowpass", rolloff: -12 },
        },
        maxPolyphony: 40,
      };
  }
}
