"""Job Vacancy Data Collector - UTS Automation Systems.

Mengambil lowongan IT dari halaman publik Dealls, membaca detail tiap
lowongan, mengenali keterampilan dengan regex, mengelompokkan per bidang,
lalu menyimpan hasilnya ke CSV, laporan teks, dan backup ZIP.

Contoh:
    python main.py --limit 30 --backup
    python main.py --keyword python --limit 10
    python main.py --offline --backup
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar
from urllib.parse import urlencode
from zipfile import ZIP_DEFLATED, ZipFile

import requests
from bs4 import BeautifulSoup


DEFAULT_URL = "https://dealls.com/loker/posisi/loker-it-and-software-engineering"
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
HTML_DIR = DATA_DIR / "html"
STAGING_DIR = DATA_DIR / "html_sementara"
RAW_FILE = DATA_DIR / "raw_data.txt"
BACKUP_FILE = PROJECT_ROOT / "backup" / "backup_data.zip"

HEADERS = {
    "User-Agent": "UTSJobCollector/1.0 (educational project; public job listings)",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}
REQUEST_TIMEOUT = 25
MAX_ATTEMPTS = 3
MAX_NETWORK_ERRORS = 3
NETWORK_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
T = TypeVar("T")

# Kalau pakai --keyword, banyak lowongan tidak lolos filter. Supaya program
# tidak terus-terusan membuka halaman detail, jumlah yang diperiksa dibatasi.
MAX_CHECK_FACTOR = 4

CSV_COLUMNS = [
    "judul_lowongan", "perusahaan", "lokasi", "bidang", "keterampilan",
    "tag_keterampilan", "tipe_pekerjaan", "sistem_kerja",
    "tanggal_publikasi", "url", "waktu_pengambilan",
]
EMPTY = "Tidak dicantumkan"

# URL detail Dealls bentuknya /loker/<slug-lowongan>~<slug-perusahaan>.
# Dipakai untuk memvalidasi URL sebelum halaman detail diminta.
JOB_URL_PATTERN = re.compile(r"^https://dealls\.com/loker/[\w-]+~[\w-]+$")

# Huruf kapital di tengah kata, misalnya "fullTime" -> "full Time".
CAMEL_CASE_PATTERN = re.compile(r"(?<=[a-z])(?=[A-Z])")


def skill_regex(body: str) -> re.Pattern[str]:
    """Bungkus pola skill dengan batas kata versi kita sendiri.

    \\b bawaan regex kurang cocok untuk nama teknologi. "C#" dan ".NET"
    mengandung simbol, dan "SQL" tidak boleh ikut cocok di dalam "NoSQL".
    Titik dan strip di belakang sengaja dibolehkan supaya "Python." di akhir
    kalimat dan "Python-based" tetap terbaca.
    """
    return re.compile(rf"(?<![\w+#.]){body}(?![\w+#])", re.IGNORECASE)


SKILL_PATTERNS = {
    "Python": skill_regex(r"python"),
    "JavaScript": skill_regex(r"javascript"),
    "TypeScript": skill_regex(r"typescript"),
    "Java": skill_regex(r"java"),
    "Kotlin": skill_regex(r"kotlin"),
    "Swift": skill_regex(r"swift"),
    "Golang": skill_regex(r"golang"),
    "PHP": skill_regex(r"php"),
    "C#": skill_regex(r"c#"),
    ".NET": skill_regex(r"\.net|asp\.net"),
    "SQL": skill_regex(r"sql"),
    "MySQL": skill_regex(r"mysql"),
    "PostgreSQL": skill_regex(r"postgres(?:ql)?"),
    "SQL Server": skill_regex(r"sql\s+server|mssql"),
    "Oracle DB": skill_regex(r"oracle(?:\s+db|\s+database)"),
    "MongoDB": skill_regex(r"mongo(?:db)?"),
    "Redis": skill_regex(r"redis"),
    "React": skill_regex(r"react(?:\.?js)?"),
    "Vue": skill_regex(r"vue(?:\.?js)?"),
    "Angular": skill_regex(r"angular"),
    "Node.js": skill_regex(r"node(?:\.?js)?"),
    "Laravel": skill_regex(r"laravel"),
    "Django": skill_regex(r"django"),
    "Spring Boot": skill_regex(r"spring\s?boot|springboot"),
    "Flutter": skill_regex(r"flutter"),
    "Android": skill_regex(r"android"),
    "Docker": skill_regex(r"docker"),
    "Kubernetes": skill_regex(r"kubernetes|k8s"),
    "Terraform": skill_regex(r"terraform"),
    "Jenkins": skill_regex(r"jenkins"),
    "AWS": skill_regex(r"aws|amazon\s+web\s+services"),
    "GCP": skill_regex(r"gcp|google\s+cloud"),
    "Azure": skill_regex(r"azure"),
    "Linux": skill_regex(r"linux"),
    "Git": skill_regex(r"git(?:hub|lab)?"),
    "REST API": skill_regex(r"rest(?:ful)?\s*api"),
    "Postman": skill_regex(r"postman"),
    "Selenium": skill_regex(r"selenium"),
    "ETL": skill_regex(r"etl"),
    "Power BI": skill_regex(r"power\s?bi"),
    "Tableau": skill_regex(r"tableau"),
    "Excel": skill_regex(r"excel"),
    "Machine Learning": skill_regex(r"machine\s+learning"),
    "TensorFlow": skill_regex(r"tensorflow"),
    "PyTorch": skill_regex(r"pytorch"),
}

# Bidang ditentukan dari JUDUL lowongan, bukan deskripsi. Deskripsi hampir
# selalu menyebut "security", "testing", atau "data", jadi kalau deskripsi
# ikut dibaca, satu lowongan bisa masuk 3-4 bidang sekaligus.
#
# Urutan dictionary penting: aturan pertama yang cocok yang dipakai.
# "DevSecOps" harus kena Keamanan Siber dulu sebelum DevOps di Infrastruktur,
# dan "Software Development Engineer in Test" harus masuk QA, bukan Developer.
FIELD_RULES = {
    "QA dan Pengujian": [
        r"quality assurance", r"\bqa\b", r"\bsdet\b", r"\btest(?:er|ing)?\b",
    ],
    "Keamanan Siber": [
        r"secur", r"cyber", r"appsec", r"devsecops", r"penetration", r"soc analyst",
    ],
    "Data dan AI": [
        r"\bdata\b", r"machine learning", r"\bai\b", r"\bml\b",
        r"business intelligence", r"analytics",
    ],
    "Dukungan IT": [
        r"\bit support\b", r"technical support", r"help ?desk", r"service desk",
        r"\bict support\b", r"\bmis\b", r"support (?:engineer|officer|operator)",
        r"application (?:operations|monitoring) support",
    ],
    "Infrastruktur dan Operasional IT": [
        r"devops", r"cloud", r"system administrator", r"sysadmin", r"network",
        r"infrastructure", r"database administrator", r"\bdba\b",
        r"site reliability", r"\bsre\b", r"platform engineer",
    ],
    "Pengembangan Perangkat Lunak": [
        r"developer", r"software engineer", r"programmer", r"front[ -]?end",
        r"back[ -]?end", r"full[ -]?stack", r"android", r"\bios\b", r"mobile",
        r"web engineer",
    ],
    "Produk dan Analisis Sistem": [
        r"product (?:manager|owner)", r"business analyst", r"system analyst",
        r"technical writer", r"ui/?ux", r"consultant",
    ],
}
OTHER_FIELD = "Lainnya"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kumpulkan dan kelompokkan lowongan IT dari halaman publik Dealls.",
    )
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="URL halaman daftar lowongan Dealls.")
    parser.add_argument("--limit", type=int, default=30,
                        help="Jumlah record yang ingin disimpan. Default: 30.")
    parser.add_argument("--keyword", default="",
                        help="Hanya simpan lowongan yang memuat kata ini.")
    parser.add_argument("--output", default="output",
                        help="Folder hasil (relatif ke folder proyek). Default: output.")
    parser.add_argument("--backup", action="store_true",
                        help="Buat backup ZIP dari folder data dan output.")
    parser.add_argument("--delay", type=float, default=0.6,
                        help="Jeda antar request dalam detik. Default: 0.6.")
    parser.add_argument("--offline", action="store_true",
                        help="Proses ulang HTML yang tersimpan di data/ tanpa internet.")
    args = parser.parse_args()

    # parser.error() langsung keluar dengan pesan yang jelas, jadi nilai
    # aneh dari user tidak sempat masuk ke proses scraping.
    if args.limit < 1:
        parser.error("--limit minimal 1.")
    if args.delay < 0:
        parser.error("--delay tidak boleh negatif.")
    if args.offline and args.url != DEFAULT_URL:
        parser.error("--url tidak dipakai saat --offline.")
    return args


# ---------------------------------------------------------------------------
# Pembersihan teks (regex)
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    """Ubah HTML/teks mentah dari sumber jadi satu baris teks yang bersih."""
    if value is None:
        return ""
    text = BeautifulSoup(unescape(str(value)), "html.parser").get_text(" ")
    # Spasi, tab, newline, dan non-breaking space yang berderet jadi satu spasi.
    return re.sub(r"\s+", " ", text).strip()


def humanize_code(value: str) -> str:
    """Kode dari API jadi teks biasa, misalnya fullTime -> Full Time."""
    return CAMEL_CASE_PATTERN.sub(" ", value).title() if value else ""


def safe_filename(value: str) -> str:
    """Nama bidang jadi nama file: "Data dan AI" -> "data_dan_ai"."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "lainnya"


