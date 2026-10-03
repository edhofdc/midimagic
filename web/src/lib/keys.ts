/** 88-key piano geometry shared by the keyboard renderer and the falling-note roll. */

export const FIRST_MIDI = 21; // A0
export const LAST_MIDI = 108; // C8
export const KEY_COUNT = LAST_MIDI - FIRST_MIDI + 1; // 88

const WHITE_PCS = new Set([0, 2, 4, 5, 7, 9, 11]); // C D E F G A B
const BLACK_PCS = new Set([1, 3, 6, 8, 10]);

export const isBlack = (midi: number) => BLACK_PCS.has(((midi % 12) + 12) % 12);
export const isWhite = (midi: number) => WHITE_PCS.has(((midi % 12) + 12) % 12);

export const WHITE_MIDI: number[] = [];
export const BLACK_MIDI: number[] = [];
for (let m = FIRST_MIDI; m <= LAST_MIDI; m++) {
  (isWhite(m) ? WHITE_MIDI : BLACK_MIDI).push(m);
}
export const WHITE_COUNT = WHITE_MIDI.length; // 52

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

export function midiToName(midi: number, flats = false): string {
  const n = Math.round(midi);
  const pc = ((n % 12) + 12) % 12;
  const octave = Math.floor(n / 12) - 1;
  return `${(flats ? FLAT_NAMES : NOTE_NAMES)[pc]}${octave}`;
}

export function nameToMidi(name: string): number {
  const m = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(name.trim());
  if (!m) return 60;
  const base: Record<string, number> = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
  let pc = base[m[1].toLowerCase()];
  if (m[2] === "#") pc += 1;
  if (m[2] === "b") pc -= 1;
  return (parseInt(m[3], 10) + 1) * 12 + pc;
}

export interface KeyLayout {
  /** x offset of the key within the keyboard, in px */
  x: number;
  /** width of the key in px */
  w: number;
  white: boolean;
  index: number; // index within white or black set
}

/** Layout for a keyboard of exactly `width` px. Black keys are drawn on top. */
export function layoutKeys(width: number): Map<number, KeyLayout> {
  const whiteW = width / WHITE_COUNT;
  const blackW = whiteW * 0.62;
  const map = new Map<number, KeyLayout>();

  WHITE_MIDI.forEach((midi, i) => {
    map.set(midi, { x: i * whiteW, w: whiteW, white: true, index: i });
  });

  // A black key sits between its neighbouring white keys; its centre is offset
  // from the white-key boundary the way a real piano is (not exactly centred).
  const offsets: Record<number, number> = {
    1: -0.06, // C#
    3: 0.06, // D#
    6: -0.08, // F#
    8: 0.0, // G#
    10: 0.08, // A#
  };

  for (const midi of BLACK_MIDI) {
    const below = midi - 1; // white key immediately below the black key
    const wi = WHITE_MIDI.indexOf(below);
    if (wi < 0) continue;
    const boundary = (wi + 1) * whiteW;
    const pc = ((midi % 12) + 12) % 12;
    const x = boundary - blackW / 2 + (offsets[pc] ?? 0) * whiteW;
    map.set(midi, { x, w: blackW, white: false, index: wi });
  }

  return map;
}
