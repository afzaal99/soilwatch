# SoilWatch ID

Implementasi skripsi: estimasi *soil moisture* bulanan per kabupaten/kota di Indonesia (Random Forest, XGBoost,
model gabungan, SHAP) beserta aplikasi webnya. Aplikasi mencakup 514 kabupaten/kota (batas FAO GAUL 2025),
dilengkapi informasi pH tanah dan kesesuaian tanaman, serta dashboard admin untuk memperbarui data dan model.

Panduan pemakaian aplikasi: [`reports/ManualBook_SoilWatchID.pdf`](reports/ManualBook_SoilWatchID.pdf).

## Struktur

```
soilwatch/
├─ data/
│  ├─ raw/          dataset asli Januari 2023 – Juni 2026 (hasil script 09)
│  ├─ processed/    dataset_bersih.csv (hasil script 01)
│  └─ geo/          batas wilayah GAUL 2025, penanda lahan, danau/waduk besar, data gambut Trase
├─ scripts/
│  ├─ config.py                      daftar fitur, pembagian waktu, 7 kelompok wilayah
│  ├─ umum.py                        fungsi bersama: metrik, 5-fold time-series CV, alur pelatihan
│  ├─ 01_cek_dan_praproses.py        cek ulang data + pra-pemrosesan
│  ├─ 02_gee_penanda_lahan_colab.py  (Colab) proporsi badan air, pertanian + batas GAUL 2025
│  ├─ 02b_gambut_trase.py            proporsi lahan gambut per wilayah (Peta Lahan Gambut Kementan 2019, via Trase)
│  ├─ 03_latih_rf.py                 Random Forest nasional + 7 regional
│  ├─ 04_latih_xgb.py                XGBoost nasional + 7 regional
│  ├─ 05_gabungan_evaluasi.py        bobot gabungan (11 bobot), evaluasi, aturan 10%, model terpilih
│  ├─ 06_shap.py                     SHAP global + cek pola + grafik untuk laporan
│  ├─ 07_peta_beranda.py             peta pratinjau + angka ringkas untuk Beranda
│  ├─ 08_data_web.py                 basis data SQLite + peta interaktif untuk aplikasi web
│  ├─ 09_gee_ekstraksi_bulanan.js    (GEE) ekstraksi 12 variabel bulanan: dataset penelitian dan data bulan baru
│  ├─ 10_gee_ph_tanah.js             (GEE) pH tanah 0–30 cm per kabupaten/kota (OpenLandMap)
│  ├─ buat_admin.py                  membuat atau mengganti akun admin (.env)
│  ├─ cek_mae.py                     diagnostik perbandingan MAE model
│  └─ peta.py                        fungsi bersama daftar wilayah dan peta
├─ models/          model .joblib hasil pelatihan + model_terpilih.json (konfigurasi dan metrik model aktif)
├─ reports/         laporan data, hasil tuning, evaluasi, SHAP, dan manual book
├─ api/             titik masuk deploy (Vercel)
└─ app/             aplikasi web Flask
   ├─ app.py        rute halaman publik dan unduhan CSV
   ├─ admin.py      dashboard admin: unggah data, data pH, model, cadangan, riwayat
   ├─ estimasi.py   memuat model, estimasi, SHAP lokal, perbandingan aktual vs estimasi
   ├─ ph_tanah.py   pH tanah, kelas pH, kesesuaian tanaman, data pH lapangan
   ├─ pembaruan.py  validasi dan penyimpanan data bulan baru, cadangan basis data
   ├─ latih_ulang.py latih ulang model dari dashboard admin
   ├─ ringkasan.py  ringkasan kondisi wilayah dan berkas CSV unduhan
   ├─ data/         soilwatch.db (hasil script 08) dan ph_tanah.csv (hasil script 10)
   ├─ templates/    beranda, prediksi, otomatis, simulasi, hasil, informasi, admin/
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
python scripts/buat_admin.py             # sekali saja, untuk membuat akun admin
python app/app.py                        # buka http://127.0.0.1:5000 (admin: /admin)
```

Langkah yang dijalankan di luar komputer:

- **Script 09 (GEE Code Editor)** menghasilkan dataset 12 variabel bulanan untuk 514 kabupaten/kota. Simpan
  hasilnya di `data/raw/` sebelum menjalankan script 01. Script yang sama dipakai admin untuk mengambil data
  bulan baru (dashboard admin menyediakan script yang sudah terisi bulannya).
