"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play, Square, Volume2, VolumeX, Waves } from "lucide-react";
import type { MidiPlayer } from "@/lib/audio";
import { formatTime } from "@/lib/midi";

interface Props {
  player: MidiPlayer;
  duration: number;
  disabled?: boolean;
}

export default function Transport({ player, duration, disabled }: Props) {
  const seekRef = useRef<HTMLInputElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(0.75);
  const [muted, setMuted] = useState(false);
  const [sustain, setSustain] = useState(false);

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

  const togglePedal = () => {
    const next = !sustain;
    setSustain(next);
    player.setSustain(next);
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
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 px-3 py-2.5 backdrop-blur">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={toggle}
          disabled={disabled}
          className="grid h-10 w-10 place-items-center rounded-lg bg-cyan-500/15 text-cyan-200 ring-1 ring-cyan-400/40 transition hover:bg-cyan-400/25 disabled:opacity-40"
          title={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button
          type="button"
          onClick={() => player.stop()}
          disabled={disabled}
          className="grid h-10 w-10 place-items-center rounded-lg bg-white/5 text-slate-300 ring-1 ring-white/10 transition hover:bg-white/10 disabled:opacity-40"
          title="Stop"
        >
          <Square size={16} />
        </button>
        <button
          type="button"
          onClick={togglePedal}
          disabled={disabled}
          title="Sustain pedal — not tetap berbunyi setelah tuts dilepas"
          className={`flex h-10 items-center gap-1.5 rounded-lg px-3 text-[11px] font-semibold uppercase tracking-wider ring-1 transition disabled:opacity-40 ${
            sustain
              ? "bg-pink-500/25 text-pink-100 ring-pink-400/50 shadow-[0_0_18px_-4px_rgba(255,0,200,0.8)]"
              : "bg-white/5 text-slate-400 ring-white/10 hover:bg-white/10"
          }`}
        >
          <Waves size={14} />
          Sustain
        </button>
      </div>

      <span
        ref={timeRef}
        className="w-12 shrink-0 font-mono text-xs text-cyan-200/90 tabular-nums"
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
        className="h-1.5 min-w-[140px] flex-1 cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan-400 disabled:opacity-40"
      />

      <span className="w-12 shrink-0 font-mono text-xs text-slate-500 tabular-nums">
        {formatTime(duration)}
      </span>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => {
            const next = !muted;
            setMuted(next);
            applyVolume(volume, next);
          }}
          className="grid h-8 w-8 place-items-center rounded-md text-slate-400 hover:text-cyan-200"
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
          className="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-white/10 accent-pink-400"
        />
        <div
          className="h-2 w-16 overflow-hidden rounded-full bg-black/50 ring-1 ring-white/10"
          title="Level output"
        >
          <div
            ref={meterRef}
            className="h-full w-0 rounded-full bg-gradient-to-r from-emerald-400 via-cyan-400 to-pink-400 transition-[width] duration-75"
          />
        </div>
      </div>
    </div>
  );
}
