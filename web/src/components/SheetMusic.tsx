"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { FileMusic, FileText, Loader2, Sheet } from "lucide-react";
import type { NoteEvent, PedalEvent } from "@/lib/audio";
import { detectKey } from "@/lib/key";
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
  const key = useMemo(() => detectKey(notes), [notes]);

  useEffect(() => {
    setRendered(null);
    setErr(null);
    if (hostRef.current) hostRef.current.innerHTML = "";
  }, [notes, bpm, pedal]);

  const render = () => {
    if (!hostRef.current) return;
    setBusy(true);
    setErr(null);
    // let the spinner paint before the synchronous engraving pass
    setTimeout(() => {
      try {
        const res = renderScore(hostRef.current!, notes, bpm, { tempo: bpm, key, pedal });
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
            {rendered.measuresRendered * 4 * (60 / bpm) > 0
              ? `≈ ${Math.round(rendered.measuresRendered * 4 * (60 / bpm))} detik pertama`
              : ""}
          </span>
          <span>·</span>
          <span className="font-mono text-pink-200">♪ = {Math.round(bpm)}</span>
          <span>·</span>
          <span className="font-mono text-pink-200">{key.label}</span>
          <span>·</span>
          <span>grid 1/{Math.round(1920 / rendered.grid)}</span>
        </p>
      )}
    </section>
  );
}
