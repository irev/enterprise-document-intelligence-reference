# Evaluasi Backend dan Frontend — Document Intelligence untuk Request of Payment (RoP)

Status: dokumen evaluasi dan perencanaan reference implementation. Dokumen ini bukan
spesifikasi normatif. Bila menyangkut kontrak, spesifikasi Enterprise Document
Intelligence (`irev/enterprise-document-intelligence`) yang berlaku; repositori
spesifikasi tidak tersedia di workspace ini dan belum diperiksa.

Dasar evaluasi: pembacaan kode pada branch `claude/document-intelligence-eval-8e135e`.
Test suite tidak dijalankan untuk evaluasi ini.

Batasan peran: sistem hanya mengekstrak dan menyajikan data. Model bukan validator
kepatuhan atau keabsahan. Keabsahan dokumen dan keputusan transaksi tetap pada petugas
(`AGENTS.md`, aturan 6).

## 1. Kesimpulan utama

Fondasi tata kelola kuat: domain bersih, `UNKNOWN` sebagai default aman, provenance dan
evidence wajib, versi hasil immutable, egress provider terkontrol. Kontrak klasifikasi,
ekstraksi, normalisasi, validasi, dan review sudah ada.

Alur pemrosesan dokumen dari ujung ke ujung belum ada:

| Temuan | Bukti |
|---|---|
| `SourceAcquirer` hanya port, tanpa implementasi. Tidak ada upload multipart maupun pengambilan signed URL/storage. | `application/ports.py:29` |
| `ClassifierAdapter` dan `ExtractorAdapter` hanya protokol dan fake. Qwen3-VL baru bisa diinstal, inferensinya belum ada. | `application/classification.py`, `application/extraction.py`, `application/qwen3_vl_install.py` |
| Satu-satunya alur nyata (`edi process`) menjalankan PaddleOCR dan melaporkan jumlah baris/karakter per halaman. Tanpa klasifikasi, bidang, atau normalisasi. | `cli.py:847`, `application/file_processing.py` |
| Istilah preprocessing/deskew, NPWP, multipart, presign, SSE/WebSocket tidak ditemukan di `src`, `docs`, maupun `migrations`. | pencarian teks |
| Frontend yang ada (`edi web`) adalah konsol operator untuk instal provider, model, dan server inferensi, bukan antarmuka petugas dokumen. | `adapters/web_panel.py`, `docs/manual/web-panel.md` |

Semua yang perlu dibangun dapat menempel pada kontrak yang sudah ada tanpa menulis ulang
inti.

## 2. Evaluasi backend

### 2.1 Pengambilan file

Sudah baik:

- `ingest_source`: magic bytes (PDF, PNG, JPEG), batas ukuran, file kosong, ketidakcocokan
  content-type deklarasi vs deteksi.
- Identitas sumber SHA-256; `SourceReference` membedakan UPLOAD, SIGNED_URL, CONNECTOR.
- `security.py` menolak URL non-HTTPS, kredensial tertanam, fragment, dan host kosong.
  Reprocess memverifikasi ulang hash (`SOURCE_CHANGED`).

Kekurangan:

1. Tidak ada adapter pengambil. Komentar di `security.py` mensyaratkan penegakan DNS/IP/
   redirect saat koneksi, tetapi kodenya belum ada (risiko SSRF).
2. Format terbatas: TIFF (umum pada hasil scan) dan HEIC belum didukung; tidak ada
   pemeriksaan struktur PDF (terenkripsi, jumlah halaman, konten aktif) sebelum OCR.
3. `ingest_source` menerima `bytes` utuh sehingga batas ukuran harus dipaksa lebih awal
   pada tahap streaming.

Rekomendasi:

- Upload multipart: stream ke file sementara dengan penghitung byte, hentikan saat melewati
  batas, baru panggil `ingest_source`.
- Pengambilan dari storage: utamakan connector (server membaca object berdasarkan key
  dengan kredensialnya sendiri) daripada menerima URL bebas.
- Signed URL tetap didukung dengan: allowlist host; resolusi DNS lalu pin IP dan tolak
  IP privat/loopback/link-local; tanpa redirect; pembacaan streaming dengan batas ukuran
  dan timeout; pembandingan hash dengan `expected_sha256` bila tersedia.
