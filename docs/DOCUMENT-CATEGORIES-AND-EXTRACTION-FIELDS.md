# Analisis Kategori Dokumen dan Field Ekstraksi

Tanggal: 8 Oktober 2026  
Status: analisis per 8 Oktober 2026. Sebagian besar usulan sudah diterapkan pada phase D ([RI-6.0 §13](RI-6.0-DATA-PLANE-API-V1.md)): registry kategori/field, schema per kategori, dan normalizer locale. Bagian 2, 7, 8, dan 9 menggambarkan kondisi sebelum phase D.  
Bahasa kategori: English, dengan ID `UPPER_SNAKE_CASE`.  
Bahasa field: English, dengan nama `lower_snake_case`.

## 1. Tujuan dan batas analisis

Dokumen ini menjelaskan lokasi kategori prediksi, cara menambahkan kategori dan field, serta usulan pemetaan kategori berdasarkan kode dan kumpulan dokumen yang diperiksa.

Nama kategori di sini merupakan kosakata bahasa Inggris yang konsisten untuk proyek ini. Nama tersebut bukan klaim kepatuhan terhadap standar internasional atau kontrak normatif Enterprise Document Intelligence. Perubahan kontrak harus diperiksa terhadap repository spesifikasi, `SPECIFICATION.md`, `NORMATIVE-MAP.md`, schema, dan conformance vectors yang berlaku.

Dasar analisis:

- Inspeksi kode panel, API v1, classifier, extractor, dan workspace RoP pada working tree saat analisis.
- Inventaris koleksi PDF privat berdasarkan label file. Jumlah per label dan pengelompokan asal tidak dicantumkan.
- Pemeriksaan text layer pada enam contoh INVOICE, BAPP, dan BAST, ditambah inspeksi visual beberapa halaman. Pemeriksaan ini bukan validasi isi seluruh koleksi.
- Nama file digunakan sebagai label awal inventaris, bukan ground truth klasifikasi.
- Tidak ada training, batch inference, atau pengukuran akurasi seluruh koleksi yang dilakukan.

Identitas pihak, isi bisnis spesifik, nomor dokumen, nilai transaksi, dan informasi rekening dari dokumen privat tidak disalin ke dokumen ini. Contoh konfigurasi hanya menggunakan istilah generik.

## 2. Kesimpulan implementasi saat ini

1. Panel/API memakai `title_rules` untuk kategori dan `extraction_schema` untuk field.
2. `INVOICE` sudah tersedia pada konfigurasi awal. `BAPP` dan `BAST` belum menjadi kategori tersendiri pada konfigurasi tersebut.
3. Rule umum `berita acara` saat ini menghasilkan `ACCEPTANCE_REPORT`.
4. Schema field panel/API masih satu schema bersama. Belum ada pemilihan schema berbeda untuk setiap kategori.
5. Workspace RoP memakai definisi kategori, field, dan prompt sendiri. Perubahan konfigurasi panel tidak otomatis berlaku pada workspace tersebut.
6. Menambah kategori melalui konfigurasi bukan melatih ulang model.

## 3. Lokasi definisi dan alur prediksi

| Komponen | File | Fungsi |
|---|---|---|
| Konfigurasi kategori awal | [title-rules-id-en.json](../deploy/classification-profiles/title-rules-id-en.json) | Pola judul, kategori, dan versi taksonomi |
| Classifier berbasis rule | [title_rules.py](../src/edi_reference/application/title_rules.py) | Mencocokkan pola dengan heading hasil OCR |
| Keputusan klasifikasi | [classification.py](../src/edi_reference/application/classification.py) | Validasi kandidat, threshold, evidence, dan `UNKNOWN` |
| Classifier berbasis LLM | [llm_classification.py](../src/edi_reference/application/llm_classification.py) | Memilih kategori terdaftar dengan kutipan sumber |
| Orkestrasi panel | [panel_service.py](../src/edi_reference/application/panel_service.py) | OCR, klasifikasi, pemilihan schema saat ini, dan ekstraksi |
| Konfigurasi berversi | [panel_config.py](../src/edi_reference/application/panel_config.py) | Validasi, penyimpanan versi, aktivasi, dan rollback |
| Default schema panel | [control_panel_web.py](../src/edi_reference/adapters/control_panel_web.py) | Inisialisasi field header bersama |
| Ekstraksi oleh LLM | [llm_extraction.py](../src/edi_reference/application/llm_extraction.py) | Meminta field dan mencocokkan nilai dengan teks sumber |
| Kontrak field internal | [field_schema.py](../src/edi_reference/domain/field_schema.py) | `FieldDefinition` dan `ExtractionSchema` |

