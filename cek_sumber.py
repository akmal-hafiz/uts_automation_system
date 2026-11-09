from pathlib import Path
import requests 
from bs4 import BeautifulSoup

# Mulai dari halaman daftar untuk memeriksa HTML yang dikirim website.
url = "https://dealls.com/loker/" 

# Kenalkan program sebagai pemeriksa sumber untuk tugas kuliah.
headers = {
    "User-Agent": "UTSJobCollector/0.1 (educational source check)"
}

try:
    # Ambil halaman dengan batas waktu tunggu koneksi dan pembacaan respons.
    response = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

    # Periksa status dan alamat akhir, termasuk jika website mengalihkan permintaan.
    print("Status HTTP:", response.status_code)
    print("URL akhir:", response.url)

  
    response.raise_for_status()

   
    soup = BeautifulSoup(response.text, "html.parser")

    
    title = soup.title.get_text(strip=True) if soup.title else "Tidak ada judul"
    heading = soup.find("h1")

    print("Judul halaman:", title)
    print("Panjang HTML:", len(response.text))

    
    if heading is not None:
        print("Heading utama:", heading.get_text(" ", strip=True))
    else:
        print("Heading utama tidak ditemukan.")

   
    data_folder = Path("data")
    data_folder.mkdir(parents=True, exist_ok=True)

    # Simpan HTML asli untuk diperiksa lagi. File lama akan diganti saat dijalankan ulang.
    raw_file = data_folder / "raw_data.txt"

    raw_file.write_text(
        response.text,
        encoding="utf-8",
    )

    print("HTML mentah disimpan di:", raw_file.resolve())


    # List menjaga urutan tautan, set membantu mengecek alamat yang sudah ditemukan.
    candidate_links = []
    seen_links = set()

    # Periksa alamat tujuan dari setiap elemen tautan.
    for link in soup.select("a[href]"):
        href = link.get("href", "").strip()

        # Ambil calon tautan di bawah /loker/. Tautan kategori bisa ikut masuk.
        is_candidate = (
            href.startswith("/loker/")
            or href.startswith("https://dealls.com/loker/")
        )

        # Simpan sekali untuk setiap href yang sama persis.
        if is_candidate and href not in seen_links:
            seen_links.add(href)
            candidate_links.append(href)

    # Jumlah ini masih calon tautan, belum jumlah lowongan yang terverifikasi.
    print("\nJumlah calon tautan unik:", len(candidate_links))

    # Batasi tampilan ke 15 tautan pertama agar mudah diperiksa di terminal.
    for number, href in enumerate(candidate_links[:15], start=1):
        print(f"{number}. {href}")


except requests.exceptions.Timeout:
    print("Website tidak merespons dalam batas waktu.")

except requests.exceptions.HTTPError as error:
    print("Server memberikan status kesalahan:", error)

except requests.exceptions.RequestException as error:
    print("Permintaan ke website gagal:", error)