- Tambahkan TIFF; normalisasi HEIC ke PNG pada preprocessing.

### 2.2 Alur analisis dokumen

Kontrak pendukung sudah ada (`quality.py`, `classification.py`, `extraction.py`,
`field_normalization.py`, `validation.py`) tetapi belum dirangkai. Urutan yang
direkomendasikan:

```text
1 Terima & identitas      ingest_source (ada)
2 Preprocessing           dekode halaman, cek DPI, orientasi, deskew       [BARU]
3 Teks asli vs OCR        assess_ocr_need (ada), per halaman
4 OCR + struktur          PaddleOCR -> StructuredDocument (ada, dirangkai)
5 Klasifikasi             per halaman/segmen, bukan hanya per berkas        [BARU]
6 Ekstraksi bidang        sesuai skema jenis dokumen, wajib evidence
7 Normalisasi             IDR, tanggal, NPWP (deterministik)                [LENGKAPI]
8 Observasi dokumen       kondisi berkas dan konsistensi antar-bidang       [BARU]
9 Hasil versi N           immutable -> antrean tinjau petugas
```

Poin penting:

- **Preprocessing belum ada.** `PageQuality.skew_degrees` hanya input keputusan perlu-OCR,
  tidak ada kode yang meluruskan gambar. Simpan gambar asli utuh; gunakan hasil praproses
  hanya sebagai input mesin dan petakan koordinat evidence kembali ke gambar asli.
- **Satu berkas RoP umumnya bundel** (RoP, invoice, faktur pajak, kwitansi). Klasifikasi
  per berkas akan menghasilkan `UNKNOWN` atau salah; lakukan per halaman lalu kelompokkan
  menjadi segmen. Sejalan dengan milestone RI-6 (bundle/business profiles) di
  `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md`.
- **Taksonomi.** Pertahankan pemisahan tipe dokumen dari proses bisnis
  (`docs/RI-3-CLASSIFICATION.md`). Usulan tipe awal: `REQUEST_FOR_PAYMENT`, `INVOICE`,
  `RECEIPT`, `TAX_INVOICE`, `PURCHASE_ORDER`, `PAYMENT_PROOF`, ditambah `UNKNOWN`.
  Dikelola lewat `DocumentTaxonomy` (konfigurasi), bukan kode.
- **Normalisasi masih tipis** (`adapters/normalizers.py`): Rupiah sudah ditangani; tanggal
  hanya menerima ISO `YYYY-MM-DD` sehingga `12/08/2026` dan `12 Agustus 2026` ditolak;
  NPWP belum ada (15 digit `XX.XXX.XXX.X-XXX.XXX` dan 16 digit). Perlu normalizer id-ID
  eksplisit tanpa menebak format ambigu; nilai mentah tetap ditampilkan bila `INVALID`.
  Cek NPWP hanya cek bentuk, bukan keabsahan.
- **Keluaran bagi petugas** mencakup daftar bidang, kondisi berkas (kualitas scan, halaman
  miring/terpotong, bagian tidak terbaca, stempel/tanda tangan terdeteksi tanpa dinilai
  sah, tulisan tangan), dan observasi konsistensi netral (misalnya total RoP berbeda dari
  jumlah baris invoice). Semuanya informasi, bukan putusan patuh/tidak patuh.
- `ValidationStatus.VALID/INVALID` dapat disalahartikan sebagai keabsahan. Di UI, tampilkan
  sebagai "Catatan untuk ditinjau" dengan tingkat perhatian, bukan status valid/invalid.

### 2.3 Model

| Tugas | Model | Status di repo |
|---|---|---|
| OCR cepat | PaddleOCR (`pp-ocrv6-medium`) | Terpasang dan teruji lewat `edi process` |
| Tata letak dan tabel | PP-StructureV3 / PaddleOCR-VL | Katalog saja |
| Klasifikasi dan ekstraksi kompleks | Qwen3-VL (4B/8B/30B-A3B), Qwen2.5-VL | Installer ada, inferensi belum |
| VLM eksternal | `REMOTE_MODEL` + `APPROVED_EXTERNAL` | Hanya kosakata, tanpa adapter |