Alur panel/API saat ini:

```text
Dokumen
  -> OCR dan struktur halaman
  -> Klasifikasi: rules / rules_then_llm / llm
  -> document_type atau UNKNOWN
  -> Schema field bersama
  -> Ekstraksi nilai dan pencocokan dengan sumber
  -> Normalisasi pada jalur API untuk tipe yang dikonfigurasi
  -> Hasil berversi dengan evidence dan provenance
```

### 3.1 Perilaku rules dan LLM

- Konfigurasi awal membaca delapan blok OCR pertama pada halaman pertama untuk rule judul.
- Rule dievaluasi menurut urutan konfigurasi. Rule pertama yang cocok menang.
- Mode `rules` mengembalikan `UNKNOWN` ketika tidak ada kecocokan.
- Mode `rules_then_llm` memakai LLM hanya setelah rules menghasilkan `UNKNOWN`. LLM tidak memeriksa ulang keputusan rules yang sudah memilih kategori.
- Mode `llm` memilih dari daftar kategori pada taksonomi dan harus menyertakan kutipan sumber yang ditemukan dalam teks OCR.
- Pada panel, daftar kategori dibentuk dari nilai `document_type` pada rules. Menambahkan label baru pada rules juga memasukkannya ke pilihan classifier LLM.
- Nilai hasil ekstraksi menjadi `PRESENT` hanya jika dapat dicocokkan dengan teks sumber sesuai mekanisme grounding. Nilai yang tidak ditemukan menjadi `MISSING`.

Grounding membuktikan nilai terdapat pada sumber, tetapi belum membuktikan bahwa nilai tersebut merupakan field yang tepat. Contohnya, nilai kontrak dan nilai pembayaran dapat sama-sama tercetak dalam satu dokumen.

### 3.2 Konfigurasi awal dan konfigurasi aktif

File pada `deploy/classification-profiles/` hanya menjadi seed ketika konfigurasi belum ada. Mengubah seed tidak otomatis mengganti konfigurasi panel yang sudah tersimpan.

Lokasi state default adalah `.edi/panel`; konfigurasi disimpan di bawah `config/title_rules`, `config/extraction_schema`, dan `config/pipeline`. Lokasi dapat diganti menggunakan `--state-dir`.

Saat pemeriksaan, konfigurasi aktif tidak ditemukan pada lokasi default. Karena itu, kategori yang disebut sudah tersedia dalam dokumen ini merujuk pada seed repository, bukan konfigurasi layanan aktif yang telah diverifikasi.

## 4. Inventaris dan usulan kategori bahasa Inggris

Pemetaan berikut adalah kandidat awal berdasarkan label file. Label ditulis sebagai istilah dokumen umum, bukan nama file atau nama sistem asal. Konfirmasi isi tetap diperlukan, terutama label singkatan dan berkas gabungan.

| Istilah label | Usulan kategori English | Catatan |
|---|---|---|
| invoice | `INVOICE` | Sudah tersedia pada seed |
| kuitansi | `RECEIPT` | Sudah tersedia pada seed |
| BAPP | Belum satu kategori final | Pisahkan berdasarkan isi; lihat bagian 5 |
| SPP | `PAYMENT_REQUEST` | Kandidat; pastikan bukan payment order dengan semantik berbeda |
| faktur | `TAX_INVOICE` atau `INVOICE` | Kata faktur saja belum membuktikan faktur pajak |
| NPWP | `TAX_REGISTRATION_CERTIFICATE` | Verifikasi bentuk dokumen registrasi pajak |
| PO | `PURCHASE_ORDER` | Sudah tersedia pada seed |
| kontrak | `CONTRACT` | Sudah tersedia pada seed |
| lampiran SPT Masa PPN | `VAT_RETURN_ATTACHMENT` | Kandidat kategori lampiran pelaporan pajak |
| sertifikat badan usaha jasa konstruksi | `CONSTRUCTION_BUSINESS_CERTIFICATE` | Kandidat berdasarkan singkatan |
| SPK | `WORK_ORDER` | Konfirmasi fungsi surat perintah kerja |
| surat pesanan | `ORDER_LETTER` | Pertahankan kategori seed sampai batas dengan purchase order ditetapkan |
| BAST | `HANDOVER_REPORT` | Kandidat; contoh yang diperiksa menunjukkan isi pemeriksaan pekerjaan |
| adendum | `CONTRACT_AMENDMENT` | Konfirmasi dokumen induk yang diubah |
| nota dinas | `INTERNAL_MEMORANDUM` | Kategori umum nota internal; nota permohonan dapat menjadi subtype setelah analisis |
| singkatan internal yang belum jelas | Belum dipetakan | Kepanjangan dan fungsi bisnis belum diverifikasi |
| surat tagihan instansi pemerintah | `GOVERNMENT_BILLING_NOTICE` | Kandidat berdasarkan label |
| berita acara pendapatan layanan | `REVENUE_REPORT` | Kandidat berdasarkan label |
| dokumen perjalanan dinas pegawai | `DOMESTIC_TRAVEL_DOCUMENT` | Kategori sementara; periksa surat tugas atau klaim biaya |
| persetujuan direksi | `BOARD_APPROVAL_DOCUMENT` | Jenis dokumen, bukan keputusan otorisasi oleh sistem |
| proposal sponsorship | `SPONSORSHIP_PROPOSAL` | Kandidat berdasarkan label |

