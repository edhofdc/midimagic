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
| AI Audio → MIDI (polifonik) | ✅ | **basic-pitch** (ONNX, CPU), 3 preset ketepatan |
| Kualitas hasil | ✅ | pra-proses audio (normalisasi + band-limit + buang perkusi), gabung fragmen not, buang noise |
| Fallback transkripsi melodi | ✅ | **librosa pyin** (monofonik) bila basic-pitch gagal |
| AI Stem Separation | ✅ | **Demucs** 2-stem (vokal/instrumental) atau 4-stem |
| Interactive Piano Simulator (88 tuts) | ✅ | tuts menyala mengikuti not yang berbunyi |
| Synthesia-style falling notes | ✅ | canvas, warna per pitch, auto-follow, click-to-seek |
| Play / Pause / Stop / Seek / Volume | ✅ | transport dengan range-request audio + level meter |
| **Sustain pedal otomatis** | ✅ | pedal dideteksi dari rekaman (CC64), mode Auto/On/Off |
| Tempo & Pitch shifting | ✅ | 25%–200% tanpa ubah pitch; transpose −12…+12 semitone |
| Sheet Music Generator | ✅ | **VexFlow** grand staff treble+bass, 4/4 |
| Multi-Instrument Synth | ✅ | 4 instrumen **berbasis rekaman asli** (sample) + 2 sintetis |
| Export | ✅ | `.mid` asli (sudah membawa pedal), `.mid` transpose/tempo, `.pdf` partitur |
| Share link | ✅ | slug unik, halaman `/share/<slug>` read-only + penghitung kunjungan |
| **Layout mobile** | ✅ | bottom tab bar, kartu, piano roll dipendekkan, tanpa scroll horizontal |

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
| `MIDIMAGIC_MAX_UPLOAD_MB` | `60` | batas upload |
| `MIDIMAGIC_ANALYSIS_SR` | `22050` | sample rate analisis (transkripsi + deteksi pedal) |
| `MIDIMAGIC_TEMPO` | *(otomatis)* | override tempo; kosongkan supaya dideteksi dari audio |

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
`accuracy` (`fast`\|`balanced`\|`precise`), `onset_threshold`, `frame_threshold`,
`min_note_length`, `min_frequency`, `max_frequency`, `suppress_percussion`,
`min_velocity`, `merge_gap`, `quantize`, `tempo`.

`accuracy` memilih satu set threshold; mengirim `onset_threshold` / `frame_threshold` /
`min_note_length` secara eksplisit akan menimpainya.

## Cara kerja kualitas hasil

### Pra-proses audio

Upload dan hasil unduhan YouTube sangat berbeda levelnya, dan membawa rumble di bawah
jangkauan piano. Keduanya membuat model "berhalusinasi" not. Jadi setiap input dinormalisasi
puncaknya, di-band-limit ke rentang piano, dan perkusinya dibuang (harmonic/percussive
separation) sebelum masuk model. Hit drum adalah sumber not palsu nomor satu; kalau pakai
Demucs stem, langkah ini dilewati karena drumnya sudah hilang.

### Preset ketepatan

| Preset | Onset | Frame | Min panjang not | Rentang frekuensi |
|---|---|---|---|---|
| `fast` | 0.60 | 0.35 | 90 ms | 55–3520 Hz |
| `balanced` (default) | 0.50 | 0.30 | 58 ms | 41–4186 Hz |
| `precise` | 0.38 | 0.22 | 42 ms | 33–4978 Hz |

Onset lebih rendah = lebih sensitif (not pelan ikut tertangkap, tapi lebih banyak sampah).

### Pembersihan MIDI

Model memecah satu not piano menjadi 2–3 event berdempetan — itu terdengar seperti stutter dan
menggelembungkan jumlah not. Post-process **menggabungkan kembali** fragmen dengan pitch sama
yang jaraknya < 55 ms, memangkas tumpang-tindih, dan membuang bintik ber-velocity rendah yang
hampir pasti noise. Pada Canon in D (183 s): 1434 → **839 not** (380 fragmen digabung, 251 noise
dibuang), dan hasilnya jauh lebih mirip aslinya.