def display_path(path: Path) -> str:
    """Path pendek untuk ditampilkan; path di luar folder proyek ditulis lengkap."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def find_skills(text: str) -> list[str]:
    return [name for name, pattern in SKILL_PATTERNS.items() if pattern.search(text)]


def classify_field(title: str) -> str:
    lowered = title.lower()
    for field, patterns in FIELD_RULES.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            return field
    return OTHER_FIELD


# ---------------------------------------------------------------------------
# Folder dan file
# ---------------------------------------------------------------------------

def prepare_folders(output_dir: Path, html_dir: Path) -> None:
    # Sisa folder sementara dari run yang dulu crash dibuang dulu.
    if html_dir == STAGING_DIR and STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)

    for folder in (DATA_DIR, html_dir, output_dir, BACKUP_FILE.parent):
        folder.mkdir(parents=True, exist_ok=True)


def promote_staging() -> None:
    """Ganti data/html lama dengan hasil download run ini.

    Run online menulis HTML ke folder sementara dulu. Baru setelah run
    berhasil, folder itu menggantikan data/html. Kalau run gagal di tengah
    (404, internet putus, keyword tidak ketemu), data/html dan raw_data.txt
    yang lama tetap utuh dan masih cocok satu sama lain untuk --offline.
    """
    if HTML_DIR.exists():
        shutil.rmtree(HTML_DIR)
    STAGING_DIR.rename(HTML_DIR)


def write_csv(records: list[dict[str, str]], path: Path) -> None:
    # utf-8-sig menambahkan BOM supaya Excel tidak salah baca huruf non-ASCII.
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def write_grouped_csv(records: list[dict[str, str]], output_dir: Path) -> Counter[str]:
    group_dir = output_dir / "per_bidang"
    group_dir.mkdir(exist_ok=True)

    # Bersihkan CSV lama. Bidang yang kosong di run ini tidak boleh
    # meninggalkan file sisa run sebelumnya.
    for old_file in group_dir.glob("*.csv"):
        old_file.unlink()

    groups: dict[str, list[dict[str, str]]] = {}
    for record in records:
        groups.setdefault(record["bidang"], []).append(record)

    for field, rows in groups.items():
        write_csv(rows, group_dir / f"{safe_filename(field)}.csv")

    return Counter({field: len(rows) for field, rows in groups.items()})


def write_report(path: Path, summary: dict[str, Any], records: list[dict[str, str]],
                 field_counts: Counter[str], failures: list[str]) -> None:
    skill_counts = Counter(
        skill
        for record in records
        if record["keterampilan"] != EMPTY
        for skill in record["keterampilan"].split("; ")
    )
    no_skill = sum(record["keterampilan"] == EMPTY for record in records)

    info = [
        ("Waktu proses", summary["finished_at"]),
        ("Mode", summary["mode"]),
        ("Sumber", summary["source"]),
        ("Kata kunci", summary["keyword"] or "-"),
        ("Lowongan diperiksa", summary["checked"]),
        ("Record tersimpan", len(records)),
        ("Tidak cocok kata kunci", summary["skipped_keyword"]),
        ("Duplikat dilewati", summary["duplicates"]),
        ("Gagal diproses", len(failures)),
        ("Tanpa skill terbaca", no_skill),
    ]
    lines = [
        "LAPORAN JOB VACANCY DATA COLLECTOR",
        "=" * 40,
        *[f"{label:<23}: {value}" for label, value in info],
        "",
        "JUMLAH PER BIDANG",
        *[f"  {field:<34} {count:>3}" for field, count in field_counts.most_common()],
        "",
        "10 KETERAMPILAN PALING SERING DISEBUT",
        *[f"  {skill:<34} {count:>3}" for skill, count in skill_counts.most_common(10)],
    ]
    if failures:
        lines += ["", "DETAIL KEGAGALAN", *[f"  - {item}" for item in failures]]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_backup(output_dir: Path) -> Path:
    # Nama file tetap (backup_data.zip) sesuai struktur pengumpulan UTS.
    # Run berikutnya menimpa backup lama.
    with ZipFile(BACKUP_FILE, "w", compression=ZIP_DEFLATED) as archive:
        for folder in (DATA_DIR, output_dir):
            for file_path in sorted(folder.rglob("*")):
                if file_path.is_file():
                    # Path di dalam ZIP dimulai dari nama folder: data/..., output/...
                    archive.write(file_path, file_path.relative_to(folder.parent))
    return BACKUP_FILE


# ---------------------------------------------------------------------------
# Membaca data dari Dealls
# ---------------------------------------------------------------------------
# Dealls dibangun dengan Next.js. Data lowongan sudah ikut terkirim di HTML
# dalam <script id="__NEXT_DATA__"> berbentuk JSON. Membaca JSON itu lebih
# stabil daripada menebak class CSS yang namanya acak dan sering berubah.

def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def fetch_with_retry(session: requests.Session, url: str, parse: Callable[[str], T],
                     delay: float, is_empty: Callable[[T], bool] = lambda value: not value,
                     ) -> tuple[str, T]:
    """Ambil halaman lalu parse, ulangi kalau hasil parse kosong.

    Dari percobaan, Dealls kadang mengirim status 200 tapi tanpa data lowongan
    di __NEXT_DATA__ (request yang sama beberapa detik kemudian normal lagi).
    Jadi "kosong" di sini belum tentu benar-benar kosong; dicoba lagi dulu
    dengan jeda yang makin lama. Error server 5xx diperlakukan sama.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            html = fetch_html(session, url)
        except requests.exceptions.HTTPError as error:
            # 5xx (misalnya 503) artinya server sedang sibuk, biasanya sementara.
            # 4xx seperti 404 tidak akan berubah walau diulang, jadi langsung dilempar.
            if error.response.status_code < 500 or attempt == MAX_ATTEMPTS:
                raise
            time.sleep(max(delay, 1.0) * attempt)
            continue
        parsed = parse(html)
        if not is_empty(parsed) or attempt == MAX_ATTEMPTS:
            return html, parsed
        time.sleep(max(delay, 1.0) * attempt)
    raise AssertionError("unreachable")