`UNKNOWN` tetap tersedia untuk kategori tidak didukung atau bukti tidak cukup. Kategori sementara pada tabel tidak boleh otomatis diaktifkan hanya berdasarkan nama file.

## 5. Temuan khusus INVOICE, BAPP, dan BAST

### 5.1 INVOICE: judul dapat mengandung beberapa istilah kategori

Satu contoh invoice menampilkan istilah surat pesanan sekaligus invoice/faktur barang. Seed menempatkan rule `pesanan` sebelum rule `invoice`.

Jika keduanya masuk jendela heading OCR, classifier saat ini dapat memilih `ORDER_LETTER`. Ini adalah risiko dari urutan rule; belum merupakan hasil inference yang direproduksi pada dokumen tersebut.

Perbaikan yang diusulkan:

- Gunakan pola judul spesifik sebelum pola umum.
- Uji kasus beberapa istilah kategori pada halaman yang sama.
- Jangan menganggap semua kemunculan kata invoice sebagai judul utama; dokumen lain juga dapat menyebut invoice sebagai referensi.
- Jika diperlukan penanganan konflik kandidat, tambahkan kebijakan eksplisit. Perilaku tersebut belum tersedia pada classifier first-match saat ini.

### 5.2 BAPP: label file bukan satu makna dokumen

Contoh berlabel BAPP yang diperiksa mencakup berita acara pembayaran dan berita acara utilitas data. Karena itu, BAPP tidak langsung diterjemahkan menjadi satu kategori pemeriksaan pekerjaan.

Usulan kategori menurut isi:

| Isi utama dokumen | Usulan kategori English |
|---|---|
| Pemeriksaan pekerjaan | `WORK_INSPECTION_REPORT` |
| Kesepakatan atau pencatatan pembayaran dalam berita acara | `PAYMENT_REPORT` |
| Rekap penggunaan layanan/utilitas | `SERVICE_USAGE_REPORT` |
| Serah terima pekerjaan/barang | `HANDOVER_REPORT` |

Istilah `PAYMENT_REPORT` tidak menyatakan bahwa pembayaran sudah terjadi. Status pembayaran hanya boleh diambil dari bukti dan proses bisnis yang sesuai.

Jika BAPP merupakan kategori lampiran pada sistem asal, bedakan label lampiran tersebut dari prediksi jenis isi. Penyimpanan kedua konsep secara terpisah masih berupa usulan desain dan perlu penyelarasan kontrak.

### 5.3 BAST: periksa kemungkinan paket dokumen

Halaman pertama salah satu file berlabel BAST berjudul berita acara pemeriksaan pekerjaan. File tersebut terdiri dari beberapa halaman; seluruh isinya belum ditelaah secara visual.

Sebelum menetapkan `HANDOVER_REPORT`, tentukan apakah berkas merupakan satu dokumen, lampiran dengan label tidak tepat, atau paket beberapa jenis dokumen. Pemisahan dan klasifikasi per segmen belum menjadi kemampuan yang dibuktikan dalam analisis ini.

## 6. Field ekstraksi yang diusulkan

Field berikut adalah rancangan awal. Ketiadaan field pada sumber tidak boleh diganti dengan tebakan atau nilai hasil perhitungan yang disajikan sebagai kutipan dokumen.