Repositori ini lokal-dahulu (`allow_external_egress` tertutup,
`allow_silent_provider_fallback = false`), sesuai untuk dokumen berisi NPWP dan rekening.
Rekomendasi: VLM lokal sebagai tingkat eskalasi pertama; model eksternal hanya opt-in per
tenant/profil dengan persetujuan egress eksplisit. Identitas model ditentukan lewat
konfigurasi, bukan kode.

### 2.4 Penentuan model dan routing

Mekanisme yang ada dipertahankan:

```text
ProcessingProfile (tenant/aplikasi) -> ExecutionPolicy -> build_execution_plan
  -> ProcessingRunExecutionSnapshot (rencana dibekukan per run)
```

`build_execution_plan` memilih satu provider per kapabilitas secara statis. Fallback
(`select_fallback_step`) hanya setelah attempt `FAILED`. Tidak ada eskalasi karena
kualitas rendah dan tidak ada sinyal biaya atau latensi.

Rekomendasi: kaskade eskalasi yang dideklarasikan di profil, bukan router bebas.

```text
T0  teks asli PDF (deterministik)               jika assess_ocr_need = NOT_REQUIRED
T1  PaddleOCR + struktur                        default untuk scan
T2  VLM lokal pada halaman bermasalah           eskalasi
T3  VLM eksternal                               hanya bila profil mengizinkan egress
```

Sinyal kompleksitas per halaman (deterministik): confidence OCR rendah; tabel dengan
kolom/baris tidak konsisten; rotasi/skew tinggi atau DPI rendah; bidang wajib tidak
ditemukan atau gagal normalisasi; mayoritas bidang di bawah ambang confidence.

Aturan:

1. Router hanya boleh naik ke tingkat yang sudah tercantum pada plan yang dibekukan
   (menjaga "no silent fallback" dan otorisasi provider).
2. Setiap eskalasi dicatat sebagai attempt tersendiri dengan alasan (misalnya
   `ESCALATED_LOW_CONFIDENCE`). Ini menyentuh kontrak `ExecutionAttempt` dan harus
   dikonfirmasi ke repositori spesifikasi sebelum implementasi.
3. Ambang berasal dari kalibrasi empiris pada set uji sintetis.
4. Eskalasi per halaman, bukan per berkas.

## 3. Evaluasi frontend

### 3.1 Kondisi saat ini

`edi web` adalah halaman tunggal dengan tiga tampilan (Overview, Servers, Install) untuk
operator infrastruktur: GPU, VRAM, instal provider, pull model. Informasi teknis tampil di
UI utama. Selain itu: tanpa autentikasi (hanya bind `127.0.0.1`), tanpa upload, viewer, atau
form tinjauan; "progres" adalah animasi tahap selama satu request berjalan, bukan event
pipeline; `http.server` stdlib tidak memadai untuk upload besar, SSE, dan banyak koneksi.
Panel ini tetap berguna sebagai menu Administrasi peran operator.

### 3.2 Pengiriman file

- Drag-and-drop multi-file; validasi sisi klien yang ramah; upload per berkas dengan progres
  masing-masing. Satu berkas gagal tidak membatalkan yang lain.
- Pesan penolakan dalam bahasa fungsional (misalnya "Berkas melebihi 20 MB"); kode seperti
  `CONTENT_TYPE_MISMATCH` hanya di log.
- Berkas duplikat (hash sama): tawarkan membuka hasil yang ada atau memproses ulang sebagai
  versi baru.
- Jalur kedua: "Ambil dari penyimpanan" lewat connector terdaftar, bukan menempel URL mentah.

### 3.3 Eksekusi dan progres

