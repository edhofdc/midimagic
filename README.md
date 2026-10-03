# MidiMagic

Ubah **MP3/WAV/OGG** atau **tautan YouTube** menjadi **MIDI**, lalu mainkan di piano
visualizer ala Synthesia langsung di browser — lengkap dengan not balok, stem separation,
multi-instrumen synth, transpose, dan tautan share.

Semua proses berat (transkripsi AI, pemisahan stem, unduh YouTube) jalan **lokal di mesin ini**;
browser hanya menangani playback, visual, dan notasi.

```
Audio / YouTube ──> yt-dlp + ffmpeg ──> [Demucs stem AI] ──> basic-pitch (AI audio→MIDI)
                          │                                            │
                          └────────────► preview audio ◄───────────────┘
                                                                       │
                                          Next.js UI  ◄──── MIDI ──────┘
                          (falling notes, 88-key piano, partitur VexFlow, Tone.js synth)
```

## Fitur

| Fitur | Status | Catatan |
|---|---|---|
| Upload lokal (MP3/WAV/OGG/FLAC/M4A/Opus/WebM) | ✅ | drag & drop, maks 60 MB |
| Input URL YouTube | ✅ | yt-dlp, batas durasi 15 menit |
| AI Audio → MIDI (polifonik) | ✅ | **basic-pitch** (ONNX, CPU) |
| Fallback transkripsi melodi | ✅ | **librosa pyin** (monofonik) bila basic-pitch gagal |
| AI Stem Separation | ✅ | **Demucs** 2-stem (vokal/instrumental) atau 4-stem |
| Interactive Piano Simulator (88 tuts) | ✅ | tuts menyala mengikuti not yang berbunyi |
| Synthesia-style falling notes | ✅ | canvas, warna per pitch, auto-follow, click-to-seek |
| Play / Pause / Stop / Seek / Volume | ✅ | transport dengan range-request audio + level meter |
| **Sustain pedal** | ✅ | not tetap berbunyi setelah tuts lepas, seperti pedal ditahan |
| Tempo & Pitch shifting | ✅ | 25%–200% tanpa ubah pitch; transpose −12…+12 semitone |
| Sheet Music Generator | ✅ | **VexFlow** grand staff treble+bass, 4/4 |
| Multi-Instrument Synth | ✅ | 4 instrumen **berbasis rekaman asli** (sample) + 2 sintetis |
| Export | ✅ | `.mid` asli, `.mid` hasil transpose/tempo (di-render ulang di server), `.pdf` partitur |
| Share link | ✅ | slug unik, halaman `/share/<slug>` read-only + penghitung kunjungan |

## Arsitektur

Dua proses, karena bagian AI-nya Python:

| Bagian | Stack | Port |
|---|---|---|
| `web/` — UI | Next.js 16 (App Router) · Tailwind v4 · Framer Motion · Tone.js · @tonejs/midi · VexFlow · jsPDF | **8891** |
| `backend/` — pipeline | FastAPI · yt-dlp · Demucs · basic-pitch (ONNX) · librosa · pretty_midi · ffmpeg | **8892** |

State disimpan di SQLite (`backend/data/midimagic.db`) dengan tabel `jobs`, `shares`, `events`
— **additive**: setiap konversi jadi record baru, tidak pernah menimpa yang lama.

## Instalasi

### 1. Sistem

```bash
sudo apt install ffmpeg python3-venv
node -v   # butuh Node 20+ — juga dipakai yt-dlp sebagai JS runtime
```

> **YouTube:** sejak yt-dlp 2025.x ekstraksi YouTube butuh JS runtime. Backend memanggilnya
> dengan `--js-runtimes node` (lihat `MIDIMAGIC_YT_JS_RUNTIME`). Tanpa itu banyak format
> hilang dan unduhan sering gagal.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -U pip wheel setuptools
.venv/bin/pip install -r requirements.txt

# PyTorch CPU (jangan pakai index default, itu CUDA dan besar)
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio

# basic-pitch dari jalur ONNX: paket normal mem-pin numpy<2 dan gagal build di Python 3.13
.venv/bin/pip install --no-deps basic-pitch
.venv/bin/pip install onnxruntime mir_eval resampy
```

> **Catatan Python 3.13:** `pip install basic-pitch` (path TensorFlow) akan gagal:
> resolvernya menurunkan numpy ke versi tanpa wheel cp313 lalu mencoba build dari source.
> Pakai urutan `--no-deps` + `onnxruntime` di atas — modelnya identik
> (`basic_pitch/saved_models/icassp_2022/nmp.onnx`), jauh lebih ringan dan cepat.

### 3. Sampel instrumen (aset audio)

Instrumennya memakai **rekaman asli**, bukan oscillator:

| Instrumen | Sumber | Sample |
|---|---|---|
| Grand Piano | [Salamander Grand Piano](https://tonejs.github.io/audio/salamander/) (Alexander Holm, CC-BY 3.0) | 30 (A0–C8) |
| Electric Piano | MusyngKite `electric_piano_1` | 30 |
| Guitar (Nylon) | MusyngKite `acoustic_guitar_nylon` | 30 |
| String Ensemble | MusyngKite `string_ensemble_1` | 30 |

```bash
python3 scripts/fetch_samples.py      # ~3,5 MB, sekali saja
```

Skrip mengunduh ke `web/public/audio/` dan menulis `web/src/lib/sample-manifest.json`.
Tone.Sampler melakukan pitch-shift antar sample (±1,5 semitone), jadi 30 sample per instrumen
sudah cukup — tidak ada artefak yang terdengar.

Analog Synth dan 8-bit Chiptune tetap sintetis (memang itu maksudnya).

### 4. Frontend

```bash
cd web
npm install
cp .env.local.example .env.local   # lalu sesuaikan
npm run build
```

## Menjalankan

```bash
# terminal 1 — backend
cd backend && ./run.sh