### 6.1 Field bersama

| Field | Tipe | Makna |
|---|---|---|
| `document_number` | `identifier` | Nomor dokumen utama |
| `document_date` | `date` | Tanggal dokumen utama |
| `issuer_name` | `string` | Penerbit dokumen |
| `recipient_name` | `string` | Penerima dokumen |
| `subject` | `string` | Judul atau pokok dokumen |

### 6.2 INVOICE

| Field tambahan | Tipe | Makna |
|---|---|---|
| `purchase_order_number` | `identifier` | Referensi purchase order |
| `contract_number` | `identifier` | Referensi kontrak |
| `due_date` | `date` | Tanggal jatuh tempo |
| `billing_period` | `string` | Periode tagihan sesuai teks sumber |
| `subtotal_amount` | `money` | Nilai sebelum komponen pajak/penyesuaian yang dinyatakan |
| `tax_base_amount` | `money` | Dasar pengenaan pajak jika dicetak |
| `tax_amount` | `money` | Nilai pajak yang dicetak |
| `total_amount` | `money` | Total tagihan |
| `tax_id` | `tax_id` | Identitas pajak; peran penerbit/penerima perlu dipertegas |
| `currency_code` | `string` | Mata uang eksplisit pada dokumen |

Untuk tabel barang/jasa, target terstruktur dapat mencakup `description`, `quantity`, `unit`, `unit_price`, dan `line_total`. Struktur berulang ini belum didukung oleh schema scalar panel saat ini.

### 6.3 WORK_INSPECTION_REPORT

| Field tambahan | Tipe | Makna |
|---|---|---|
| `contract_number` | `identifier` | Kontrak yang menjadi dasar pemeriksaan |
| `contract_amount` | `money` | Nilai kontrak, bukan otomatis nilai pembayaran |
| `work_description` | `string` | Pekerjaan yang diperiksa |
| `inspection_date` | `date` | Tanggal pemeriksaan |
| `inspection_result` | `string` | Hasil pemeriksaan yang tertulis |
| `first_party_name` | `string` | Pihak pertama menurut dokumen |
| `second_party_name` | `string` | Pihak kedua menurut dokumen |
| `payment_stage` | `string` | Termin/tahap pembayaran jika disebut |
| `payment_amount` | `money` | Nominal pembayaran jika dicetak secara eksplisit |

Nilai persentase termin tidak otomatis diubah menjadi `payment_amount` oleh extractor. Jika diperlukan, perhitungan harus menjadi tahap derivasi terpisah dengan provenance.

### 6.4 PAYMENT_REPORT, SERVICE_USAGE_REPORT, dan HANDOVER_REPORT

| Kategori | Kandidat field tambahan |
|---|---|
| `PAYMENT_REPORT` | `reference_document_number`, `first_party_name`, `second_party_name`, `payment_amount`, `payment_period` |
| `SERVICE_USAGE_REPORT` | `service_description`, `service_period_start`, `service_period_end`, `provider_name`; rincian penggunaan membutuhkan tabel berulang |
| `HANDOVER_REPORT` | `contract_number`, `handover_date`, `handover_description`, `first_party_name`, `second_party_name`, `handover_result` |

Tanggal menggunakan tipe `date`, nominal menggunakan `money`, nomor referensi menggunakan `identifier`, dan teks lain menggunakan `string`. Pengesahan, tanda tangan, dan kondisi pekerjaan tidak boleh disimpulkan sebagai otorisasi pembayaran.

## 7. Cara menambahkan kategori melalui panel

1. Login dengan peran ADMIN.
2. Buka **Konfigurasi -> Profil aturan judul**.
3. Pertahankan rules yang masih diperlukan dan tambahkan pola kategori baru pada array `rules`.
4. Letakkan rule spesifik sebelum rule umum `berita acara`.
5. Naikkan `version`; naikkan `taxonomy_version` ketika daftar/semantik kategori berubah.
6. Isi alasan perubahan dan pilih **Simpan sebagai versi baru**.
7. Proses ulang sampel untuk menghasilkan versi hasil baru.

Contoh fragmen JSON untuk ditambahkan ke array `rules`:

```json
[
  {
    "pattern": "\\bberita\\s+acara\\s+pemeriksaan\\s+pekerjaan\\b",
    "document_type": "WORK_INSPECTION_REPORT"
  },
  {
    "pattern": "\\bberita\\s+acara\\s+serah\\s+terima\\b",
    "document_type": "HANDOVER_REPORT"
  }
]
```

