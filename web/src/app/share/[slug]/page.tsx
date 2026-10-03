"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AudioWaveform, Download, Loader2 } from "lucide-react";
import { api, type ShareInfo } from "@/lib/api";
import { loadMidi, sanitizeNotes, formatTime } from "@/lib/midi";
import type { InstrumentId, MidiPlayer, NoteEvent } from "@/lib/audio";
import PianoRoll from "@/components/PianoRoll";
import Transport from "@/components/Transport";
import TransformPanel from "@/components/TransformPanel";

export default function SharePage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug ?? "";

  const [info, setInfo] = useState<ShareInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<NoteEvent[]>([]);
  const [player, setPlayer] = useState<MidiPlayer | null>(null);
  const [instrument, setInstrument] = useState<InstrumentId>("grand-piano");
  const [speed, setSpeed] = useState(1);
  const [transpose, setTranspose] = useState(0);
  const [zoom] = useState(24);

  useEffect(() => {
    let instance: MidiPlayer | null = null;
    let cancelled = false;
    import("@/lib/audio").then(({ MidiPlayer }) => {
      if (cancelled) return;
      instance = new MidiPlayer();
      setPlayer(instance);
    });
    return () => {
      cancelled = true;
      instance?.dispose();
    };
  }, []);

  useEffect(() => {
    if (!slug) return;
    let alive = true;
    (async () => {
      try {
        const meta = await api.getShare(slug);
        if (!alive) return;
        setInfo(meta);
        const parsed = await loadMidi(api.shareMidiUrl(slug));
        if (!alive) return;
        setNotes(sanitizeNotes(parsed.notes));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [slug]);

  useEffect(() => {
    if (!player) return;
    player.setInstrument(instrument);
  }, [player, instrument]);
  useEffect(() => {
    if (player) player.speed = speed;
  }, [player, speed]);
  useEffect(() => {
    if (player) player.transpose = transpose;
  }, [player, transpose]);
  useEffect(() => {
    if (player && notes.length) player.load(notes, Math.max(...notes.map((n) => n.end)));
  }, [player, notes]);

  const duration = notes.length ? Math.max(...notes.map((n) => n.end)) : 0;

  return (
    <div className="min-h-dvh bg-[#05060c] text-slate-200">
      <div className="mx-auto max-w-[1200px] px-3 py-5 sm:px-5">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <Link href="/" className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-black">
              <AudioWaveform size={18} />
            </span>
            <span className="text-base font-semibold text-white">
              Midi<span className="text-cyan-300">Magic</span>
            </span>
          </Link>
          <a
            href={api.shareMidiUrl(slug, true)}
            className="flex items-center gap-1.5 rounded-lg bg-cyan-500/15 px-3 py-2 text-xs text-cyan-100 ring-1 ring-cyan-400/40 hover:bg-cyan-400/25"
          >
            <Download size={13} /> unduh .mid
          </a>
        </header>

        {error && (
          <p className="mb-4 rounded-lg border border-pink-500/30 bg-pink-500/10 px-3 py-2 text-sm text-pink-200">
            {error}
          </p>
        )}

        {!info && !error && (
          <div className="grid h-64 place-items-center text-slate-500">
            <Loader2 className="animate-spin" />
          </div>
        )}

        {info && (
          <>
            <div className="mb-4">
              <h1 className="text-lg font-semibold text-white">{info.title}</h1>
              <p className="text-[11px] text-slate-500">
                {info.note_count} not · {formatTime(duration || info.duration)}
                {typeof info.hits === "number" && ` · ${info.hits} kali dibuka`}
              </p>
            </div>

            <div className="space-y-4">
              {player ? (
                <PianoRoll
                  player={player}
                  notes={notes}
                  zoom={zoom}
                  visibleSeconds={3.5}
                  onSeek={(s) => player.seek(s)}
                />
              ) : (
                <div className="grid h-[476px] place-items-center rounded-xl border border-cyan-500/20 text-xs text-slate-500">
                  menyiapkan audio engine…
                </div>
              )}

              {player && (
                <Transport player={player} duration={duration} disabled={!notes.length} />
              )}

              <TransformPanel
                instrument={instrument}
                onInstrument={setInstrument}
                speed={speed}
                onSpeed={setSpeed}
                transpose={transpose}
                onTranspose={setTranspose}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
