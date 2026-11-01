# SoilWatch ID

Implementasi skripsi: estimasi *soil moisture* bulanan per kabupaten/kota (Random Forest, XGBoost, model gabungan, SHAP) beserta aplikasi webnya.

## Struktur

```
soilwatch/
├─ data/
│  ├─ raw/          dataset asli 2023–2026 (xls atau csv)
│  ├─ processed/    dataset_bersih.csv (hasil script 01)
│  └─ geo/          batas wilayah untuk peta
├─ scripts/
│  ├─ config.py                      daftar fitur, pembagian waktu, 7 kelompok wilayah
│  ├─ umum.py                        fungsi bersama: metrik, 5-fold time-series CV, alur pelatihan
│  ├─ 01_cek_dan_praproses.py        cek ulang data + pra-pemrosesan
│  ├─ 02_gee_penanda_lahan_colab.py  (Colab) proporsi gambut, badan air, pertanian + batas GAUL
│  ├─ 03_latih_rf.py                 Random Forest nasional + 7 regional
│  ├─ 04_latih_xgb.py                XGBoost nasional + 7 regional
│  ├─ 05_gabungan_evaluasi.py        bobot gabungan (11 bobot), evaluasi, aturan 10%, model terpilih
│  ├─ 06_shap.py                     SHAP global + cek pola + grafik untuk laporan
│  ├─ 07_peta_beranda.py             peta pratinjau + angka ringkas untuk Beranda
│  ├─ 08_data_web.py                 basis data SQLite + peta interaktif untuk aplikasi web
│  └─ peta.py                        fungsi bersama daftar wilayah dan peta (GAUL jika ada, GADM jika belum)
├─ models/          model .joblib hasil pelatihan
├─ reports/         laporan data, hasil tuning, evaluasi, perbandingan nasional vs regional
└─ app/             aplikasi web Flask
   ├─ app.py        rute halaman
   ├─ estimasi.py   memuat model RF, kategori, data grafik
   ├─ data/         soilwatch.db: basis data SQLite (hasil script 08)
   ├─ templates/    beranda, prediksi, otomatis, simulasi, hasil, informasi
   └─ static/       css, js, gambar, data peta
```

## Urutan menjalankan

```bash
pip install pandas numpy scikit-learn joblib flask xgboost shap matplotlib
python scripts/01_cek_dan_praproses.py   # beberapa detik
python scripts/03_latih_rf.py            # 10-40 menit
python scripts/04_latih_xgb.py           # 10-30 menit
python scripts/05_gabungan_evaluasi.py   # beberapa detik
python scripts/06_shap.py                # beberapa menit (sampel 1.000 baris data uji)
python scripts/07_peta_beranda.py
python scripts/08_data_web.py
python app/app.py                        # buka http://127.0.0.1:5000
```

Script 02 dijalankan di Google Colab (butuh akun Earth Engine). Hasilnya
(`penanda_lahan_kabkota.csv`, `batas_kabkota_gaul2015.geojson`, `badan_air_besar.geojson`, dan
`sebaran_gambut.geojson` jika aset gambut diisi) disimpan ke `data/geo/`,
lalu jalankan ulang script 05, 07, dan 08 (tanpa perlu melatih ulang model).
Peta otomatis memakai batas GAUL 2015 (442 wilayah), serta menampilkan bentuk asli danau/waduk besar
(diberi nama dari daftar acuan di scripts/peta.py) dan sebaran gambut, begitu file-file tersebut ada.

## Status (tahap 4)

- Pelatihan lengkap: RF (03), XGBoost (04), gabungan + evaluasi + pemilihan model (05), SHAP (06).
- Aplikasi membaca data dari basis data SQLite `app/data/soilwatch.db` (dibuat script 08),
  sesuai Arsitektur Data di Bab 1. Peta Mode Otomatis diambil dari `/api/peta`.
- Beranda berisi panduan singkat; halaman Informasi berisi teknologi yang digunakan.
- Menunggu hasil GEE (script 02): penanda lahan asli dan batas peta GAUL 442 wilayah.
