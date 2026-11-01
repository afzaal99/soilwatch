"""Konfigurasi bersama untuk seluruh script SoilWatch ID."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"

KEY = ["ADM2_NAME", "ADM1_NAME"]
TARGET = "soil_moisture"
FITUR = [
    "curah_hujan_bulanan", "suhu_celsius", "dew_point_celsius", "ndvi",
    "lst_celsius", "elevation", "slope", "solar_radiation", "wind_speed",
    "clay_content", "soil_temperature", "relative_humidity",
]

# Pembagian temporal (Subbab 2.2.1.11): 33 bulan latih, 9 bulan uji
AKHIR_LATIH = "2025-09-01"   # Jan 2023 - Sep 2025
AWAL_UJI = "2025-10-01"      # Okt 2025 - Jun 2026
AKHIR_DATA = "2026-06-01"    # batas akhir periode penelitian (bulan setelahnya diabaikan oleh script 01)

# Tujuh kelompok wilayah (Subbab 2.2.3.4), dipetakan dari nama provinsi di data
# (FAO GAUL 2025: 38 provinsi, 514 kabupaten/kota, termasuk 4 provinsi baru di Papua)
KELOMPOK = {
    "Sumatera": ["Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Kepulauan Riau", "Jambi",
                 "Sumatera Selatan", "Kepulauan Bangka Belitung", "Bengkulu", "Lampung"],
    "Jawa": ["Dki Jakarta", "Banten", "Jawa Barat", "Jawa Tengah", "Daerah Istimewa Yogyakarta", "Jawa Timur"],
    "Bali-Nusa Tenggara": ["Bali", "Nusa Tenggara Barat", "Nusa Tenggara Timur"],
    "Kalimantan": ["Kalimantan Barat", "Kalimantan Tengah", "Kalimantan Selatan", "Kalimantan Timur",
                   "Kalimantan Utara"],
    "Sulawesi": ["Sulawesi Utara", "Gorontalo", "Sulawesi Tengah", "Sulawesi Barat", "Sulawesi Selatan",
                 "Sulawesi Tenggara"],
    "Maluku": ["Maluku", "Maluku Utara"],
    "Papua": ["Papua", "Papua Barat", "Papua Barat Daya", "Papua Tengah", "Papua Pegunungan", "Papua Selatan"],
}
PROV_KE_KELOMPOK = {p: k for k, ps in KELOMPOK.items() for p in ps}

# Nama variabel dalam bahasa Indonesia untuk grafik dan laporan
LABEL_FITUR = {
    "curah_hujan_bulanan": "Curah hujan", "suhu_celsius": "Suhu udara",
    "dew_point_celsius": "Suhu titik embun", "ndvi": "NDVI", "lst_celsius": "LST",
    "elevation": "Elevasi", "slope": "Kemiringan lereng", "solar_radiation": "Radiasi matahari",
    "wind_speed": "Kecepatan angin", "clay_content": "Kandungan liat",
    "soil_temperature": "Suhu tanah", "relative_humidity": "Kelembapan relatif",
}
