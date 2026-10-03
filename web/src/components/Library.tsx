"use client";

import { motion } from "framer-motion";
import { Clock, Film, Music2, RefreshCw, Trash2, Upload } from "lucide-react";
import type { Job } from "@/lib/api";
import { formatTime } from "@/lib/midi";

interface Props {
  jobs: Job[];
  activeId: string | null;
  onSelect: (job: Job) => void;
  onDelete: (job: Job) => void;
  onRefresh: () => void;
  loading?: boolean;
}

const statusStyle: Record<string, string> = {
  done: "text-emerald-300 ring-emerald-400/30 bg-emerald-500/10",
  error: "text-pink-300 ring-pink-400/30 bg-pink-500/10",
  running: "text-cyan-200 ring-cyan-400/30 bg-cyan-500/10",
  queued: "text-slate-300 ring-white/15 bg-white/5",
  deleted: "text-slate-500 ring-white/10 bg-white/5",
};

export default function Library({
  jobs,
  activeId,
  onSelect,
  onDelete,
  onRefresh,
  loading,
}: Props) {
  return (
    <section className="rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 backdrop-blur">
      <header className="flex items-center justify-between border-b border-cyan-500/15 px-4 py-3">
        <h2 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300/80">
          <Music2 size={13} /> Library
        </h2>
        <button
          type="button"
          onClick={onRefresh}
          className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-cyan-300"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> refresh
        </button>
      </header>

      <div className="max-h-[420px] divide-y divide-white/5 overflow-auto">
        {jobs.length === 0 && (
          <p className="px-4 py-8 text-center text-xs text-slate-500">
            Belum ada konversi. Mulai dari panel di atas.
          </p>
        )}
        {jobs.map((job) => {
          const active = job.id === activeId;
          return (
            <motion.div
              key={job.id}
              layout
              className={`group flex items-center gap-3 px-4 py-2.5 transition ${
                active ? "bg-cyan-500/10" : "hover:bg-white/5"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(job)}
                className="flex min-w-0 flex-1 items-center gap-3 text-left"
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-black/40 text-cyan-300/80 ring-1 ring-white/10">
                  {job.source_type === "youtube" ? <Film size={14} /> : <Upload size={14} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-slate-200">
                    {job.title || job.source_ref || job.id}
                  </span>
                  <span className="flex items-center gap-2 text-[10px] text-slate-500">
                    <span
                      className={`rounded-full px-1.5 py-0.5 ring-1 ${
                        statusStyle[job.status] ?? statusStyle.queued
                      }`}
                    >
                      {job.status}
                    </span>
                    {job.note_count > 0 && <span>{job.note_count} not</span>}
                    {job.duration > 0 && (
                      <span className="flex items-center gap-1">
                        <Clock size={9} /> {formatTime(job.duration)}
                      </span>
                    )}
                  </span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => onDelete(job)}
                title="hapus"
                className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-slate-600 opacity-0 transition hover:bg-pink-500/15 hover:text-pink-300 group-hover:opacity-100"
              >
                <Trash2 size={13} />
              </button>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}
