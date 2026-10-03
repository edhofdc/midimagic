/**
 * Instrument definitions. Deliberately free of any Tone.js import so components
 * can use them during SSR without pulling the audio engine into the server bundle.
 *
 * `sampled` instruments stream real recorded notes (see scripts/fetch_samples.py);
 * the rest are synthesised, which is the point for a chiptune/square lead.
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
  /** "sample" = recorded instrument, "synth" = oscillator. */
  kind: "sample" | "synth";
}

export const INSTRUMENTS: InstrumentDef[] = [
  { id: "grand-piano", label: "Grand Piano", hint: "Salamander — rekaman piano asli", kind: "sample" },
  { id: "electric-piano", label: "Electric Piano", hint: "MusyngKite Rhodes", kind: "sample" },
  { id: "guitar", label: "Guitar (Nylon)", hint: "MusyngKite akustik nilon", kind: "sample" },
  { id: "strings", label: "String Ensemble", hint: "MusyngKite strings", kind: "sample" },
  { id: "synth-lead", label: "Analog Synth", hint: "Sawtooth tajam (sintetis)", kind: "synth" },
  { id: "chiptune", label: "8-bit Chiptune", hint: "Square wave retro (sintetis)", kind: "synth" },
];

/** Tone voice class the synthesised presets are built on. */
export type VoiceKind = "synth" | "fm";

export interface Preset {
  kind: "sample" | "synth";
  /** Key into src/lib/sample-manifest.json for sampled instruments. */
  asset?: string;
  /** Fade-out seconds applied when a note or the whole voice is released. */
  release: number;
  /** Synth-only: which Tone voice class to build. */
  voice?: VoiceKind;
  /** Synth-only: constructor options. */
  options?: Record<string, unknown>;
  maxPolyphony: number;
}

export function presetFor(id: InstrumentId): Preset {
  switch (id) {
    case "electric-piano":
      return { kind: "sample", asset: "electric-piano", release: 1.1, maxPolyphony: 40 };
    case "guitar":
      return { kind: "sample", asset: "guitar", release: 1.4, maxPolyphony: 32 };
    case "strings":
      return { kind: "sample", asset: "strings", release: 2.6, maxPolyphony: 32 };
    case "synth-lead":
      return {
        kind: "synth",
        voice: "synth",
        release: 0.6,
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
    case "chiptune":
      return {
        kind: "synth",
        voice: "synth",
        release: 0.05,
        options: {
          oscillator: { type: "square" },
          envelope: { attack: 0.001, decay: 0.06, sustain: 0.72, release: 0.05 },
        },
        maxPolyphony: 20,
      };
    case "grand-piano":
    default:
      // A real piano rings: the sample carries the decay, `release` is the
      // damper fall when the key/pedal comes up.
      return { kind: "sample", asset: "grand-piano", release: 1.8, maxPolyphony: 48 };
  }
}