# terminal 2 — frontend (production)
cd web && npx next start -p 8891 -H 0.0.0.0
```

Buka `http://localhost:8891`.

### Systemd (opsional, auto-start)

```bash
cp deploy/midimagic-api.service deploy/midimagic-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now midimagic-api midimagic-web
```

## Konfigurasi

Backend membaca env var berikut (default di `backend/app/config.py`):

| Variabel | Default | Arti |
|---|---|---|
| `MIDIMAGIC_PORT` | `8892` | port API |
| `MIDIMAGIC_PUBLIC_ORIGIN` | `http://localhost:8891` | dipakai menyusun URL share |
| `MIDIMAGIC_DEMUCS_MODEL` | `htdemucs` | model Demucs |
| `MIDIMAGIC_WORKERS` | `1` | worker paralel (naikkan hanya kalau RAM cukup) |
| `MIDIMAGIC_YT_MAX_SECONDS` | `900` | batas durasi YouTube |
| `MIDIMAGIC_YT_JS_RUNTIME` | `node` | JS runtime untuk ekstraksi YouTube (kosongkan untuk mematikan) |
| `MIDIMAGIC_MAX_UPLOAD_MB` | `60` | batas ukuran upload |

Frontend: `NEXT_PUBLIC_API_BASE` di `web/.env.local` — **di-bake saat build**, jadi ubah lalu
`npm run build` ulang.

## API

| Method | Path | Fungsi |
|---|---|---|
| `GET` | `/api/health` | status engine + statistik |
| `POST` | `/api/jobs` | multipart `file` **atau** JSON `{youtube_url, options}` |
| `GET` | `/api/jobs` | daftar job |
| `GET` | `/api/jobs/{id}` | detail + progress + log event |
| `DELETE` | `/api/jobs/{id}` | hapus job + artefaknya |
| `GET` | `/api/jobs/{id}/midi` | `.mid` (query: `download`, `semitones`, `tempo`) |
| `GET` | `/api/jobs/{id}/audio` | preview mp3, mendukung `Range` |
| `POST` | `/api/shares` | buat share `{job_id, title}` |
| `GET` | `/api/shares/{slug}` | metadata share |
| `GET` | `/api/shares/{slug}/midi` | `.mid` hasil share |

Opsi job: `stems` (bool), `stem_mode` (`vocals`\|`full`), `target`
(`melody`\|`instrumental`\|`mix`), `engine` (`basic-pitch`\|`librosa-pyin`),
`onset_threshold`, `frame_threshold`, `min_note_length`.

## Uji

```bash
cd backend && .venv/bin/python tests/smoke_api.py data/test/melody_stereo.wav          # cepat
cd backend && .venv/bin/python tests/smoke_api.py data/test/melody_stereo.wav --stems  # ikut Demucs
```

Skrip membuat file WAV sintetis sendiri (`data/test/`), menjalankan job sampai selesai, lalu
memverifikasi MIDI, preview audio, range request, share, dan export transpose.

## Performa (mesin 4 vCPU, tanpa GPU)

| Tahap | 4 detik audio | Perkiraan lagu 3 menit |
|---|---|---|
| Transkripsi basic-pitch (ONNX) | ~1,5 s | ~1–2 menit |
| Stem separation Demucs | ~30 s | **~20–30 menit** |

Demucs memang berat di CPU. Kalau hanya butuh MIDI cepat, matikan stem separation — akurasi
sedikit turun tapi hasilnya tetap polifonik.

## Struktur

```
midimagic/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI: jobs, shares, range streaming
│   │   ├── jobs.py            # runner + orkestrasi pipeline
│   │   ├── db.py              # SQLite (additive)
│   │   ├── config.py
│   │   └── pipeline/
│   │       ├── fetch.py       # upload / yt-dlp → WAV
│   │       ├── stems.py       # Demucs
│   │       ├── transcribe.py  # basic-pitch / librosa-pyin → MIDI
│   │       └── post.py        # pembersihan + transpose/tempo
│   ├── tests/smoke_api.py
│   ├── data/                  # sqlite, artefak job, share
│   └── run.sh
├── web/
│   ├── src/app/{page,layout,globals.css,share/[slug]/page.tsx}
│   ├── src/components/        # Studio, PianoRoll, Transport, SheetMusic, dll
│   └── src/lib/               # api, audio (Tone), midi, score (VexFlow), keys, instruments
└── deploy/                    # unit systemd
```

## Kredit

basic-pitch (Spotify) · Demucs (Meta) · Tone.js · VexFlow · yt-dlp · Next.js