- **Script 02 (Google Colab)** menghasilkan `penanda_lahan_kabkota.csv`, `batas_kabkota_gaul2025.geojson`, dan
  `badan_air_besar.geojson` di `data/geo/`. Setelah itu jalankan **script 02b** untuk menambahkan proporsi
  lahan gambut, lalu ulangi script 05, 07, dan 08 (tanpa perlu melatih ulang model).
- **Script 10 (GEE Code Editor)** menghasilkan `ph_tanah_kabkota.csv`. Simpan sebagai `app/data/ph_tanah.csv`.

Pembagian data: latih Januari 2023 – September 2025, uji Oktober 2025 – Juni 2026.
Model aktif: XGBoost (regional untuk Jawa dan Papua, nasional untuk kelompok lain menurut aturan 10%),
R² 0,800 dan MAE 0,0307 m³/m³ pada data uji.

## Fitur aplikasi

- **Beranda:** peta ringkas dan unduhan rata-rata tahunan seluruh kabupaten/kota.
- **Mode Otomatis:** peta interaktif *soil moisture* per bulan (SMAP L4, lapisan 0–5 cm), arsiran gambut,
  danau/waduk besar, dan pH tanah wilayah.
- **Mode Simulasi:** estimasi dari nilai variabel yang diisi sendiri.
- **Halaman hasil**, berurutan:
  1. estimasi, penjelasan SHAP lokal, dan faktor paling berpengaruh secara umum;
  2. tren dan riwayat wilayah, ringkasan kondisi, pola bulanan, unduh CSV, dan cetak;
  3. perbandingan nilai aktual (SMAP L4) dan estimasi model per bulan;
  4. pH tanah dan kesesuaian tanaman: pH lapisan olah 0–30 cm, kelas pH, tanaman sangat sesuai (S1) dan
     cukup sesuai (S2), arahan penyesuaian pH, serta grafik pH bulanan bila tersedia data uji tanah lapangan.
- **Informasi:** data dan metode, tabel akurasi 16 model beserta aturan 10%, batasan, dan pertanyaan umum.

## Dashboard admin (`/admin`)

- **Dashboard:** pemantauan akurasi per bulan, riwayat aktivitas (dan halaman riwayat lengkap), status latih ulang.
- **Unggah Data:** pembuat script GEE 09, unggah CSV bulan baru (wajib berurutan), pratinjau dan validasi
  sebelum disimpan, serta tombol batal.
- **Data pH:** templat CSV per bulan (514 wilayah, urut Sabang–Merauke), unggah beberapa berkas sekaligus,
  hapus per bulan atau semua, dan kembalikan data sebelum perubahan terakhir.
- **Model:** latih ulang dengan data terbaru, bandingkan dengan model aktif, pakai atau kembalikan model.
- **Cadangan:** salinan basis data otomatis sebelum setiap perubahan (maksimal 12), dapat dipulihkan.
- Keamanan: kata sandi disimpan sebagai hash, batas percobaan masuk, token formulir, dan keluar otomatis
  setelah 1 jam tidak aktif.

## Sumber data

SMAP L4 (*soil moisture*), CHIRPS (curah hujan), ERA5-Land (suhu, titik embun, radiasi, angin, suhu tanah),
MODIS (NDVI, LST), SRTM (elevasi, kemiringan), OpenLandMap (kandungan liat; pH tanah, Hengl 2018),
ESA WorldCover (badan air, pertanian), Peta Lahan Gambut Kementan 2019 (via Trase), FAO GAUL 2025 (batas wilayah).
Kelas pH menurut Eviati & Sulaeman (2009), Balai Penelitian Tanah (kini Balai Perakitan dan Pengujian Tanah
dan Pupuk); kesesuaian tanaman menurut Ritung dkk. (2011).

## Berkas yang tidak disimpan di GitHub

- `.env`: akun admin dan kunci sesi. Buat dengan `python scripts/buat_admin.py`.
- `models/rf_nasional.joblib`: model Random Forest nasional (107 MB, melebihi batas GitHub 100 MB).
  Model aktif (XGBoost) tidak memerlukannya. Buat ulang dengan script 03 bila diperlukan.
- `instance/`: cadangan basis data, berkas sementara, dan arsip model yang dibuat saat aplikasi berjalan.
- `app/data/ph_lapangan*.csv`: data pH uji tanah lapangan yang diisi admin langsung di aplikasi yang berjalan.