Fragmen tersebut bukan pengganti seluruh konfigurasi dan belum diuji pada seluruh koleksi. Pola sengaja memakai judul deskriptif; singkatan BAPP/BAST tidak ditambahkan sebagai pemetaan pasti karena maknanya belum konsisten pada sampel.

Rule umum `ACCEPTANCE_REPORT` dapat dipertahankan sementara untuk kompatibilitas. Namun, penggunaan kategori tersebut bagi setiap berita acara perlu dievaluasi. Jangan mengganti label keluaran yang sudah dikonsumsi aplikasi tanpa keputusan versi dan pemetaan migrasi.

## 8. Cara menambahkan field melalui panel

1. Buka **Konfigurasi -> Schema field ekstraksi**.
2. Tambahkan field pada array `fields`, tanpa menghapus field lama yang masih diperlukan.
3. Naikkan `version` di dalam isi schema.
4. Isi alasan perubahan dan simpan sebagai versi baru.
5. Proses ulang dengan ekstraksi LLM aktif.
6. Periksa nilai, evidence, dan versi konfigurasi yang dicatat pada hasil.

Contoh objek field tambahan:

```json
{
  "field_name": "purchase_order_number",
  "value_type": "identifier"
}
```

Batas validator panel saat ini:

- Nama field memakai huruf kecil, angka, dan underscore, diawali huruf.
- Tipe tersedia: `string`, `date`, `money`, `identifier`, `tax_id`, `number`.
- Schema berisi 1 sampai 50 field; nama field tidak boleh duplikat.
- Definisi field hanya memiliki nama dan tipe. Deskripsi, alias label, aturan required per kategori, dan struktur array belum tersedia pada definisi tersebut.
- Field yang ditambahkan berlaku untuk semua kategori karena schema masih global.

Tipe `date` atau `money` tidak menjamin semua format sumber dapat dinormalisasi. Jalur API memakai normalizer yang dikonfigurasi; format yang tidak didukung harus mempertahankan nilai mentah dan melaporkan kegagalan normalisasi.

## 9. Perubahan kode untuk schema per kategori

Target yang diusulkan:

```text
INVOICE                -> invoice-header@1
WORK_INSPECTION_REPORT  -> work-inspection-header@1
PAYMENT_REPORT         -> payment-report-header@1
SERVICE_USAGE_REPORT   -> service-usage-header@1
HANDOVER_REPORT        -> handover-header@1
UNKNOWN                -> kebijakan eksplisit: abstain atau schema umum terbatas
```

Pekerjaan yang diperlukan:

1. Periksa kontrak spesifikasi sebelum menambah bentuk konfigurasi/schema.
2. Tambahkan registry/pemetaan kategori ke schema berversi dengan pola konfigurasi yang sudah ada.
3. Pada `PanelService`, klasifikasikan dahulu lalu pilih schema yang sesuai sebelum membuat extractor.
4. Sesuaikan discovery schema API agar mengembalikan field kategori yang diminta. Saat ini API membaca schema global.
5. Catat identitas dan versi schema yang benar-benar dipakai pada provenance.
6. Tetapkan perilaku ketika kategori tidak punya schema; jangan diam-diam memakai schema kategori lain.
7. Tambahkan pengujian pemilihan schema, evidence, `UNKNOWN`, dan reprocessing tanpa menimpa hasil lama.

Ini merupakan usulan implementasi. Menempelkan mapping di atas ke editor JSON panel saat ini tidak akan mengaktifkan fitur tersebut.

## 10. Perbedaan workspace RoP

Workspace RoP belum memakai registry kategori/schema panel. Kodenya dipindahkan ke branch `feat/rop-workspace` dan tidak ada di branch API, sehingga lokasi di bawah ditulis sebagai path, bukan tautan.

| Komponen workspace | Lokasi | Kondisi saat ini |
|---|---|---|
| Kategori dan pola ekstraksi | `src/edi_reference/application/rop.py` | Subtype `RoP`, `Invoice`, `Receipt`, atau `UNKNOWN` |
| Daftar field | `src/edi_reference/domain/rop.py` | `document_number`, `document_date`, `total_idr`, `npwp` |
| Instruksi model vision | `src/edi_reference/adapters/rop_runtime.py` | Kategori dan field ditulis dalam prompt |