### Sustain pedal otomatis

Pedal piano itu **terdengar**, bukan ditebak. Saat pedal ditahan, senar terus berbunyi melewati
jeda antar-not alih-alih teredam. Jadi untuk setiap jeda diukur RMS jeda terhadap RMS not
sebelumnya:

- jeda yang tetap berbunyi → pedal ditahan
- jeda yang jatuh ke senyap → pedal dilepas

Jeda berbunyi berurutan dirangkai jadi satu region pedal — persis seperti pemain menahan pedal
sepanjang frasa. Region yang sangat panjang (> 8 s) dipotong dengan lepas-singkat 120 ms, seperti
pemain menekan ulang pedal.

Hasilnya ditulis ke MIDI sebagai **CC64**, jadi pedalnya ikut di dalam file: pemutar membacanya,
dan siapa pun yang mengunduh atau membuka `.mid` hasil share juga mendapatkannya.

Hasil pengukuran pada dua rekaman piano nyata:

| Rekaman | Jeda panjang turun ke | Coverage pedal |
|---|---|---|
| Canon in D (Jacob's Piano) — pedal ditahan terus | −4 dB | 99% |
| Rachmaninoff Op. 39 No. 6 — staccato/marcato | −33 dB (benar-benar teredam) | 88% |

Perbedaan −4 dB vs −33 dB itulah yang dipakai algoritma untuk memutuskan.

Mode pedal di UI: **Auto** (memakai hasil deteksi), **On** (paksa tahan), **Off** (paksa lepas).
Piano roll menampilkan lampu pedal kecil di atas keyboard saat pedal sedang aktif.

### Partitur (not balok)

Tiga hal menentukan apakah partitur cocok dengan rekaman, dan ketiganya dulu salah:

1. **Tempo.** Header tempo MIDI-lah yang memetakan detik ke waktu musikal. basic-pitch
   selalu menulis **120 BPM** kalau tidak diberi tahu, jadi setiap garis birama jatuh di
   tempat yang salah. Sekarang tempo dideteksi dari audio dan diteruskan ke basic-pitch
   (`--midi-tempo`). Contoh nyata: Rachmaninoff Op. 39 No. 6 terdeteksi **136 BPM**
   (sebelumnya 120).
2. **Kunci (key signature).** Dulu dipaksa C mayor, jadi semua accidental ditulis eksplisit
   dan tanda kunci salah. Sekarang kunci dideteksi dengan kecocokan profil
   Krumhansl-Kessler atas not hasil transkripsi.
3. **Grid kuantisasi.** Dulu kaku 1/16. Sekarang dipilih dari tempo (1/8 · 1/16 · 1/32)
   karena onset hasil transkripsi sifatnya kontinu — menebak grid dari jarak antar-onset
   selalu gagal dan menghasilkan halaman penuh not 1/64.

Selain itu, **tanda pedal (Ped. / \*)** digambar di bawah bass staff mengikuti CC64 hasil
deteksi — jadi "cara mainnya" ikut terlihat di partitur, bukan cuma terdengar.

#### Deteksi kunci: kenapa dibobot register

Pada repertoar kromatik, bobot durasi saja tidak cukup. Op. 39 No. 6 milik Rachmaninoff
mendapat skor **0.9717 untuk E major** melawan **0.9715 untuk A minor** — praktis seri.
Bass yang menentukan tonalitas, jadi not rendah diberi bobot lebih besar:

```
weight = durasi × (1 + max(0, (72 − midi)) / 24)      // sampai 2× di dasar piano
```

Diuji pada dua lagu yang kuncinya diketahui; hanya pembobotan ini yang benar di keduanya:

| Skema | Op. 39 No. 6 (A minor) | Canon in D (D major) |
|---|---|---|
| durasi saja | ✗ E major | ✓ D major |
| jumlah onset | ✓ A minor | ✓ D major |
| **durasi × bass boost** | **✓ A minor** | **✓ D major** |
| bass line (nada terendah per onset) | ✓ A minor | ✓ D major |
| sepertiga not terendah | ✗ E major | ✓ D major |
| harmoni penutup saja | ✗ F# minor | ✓ D major |

### Kenapa hasilnya bisa "ngelantur" dari rekaman

Ini bug paling berpengaruh di seluruh pipeline, dan sifatnya senyap.

`prepare()` dulu memanggil `librosa.effects.trim`, yang memotong silence di ujung file:
rekaman 199.9s menjadi 198.1s sebelum model melihatnya. Karena itu, **setiap timestamp
hasil transkripsi relatif terhadap file yang sudah dipotong** — seluruh MIDI meleset
~1.1s dari rekaman yang sedang kamu bandingkan, tetapi tetap konsisten dengan dirinya
sendiri, jadi tidak ada yang terlihat rusak.

Terukur terhadap rekaman asli:

| metrik | sebelum | sesudah |
|---|---|---|
| chroma similarity | 0.581 | **0.879** |
| jendela 10s dengan kemiripan ≥0.85 | 0/20 | **15/20** |
| lag terbaik | +1.138s | **+0.023s** |
| not yang didukung spektrum rekaman | 55.2% | **98.6%** |

Perbaikannya tiga lapis:

1. **Jangan pernah mengubah panjang audio.** Silence di-*gate* (dinolkan), bukan
   dipotong, sehingga timeline tetap persis. Setiap langkah yang mengubah panjang
   (resample, padding stem, trim) diikuti pemeriksaan panjang terhadap sumber dengan
   peringatan keras di log kalau berubah.
2. **Ukur sisa lag lalu koreksi** (`pipeline/align.py`). Bangun matriks chroma langsung
   dari event not MIDI (tanpa render audio), bandingkan dengan chroma audio sumber,
   cari lag terbaik, geser MIDI kalau |lag| > 40 ms. Jalan **sebelum** deteksi pedal,
   karena deteksi pedal memasangkan waktu not dengan jeda di audio.
3. **Tampilkan hasilnya di UI** sebagai `align_ms` pada job, supaya regresi langsung
   kelihatan.

### Cek hasilnya sendiri: tombol **Asli**

Tidak ada cara jujur menilai transkripsi selain mendengarkannya bersamaan dengan
rekamannya. Tombol **Asli** di transport memutar rekaman sumber sejajar dengan piano
(disajikan dari `/api/jobs/{id}/audio`, elemen audio-nya terpisah dari DOM dan jam-nya
disetel dari clock pemutar). Kalau masih terasa maju/mundur, ada kontrol geser ±50 ms.

Kalau tombol ini butuh geseran besar, itu **bug pipeline, bukan selera** — laporkan.

### Koreksi manual partitur

Deteksi kunci dan tempo itu heuristik, jadi keduanya bisa ditimpa di panel partitur:
dropdown kunci (28 pilihan) dan input ♪ = BPM. Kalau kunci hasil deteksi ambigu
(selisih skor antar-kandidat < 0.01), UI memberi peringatan eksplisit — itu terjadi
pada repertoar kromatik seperti Op. 39 No. 6, di mana E major dan A minor nyaris seri.

## Uji

```bash
cd backend && .venv/bin/python tests/smoke_api.py data/test/melody_stereo.wav          # cepat
cd backend && .venv/bin/python tests/smoke_api.py data/test/melody_stereo.wav --stems  # ikut Demucs
```

Skrip membuat file WAV sintetis sendiri (`data/test/`), menjalankan job sampai selesai, lalu
memverifikasi MIDI, preview audio, range request, share, dan export transpose.

Alat diagnosa pipeline (memakai audio dari job yang sudah ada):

```bash
cd backend
.venv/bin/python tests/pipeline_check.py data/jobs/<id>/source.wav --preset balanced
.venv/bin/python tests/pedal_probe.py  /tmp/mm_check/prepared.wav /tmp/mm_check/raw.mid
.venv/bin/python tests/gap_shape.py    /tmp/mm_check/prepared.wav /tmp/mm_check/raw.mid
```

`gap_shape.py` mencetak bentuk decay di dalam setiap jeda antar-not — inilah data yang
menentukan ambang `RINGING_RATIO`: piano yang dipedal turun hanya beberapa dB, yang teredam
jatuh puluhan dB.

Menilai ketepatan terhadap rekaman aslinya:

```bash
cd backend
.venv/bin/python tests/accuracy_report.py prepared.wav output.mid
.venv/bin/python tests/key_probe.py       output.mid "A minor"
```

`accuracy_report.py` merender MIDI-nya jadi audio (synth harmonik sederhana), lalu
membandingkan **chroma** dengan rekaman asli — time-aligned maupun bebas-waktu (DTW) —
plus precision/recall onset terhadap onset detector librosa. `key_probe.py` mencetak
perbandingan beberapa skema pembobotan kunci terhadap kunci yang kamu tahu benar.

`diagnose.py` menjawab "di mana persisnya hasilnya meleset": kemiripan chroma per
jendela 10 detik (bagian mana yang salah), lag global terbaik (geseran atau nada salah),
**dukungan spektrum per not** (berapa persen not benar-benar ada di rekaman), dan sebaran
offset onset. Bandingkan selalu terhadap **rekaman sumber**, bukan `prepared.wav` —
`prepared.wav` sudah satu timeline dengan MIDI, jadi ia menyembunyikan bug geseran.

## Performa (mesin 4 vCPU, tanpa GPU)

| Tahap | 4 detik audio | Lagu 3 menit |
|---|---|---|
| Pra-proses (normalisasi + band-limit + HPSS) | ~1 s | **~10–13 s** |
| Transkripsi basic-pitch (ONNX) | ~1,5 s | ~4–6 s |
| Bersihkan MIDI | <0,1 s | ~0,1 s |
| Deteksi pedal | <0,1 s | ~0,3 s |
| Stem separation Demucs | ~30 s | **~20–30 menit** |

Demucs memang berat di CPU. Kalau hanya butuh MIDI cepat, matikan stem separation — pra-proses
sudah membuang perkusi, jadi akurasinya masih bagus.

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
│   │       ├── transcribe.py  # pra-proses + basic-pitch / librosa-pyin → MIDI
│   │       ├── sustain.py     # deteksi pedal dari audio → CC64 di MIDI
│   │       ├── align.py       # ukur & koreksi offset MIDI vs rekaman sumber
│   │       └── post.py        # gabung fragmen, buang noise, transpose/tempo
│   ├── tests/
│   │   ├── smoke_api.py       # uji end-to-end lewat HTTP
│   │   ├── pipeline_check.py  # jalankan pipeline pada audio nyata, cetak waktu
│   │   ├── accuracy_report.py # chroma vs rekaman + precision/recall onset
│   │   ├── diagnose.py        # di mana persisnya hasilnya meleset
│   │   ├── key_probe.py       # banding skema pembobotan deteksi kunci
│   │   ├── gap_shape.py       # bentuk decay di jeda antar-not (tuning pedal)
│   │   └── pedal_probe.py     # sebaran rasio energi jeda
│   ├── data/                  # sqlite, artefak job, share
│   └── run.sh
├── web/
│   ├── src/app/{page,layout,globals.css,share/[slug]/page.tsx}
│   ├── src/components/        # Studio, PianoRoll, Transport, BottomTabs (mobile), dll
│   ├── src/lib/               # api, audio (Tone), midi (+CC64), score (VexFlow), keys,
│   │                          # instruments, useMediaQuery
│   └── public/audio/          # sample instrumen (Salamander + MusyngKite)
└── deploy/                    # unit systemd
```

### Mobile

Breakpoint tunggal di 1023 px (`useMediaQuery.ts`). Di bawah itu Studio berubah jadi satu
kolom + **bottom tab bar** (Putar · Sumber · Suara · Partitur · Pustaka), piano roll
dipendekkan (250 px + keyboard 74 px), dan `overflow-x` dikunci supaya tidak ada scroll
horizontal. Posisi tab dipertahankan saat memuat hasil baru (otomatis pindah ke **Putar**).
Halaman share memakai breakpoint yang sama.

## Kredit

basic-pitch (Spotify) · Demucs (Meta) · Tone.js · VexFlow · yt-dlp · Next.js
