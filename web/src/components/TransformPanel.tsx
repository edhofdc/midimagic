"use client";

import { Gauge, Music4, RotateCcw } from "lucide-react";
import { INSTRUMENTS, type InstrumentId } from "@/lib/instruments";

interface Props {
  instrument: InstrumentId;
  onInstrument: (id: InstrumentId) => void;
  speed: number;
  onSpeed: (v: number) => void;
  transpose: number;
  onTranspose: (v: number) => void;
}

const SEMITONES = Array.from({ length: 25 }, (_, i) => i - 12); // -12..+12

export default function TransformPanel({
  instrument,
  onInstrument,
  speed,
  onSpeed,
  transpose,
  onTranspose,
}: Props) {
  return (
    <div className="grid gap-4 rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 p-4 backdrop-blur md:grid-cols-3">
      {/* instrument */}
      <section className="md:col-span-2">
        <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300/80">
          <Music4 size={13} /> Multi-Instrument Synth
        </h3>
        <div className="flex flex-wrap gap-2">
          {INSTRUMENTS.map((ins) => {
            const active = ins.id === instrument;
            return (
              <button
                key={ins.id}
                type="button"
                onClick={() => onInstrument(ins.id)}
                title={ins.hint}
                className={`rounded-lg px-3 py-1.5 text-xs ring-1 transition ${
                  active
                    ? "bg-pink-500/20 text-pink-100 ring-pink-400/50 shadow-[0_0_18px_-4px_rgba(255,0,200,0.7)]"
                    : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"
                }`}
              >
                {ins.label}
              </button>
            );
          })}
        </div>
      </section>

      {/* tempo */}
      <section>
        <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300/80">
          <Gauge size={13} /> Tempo
        </h3>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0.25}
            max={2}
            step={0.05}
            value={speed}
            onChange={(e) => onSpeed(Number(e.target.value))}
            className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan-400"
          />
          <span className="w-14 shrink-0 text-right font-mono text-xs text-cyan-200">
            {Math.round(speed * 100)}%
          </span>
        </div>
        <div className="mt-1.5 flex gap-1">
          {[0.5, 0.75, 1, 1.25, 1.5].map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => onSpeed(v)}
              className={`rounded px-2 py-0.5 text-[10px] ring-1 transition ${
                Math.abs(speed - v) < 0.001
                  ? "bg-cyan-500/20 text-cyan-100 ring-cyan-400/40"
                  : "bg-white/5 text-slate-400 ring-white/10 hover:bg-white/10"
              }`}
            >
              {v}×
            </button>
          ))}
        </div>

        <h3 className="mt-4 mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-pink-300/80">
          <RotateCcw size={13} /> Transpose
        </h3>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={-12}
            max={12}
            step={1}
            value={transpose}
            onChange={(e) => onTranspose(Number(e.target.value))}
            className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-white/10 accent-pink-400"
          />
          <span className="w-14 shrink-0 text-right font-mono text-xs text-pink-200">
            {transpose > 0 ? `+${transpose}` : transpose} st
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {SEMITONES.filter((s) => s % 3 === 0 || Math.abs(s) === 1).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onTranspose(s)}
              className={`rounded px-1.5 py-0.5 text-[10px] ring-1 transition ${
                transpose === s
                  ? "bg-pink-500/20 text-pink-100 ring-pink-400/40"
                  : "bg-white/5 text-slate-400 ring-white/10 hover:bg-white/10"
              }`}
            >
              {s > 0 ? `+${s}` : s}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
