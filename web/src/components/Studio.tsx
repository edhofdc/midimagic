"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioWaveform, HardDrive, Loader2, Sparkles, Zap } from "lucide-react";
import { api, API_BASE, type Health, type Job, type JobOptions } from "@/lib/api";
import type { InstrumentId, MidiPlayer, NoteEvent, PedalEvent } from "@/lib/audio";
import { INSTRUMENTS } from "@/lib/instruments";
import { loadMidi, sanitizeNotes } from "@/lib/midi";
import { useIsMobile } from "@/lib/useMediaQuery";
import SourcePanel from "@/components/SourcePanel";
import JobProgress from "@/components/JobProgress";
import PianoRoll from "@/components/PianoRoll";
import Transport from "@/components/Transport";
import TransformPanel from "@/components/TransformPanel";
import SheetMusic from "@/components/SheetMusic";
import SharePanel from "@/components/SharePanel";
import Library from "@/components/Library";
import BottomTabs, { type MobileTab } from "@/components/BottomTabs";

export default function Studio() {
  const playerRef = useRef<MidiPlayer | null>(null);
  const [player, setPlayer] = useState<MidiPlayer | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [notes, setNotes] = useState<NoteEvent[]>([]);
  const [pedal, setPedal] = useState<PedalEvent[]>([]);
  const [bpm, setBpm] = useState(120);
  const [instrument, setInstrument] = useState<InstrumentId>("grand-piano");
  const [speed, setSpeed] = useState(1);
  const [transpose, setTranspose] = useState(0);
  const [zoom, setZoom] = useState(26);
  const [visibleSeconds, setVisibleSeconds] = useState(3.5);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [libBusy, setLibBusy] = useState(false);
  const [engineReady, setEngineReady] = useState(false);
  const [tab, setTab] = useState<MobileTab>("play");
  const isMobile = useIsMobile();

  /* ---------------------------------------------------------------- engine */
  useEffect(() => {
    let instance: MidiPlayer | null = null;
    let cancelled = false;
    // Tone.js needs a real AudioContext, so the engine is built client-side only
    import("@/lib/audio").then(async ({ MidiPlayer }) => {
      if (cancelled) return;
      instance = new MidiPlayer();
      playerRef.current = instance;
      setPlayer(instance);
      // debug handle: lets us inspect the audio graph from the console / QA
      (window as unknown as { __midimagic?: unknown }).__midimagic = instance;
      await instance.whenReady();
      if (!cancelled) setEngineReady(true);
    });
    return () => {
      cancelled = true;
      instance?.dispose();
      playerRef.current = null;
      setEngineReady(false);
    };
  }, []);

  useEffect(() => {
    if (!player) return;
    const wasSame = player.getInstrument() === instrument;
    player.setInstrument(instrument);
    if (wasSame) return;
    setEngineReady(false);
    let cancelled = false;
    player.whenReady().then(() => {
      if (!cancelled) setEngineReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [player, instrument]);
  useEffect(() => {
    if (player) player.speed = speed;
  }, [player, speed]);
  useEffect(() => {
    if (player) player.transpose = transpose;
  }, [player, transpose]);

  /* ---------------------------------------------------------------- data */
  const refresh = useCallback(async () => {
    setLibBusy(true);
    try {
      const res = await api.listJobs(40);
      setJobs(res.jobs);
    } catch {
      /* library is non-critical */
    } finally {
      setLibBusy(false);
    }
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    void refresh();
  }, [refresh]);

  const loadResult = useCallback(
    async (j: Job) => {
      setJob(j);
      if (j.status !== "done") return;
      try {
        const parsed = await loadMidi(api.midiUrl(j.id));
        const clean = sanitizeNotes(parsed.notes);
        setNotes(clean);
        setPedal(parsed.pedal);
        setBpm(parsed.tempo || 120);
        // the pedal inferred from the recording is replayed automatically
        playerRef.current?.load(clean, parsed.duration, parsed.pedal);
        setError(null);
        // picking a track means you want to hear it — jump to the player
        setTab("play");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    []
  );

  /* poll while the pipeline is running */
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const t = setInterval(async () => {
      try {
        const fresh = await api.getJob(job.id);
        setJob(fresh);
        if (fresh.status === "done") {
          void loadResult(fresh);
          void refresh();
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job, loadResult, refresh]);

  /* ---------------------------------------------------------------- submit */
  const submitFile = async (file: File, options: JobOptions) => {
    setBusy(true);
    setError(null);
    setUploadPct(0);
    try {
      const { job_id } = await api.createFromFile(file, options, setUploadPct);
      setUploadPct(1);
      const created = await api.getJob(job_id);
      setJob(created);
      setNotes([]);
      setPedal([]);
      playerRef.current?.load([], 0, []);
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setTimeout(() => setUploadPct(null), 1200);
    }
  };

  const submitYoutube = async (url: string, options: JobOptions) => {
    setBusy(true);
    setError(null);
    try {
      const { job_id } = await api.createFromYoutube(url, options);
      const created = await api.getJob(job_id);
      setJob(created);
      setNotes([]);
      setPedal([]);
      playerRef.current?.load([], 0, []);
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const removeJob = async (j: Job) => {
    try {
      await api.deleteJob(j.id);
      if (job?.id === j.id) {
        setJob(null);
        setNotes([]);
        setPedal([]);
        playerRef.current?.load([], 0, []);
      }
      void refresh();
    } catch {
      /* ignore */
    }
  };

  const title = job?.title || job?.source_ref || "midimagic";
  const stats = health?.stats;
  const duration = notes.length ? Math.max(...notes.map((n) => n.end)) : 0;
  const running = !!job && job.status !== "done" && job.status !== "error";

  const pills = useMemo(
    () =>
      health
        ? [
            { label: "Transkripsi", ok: health.engines.basic_pitch || health.engines.librosa, value: health.engines.transcription },
            { label: "Stem AI", ok: health.engines.demucs, value: health.engines.demucs ? health.config.demucs_model : "off" },
            { label: "YouTube", ok: health.engines.yt_dlp, value: health.engines.yt_dlp ? "yt-dlp" : "off" },
            { label: "FFmpeg", ok: health.engines.ffmpeg, value: health.engines.ffmpeg ? "ready" : "off" },
          ]
        : [],
    [health]
  );

  /* ------------------------------------------------------------- fragments */
  const header = (
    <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-black shadow-[0_0_28px_-6px_rgba(0,240,255,0.9)]">
          <AudioWaveform size={20} />
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight text-white">
            Midi<span className="text-cyan-300">Magic</span>
          </h1>
          <p className="truncate text-[11px] text-slate-500">
            {isMobile ? truncate(title, 42) : "Audio · YouTube → MIDI → Piano Visualizer"}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {pills.map((p) => (
          <span
            key={p.label}
            title={`${p.label}: ${p.value}`}
            className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] ring-1 ${
              p.ok
                ? "bg-emerald-500/10 text-emerald-200 ring-emerald-400/25"
                : "bg-pink-500/10 text-pink-200 ring-pink-400/25"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${p.ok ? "bg-emerald-400" : "bg-pink-400"}`}
            />
            <span className={isMobile ? "hidden" : ""}>{p.label}</span>
          </span>
        ))}
      </div>
    </header>
  );

  const sourceGroup = (
    <>
      <SourcePanel
        health={health}
        busy={busy}
        error={error}
        onSubmitFile={submitFile}
        onSubmitYoutube={submitYoutube}
      />
      <JobProgress job={job} uploadPct={uploadPct} />
    </>
  );

  const libraryGroup = (
    <>
      <Library
        jobs={jobs}
        activeId={job?.id ?? null}
        onSelect={loadResult}
        onDelete={removeJob}
        onRefresh={() => void refresh()}
        loading={libBusy}
      />
      {stats && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
          {[
            ["Konversi", stats.done],
            ["Aktif", stats.active],
            ["Total not", stats.notes],
            ["Share", stats.shares],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2"
            >
              <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
              <p className="font-mono text-sm text-cyan-200">{value}</p>
            </div>
          ))}
        </div>
      )}
    </>
  );

  const playerGroup = (
    <>
      {player ? (
        <div className="relative">
          <PianoRoll
            player={player}
            notes={notes}
            zoom={zoom}
            visibleSeconds={visibleSeconds}
            onSeek={(s) => player.seek(s)}
            rollHeight={isMobile ? 250 : 380}
            keyboardHeight={isMobile ? 74 : 96}
          />
          {!engineReady && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center rounded-xl bg-black/60 backdrop-blur-sm">
              <span className="flex items-center gap-2 rounded-full bg-cyan-500/15 px-3 py-1.5 text-xs text-cyan-100 ring-1 ring-cyan-400/30">
                <Loader2 size={13} className="animate-spin" />
                memuat sample {INSTRUMENTS.find((i) => i.id === instrument)?.label}…
              </span>
            </div>
          )}
        </div>
      ) : (
        <div
          className="grid place-items-center rounded-xl border border-cyan-500/20 bg-[#05060c] text-xs text-slate-500"
          style={{ height: isMobile ? 250 : 476 }}
        >
          menyiapkan audio engine…
        </div>
      )}

      {player && (
        <Transport
          player={player}
          duration={duration}
          disabled={notes.length === 0}
          hasPedal={pedal.length > 0}
          referenceUrl={job?.status === "done" ? api.audioUrl(job.id) : undefined}
          alignMs={job?.align_ms}
        />
      )}

      {notes.length > 0 && job?.pedal && !job.pedal.skipped && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-pink-500/20 bg-pink-500/[0.06] px-3 py-2 text-[11px] text-pink-100/80">
          <Zap size={11} className="text-pink-300" />
          Sustain dideteksi dari rekaman:
          <span className="font-mono text-pink-200">{job.pedal.segments ?? 0} segmen</span>
          <span className="text-slate-500">·</span>
          <span className="font-mono text-pink-200">
            {Math.round((job.pedal.ratio ?? 0) * 100)}% durasi
          </span>
          <span className="text-slate-500">— mode Auto memakai ini</span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-cyan-500/20 bg-[#0a0c16]/80 px-3 py-2 text-[11px] text-slate-400 backdrop-blur">
        <label className="flex items-center gap-2">
          Zoom piano
          <input
            type="range"
            min={14}
            max={48}
            step={1}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            className="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan-400"
          />
        </label>
        <label className="flex items-center gap-2">
          Rentang jatuh
          <input
            type="range"
            min={1.5}
            max={8}
            step={0.25}
            value={visibleSeconds}
            onChange={(e) => setVisibleSeconds(Number(e.target.value))}
            className="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-white/10 accent-pink-400 sm:w-28"
          />
          <span className="font-mono text-cyan-300">{visibleSeconds.toFixed(1)}s</span>
        </label>
        <span className="ml-auto flex items-center gap-1 text-slate-500">
          <Zap size={11} className="text-cyan-400" /> {notes.length} not
        </span>
        <span className="flex items-center gap-1 font-mono text-pink-200" title="Tempo terdeteksi dari rekaman">
          ♪ = {Math.round(bpm)}
        </span>
      </div>
    </>
  );

  const soundGroup = (
    <TransformPanel
      instrument={instrument}
      onInstrument={setInstrument}
      speed={speed}
      onSpeed={setSpeed}
      transpose={transpose}
      onTranspose={setTranspose}
    />
  );

  const scoreGroup = (
    <>
      <SheetMusic notes={notes} bpm={bpm} title={title} pedal={pedal} />
      <SharePanel job={job} title={title} semitones={transpose} speed={speed} />
    </>
  );

  return (
    <div className="min-h-dvh bg-[#05060c] text-slate-200">
      {/* ambient background */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 opacity-[0.5]"
        style={{
          background:
            "radial-gradient(1100px 500px at 12% -8%, rgba(0,240,255,0.16), transparent 60%), radial-gradient(900px 480px at 92% 4%, rgba(255,0,200,0.14), transparent 62%)",
        }}
      />

      <div
        className={`relative mx-auto max-w-[1500px] px-3 pt-4 sm:px-5 ${
          isMobile ? "pb-28" : "pb-24"
        }`}
      >
        {header}

        {isMobile ? (
          <div className="space-y-3">
            {tab === "play" && playerGroup}
            {tab === "source" && <div className="space-y-3">{sourceGroup}</div>}
            {tab === "sound" && soundGroup}
            {tab === "score" && <div className="space-y-3">{scoreGroup}</div>}
            {tab === "library" && <div className="space-y-3">{libraryGroup}</div>}
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
            {/* left column */}
            <div className="min-w-0 space-y-4">
              {sourceGroup}
              {libraryGroup}
            </div>

            {/* right column — min-w-0 matters: a grid track defaults to
                min-width:auto, so the wide piano-roll canvas and the score's
                min-w-[900px] page would stretch the 1fr column past the viewport
                and clip its right edge (the transport controls live there). */}
            <div className="min-w-0 space-y-4">
              {playerGroup}
              {soundGroup}
              <div className="grid min-w-0 gap-4 xl:grid-cols-2 [&>*]:min-w-0">
                {scoreGroup}
              </div>
            </div>
          </div>
        )}

        <footer className="mt-8 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
          <span className="flex items-center gap-1.5">
            <Sparkles size={11} /> basic-pitch · Demucs · Tone.js · VexFlow
          </span>
          <span className="flex items-center gap-1.5">
            <HardDrive size={11} /> backend <span className="font-mono">{API_BASE}</span> — semua
            proses lokal
          </span>
        </footer>
      </div>

      {isMobile && (
        <BottomTabs
          tab={tab}
          onChange={setTab}
          badges={{
            source: running ? "busy" : undefined,
            library: notes.length > 0 ? "ready" : undefined,
          }}
        />
      )}
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
