# Job Vacancy Data Collector

Proyek UTS mata kuliah Automation Systems. Program CLI ini mengambil lowongan
kerja IT dari halaman publik [Dealls](https://dealls.com/loker/posisi/loker-it-and-software-engineering),
membuka halaman detail setiap lowongan, lalu menyimpan judul, perusahaan,
lokasi, keterampilan, dan bidang pekerjaannya ke CSV. Hasilnya dipisah per
bidang, diringkas di `laporan.txt`, dan bisa di-backup ke ZIP.

## Instalasi

Butuh Python 3.10 atau lebih baru. Dari PowerShell, di folder proyek:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Cara pakai

Run standar untuk tugas (30 record + backup ZIP):

```powershell
python main.py --limit 30 --backup
```

| Argumen | Default | Fungsi |
|---|---|---|
| `--url URL` | kategori IT & Software Engineering | Halaman daftar Dealls yang diambil |
| `--limit N` | 30 | Jumlah record yang ingin disimpan |
| `--keyword KATA` | (kosong) | Simpan hanya lowongan yang memuat kata ini di judul, perusahaan, lokasi, bidang, atau skill |
| `--output FOLDER` | `output` | Folder hasil |
| `--backup` | mati | Buat `backup/backup_data.zip` dari folder `data/` dan folder output |
| `--delay DETIK` | 0.6 | Jeda antar request supaya tidak membebani server |
| `--offline` | mati | Proses ulang HTML yang sudah tersimpan di `data/`, tanpa internet |

Contoh lain:

```powershell
# Hanya lowongan yang menyebut Python
python main.py --keyword python --limit 10

# Kategori lain di Dealls, hasil ke folder terpisah
python main.py --url https://dealls.com/loker/posisi/loker-sistem-informasi --output output_si

# Internet mati saat demo? Pakai data dari run terakhir
python main.py --offline --backup
```

## Struktur folder

```
main.py                    program utama
requirements.txt
tests/test_rules.py        tes regex dan klasifikasi bidang
data/
  raw_data.txt             JSON ringkasan lowongan yang diperiksa (data mentah)
  html/                    HTML halaman daftar dan detail yang diunduh
output/
  hasil_scraping.csv       dataset utama
  laporan.txt              ringkasan proses
  per_bidang/*.csv         satu CSV per bidang pekerjaan
backup/
  backup_data.zip
dokumentasi/
  laporan_uts.pdf
```

Folder `data/`, `output/`, dan `backup/` dibuat otomatis oleh program.

## Kolom dataset

| Kolom | Isi |
|---|---|
| `judul_lowongan` | Nama posisi dari pemberi kerja |
| `perusahaan` | Nama perusahaan |
| `lokasi` | Kota, negara |
| `bidang` | Hasil klasifikasi dari judul (lihat di bawah) |
| `keterampilan` | Skill yang dikenali regex dari deskripsi, persyaratan, dan tag |
| `tag_keterampilan` | Tag skill asli dari pemberi kerja, apa adanya |
| `tipe_pekerjaan` | Full Time, Contract, Internship, ... |
| `sistem_kerja` | On Site, Hybrid, Remote |
| `tanggal_publikasi` | Tanggal lowongan dipublikasikan (YYYY-MM-DD) |
| `url` | Halaman detail lowongan |
| `waktu_pengambilan` | Kapan data diambil |

Kalau informasi tidak tersedia di sumber, kolom diisi `Tidak dicantumkan`
(tidak ditebak).

## Cara kerja singkat

1. Dealls dibangun dengan Next.js, jadi data lowongan sudah ada di dalam HTML
   pada tag `<script id="__NEXT_DATA__">` dalam bentuk JSON. Program membaca
   tag itu dengan BeautifulSoup, lalu `json.loads`. Cara ini lebih stabil
   daripada menebak class CSS yang namanya acak.
2. Halaman daftar diambil per halaman (`?page=1`, `?page=2`, ...) sampai
   jumlah record mencapai `--limit`.
3. Setiap lowongan dibuka halaman detailnya untuk mengambil deskripsi dan
   persyaratan.
4. Regex dipakai untuk:
   - membersihkan spasi/tab/newline berlebih (`\s+`)
   - memvalidasi URL detail (`^https://dealls\.com/loker/[\w-]+~[\w-]+$`)
   - mengenali 45 nama skill dengan batas kata khusus, supaya "SQL" tidak
     terbaca di dalam "NoSQL" dan "Java" tidak terbaca di dalam "JavaScript"
   - mengelompokkan bidang dari judul lowongan
   - mengubah kode seperti `fullTime` jadi `Full Time`
   - membuat nama file aman dari nama bidang
5. Bidang ditentukan dari judul, bukan deskripsi. Deskripsi lowongan hampir
   selalu menyebut "security" atau "testing", sehingga kalau ikut dibaca,
   satu lowongan bisa masuk 3-4 bidang sekaligus.

## Penanganan error

| Kondisi | Yang terjadi |
|---|---|
| Internet mati / domain salah | Pesan jelas, saran pakai `--offline`, exit code 1 |
| Server lambat | Timeout 25 detik, pesan jelas |
| URL salah (404) | Pesan berisi status code dan URL yang dipakai |
| Halaman terkirim tanpa data, atau server error 5xx (misal 503) | Dicoba ulang maksimal 3 kali dengan jeda bertambah |
| Satu halaman detail gagal | Dicatat di laporan, lowongan lain tetap diproses |
| Tidak ada record (misal keyword tidak cocok) | Pesan jelas, file hasil lama tidak ditimpa |
| `data/raw_data.txt` tidak ada saat `--offline` | Pesan "jalankan sekali tanpa --offline dulu" |
| File HTML detail hilang saat `--offline` | Dicatat sebagai gagal, sisanya tetap diproses |
| Argumen tidak valid (`--limit 0`) | Ditolak argparse sebelum scraping dimulai |
| Internet putus di tengah run | 3 error jaringan berturut-turut menghentikan run, hasil lama tidak ditimpa |
| Ctrl+C | Berhenti dengan pesan, tanpa traceback |

Run online menyimpan HTML ke `data/html_sementara/` dulu dan baru
menggantikan `data/html/` setelah berhasil. Run yang gagal tidak merusak
data dari run sebelumnya.

## Tes

```powershell
python -m unittest discover tests
```

## Etika pengambilan data

`robots.txt` Dealls mengizinkan semua path (`Allow: /`). Program hanya
membuka halaman publik, tidak login, tidak mengisi formulir, dan tidak
mengambil data pribadi pelamar. User-Agent menyebut bahwa ini proyek
pendidikan, dan ada jeda antar request. Kalau Dealls mengubah kebijakan atau
mulai menolak akses, hentikan pengambilan dan gunakan sumber lain sesuai
arahan dosen.
