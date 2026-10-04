"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2 } from "lucide-react";
import type { Job } from "@/lib/api";
import { formatTime } from "@/lib/midi";

const STAGES: { id: string; label: string }[] = [
  { id: "fetching", label: "Ambil audio" },
  { id: "separating", label: "Stem separation" },
  { id: "transcribing", label: "Audio → MIDI" },
  { id: "finalizing", label: "Bersihkan MIDI" },
  { id: "done", label: "Selesai" },
];

interface Props {
  job: Job | null;
  uploadPct?: number | null;
  /** engine → wall-clock cost as a multiple of audio length (from /health) */
  speedFactors?: Record<string, number>;
}

export default function JobProgress({ job, uploadPct, speedFactors }: Props) {
  if (!job) return null;

  const order = STAGES.map((s) => s.id);
  const activeIdx = order.indexOf(job.stage === "queued" ? "fetching" : job.stage);
  const failed = job.status === "error";

  // Long inputs are a long wait, and it is better to say so up front than to let
  // someone conclude the app has hung. The engine is named in the job's own events
  // (the pipeline logs "engine: transkun"), so no extra request is needed.
  const engine = job.events
    ?.find((e) => e.message.startsWith("engine: "))
    ?.message.slice("engine: ".length)
    .trim();
  const factor = engine ? speedFactors?.[engine] : undefined;
  const estMinutes = factor && job.duration ? (job.duration * factor) / 60 : 0;

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 p-4 backdrop-blur"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm text-slate-100">
            {job.title || (job.source_type === "youtube" ? job.source_ref : "Audio upload")}
          </p>
          <p className="text-[11px] text-slate-500">
            {job.source_type === "youtube" ? "YouTube" : "File"} ·{" "}
            <span className="font-mono">{job.id}</span>
            {job.duration > 0 && ` · ${formatTime(job.duration)}`}
          </p>
        </div>
        {failed ? (
          <span className="flex items-center gap-1.5 rounded-full bg-pink-500/15 px-2.5 py-1 text-[11px] text-pink-200 ring-1 ring-pink-400/30">
            <AlertTriangle size={12} /> Gagal
          </span>
        ) : job.status === "done" ? (
          <span className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] text-emerald-200 ring-1 ring-emerald-400/30">
            <CheckCircle2 size={12} /> {job.note_count} not
          </span>
        ) : (
          <span className="flex items-center gap-1.5 rounded-full bg-cyan-500/15 px-2.5 py-1 text-[11px] text-cyan-200 ring-1 ring-cyan-400/30">
            <Loader2 size={12} className="animate-spin" /> {Math.round(job.progress * 100)}%
          </span>
        )}
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <motion.div
          className={`h-full ${failed ? "bg-pink-500" : "bg-gradient-to-r from-cyan-400 to-pink-400"}`}
          animate={{ width: `${Math.max(2, job.progress * 100)}%` }}
          transition={{ ease: "easeOut", duration: 0.4 }}
        />
      </div>

      <ol className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {STAGES.filter((s) => s.id !== "separating" || job.options?.stems).map((s, i) => {
          const idx = order.indexOf(s.id);
          const done = !failed && (job.status === "done" || idx < activeIdx);
          const current = !failed && idx === activeIdx && job.status !== "done";
          return (
            <li
              key={s.id}
              className={`flex items-center gap-1.5 text-[11px] ${
                failed && current
                  ? "text-pink-300"
                  : done
                    ? "text-emerald-300/90"
                    : current
                      ? "text-cyan-200"
                      : "text-slate-600"
              }`}
            >
              {done ? (
                <CheckCircle2 size={11} />
              ) : current ? (
                <Loader2 size={11} className="animate-spin" />
              ) : (
                <CircleDashed size={11} />
              )}
              {s.label}
              {i === 0 && uploadPct != null && uploadPct < 1 && !failed && (
                <span className="text-slate-500">({Math.round(uploadPct * 100)}%)</span>
              )}
            </li>
          );
        })}
      </ol>

      <AnimatePresence initial={false}>
        {job.events && job.events.length > 0 && !failed && (
          <motion.p
            key={job.events[job.events.length - 1].message}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="mt-3 truncate font-mono text-[11px] text-slate-500"
          >
            {job.events[job.events.length - 1].message}
          </motion.p>
        )}
      </AnimatePresence>

      {estMinutes > 0 && job.status === "running" && (
        <p className="mt-2 text-[11px] text-slate-500">
          perkiraan total ≈ <span className="font-mono text-slate-400">
            {estMinutes >= 1 ? `${Math.round(estMinutes)} menit` : `${Math.round(estMinutes * 60)} detik`}
          </span>{" "}
          · {engine} {factor}× durasi audio
          {estMinutes >= 10 && " — biarkan tab ini terbuka, proses jalan di server"}
        </p>
      )}

      {failed && (
        <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-pink-500/20 bg-black/40 p-2.5 font-mono text-[11px] text-pink-200/90">
          {job.error || "terjadi kesalahan"}
          {job.events
            ?.filter((e) => e.stage === "error")
            .slice(-1)
            .map((e) => `\n\n${e.message}`)}
        </pre>
      )}
    </motion.section>
  );
}