Penambahan kategori/field pada workspace memerlukan penyelarasan classifier, validator prediction, prompt, normalisasi, tampilan/review, dan tes terkait. ID English pada dokumen ini adalah usulan konsolidasi; subtype workspace belum otomatis berubah menjadi ID tersebut.

## 11. Rencana validasi berdasarkan koleksi

1. Validasi label setiap kelompok, terutama BAPP, BAST, faktur, dan singkatan yang belum jelas.
2. Pisahkan berkas tunggal dari paket yang memuat beberapa jenis dokumen.
3. Buat ground truth kategori dan nilai field dengan pemeriksaan manusia di penyimpanan privat.
4. Pilih variasi layout, kualitas scan, panjang dokumen, dan penerbit. Sebagian contoh yang diperiksa tidak memiliki text layer sehingga membutuhkan OCR.
5. Pisahkan sampel penyusunan rules dari sampel evaluasi. Hindari template yang hampir sama berada pada kedua kelompok jika tujuannya mengukur generalisasi.
6. Ukur confusion matrix kategori, precision/recall per kategori, proporsi `UNKNOWN`, ketepatan nilai per field, dan ketepatan evidence.
7. Uji konflik judul, dokumen tanpa judul, nomor referensi yang mirip, serta beberapa nominal berbeda dalam satu halaman.
8. Periksa batas halaman: seed panel membatasi tiga halaman, sementara beberapa contoh lebih panjang. Field di luar halaman yang diproses tidak boleh dianggap sudah diperiksa.
9. Uji normalisasi tanggal, angka, dan mata uang berdasarkan format nyata tanpa mengubah nilai sumber secara diam-diam.
10. Simpan perubahan konfigurasi sebagai versi baru dan pertahankan hasil mesin sebelumnya saat reprocessing atau koreksi manusia.

Contoh privat tidak boleh dimasukkan ke repository. Tes yang di-commit harus memakai dokumen dan nilai sintetis yang tidak merekonstruksi sumber privat.

## 12. Rekomendasi pengelolaan kategori dan field

### 12.1 Satu registry bersama untuk seluruh jalur aplikasi

Gunakan satu sumber konfigurasi kategori dan schema yang dibaca oleh panel, API, dan workspace. Hindari daftar kategori terpisah di Python, JavaScript, dan prompt model.

Manfaat yang dituju:

- Kategori baru yang diaktifkan tersedia konsisten pada classifier, pilihan UI, API discovery, dan validator.
- Prompt model dibentuk dari konfigurasi tervalidasi, bukan diedit manual setiap kali field bertambah.
- Perubahan field tidak memerlukan perubahan kode selama tipe dan kemampuan ekstraksinya sudah didukung.
- Riwayat perubahan dan rollback dapat dilacak melalui versi konfigurasi yang sama.

Gunakan `ConfigStore` dan batas port/adapter yang ada sebagai titik awal. Tidak perlu menambah framework, database, atau layanan baru hanya untuk membuat katalog konfigurasi. Penyatuan runtime dilakukan bertahap agar perilaku panel/API dan workspace tidak berubah tanpa pengujian.

### 12.2 Pisahkan katalog kategori, katalog field, dan schema kategori

| Bagian konfigurasi | Informasi yang dikelola | Contoh |
|---|---|---|
| Katalog kategori | ID stabil, label tampilan, definisi, batas kategori, status, petunjuk judul, versi | `INVOICE`: permintaan pembayaran dari penerbit kepada penerima |
| Katalog field | ID stabil, label, deskripsi makna, tipe, alias label sumber, normalizer, kebijakan evidence | `contract_amount`: nilai kontrak yang tertulis, bukan nilai tagihan |
| Schema kategori | Referensi field yang berlaku, urutan, kewajiban review, batasan khusus kategori | INVOICE memakai field header dan total tagihan |
| Binding pipeline/profile | Versi taksonomi, schema, rules, normalizer, dan kebijakan eksekusi yang digunakan bersama | Satu paket konfigurasi tervalidasi untuk pemrosesan |

Field umum seperti `document_number` didefinisikan sekali lalu direferensikan oleh beberapa schema. Field dengan makna berbeda tetap memiliki ID berbeda, misalnya `contract_amount`, `payment_amount`, dan `total_amount`; jangan disatukan hanya karena semuanya berupa nominal.

Kategori dibedakan berdasarkan jenis isi dokumen. Variasi pelanggan, vendor, layout, bahasa, atau model OCR dikelola melalui profile/configuration/policy, bukan membuat cabang kode berdasarkan nama pihak.

