"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import type { MidiPlayer, NoteEvent, TickState } from "@/lib/audio";
import { layoutKeys, FIRST_MIDI, WHITE_COUNT, midiToName } from "@/lib/keys";

interface Props {
  player: MidiPlayer;
  notes: NoteEvent[];
  zoom: number; // white-key width in px
  visibleSeconds: number;
  onSeek: (sec: number) => void;
  /** roll / keyboard pixel heights — phones get a shorter, wider-feeling view */
  rollHeight?: number;
  keyboardHeight?: number;
}

export default function PianoRoll({
  player,
  notes,
  zoom,
  visibleSeconds,
  onSeek,
  rollHeight = 380,
  keyboardHeight = 96,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const followRef = useRef(true);

  const width = WHITE_COUNT * zoom;
  const rollH = rollHeight;
  const KEYBOARD_H = keyboardHeight;
  const totalH = rollH + KEYBOARD_H;

  const layout = useMemo(() => layoutKeys(width), [width]);

  // A 98-minute transcription is ~40k notes and this draw runs every frame. The
  // loop below used to walk the array from index 0 each time, skipping the
  // already-played ones one comparison at a time — fine at 1.5k notes, tens of
  // thousands of wasted comparisons per frame at this size. Notes sorted by onset
  // plus the longest note in the piece let a binary search jump straight to the
  // first note that can still be visible: anything starting before
  // (now - longest) has already finished sounding, whatever the pedal did.
  const { byStart, maxLen } = useMemo(() => {
    const sorted = [...notes].sort((a, b) => a.start - b.start);
    let m = 0;
    for (const n of sorted) m = Math.max(m, n.end - n.start);
    return { byStart: sorted, maxLen: m };
  }, [notes]);

  const draw = useCallback(
    (state: TickState) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (canvas.width !== width * dpr || canvas.height !== totalH * dpr) {
        canvas.width = width * dpr;
        canvas.height = totalH * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${totalH}px`;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, totalH);

      // background
      const bg = ctx.createLinearGradient(0, 0, 0, rollH);
      bg.addColorStop(0, "#070912");
      bg.addColorStop(1, "#0d1020");
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, width, rollH);

      const pps = rollH / visibleSeconds;
      const pos = state.position;

      // second grid
      ctx.strokeStyle = "rgba(0,240,255,0.07)";
      ctx.lineWidth = 1;
      const firstSec = Math.floor(pos);
      for (let s = firstSec; s < pos + visibleSeconds + 1; s++) {
        const y = rollH - (s - pos) * pps;
        if (y < 0 || y > rollH) continue;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // bar lines every 2s stronger
      ctx.strokeStyle = "rgba(255,0,200,0.10)";
      for (let s = Math.ceil(pos / 2) * 2; s < pos + visibleSeconds; s += 2) {
        const y = rollH - (s - pos) * pps;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // falling notes
      const horizon = pos + visibleSeconds + 1;
      ctx.save();
      // jump to the first note that could still be on screen (see byStart above)
      let lo = 0;
      let hi = byStart.length;
      const floorStart = pos - maxLen - 0.05;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (byStart[mid].start < floorStart) lo = mid + 1;
        else hi = mid;
      }
      for (let i = lo; i < byStart.length; i++) {
        const n = byStart[i];
        if (n.end < pos - 0.05) continue;
        if (n.start > horizon) break;

        const key = layout.get(Math.round(n.midi));
        if (!key) continue;

        const yTop = rollH - (n.start + (n.end - n.start) - pos) * pps;
        const yBottom = rollH - (n.start - pos) * pps;
        const h = Math.max(4, yBottom - yTop);
        const x = key.x + (key.white ? 1.5 : 1);
        const w = key.w - (key.white ? 3 : 2);

        const hue = 192 + ((n.midi - FIRST_MIDI) / 87) * 138;
        const active = n.start <= pos && n.end >= pos;
        const alpha = n.start > pos ? 0.92 : active ? 1 : 0.25;

        ctx.globalAlpha = alpha;
        ctx.shadowColor = `hsla(${hue}, 100%, 60%, 0.85)`;
        ctx.shadowBlur = active ? 18 : 8;
        const grad = ctx.createLinearGradient(x, yTop, x, yTop + h);
        grad.addColorStop(0, `hsla(${hue}, 100%, 72%, 1)`);
        grad.addColorStop(1, `hsla(${hue}, 95%, 46%, 1)`);
        ctx.fillStyle = grad;
        const r = Math.min(4, w / 2, h / 2);
        ctx.beginPath();
        ctx.roundRect(x, yTop, w, h, r);
        ctx.fill();
      }
      ctx.restore();

      // keyboard
      const kbY = rollH;
      ctx.fillStyle = "#05060c";
      ctx.fillRect(0, kbY, width, KEYBOARD_H);

      for (const [midi, k] of layout) {
        if (!k.white) continue;
        const on = state.activeNotes.has(midi);
        ctx.fillStyle = on ? "#7ef9ff" : "#e8ecf4";
        ctx.fillRect(k.x, kbY, k.w - 1, KEYBOARD_H);
        if (on) {
          ctx.shadowColor = "rgba(0,240,255,0.9)";
          ctx.shadowBlur = 16;
          ctx.fillRect(k.x, kbY, k.w - 1, KEYBOARD_H);
          ctx.shadowBlur = 0;
        }
        ctx.fillStyle = "rgba(0,0,0,0.35)";
        ctx.fillRect(k.x + k.w - 1, kbY, 1, KEYBOARD_H);

        const pc = ((midi % 12) + 12) % 12;
        if (pc === 0) {
          ctx.fillStyle = "#8a93a6";
          ctx.font = "9px ui-monospace, monospace";
          ctx.fillText(midiToName(midi), k.x + 3, kbY + KEYBOARD_H - 5);
        }
      }

      for (const [midi, k] of layout) {
        if (k.white) continue;
        const on = state.activeNotes.has(midi);
        ctx.fillStyle = on ? "#ff6ee0" : "#12141d";
        ctx.shadowColor = on ? "rgba(255,0,200,0.9)" : "transparent";
        ctx.shadowBlur = on ? 16 : 0;
        ctx.fillRect(k.x, kbY, k.w, KEYBOARD_H * 0.62);
        ctx.shadowBlur = 0;
      }

      // playhead
      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, kbY);
      ctx.lineTo(width, kbY);
      ctx.stroke();

      // damper pedal lamp — lit while the sustain is engaged
      if (state.pedal) {
        ctx.fillStyle = "rgba(255,0,200,0.85)";
        ctx.shadowColor = "rgba(255,0,200,0.9)";
        ctx.shadowBlur = 10;
        ctx.fillRect(0, rollH - 3, width, 3);
        ctx.shadowBlur = 0;
      }
    },
    [layout, notes, rollH, totalH, visibleSeconds, width]
  );

  useEffect(() => {
    const off = player.onTick(draw);
    draw({
      position: 0,
      duration: player.durationValue,
      playing: false,
      activeNotes: new Set(),
      pedal: false,
    });
    return off;
  }, [player, draw]);

  // keep the sounding keys in view while playing
  const follow = useCallback(
    (state: TickState) => {
      if (!followRef.current) return;
      const wrap = wrapRef.current;
      if (!wrap) return;
      const xs: number[] = [];
      for (const m of state.activeNotes) {
        const k = layout.get(m);
        if (k) xs.push(k.x);
      }
      if (xs.length === 0) return;
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs) + zoom;
      const view = wrap.clientWidth;
      if (minX < wrap.scrollLeft + 20 || maxX > wrap.scrollLeft + view - 20) {
        wrap.scrollTo({
          left: Math.max(0, (minX + maxX) / 2 - view / 2),
          behavior: "auto",
        });
      }
    },
    [layout, zoom]
  );

  useEffect(() => player.onTick(follow), [player, follow]);

  const handlePointer = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const y = e.clientY - rect.top;
    if (y > rollH) return;
    const pps = rollH / visibleSeconds;
    const target = player.positionSec + (rollH - y) / pps;
    onSeek(Math.max(0, Math.min(player.durationValue, target)));
  };

  return (
    <div className="rounded-xl border border-cyan-500/20 bg-[#05060c] overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-cyan-500/15 px-3 py-2">
        <span className="text-[11px] uppercase tracking-[0.18em] text-cyan-300/80">
          Piano Roll · Synthesia View
        </span>
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <input
            type="checkbox"
            defaultChecked
            onChange={(e) => (followRef.current = e.target.checked)}
            className="accent-cyan-400"
          />
          auto-follow
        </label>
      </div>
      <div ref={wrapRef} className="overflow-x-auto overscroll-x-contain">
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointer}
          className="block cursor-crosshair touch-pan-x"
        />
      </div>
    </div>
  );
}
