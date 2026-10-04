/** Typed client for the MidiMagic Python backend. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8892";

export type JobStage =
  | "queued"
  | "fetching"
  | "separating"
  | "transcribing"
  | "finalizing"
  | "done"
  | "error";

export interface JobEvent {
  ts: number;
  stage: string;
  message: string;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "done" | "error" | "deleted";
  stage: JobStage;
  progress: number;
  message: string;
  source_type: "upload" | "youtube";
  source_ref: string;
  title: string;
  options: Record<string, unknown>;
  midi_path?: string | null;
  audio_path?: string | null;
  stems: Record<string, string>;
  /** sustain-pedal detection result from the backend */
  pedal?: PedalInfo;
  accuracy?: string;
  note_count: number;
  duration: number;
  error: string;
  created_at: number;
  updated_at: number;
  events?: JobEvent[];
}

export interface JobOptions {
  stems?: boolean;
  stem_mode?: "vocals" | "full";
  target?: "melody" | "vocals" | "instrumental" | "mix";
  engine?: "basic-pitch" | "librosa-pyin";
  /** accuracy preset — thresholds below only apply when set explicitly */
  accuracy?: "fast" | "balanced" | "precise";
  onset_threshold?: number;
  frame_threshold?: number;
  min_note_length?: number;
  min_frequency?: number;
  max_frequency?: number;
  suppress_percussion?: boolean;
  min_velocity?: number;
  merge_gap?: number;
  quantize?: number;
}

export interface PedalInfo {
  segments?: number;
  pedalled_seconds?: number;
  ratio?: number;
  median_gap_ratio?: number;
  gaps?: number;
  skipped?: boolean;
}

export interface Health {
  status: string;
  time: number;
  engines: {
    transcription: string;
    basic_pitch: boolean;
    librosa: boolean;
    demucs: boolean;
    yt_dlp: boolean;
    ffmpeg: boolean;
  };
  config: {
    demucs_model: string;
    workers: number;
    yt_max_seconds: number;
    max_upload_mb: number;
    accuracy_presets?: string[];
    default_accuracy?: string;
  };
  stats: {
    total: number;
    done: number;
    failed: number;
    active: number;
    notes: number;
    shares: number;
  };
}

export interface ShareInfo {
  slug: string;
  title: string;
  note_count: number;
  duration: number;
  created_at?: number;
  hits?: number;
  midi_url?: string;
  url?: string;
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body?.detail || body?.error || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => jsonFetch<Health>("/api/health"),

  listJobs: (limit = 30) =>
    jsonFetch<{ jobs: Job[]; stats: Health["stats"] }>(`/api/jobs?limit=${limit}`),

  getJob: (id: string) => jsonFetch<Job>(`/api/jobs/${id}`),

  deleteJob: (id: string) =>
    jsonFetch<{ ok: boolean }>(`/api/jobs/${id}`, { method: "DELETE" }),

  createFromFile: (file: File, options: JobOptions, onProgress?: (pct: number) => void) =>
    new Promise<{ job_id: string }>((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      for (const [k, v] of Object.entries(options)) {
        if (v !== undefined && v !== null) fd.append(k, String(v));
      }
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/api/jobs`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new Error("respons tidak valid"));
          }
        } else {
          let detail = `upload gagal (${xhr.status})`;
          try {
            detail = JSON.parse(xhr.responseText).detail || detail;
          } catch {
            /* ignore */
          }
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error("koneksi ke backend gagal"));
      xhr.send(fd);
    }),

  createFromYoutube: (youtube_url: string, options: JobOptions, title = "") =>
    jsonFetch<{ job_id: string }>("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ youtube_url, options, title }),
    }),

  midiUrl: (id: string, opts?: { download?: boolean; semitones?: number; tempo?: number }) => {
    const q = new URLSearchParams();
    if (opts?.download) q.set("download", "1");
    if (opts?.semitones) q.set("semitones", String(opts.semitones));
    if (opts?.tempo && opts.tempo !== 1) q.set("tempo", String(opts.tempo));
    const s = q.toString();
    return `${API_BASE}/api/jobs/${id}/midi${s ? `?${s}` : ""}`;
  },

  audioUrl: (id: string) => `${API_BASE}/api/jobs/${id}/audio`,

  createShare: (job_id: string, title?: string) =>
    jsonFetch<ShareInfo>("/api/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id, title }),
    }),

  getShare: (slug: string) => jsonFetch<ShareInfo>(`/api/shares/${slug}`),

  shareMidiUrl: (slug: string, download = false) =>
    `${API_BASE}/api/shares/${slug}/midi${download ? "?download=1" : ""}`,
};