def read_next_data(html: str) -> dict[str, Any]:
    script = BeautifulSoup(html, "html.parser").select_one("script#__NEXT_DATA__")
    if script is None or not script.string:
        raise ValueError("blok __NEXT_DATA__ tidak ada, struktur halaman mungkin berubah")
    return json.loads(script.string)


def walk(value: Any) -> Iterator[dict[str, Any]]:
    """Telusuri semua dict di dalam JSON bersarang.

    Posisi data lowongan di JSON Next.js bisa bergeser kalau website diupdate.
    Daripada hard-code path panjang, kita cari dict yang bentuknya cocok.
    """
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def jobs_from_listing(next_data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    jobs, total_pages = [], 1
    for item in walk(next_data):
        if isinstance(item.get("totalPages"), int):
            total_pages = max(total_pages, item["totalPages"])
        # Ciri ringkasan lowongan: punya id, slug, role, dan objek company.
        if {"id", "slug", "role"} <= item.keys() and isinstance(item.get("company"), dict):
            jobs.append(item)
    return jobs, total_pages


def job_from_detail(next_data: dict[str, Any]) -> dict[str, Any] | None:
    for item in walk(next_data):
        if isinstance(item.get("company"), dict) and item.get("role") and "requirements" in item:
            return item
    return None


def page_url(base_url: str, page: int) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'page': page})}"


