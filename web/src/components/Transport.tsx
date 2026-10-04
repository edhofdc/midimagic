"use client";

import { useEffect, useRef, useState } from "react";
import { Headphones, Pause, Play, RotateCcw, Square, Volume2, VolumeX, Waves } from "lucide-react";
import type { MidiPlayer, PedalMode } from "@/lib/audio";
import { formatTime } from "@/lib/midi";

interface Props {
  player: MidiPlayer;
  duration: number;
  disabled?: boolean;
  /** whether the loaded MIDI carried a CC64 lane (i.e. Auto means something) */
  hasPedal?: boolean;
  /** the source recording, so the transcription can be checked by ear */
  referenceUrl?: string;
  /** offset the pipeline had to correct, in ms — surfaced so a regression is visible */
  alignMs?: number;
}

const PEDAL_LABEL: Record<PedalMode, string> = {
  auto: "Auto",
  on: "On",
  off: "Off",
};

export default function Transport({ player, duration, disabled, hasPedal, referenceUrl, alignMs }: Props) {
  const seekRef = useRef<HTMLInputElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const pedalRef = useRef<HTMLSpanElement>(null);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(0.75);
  const [muted, setMuted] = useState(false);
  const [pedalMode, setPedalMode] = useState<PedalMode>("auto");
  const [refOn, setRefOn] = useState(false);
  const [refMs, setRefMs] = useState(0);

  useEffect(() => {
    setPedalMode(player.pedalMode);
  }, [player]);

  // hand the source recording to the player so it can run alongside the MIDI
  useEffect(() => {
    player.setReference(referenceUrl ?? null);
  }, [player, referenceUrl]);

  useEffect(() => {
    player.setReferenceEnabled(refOn);
  }, [player, refOn]);

  useEffect(() => {
    player.setReferenceOffset(refMs / 1000);
  }, [player, refMs]);

  useEffect(() => {
    let lastSec = -1;
    return player.onTick((s) => {
      setPlaying((p) => (p === s.playing ? p : s.playing));
      if (seekRef.current && document.activeElement !== seekRef.current) {
        seekRef.current.value = String(s.position);
      }
      const sec = Math.floor(s.position);
      if (sec !== lastSec && timeRef.current) {
        lastSec = sec;
        timeRef.current.textContent = formatTime(s.position);
      }
      // live damper state — the pedal is driven by the recording, not by a click
      if (pedalRef.current) {
        pedalRef.current.dataset.down = s.pedal ? "1" : "0";
      }
    });
  }, [player]);

  const toggle = async () => {
    if (playing) player.pause();
    else await player.play();
  };

  const applyVolume = (v: number, mute = muted) => {
    setVolume(v);
    player.setVolume(mute ? 0 : v);
  };

  const choosePedal = (mode: PedalMode) => {
    setPedalMode(mode);
    player.setPedalMode(mode);
  };

  // output level meter — proof the graph is actually producing signal
  const meterRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const db = player.getLevel();
      const pct = Number.isFinite(db) ? Math.max(0, Math.min(1, (db + 60) / 60)) : 0;
      if (meterRef.current) meterRef.current.style.width = `${(pct * 100).toFixed(1)}%`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [player]);

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 px-2.5 py-2.5 backdrop-blur sm:gap-3 sm:px-3">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={toggle}
          disabled={disabled}
          className="grid h-11 w-11 place-items-center rounded-lg bg-cyan-500/15 text-cyan-200 ring-1 ring-cyan-400/40 transition active:scale-95 hover:bg-cyan-400/25 disabled:opacity-40 sm:h-10 sm:w-10"
          title={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button
          type="button"
          onClick={() => player.stop()}
          disabled={disabled}
          className="grid h-11 w-11 place-items-center rounded-lg bg-white/5 text-slate-300 ring-1 ring-white/10 transition active:scale-95 hover:bg-white/10 disabled:opacity-40 sm:h-10 sm:w-10"
          title="Stop"
        >
          <Square size={16} />
        </button>

        {/* pedal: Auto replays the CC64 lane inferred from the recording */}
        <div
          className="flex h-11 items-center overflow-hidden rounded-lg ring-1 ring-white/10 sm:h-10"
          title={
            hasPedal
              ? "Sustain pedal — Auto memakai pedal hasil deteksi dari rekaman"
              : "Sustain pedal — rekaman ini tidak punya sustain terdeteksi, pakai Auto/On/Off"
          }
        >
          <span className="grid h-full place-items-center bg-white/5 px-2 text-slate-400">
            <Waves size={14} />
          </span>
          {(Object.keys(PEDAL_LABEL) as PedalMode[]).map((mode) => {
            const active = pedalMode === mode;
            return (
              <button
                key={mode}
                type="button"
                onClick={() => choosePedal(mode)}
                disabled={disabled}
                className={`h-full px-2.5 text-[11px] font-semibold uppercase tracking-wider transition disabled:opacity-40 ${
                  active
                    ? "bg-pink-500/25 text-pink-100"
                    : "text-slate-400 hover:bg-white/10 hover:text-slate-200"
                }`}
              >
                {PEDAL_LABEL[mode]}
              </button>
            );
          })}
          <span
            ref={pedalRef}
            data-down="0"
            className="h-full w-1.5 bg-black/40 data-[down=0]:bg-black/40 data-[down=1]:bg-pink-400 data-[down=1]:shadow-[0_0_12px_2px_rgba(255,0,200,0.9)]"
          />
        </div>
      </div>

      <span
        ref={timeRef}
        className="w-11 shrink-0 font-mono text-xs text-cyan-200/90 tabular-nums sm:w-12"
      >
        0:00
      </span>

      <input
        ref={seekRef}
        type="range"
        min={0}
        max={Math.max(0.1, duration)}
        step={0.01}
        defaultValue={0}
        onChange={(e) => player.seek(Number(e.target.value))}
        disabled={disabled}
        className="order-last h-1.5 w-full min-w-0 flex-1 cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan-400 disabled:opacity-40 sm:order-none sm:w-auto"
      />

      <span className="hidden w-12 shrink-0 font-mono text-xs text-slate-500 tabular-nums sm:block">
        {formatTime(duration)}
      </span>

      <div className="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => setRefOn((v) => !v)}
          disabled={disabled || !referenceUrl}
          className={`flex h-9 items-center gap-1.5 rounded-md px-2 text-[11px] font-semibold uppercase tracking-wider ring-1 transition disabled:opacity-40 ${
            refOn
              ? "bg-emerald-400/20 text-emerald-100 ring-emerald-400/50"
              : "text-slate-400 ring-white/10 hover:text-emerald-200"
          }`}
          title="Putar rekaman asli bersamaan — cara paling jujur mengecek hasilnya"
        >
          <Headphones size={15} />
          <span className="hidden sm:inline">Asli</span>
        </button>
        <button
          type="button"
          onClick={() => {
            const next = !muted;
            setMuted(next);
            applyVolume(volume, next);
          }}
          className="grid h-9 w-9 place-items-center rounded-md text-slate-400 hover:text-cyan-200"
          title="Mute"
        >
          {muted || volume === 0 ? <VolumeX size={15} /> : <Volume2 size={15} />}
        </button>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={muted ? 0 : volume}
          onChange={(e) => applyVolume(Number(e.target.value))}
          className="h-1.5 w-20 cursor-pointer appearance-none rounded-full bg-white/10 accent-pink-400 sm:w-24"
        />
        <div
          className="h-2 w-12 overflow-hidden rounded-full bg-black/50 ring-1 ring-white/10 sm:w-16"
          title="Level output"
        >
          <div
            ref={meterRef}
            className="h-full w-0 rounded-full bg-gradient-to-r from-emerald-400 via-cyan-400 to-pink-400 transition-[width] duration-75"
          />
        </div>
      </div>

      {refOn && (
        <div className="order-last flex w-full flex-wrap items-center gap-x-2 gap-y-1 border-t border-white/5 pt-2 text-[11px] text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-emerald-200/80">
            Rekaman asli
          </span>
          <div className="flex items-center overflow-hidden rounded-md ring-1 ring-white/10">
            <button
              type="button"
              onClick={() => setRefMs((v) => Math.max(-2000, v - 50))}
              className="h-7 px-2 text-slate-300 hover:bg-white/10"
              title="Maju 50 ms"
            >
              ½×
            </button>
            <span className="min-w-14 bg-white/5 px-2 py-1 text-center font-mono tabular-nums text-emerald-100">
              {refMs > 0 ? "+" : ""}
              {refMs} ms
            </span>
            <button
              type="button"
              onClick={() => setRefMs((v) => Math.min(2000, v + 50))}
              className="h-7 px-2 text-slate-300 hover:bg-white/10"
              title="Mundur 50 ms"
            >
              ¼×
            </button>
            <button
              type="button"
              onClick={() => setRefMs(0)}
              className="grid h-7 w-7 place-items-center text-slate-400 hover:bg-white/10 hover:text-cyan-200"
              title="Reset ke 0"
            >
              <RotateCcw size={12} />
            </button>
          </div>
          <span className="text-slate-600">
            {refMs === 0
              ? "sejajar dengan transkripsi"
              : "geser sampai piano dan rekaman terdengar bersamaan"}
          </span>
          {typeof alignMs === "number" && alignMs !== 0 && (
            <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-amber-200/90">
              pipeline mengoreksi {alignMs > 0 ? "+" : ""}
              {alignMs} ms
            </span>
          )}
        </div>
      )}
    </div>
  );
}