### 12.3 Aturan penamaan dan perubahan semantik

- Gunakan ID English yang stabil: `WORK_INSPECTION_REPORT`, `purchase_order_number`.
- Pisahkan ID mesin dari label tampilan. UI boleh menampilkan terjemahan Indonesia tanpa mengubah ID API.
- Sertakan definisi singkat tentang apa yang termasuk dan tidak termasuk dalam kategori.
- Gunakan alias untuk variasi label yang benar-benar setara. Jangan menjadikan singkatan ambigu seperti BAPP sebagai alias pasti sebelum definisinya disepakati.
- Perubahan label tampilan tidak boleh mengubah arti kategori atau field.
- Perubahan makna, tipe, atau struktur membutuhkan versi baru dan evaluasi kompatibilitas.
- Jangan menggunakan kembali ID lama untuk arti baru. Tandai sebagai deprecated bila sudah tidak dipakai; hasil historis tetap dapat dibaca.

### 12.4 Alur pemeliharaan melalui panel

Alur yang disarankan:

```text
Draft
  -> Validasi struktur dan referensi
  -> Preview kategori, field, dan prompt
  -> Evaluasi pada sampel
  -> Review perubahan
  -> Aktivasi paket versi
  -> Pemantauan hasil
  -> Rollback bila diperlukan
```

UI yang perlu tersedia:

1. **Categories**: daftar kategori, definisi, status aktif/deprecated, dan schema terkait.
2. **Fields**: katalog field reusable dengan tipe, deskripsi, alias, dan normalizer.
3. **Category schemas**: pilih field dari katalog dan tentukan kebutuhan tiap kategori.
4. **Preview and validation**: tampilkan field efektif, konflik rule, referensi yang hilang, serta dampak terhadap output.
5. **Version history**: pembuat, waktu, alasan perubahan, perbedaan antarversi, aktivasi, dan rollback.
6. **Import/export JSON**: format berversi untuk review dan pemindahan antarlingkungan. Validasi sebelum import; jangan menimpa versi lama.

Editor JSON dapat tetap disediakan untuk administrator teknis. Form terstruktur menjadi jalur utama agar operator tidak perlu memahami format JSON atau regex untuk perubahan rutin.

Ini merupakan rekomendasi, bukan fitur yang sudah tersedia. Panel saat ini menyediakan editor JSON berversi dan aktivasi ulang versi lama; penyimpanan melalui UI langsung mengaktifkan versi baru. Alur draft/review perlu ditambahkan secara eksplisit bila dipilih.

### 12.5 Validasi sebelum aktivasi

Paket konfigurasi hanya diaktifkan setelah pemeriksaan berikut:

- ID kategori/field unik dan semua referensi schema dapat ditemukan.
- Normalizer dan kemampuan tipe field tersedia pada runtime yang dituju.
- Rule dapat dikompilasi dan memenuhi batas konfigurasi; konflik semantik dievaluasi dengan contoh.
- Setiap kategori memiliki schema atau kebijakan tanpa ekstraksi yang eksplisit.
- Perilaku `UNKNOWN` dan evidence tetap fail-safe.
- Field yang wajib pada schema tetapi tidak ditemukan menghasilkan temuan validasi/review, bukan nilai buatan.
- Output schema/API dan UI masih dapat menampilkan field tambahan.
- Perubahan yang memengaruhi konsumen memiliki versi dan rencana transisi yang jelas.

Bedakan nomor versi penyimpanan konfigurasi dari versi semantik taksonomi/schema. Jangan hanya menaikkan pointer konfigurasi ketika arti kontraknya berubah.

### 12.6 Aktivasi konsisten dan kompatibilitas

Perubahan kategori dan schema yang saling bergantung sebaiknya diaktifkan sebagai satu paket tervalidasi. Jika aktivasi dilakukan terpisah, worker dapat melihat kategori baru dengan schema lama.

Pada awal processing run, ikat versi konfigurasi yang digunakan. Perubahan konfigurasi berikutnya tidak boleh mengganti aturan di tengah run. Retry run yang sama memakai versi yang terikat; pemrosesan ulang dengan konfigurasi baru membuat run/result version baru, sesuai kontrak yang berlaku.

Provenance perlu menunjukkan versi taksonomi, classifier/rules, schema, normalizer, dan konfigurasi eksekusi yang benar-benar dipakai. Rollback berlaku untuk pemrosesan berikutnya dan tidak mengubah hasil yang sudah selesai.