def detail_url(job: dict[str, Any]) -> str:
    job_slug = job.get("slug") or ""
    company_slug = (job.get("company") or {}).get("slug") or ""
    return f"https://dealls.com/loker/{job_slug}~{company_slug}"


def online_candidates(session: requests.Session, source_url: str,
                      delay: float, html_dir: Path) -> Iterator[dict[str, Any]]:
    """Ambil ringkasan lowongan halaman demi halaman.

    Pakai generator supaya halaman berikutnya baru diminta saat memang
    dibutuhkan. Kalau 30 record sudah terkumpul di halaman 2, halaman 3
    dan seterusnya tidak pernah di-request.
    """
    page, total_pages = 1, 1
    while page <= total_pages:
        html, (jobs, pages_found) = fetch_with_retry(
            session, page_url(source_url, page),
            parse=lambda text: jobs_from_listing(read_next_data(text)),
            delay=delay,
            is_empty=lambda result: not result[0],
        )
        (html_dir / f"listing_page_{page}.html").write_text(html, encoding="utf-8")
        if not jobs:
            return

        # Halaman yang gagal dimuat melaporkan totalPages=1, jadi pakai
        # angka terbesar yang pernah terlihat.
        total_pages = max(total_pages, pages_found)
        yield from jobs

        page += 1
        time.sleep(delay)