Gunakan SSE (satu arah, lebih mudah melewati proxy, sambung ulang otomatis); WebSocket baru
bila perlu kolaborasi dua arah. Tahap yang ditampilkan: berkas diterima; memeriksa kualitas
gambar; mengenali jenis dokumen; membaca isi dokumen; merapikan format (tanggal, Rupiah,
NPWP); siap ditinjau. Hasil per berkas berupa ringkasan fungsional (misalnya "RoP, 3 halaman,
2 bidang perlu dicek, 1 halaman miring"). Provider, model, durasi, stack trace, dan JSON
mentah hanya di log sistem; UI menampilkan kode referensi. `ProcessingLog` JSONL dapat
menjadi sumbernya.

### 3.4 Struktur menu dan fungsi

| Menu | Fungsi |
|---|---|
| Dashboard | Antrean per status (Menunggu, Diproses, Perlu ditinjau, Selesai ditinjau, Gagal dibaca), area unggah, filter jenis/tanggal/prioritas. |
| Workspace | Split view: viewer halaman (zoom, putar tampilan, navigasi, sorot area bukti) dan formulir bidang; panel catatan kondisi berkas dan observasi konsistensi. |
| Riwayat Audit | Siapa mengubah apa dan kapan, nilai mesin awal vs terkoreksi, versi hasil, alasan koreksi; hanya baca, dapat diekspor. |
| Administrasi (peran operator) | Konsol runtime yang ada; kelak profil, ambang, taksonomi. |

Perilaku Workspace:

- Klik bidang menyorot area di dokumen dan sebaliknya (memanfaatkan `EvidenceReference`).
- Confidence berkode warna plus ikon dan label teks. Bedakan keadaan `FieldState`:
  `PRESENT`, `MISSING` ("Tidak ditemukan"), `EXPLICIT_NULL`, `INVALID` ("Format tidak
  dikenali", nilai mentah tetap tampil).
- Edit inline memetakan 1:1 ke `ReviewActionType`: Konfirmasi, Koreksi, Tandai tidak ada,
  Tandai tidak terbaca, Klasifikasi ulang, Eskalasi. Nilai asli mesin tidak ditimpa
  (`AGENTS.md`, aturan 10).
- Tombol akhir berlabel "Tandai selesai ditinjau", bukan "Setujui"/"Valid". Pernyataan
  petugas hanya soal ketepatan pembacaan data; persetujuan transaksi dan keabsahan dokumen
  di luar sistem ini, dan teks bantu harus menyatakannya.
- Pintasan keyboard dan filter "hanya bidang bermasalah".

## 4. Rekomendasi refaktor dan implementasi

Tidak perlu menulis ulang. Urutan kerja:

1. Use case orkestrasi pipeline di `application/` (langkah 1-9) dengan port baru:
   `PreprocessorPort`, implementasi `SourceAcquirer`, implementasi nyata
   `ClassifierAdapter`/`ExtractorAdapter`. Tanpa dependensi framework.
2. Adapter API data-plane terpisah dari `web_panel.py`. Sesuai kebijakan dependensi
   `AGENTS.md`, framework ASGI ringan dapat masuk sebagai extra opsional (`.[web]`) di
   lapisan adapter, tidak menyentuh domain.
3. Frontend terpisah (SPA, aset lokal tanpa CDN agar cocok untuk air-gap) yang memanggil API
   tersebut; panel runtime dipindah ke menu Administrasi dengan autentikasi dan peran.
4. Autentikasi dan peran (Petugas, Peninjau, Operator, Auditor) sebelum bind non-lokal.
5. Normalizer id-ID untuk tanggal dan NPWP dengan test sintetis. Kecil, deterministik, tanpa
   model; dapat dikerjakan lebih dulu.
6. Kalibrasi ambang confidence dan skor kompleksitas pada dokumen sintetis sebelum routing
   diaktifkan.

Titik berisiko kontrak yang perlu dikonfirmasi ke repositori spesifikasi: atribut eskalasi
pada `ExecutionAttempt` dan format segmen bundel.

## 5. Ketidakpastian

- SSE, prioritas model lokal, dan kaskade eskalasi adalah rekomendasi, bukan keputusan yang
  sudah diambil proyek.
- `docs/REQUIREMENTS-ANALYSIS.md` (G5) sendiri mencatat alur submit sampai review sebagai
  milestone mendatang; evaluasi ini konsisten dengan catatan itu.
- Aplikasi dan test tidak dijalankan; kualitas PaddleOCR pada dokumen Indonesia nyata dan
  ambang eskalasi belum diuji.
- Dokumen ini ditulis dalam bahasa Indonesia atas permintaan pemilik proyek, sementara
  dokumentasi lain di repositori berbahasa Inggris.