Penambahan field tidak selalu aman bagi semua konsumen. Uji konsumen yang mengasumsikan daftar field tetap, dan jangan mengubah tipe scalar menjadi array pada versi kontrak yang sama tanpa keputusan kompatibilitas.

### 12.7 Perubahan konfigurasi versus perubahan kode

| Kebutuhan | Saat ini | Target pemeliharaan |
|---|---|---|
| Tambah kategori pada panel/API | Edit rules dan versi konfigurasi | Form kategori dengan validasi dan preview |
| Tambah field scalar bersama | Edit schema global | Tambah field katalog, lalu pilih schema terkait |
| Field berbeda untuk tiap kategori | Perlu perubahan kode | Pemetaan schema lewat konfigurasi |
| Perbarui label/deskripsi/alias | Dukungan metadata masih terbatas | Perubahan konfigurasi tanpa deploy kode |
| Tambah tipe/normalizer baru | Perlu implementasi dan tes | Tetap memerlukan kode jika kemampuan belum ada |
| Tambah tabel atau struktur nested | Schema scalar belum mendukung | Perubahan kontrak dan implementasi teruji |
| Ubah kategori/field workspace | Beberapa bagian kode perlu diselaraskan | Membaca registry bersama |
| Ubah kebijakan otorisasi bisnis | Di luar fungsi prediksi dokumen | Tetap dipisahkan dari output AI |

### 12.8 Tahapan implementasi yang mudah dipelihara

1. **Fondasi konfigurasi:** tetapkan definisi English dan ID stabil, lalu dokumentasikan label sumber yang ambigu.
2. **Schema per kategori:** tambahkan pemetaan dengan kompatibilitas untuk schema global lama dan uji pemilihan schema.
3. **Katalog field reusable:** tambahkan metadata field dan bangun prompt/validator dari schema efektif yang sama.
4. **Penyatuan jalur:** buat panel/API/workspace membaca registry yang sama melalui port yang eksplisit.
5. **Pengelolaan operator:** tambahkan form, draft, preview, paket aktivasi, riwayat, dan rollback.
6. **Kemampuan lanjutan:** tambahkan tabel berulang dan pemrosesan paket dokumen setelah kontrak dan kebutuhan terkonfirmasi.

Untuk setiap perubahan, jalankan tes terarah yang membuktikan kategori baru, field yang relevan, konflik, `UNKNOWN`, dan hasil historis tetap benar. Gunakan regresi sintetis di repository serta evaluasi dokumen privat di lokasi terpisah. Hentikan perluasan pengujian jika tidak ada perubahan atau risiko baru yang membutuhkannya.

Ukuran keberhasilan pengelolaan: operator dapat menambahkan kategori dengan kemampuan yang sudah didukung tanpa deploy kode, semua jalur aplikasi menghasilkan schema yang konsisten, dan setiap keputusan prediksi dapat ditelusuri ke paket konfigurasi yang digunakan.

## 13. Prioritas dan status verifikasi

| Prioritas | Tindakan | Hasil yang diharapkan |
|---|---|---|
| 1 | Tetapkan arti kategori dari isi, khususnya label BAPP/BAST | Taksonomi English yang tidak ambigu |
| 2 | Evaluasi urutan dan konflik rule judul | Mengurangi salah klasifikasi seperti invoice/pesanan |
| 3 | Terapkan pemilihan schema per kategori | Field relevan untuk setiap jenis dokumen |
| 4 | Tambahkan metadata field dan dukungan tabel sesuai kontrak | Ekstraksi yang lebih jelas dan terstruktur |
| 5 | Evaluasi pada sampel terpisah dan audit evidence | Bukti kualitas sebelum penggunaan operasional |

Catatan historis (sebelum phase D): pada analisis kode saat itu, suite melalui `.venv-win\Scripts\python.exe -m pytest` menghasilkan 522 passed, 41 skipped, dan 1 failed. Kegagalan berada pada pemeriksaan frontend lokal yang juga menolak teks placeholder URL. PostgreSQL tidak diverifikasi karena DSN pengujian tidak tersedia.

Hasil tes tersebut bukan bukti akurasi OCR, klasifikasi, atau ekstraksi pada koleksi ini. Suite tidak dijalankan ulang untuk penulisan dokumen Markdown ini. Penyelarasan terhadap repository spesifikasi eksternal, inference seluruh koleksi, dan perubahan konfigurasi runtime belum dilakukan.
