"use client";

import { useCallback, useRef, useState } from "react";
import {
  AudioLines,
  Cloud,
  Link2,
  Loader2,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { api, type Health, type JobOptions } from "@/lib/api";

interface Props {
  health: Health | null;
  busy: boolean;
  onSubmitFile: (file: File, options: JobOptions) => Promise<void>;
  onSubmitYoutube: (url: string, options: JobOptions) => Promise<void>;
  error?: string | null;
}

const ACCEPT = ".mp3,.wav,.ogg,.flac,.m4a,.aac,.opus,.webm,audio/*";

const ACCURACY: { id: string; label: string; hint: string }[] = [
  { id: "fast", label: "Cepat", hint: "not panjang & jelas, paling sedikit noise" },
  { id: "balanced", label: "Seimbang", hint: "rekomendasi — detail vs noise" },
  { id: "precise", label: "Presisi", hint: "not halus & pelan ikut terdeteksi" },
];

export default function SourcePanel({
  health,
  busy,
  onSubmitFile,
  onSubmitYoutube,
  error,
}: Props) {
  const [tab, setTab] = useState<"file" | "url">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const [stems, setStems] = useState(false);
  const [stemMode, setStemMode] = useState<"vocals" | "full">("vocals");
  const [target, setTarget] = useState<"melody" | "instrumental" | "mix">("melody");
  const [engine, setEngine] = useState<"" | "transkun" | "basic-pitch" | "librosa-pyin">("");
  const [accuracy, setAccuracy] = useState<"fast" | "balanced" | "precise">("balanced");
  const [advanced, setAdvanced] = useState(false);
  const [customThresholds, setCustomThresholds] = useState(false);
  const [onset, setOnset] = useState(0.5);
  const [frame, setFrame] = useState(0.3);
  const [minLen, setMinLen] = useState(0.06);

  const buildOptions = useCallback(
    (): JobOptions => ({
      stems,
      stem_mode: stems ? stemMode : undefined,
      target: stems ? target : undefined,
      engine: engine || undefined,
      accuracy,
      // only send raw numbers once the user overrides the preset by hand
      onset_threshold: customThresholds ? onset : undefined,
      frame_threshold: customThresholds ? frame : undefined,
      min_note_length: customThresholds ? minLen : undefined,
    }),
    [stems, stemMode, target, engine, accuracy, customThresholds, onset, frame, minLen]
  );

  const pick = (f: File | null) => {
    if (!f) return;
    setFile(f);
  };

  const maxMb = health?.config.max_upload_mb ?? 60;

  return (
    <section className="rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 p-4 backdrop-blur">
      <div className="mb-3 flex gap-1 rounded-lg bg-black/40 p-1">
        {(
          [
            { id: "file", label: "Upload Audio", icon: Upload },
            { id: "url", label: "YouTube URL", icon: Link2 },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-medium transition ${
              tab === id
                ? "bg-cyan-500/20 text-cyan-100 ring-1 ring-cyan-400/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "file" ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files?.[0] ?? null);
          }}
          onClick={() => inputRef.current?.click()}
          className={`flex min-h-[120px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-6 text-center transition ${
            dragging
              ? "border-cyan-400 bg-cyan-500/10"
              : "border-white/15 bg-black/20 hover:border-cyan-400/50"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
          {file ? (
            <>
              <AudioLines className="text-cyan-300" size={22} />
              <p className="max-w-full truncate text-sm text-cyan-100">{file.name}</p>
              <p className="text-[11px] text-slate-500">
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setFile(null);
                }}
                className="mt-1 flex items-center gap-1 text-[11px] text-slate-400 hover:text-pink-300"
              >
                <X size={12} /> hapus
              </button>
            </>
          ) : (
            <>
              <Cloud className="text-slate-500" size={22} />
              <p className="text-sm text-slate-300">
                Drop file audio di sini atau klik untuk memilih
              </p>
              <p className="text-[11px] text-slate-500">
                MP3 · WAV · OGG · FLAC · M4A — maks {maxMb} MB
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2.5 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-400/60"
          />
          <p className="text-[11px] text-slate-500">
            Audio di-download via yt-dlp. Batas durasi{" "}
            {Math.round(
              (health?.limits?.max_duration_seconds ?? health?.config.yt_max_seconds ?? 7200) / 60,
            )}{" "}
            menit.
            {(() => {
              const f = health?.speed_factors?.transkun;
              const lim = health?.limits?.long_audio_seconds ?? 600;
              return f ? (
                <>
                  {" "}Di atas {Math.round(lim / 60)} menit transkun jalan per-window
                  (aman memori), dan waktunya ≈ <b>{(f * 60).toFixed(0)} menit per jam audio</b> —
                  video 1,5 jam ≈ 1 jam proses. Mau cepat? pilih basic-pitch.
                </>
              ) : null;
            })()}
          </p>
        </div>
      )}

      {/* options */}
      <div className="mt-4 space-y-3">
        <div className="space-y-1.5">
          <span className="text-[11px] uppercase tracking-wider text-slate-500">
            Ketepatan transkripsi
          </span>
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-black/40 p-1">
            {ACCURACY.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => {
                  setAccuracy(a.id as typeof accuracy);
                  setCustomThresholds(false);
                }}
                className={`rounded-md px-2 py-2 text-xs font-medium transition ${
                  accuracy === a.id
                    ? "bg-cyan-500/20 text-cyan-100 ring-1 ring-cyan-400/40"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {a.label}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-500">
            {ACCURACY.find((a) => a.id === accuracy)?.hint}
          </p>
        </div>

        <label className="flex items-start gap-3 rounded-lg bg-black/20 p-3 ring-1 ring-white/10">
          <input
            type="checkbox"
            checked={stems}
            onChange={(e) => setStems(e.target.checked)}
            className="mt-0.5 accent-cyan-400"
          />
          <span>
            <span className="flex items-center gap-1.5 text-sm text-slate-200">
              <Sparkles size={13} className="text-pink-300" /> AI Stem Separation
            </span>
            <span className="block text-[11px] text-slate-500">
              Pisahkan vokal/instrumen sebelum transkripsi — MIDI jauh lebih akurat.
              Ini tahap paling berat di CPU (tanpa GPU bisa 10-20 menit per lagu).
            </span>
          </span>
        </label>

        {stems && (
          <div className="grid gap-2 rounded-lg bg-black/20 p-3 text-xs ring-1 ring-white/10 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-slate-400">Mode pemisahan</span>
              <select
                value={stemMode}
                onChange={(e) => setStemMode(e.target.value as "vocals" | "full")}
                className="w-full rounded-md border border-white/10 bg-black/50 px-2 py-1.5 text-slate-200"
              >
                <option value="vocals">2-stem — vokal vs instrumental (cepat)</option>
                <option value="full">4-stem — vokal/drum/bass/other (lambat)</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-slate-400">Transkripsi dari</span>
              <select
                value={target}
                onChange={(e) =>
                  setTarget(e.target.value as "melody" | "instrumental" | "mix")
                }
                className="w-full rounded-md border border-white/10 bg-black/50 px-2 py-1.5 text-slate-200"
              >
                <option value="melody">Vokal / melodi utama</option>
                <option value="instrumental">Instrumental (piano/band)</option>
                <option value="mix">Campuran penuh</option>
              </select>
            </label>
          </div>
        )}

        <button
          type="button"
          onClick={() => setAdvanced((v) => !v)}
          className="text-[11px] text-slate-500 hover:text-cyan-300"
        >
          {advanced ? "▾" : "▸"} Pengaturan lanjutan (engine & threshold)
        </button>

        {advanced && (
          <div className="grid gap-3 rounded-lg bg-black/20 p-3 text-xs ring-1 ring-white/10 sm:grid-cols-2">
            <label className="space-y-1 sm:col-span-2">
              <span className="text-slate-400">Engine transkripsi</span>
              <select
                value={engine}
                onChange={(e) =>
                  setEngine(e.target.value as "" | "transkun" | "basic-pitch" | "librosa-pyin")
                }
                className="w-full rounded-md border border-white/10 bg-black/50 px-2 py-1.5 text-slate-200"
              >
                <option value="">
                  Otomatis ({health?.engines.transcription ?? "…"})
                </option>
                {(health?.config.engines ?? ["transkun", "basic-pitch", "librosa-pyin"]).includes(
                  "transkun"
                ) && (
                  <option value="transkun">transkun — khusus piano, paling presisi</option>
                )}
                <option value="basic-pitch">basic-pitch (polifonik umum)</option>
                <option value="librosa-pyin">librosa pyin (melodi monofonik)</option>
              </select>
              <span className="block text-[11px] leading-relaxed text-slate-500">
                {engine === "transkun" || (!engine && health?.engines.transcription === "transkun")
                  ? "transkun memakai model piano semi-CRF (MIT, Yujia Yan), memprediksi pedal sendiri, dan memperpanjang not lewat pedal. Khusus piano — untuk campuran vokal/instrumen pakai basic-pitch. Lebih lambat (~0.6× durasi audio di 4 CPU)."
                  : engine === "basic-pitch" || (!engine && health?.engines.transcription === "basic-pitch")
                    ? "basic-pitch: model polifonik umum. Cepat, tapi presisi piano di bawah transkun. Slider threshold di bawah hanya berlaku untuk engine ini."
                    : "pyin: pelacak melodi monofonik, untuk materi satu nada (vokal, seruling). Tidak untuk piano."}
              </span>
            </label>
            {(
              [
                ["Onset threshold", onset, setOnset, 0.1, 0.95],
                ["Frame threshold", frame, setFrame, 0.05, 0.95],
                ["Min note length (s)", minLen, setMinLen, 0.02, 0.5],
              ] as const
            ).map(([label, val, setter, min, max]) => (
              <label key={label} className="space-y-1">
                <span className="flex justify-between text-slate-400">
                  {label} <span className="font-mono text-cyan-300">{val}</span>
                </span>
                <input
                  type="range"
                  min={min}
                  max={max}
                  step={0.01}
                  value={val}
                  onChange={(e) => {
                    setCustomThresholds(true);
                    setter(Number(e.target.value));
                  }}
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan-400"
                />
              </label>
            ))}
            {customThresholds && (
              <p className="text-[11px] text-pink-200/80 sm:col-span-2">
                Threshold manual aktif — mengalahkan preset ketepatan.
              </p>
            )}
          </div>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-pink-500/30 bg-pink-500/10 px-3 py-2 text-xs text-pink-200">
          {error}
        </p>
      )}

      <button
        type="button"
        disabled={busy || (tab === "file" ? !file : !url.trim())}
        onClick={() => {
          if (tab === "file" && file) void onSubmitFile(file, buildOptions());
          if (tab === "url" && url.trim()) void onSubmitYoutube(url.trim(), buildOptions());
        }}
        className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-pink-500 px-4 py-2.5 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
        {busy ? "Memproses…" : "Convert ke MIDI"}
      </button>
    </section>
  );
}
