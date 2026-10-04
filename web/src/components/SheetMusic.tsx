"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { FileMusic, FileText, Loader2, Sheet } from "lucide-react";
import type { NoteEvent, PedalEvent } from "@/lib/audio";
import { detectKey, keyFromVex, KEY_CHOICES } from "@/lib/key";
import { exportScorePdf, renderScore, type RenderResult } from "@/lib/score";

interface Props {
  notes: NoteEvent[];
  bpm: number;
  title: string;
  pedal?: PedalEvent[];
}

export default function SheetMusic({ notes, bpm, title, pedal }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState<RenderResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const detected = useMemo(() => detectKey(notes), [notes]);
  // manual overrides — the detectors are heuristics and a musician can see the
  // right answer at a glance, so never make the detected value the only option
  const [keyVex, setKeyVex] = useState<string>("auto");
  const [bpmOverride, setBpmOverride] = useState<number | null>(null);
  const key = keyVex === "auto" ? detected : keyFromVex(keyVex);
  const scoreBpm = bpmOverride ?? bpm;

  useEffect(() => {
    setRendered(null);
    setErr(null);
    if (hostRef.current) hostRef.current.innerHTML = "";
  }, [notes, bpm, pedal, keyVex, bpmOverride]);

  const render = () => {
    if (!hostRef.current) return;
    setBusy(true);
    setErr(null);
    // let the spinner paint before the synchronous engraving pass
    setTimeout(() => {
      try {
        const res = renderScore(hostRef.current!, notes, scoreBpm, {
          tempo: scoreBpm,
          key,
          pedal,
        });
        setRendered(res);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    }, 30);
  };

  const exportPdf = async () => {
    if (!hostRef.current) return;
    setPdfBusy(true);
    setErr(null);
    try {
      await exportScorePdf(hostRef.current, title || "midimagic");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 backdrop-blur">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-cyan-500/15 px-4 py-3">
        <h2 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300/80">
          <FileMusic size={13} /> Sheet Music Generator
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={render}
            disabled={busy || notes.length === 0}
            className="flex items-center gap-1.5 rounded-lg bg-cyan-500/15 px-3 py-1.5 text-xs text-cyan-100 ring-1 ring-cyan-400/40 transition hover:bg-cyan-400/25 disabled:opacity-40"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Sheet size={13} />}
            {rendered ? "Render ulang" : "Render partitur"}
          </button>
          <button
            type="button"
            onClick={exportPdf}
            disabled={!rendered || pdfBusy}
            className="flex items-center gap-1.5 rounded-lg bg-pink-500/15 px-3 py-1.5 text-xs text-pink-100 ring-1 ring-pink-400/40 transition hover:bg-pink-400/25 disabled:opacity-40"
          >
            {pdfBusy ? <Loader2 size={13} className="animate-spin" /> : <FileText size={13} />}
            PDF
          </button>
        </div>
      </header>

      {notes.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-cyan-500/10 px-4 py-2 text-[11px] text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-slate-500">
            Koreksi manual
          </span>
          <label className="flex items-center gap-1.5">
            Kunci
            <select
              value={keyVex}
              onChange={(e) => setKeyVex(e.target.value)}
              className="rounded-md border border-white/10 bg-[#0d1020] px-1.5 py-1 text-[11px] text-cyan-100 outline-none focus:border-cyan-400/50"
            >
              <option value="auto">Otomatis ({detected.label})</option>
              {KEY_CHOICES.map((k) => (
                <option key={k.vex} value={k.vex}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            ♪ =
            <input
              type="number"
              min={20}
              max={300}
              value={Math.round(scoreBpm)}
              onChange={(e) => {
                const v = Number(e.target.value);
                setBpmOverride(Number.isFinite(v) && v >= 20 && v <= 300 ? v : null);
              }}
              className="w-16 rounded-md border border-white/10 bg-[#0d1020] px-1.5 py-1 font-mono text-[11px] text-cyan-100 outline-none focus:border-cyan-400/50"
            />
            {bpmOverride === null ? (
              <span className="text-slate-600">terdeteksi</span>
            ) : (
              <button
                type="button"
                onClick={() => setBpmOverride(null)}
                className="text-cyan-300 hover:text-cyan-100"
              >
                auto
              </button>
            )}
          </label>
          {keyVex === "auto" && detected.margin < 0.01 && (
            <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-amber-200/90">
              kunci ambigu (selisih {detected.margin.toFixed(4)}) — periksa manual
            </span>
          )}
        </div>
      )}

      {err && (
        <p className="mx-4 mt-3 rounded-lg border border-pink-500/30 bg-pink-500/10 px-3 py-2 text-xs text-pink-200">
          {err}
        </p>
      )}

      <div className="max-h-[560px] overflow-auto p-4">
        {notes.length === 0 ? (
          <p className="py-10 text-center text-xs text-slate-500">
            Belum ada MIDI — convert audio dulu.
          </p>
        ) : (
          <div className="min-w-[900px] rounded-lg bg-[#f6f7fb] p-2 shadow-inner">
            <div ref={hostRef} />
            {!rendered && (
              <p className="py-10 text-center text-xs text-slate-400">
                Klik <b>Render partitur</b> untuk membuat not balok.
              </p>
            )}
          </div>
        )}
      </div>

      {rendered && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-cyan-500/15 px-4 py-2 text-[11px] text-slate-500">
          <span>
            {rendered.measuresRendered} dari {rendered.totalMeasures} birama
          </span>
          <span>·</span>
          <span className="font-mono text-cyan-300">
            {rendered.measuresRendered * 4 * (60 / scoreBpm) > 0
              ? `≈ ${Math.round(rendered.measuresRendered * 4 * (60 / scoreBpm))} detik pertama`
              : ""}
          </span>
          <span>·</span>
          <span className="font-mono text-pink-200">
            ♪ = {Math.round(scoreBpm)}
            {bpmOverride !== null ? " (manual)" : ""}
          </span>
          <span>·</span>
          <span className="font-mono text-pink-200">
            {key.label}
            {keyVex !== "auto" ? " (manual)" : ""}
          </span>
          <span>·</span>
          <span>grid 1/{Math.round(1920 / rendered.grid)}</span>
        </p>
      )}
    </section>
  );
}
