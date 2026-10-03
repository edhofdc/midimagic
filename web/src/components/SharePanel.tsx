"use client";

import { useState } from "react";
import { Check, Copy, Download, Link2, Loader2, Share2 } from "lucide-react";
import { api, type Job, type ShareInfo } from "@/lib/api";
import { downloadBlob } from "@/lib/midi";

interface Props {
  job: Job | null;
  title: string;
  semitones: number;
  speed: number;
}

export default function SharePanel({ job, title, semitones, speed }: Props) {
  const [share, setShare] = useState<ShareInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const ready = job?.status === "done";

  const downloadMidi = (withTransform: boolean) => {
    if (!job) return;
    const url = withTransform
      ? api.midiUrl(job.id, { download: true, semitones, tempo: speed })
      : api.midiUrl(job.id, { download: true });
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(title || job.title || "midimagic").replace(/\s+/g, "_")}.mid`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const downloadRaw = async () => {
    if (!job) return;
    const res = await fetch(api.midiUrl(job.id));
    downloadBlob(await res.blob(), `${(title || job.title || "midimagic").replace(/\s+/g, "_")}.mid`);
  };

  const makeShare = async () => {
    if (!job) return;
    setBusy(true);
    setErr(null);
    try {
      setShare(await api.createShare(job.id, title || job.title));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!share) return;
    try {
      await navigator.clipboard.writeText(share.url!);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setErr("gagal menyalin — salin manual dari kotak di bawah");
    }
  };

  return (
    <section className="rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 p-4 backdrop-blur">
      <h2 className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300/80">
        <Share2 size={13} /> Export & Share
      </h2>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={downloadRaw}
          disabled={!ready}
          className="flex items-center gap-1.5 rounded-lg bg-cyan-500/15 px-3 py-2 text-xs text-cyan-100 ring-1 ring-cyan-400/40 transition hover:bg-cyan-400/25 disabled:opacity-40"
        >
          <Download size={13} /> .mid (asli)
        </button>
        <button
          type="button"
          onClick={() => downloadMidi(true)}
          disabled={!ready}
          className="flex items-center gap-1.5 rounded-lg bg-pink-500/15 px-3 py-2 text-xs text-pink-100 ring-1 ring-pink-400/40 transition hover:bg-pink-400/25 disabled:opacity-40"
          title="MIDI ditulis ulang di server dengan transpose & tempo saat ini"
        >
          <Download size={13} /> .mid (transpose {semitones >= 0 ? `+${semitones}` : semitones},{" "}
          {Math.round(speed * 100)}%)
        </button>
        <button
          type="button"
          onClick={makeShare}
          disabled={!ready || busy}
          className="flex items-center gap-1.5 rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-200 ring-1 ring-white/10 transition hover:bg-white/10 disabled:opacity-40"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Link2 size={13} />}
          Buat tautan share
        </button>
      </div>

      {err && <p className="mt-3 text-xs text-pink-300">{err}</p>}

      {share && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-3 py-2">
          <input
            readOnly
            value={share.url}
            className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-emerald-200 outline-none"
            onFocus={(e) => e.currentTarget.select()}
          />
          <button
            type="button"
            onClick={copy}
            className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-slate-300 hover:bg-white/10"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? "tersalin" : "salin"}
          </button>
        </div>
      )}

      <p className="mt-3 text-[11px] text-slate-500">
        Unduhan MIDI yang sudah ditranspose/tempo dihasilkan ulang di server, jadi hasilnya
        sama persis dengan yang kamu dengar di sini.
      </p>
    </section>
  );
}