def offline_candidates() -> Iterator[dict[str, Any]]:
    # Akan memunculkan FileNotFoundError kalau belum pernah run online.
    # Error itu ditangkap di main() dan diberi pesan yang lebih jelas.
    yield from json.loads(RAW_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Satu lowongan -> satu record
# ---------------------------------------------------------------------------

def build_record(job: dict[str, Any], url: str, captured_at: str) -> dict[str, str]:
    title = clean_text(job.get("role"))
    company = clean_text((job.get("company") or {}).get("name"))

    location = job.get("location") or {}
    city = clean_text((location.get("city") or {}).get("name"))
    country = clean_text((location.get("country") or {}).get("name"))
    place = ", ".join(part for part in (city, country) if part)

    # Tag dari pemberi kerja (pre-screening questions) disimpan apa adanya,
    # karena isinya bebas: kadang "Java Springboot", kadang "Communication".
    tags: list[str] = []
    for question in job.get("preScreeningQuestions") or []:
        for tag in question.get("dynamicItems") or []:
            tag = clean_text(tag)
            if tag and tag not in tags:
                tags.append(tag)

    # Kolom keterampilan diisi dari hasil regex supaya namanya seragam
    # dan bisa dihitung di laporan ("SQL" bukan "sql (basic)").
    full_text = " ".join(
        clean_text(job.get(key)) for key in ("description", "requirements", "responsibilities")
    )
    skills = find_skills(f"{full_text} {' '.join(tags)}")

    return {
        "judul_lowongan": title,
        "perusahaan": company,
        "lokasi": place or EMPTY,
        "bidang": classify_field(title),
        "keterampilan": "; ".join(skills) or EMPTY,
        "tag_keterampilan": "; ".join(tags) or EMPTY,
        "tipe_pekerjaan": ", ".join(humanize_code(t) for t in job.get("employmentTypes") or []) or EMPTY,
        "sistem_kerja": humanize_code(job.get("workplaceType") or "") or EMPTY,
        "tanggal_publikasi": (job.get("publishedAt") or "")[:10] or EMPTY,
        "url": url,
        "waktu_pengambilan": captured_at,
    }


def matches_keyword(record: dict[str, str], keyword: str) -> bool:
    if not keyword:
        return True
    haystack = " ".join(record[key] for key in (
        "judul_lowongan", "perusahaan", "lokasi", "bidang", "keterampilan", "tag_keterampilan",
    ))
    return keyword.casefold() in haystack.casefold()


# ---------------------------------------------------------------------------
# Alur utama
# ---------------------------------------------------------------------------

def collect(args: argparse.Namespace, session: requests.Session | None,
            html_dir: Path) -> tuple[
        list[dict[str, str]], list[dict[str, Any]], list[str], dict[str, int]]:
    """Loop utama: kandidat -> halaman detail -> record.

    Berhenti kalau record sudah mencapai --limit, kandidat habis, atau
    jumlah lowongan yang diperiksa sudah mencapai batas MAX_CHECK_FACTOR.
    """
    records: list[dict[str, str]] = []
    checked_jobs: list[dict[str, Any]] = []   # ditulis ke raw_data.txt
    failures: list[str] = []
    stats = {"duplicates": 0, "skipped_keyword": 0}
    seen_ids: set[str] = set()
    max_checks = args.limit * MAX_CHECK_FACTOR
    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")

    network_errors = 0
    candidates = offline_candidates() if args.offline else online_candidates(
        session, args.url, args.delay, html_dir)

    # Error dari halaman DAFTAR tidak ditangkap di sini. Kalau halaman daftar
    # gagal, run dianggap gagal total dan main() yang memberi pesan.
    for job in candidates:
        if len(records) >= args.limit or len(checked_jobs) >= max_checks:
            break

        # Lowongan "boosted" bisa muncul lagi di halaman berikutnya.
        job_id = str(job.get("id"))
        if job_id in seen_ids:
            stats["duplicates"] += 1
            continue
        seen_ids.add(job_id)
        checked_jobs.append(job)

        number = len(checked_jobs)
        url = detail_url(job)
        if not JOB_URL_PATTERN.match(url):
            failures.append(f"#{number} URL tidak valid: {url}")
            continue

        print(f"[{number:>3}] {clean_text(job.get('role'))[:60]}")
        html_file = html_dir / f"detail_{number:03d}.html"
        try:
            if args.offline:
                detail = job_from_detail(read_next_data(html_file.read_text(encoding="utf-8")))
            else:
                html, detail = fetch_with_retry(
                    session, url, lambda text: job_from_detail(read_next_data(text)), args.delay)
                html_file.write_text(html, encoding="utf-8")
                time.sleep(args.delay)
        except FileNotFoundError:
            failures.append(f"#{number} file {html_file.name} tidak ditemukan")
            continue
        except NETWORK_ERRORS as error:
            # Satu timeout bisa kebetulan. Tiga kali berturut-turut hampir
            # pasti internet putus, jadi hentikan run. Error dilempar ke
            # main(), dan hasil run sebelumnya tidak ditimpa data setengah jadi.
            network_errors += 1
            if network_errors >= MAX_NETWORK_ERRORS:
                raise
            failures.append(f"#{number} {url}: {error}")
            continue
        except (requests.exceptions.RequestException, ValueError) as error:
            # Satu halaman detail gagal (404, 5xx, JSON rusak) cukup
            # dicatat. Lowongan lain tetap diproses.
            failures.append(f"#{number} {url}: {error}")
            continue

        network_errors = 0

        if detail is None:
            failures.append(f"#{number} {url}: data lowongan kosong di halaman detail")
            continue

        record = build_record(detail, url, captured_at)
        if not record["judul_lowongan"] or not record["perusahaan"]:
            failures.append(f"#{number} {url}: judul atau perusahaan kosong")
            continue

        if matches_keyword(record, args.keyword):
            records.append(record)
        else:
            stats["skipped_keyword"] += 1

    return records, checked_jobs, failures, stats


def main() -> int:
    # Konsol Windows kadang bukan UTF-8. Karakter seperti "–" di judul
    # lowongan jangan sampai bikin program crash hanya karena print().
    sys.stdout.reconfigure(errors="replace")

    args = parse_arguments()
    output_dir = PROJECT_ROOT / args.output
    html_dir = HTML_DIR if args.offline else STAGING_DIR
    prepare_folders(output_dir, html_dir)

    try:
        return run(args, output_dir, html_dir)
    finally:
        # Kalau run online gagal, folder sementara belum sempat dipindah.
        # Buang saja supaya tidak ikut masuk backup.
        shutil.rmtree(STAGING_DIR, ignore_errors=True)


def run(args: argparse.Namespace, output_dir: Path, html_dir: Path) -> int:
    session = None
    if not args.offline:
        session = requests.Session()
        session.headers.update(HEADERS)

    print(f"Mode {'offline' if args.offline else 'online'} | target {args.limit} record\n")
    try:
        records, checked_jobs, failures, stats = collect(args, session, html_dir)
    except FileNotFoundError:
        print(f"Gagal: {display_path(RAW_FILE)} tidak ditemukan. "
              "Jalankan sekali tanpa --offline untuk mengambil data dulu.")
        return 1
    except requests.exceptions.ConnectionError:
        print("\nGagal: tidak bisa terhubung ke website. Cek koneksi internet, "
              "atau pakai --offline untuk memproses data yang sudah tersimpan.\n"
              "Hasil dari run sebelumnya tidak diubah.")
        return 1
    except requests.exceptions.Timeout:
        print(f"\nGagal: website tidak merespons dalam {REQUEST_TIMEOUT} detik. "
              "Hasil dari run sebelumnya tidak diubah.")
        return 1
    except requests.exceptions.HTTPError as error:
        print(f"Gagal: server menolak request ({error.response.status_code}). "
              f"Periksa kembali --url: {args.url}")
        return 1
    except requests.exceptions.RequestException as error:
        print(f"Gagal: request bermasalah: {error}")
        return 1
    except ValueError as error:
        print(f"Gagal: data halaman tidak bisa dibaca ({error}).")
        return 1
    except KeyboardInterrupt:
        print("\nDibatalkan oleh pengguna. Tidak ada file hasil yang ditulis.")
        return 130

    if not records:
        print("\nTidak ada record yang tersimpan. "
              "Coba kata kunci lain atau periksa URL sumber.")
        return 1

    # Di mode offline raw_data.txt adalah input, jadi jangan ditimpa.
    if not args.offline:
        promote_staging()
        RAW_FILE.write_text(json.dumps(checked_jobs, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    dataset_file = output_dir / "hasil_scraping.csv"
    report_file = output_dir / "laporan.txt"
    write_csv(records, dataset_file)
    field_counts = write_grouped_csv(records, output_dir)
    write_report(report_file, {
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "offline" if args.offline else "online",
        "source": RAW_FILE.name if args.offline else args.url,
        "keyword": args.keyword,
        "checked": len(checked_jobs),
        **stats,
    }, records, field_counts, failures)
    backup_path = create_backup(output_dir) if args.backup else None

    print("\n" + "=" * 46)
    print("RINGKASAN PEMROSESAN")
    print("=" * 46)
    print(f"Lowongan diperiksa : {len(checked_jobs)}")
    print(f"Record tersimpan   : {len(records)}")
    print(f"Tidak cocok keyword: {stats['skipped_keyword']}")
    print(f"Duplikat dilewati  : {stats['duplicates']}")
    print(f"Gagal diproses     : {len(failures)}")
    print("\nPer bidang:")
    for field, count in field_counts.most_common():
        print(f"  {field:<34} {count:>3}")
    print(f"\nDataset : {display_path(dataset_file)}")
    print(f"Laporan : {display_path(report_file)}")
    if backup_path:
        print(f"Backup  : {display_path(backup_path)}")
    if len(records) < args.limit:
        print(f"\nCatatan: hanya {len(records)} dari target {args.limit} record yang terkumpul.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
