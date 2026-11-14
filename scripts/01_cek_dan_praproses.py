"""
01 - Cek ulang dan pra-pemrosesan dataset soil moisture (Subbab 2.2.1.11)
=========================================================================
Masukan : data/raw/SoilMoisture_*.csv (hasil script 09, GAUL 2025)
          atau data/raw/Dataset_SoilMoisture_{2023..2026}_with_RH.(xls|csv) (dataset lama, GAUL 2015)
Keluaran: data/processed/dataset_bersih.csv
          reports/01_laporan_data.txt

Langkah:
1. Gabung 4 file, cek kunci (wilayah x bulan), duplikat, kelengkapan panel.
2. Cek variabel statis (elevasi, lereng, liat) dan rumus kelembapan relatif.
3. Tandai artefak radiasi matahari (< 50% median wilayahnya) sebagai nilai hilang.
4. Aturan missing value: wilayah dengan > 30% nilai hilang dikeluarkan,
   sisanya diisi interpolasi temporal per wilayah.
5. Kandidat outlier IQR dihitung (dari data latih) dan divalidasi batas fisik;
   nilai yang lolos batas fisik dipertahankan.
6. Tambahkan kolom periode, kelompok wilayah, dan penanda latih/uji.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import (AKHIR_DATA, AKHIR_LATIH, DATA_PROCESSED, DATA_RAW, FITUR, KEY,
                    PROV_KE_KELOMPOK, REPORTS, TARGET) # mengecek dri file confi.py

DATA_PROCESSED.mkdir(parents=True, exist_ok=True) # membuat folder data processed
REPORTS.mkdir(parents=True, exist_ok=True) # membuat folder reports
log = []


def tulis(s=""):
    print(s)
    log.append(str(s))


# ------------------------------------------------------------------ 1. gabung
# Hasil script 09 (GEE, batas GAUL 2025): data/raw/SoilMoisture_*.csv (misal SoilMoisture_2023_01_sd_2023_12.csv).
# Jika belum ada, dipakai file lama Dataset_SoilMoisture_{tahun}_with_RH (batas GAUL 2015).
frames = []
baru = sorted(DATA_RAW.glob("SoilMoisture_*.csv")) # mengambil folder dri data raw
if baru:
    for f in baru:
        d = pd.read_csv(f) # membaca setiap csv
        tulis(f"{f.name}: {len(d):,} baris, {d['ADM2_NAME'].nunique()} kabupaten/kota, "
              f"{d['tanggal'].nunique()} bulan")
        frames.append(d)
else:
    for th in [2023, 2024, 2025, 2026]:
        base = DATA_RAW / f"Dataset_SoilMoisture_{th}_with_RH"
        if base.with_suffix(".csv").exists():
            f = pd.read_csv(base.with_suffix(".csv"))
        else:
            f = pd.read_excel(base.with_suffix(".xls"))  # butuh xlrd (Colab: pip install xlrd)
        tulis(f"{th}: {len(f):,} baris, {f['ADM2_NAME'].nunique()} kabupaten/kota")
        frames.append(f)
df = pd.concat(frames, ignore_index=True) # menggabungkan ke empat file
df["periode"] = pd.to_datetime(df["tanggal"])
lewat = df["periode"] > AKHIR_DATA # membuang bulan setelah juni
if lewat.any():
    tulis(f"Diabaikan: {lewat.sum():,} baris setelah periode penelitian ({AKHIR_DATA[:7]}).")
    df = df[~lewat].copy()
n_wil = df.groupby(KEY).ngroups
n_bln = df["periode"].nunique()
tulis(f"\nTotal: {len(df):,} baris = {n_wil} kabupaten/kota x {n_bln} bulan " # cek jumlah wilayah, bulan dan duplikasi
      f"({df['periode'].min():%b %Y} - {df['periode'].max():%b %Y}), {df['ADM1_NAME'].nunique()} provinsi")
tulis(f"Duplikat (wilayah, bulan): {df.duplicated(KEY + ['periode']).sum()}")
lengkap = (df.groupby(KEY).size() == n_bln).all()
tulis(f"Panel lengkap (setiap wilayah punya {n_bln} bulan): {'ya' if lengkap else 'TIDAK'}")

# ------------------------------------------------------------------ 2. konsistensi
# mengecek konsistensi 3 variabel statis dalam setiap bulan
for v in ["elevation", "slope", "clay_content"]:
    rentang = df.groupby(KEY)[v].agg(lambda s: s.max() - s.min()).max()
    tulis(f"Variabel statis {v}: selisih maks antarbulan dalam satu wilayah = {rentang:.2e}")
# menghitung ulang RH
es = lambda T: 6.112 * np.exp(17.67 * T / (T + 243.5))
rh = 100 * es(df["dew_point_celsius"]) / es(df["suhu_celsius"])
tulis(f"Kelembapan relatif vs Persamaan (2.5)-(2.6): selisih maks = {(rh - df['relative_humidity']).abs().max():.1e}")

tulis("\nNilai hilang awal:")
for v in FITUR + [TARGET]:
    n = df[v].isna().sum() #mencatat nilai yg hilang
    if n:
        tulis(f"  {v}: {n} baris di {df.loc[df[v].isna(), 'ADM2_NAME'].nunique()} wilayah")

# ------------------------------------------------------------------ 3. artefak radiasi
med = df.groupby(KEY)["solar_radiation"].transform("median")
artefak = df["solar_radiation"] < 0.5 * med # radiasi yg kurang dri 50% dari median wilayahnya dianggap artefak dan akan di isi interpolasi
tulis(f"\nArtefak radiasi matahari (< 50% median wilayahnya): {artefak.sum()} baris di "
      f"{df.loc[artefak, 'ADM2_NAME'].nunique()} wilayah pesisir/pulau kecil -> dijadikan nilai hilang")
tulis("  wilayah: " + ", ".join(sorted(df.loc[artefak, "ADM2_NAME"].unique())))
df.loc[artefak, "solar_radiation"] = np.nan

# ------------------------------------------------------------------ 4. missing value
prop = df.groupby(KEY)[FITUR + [TARGET]].apply(lambda g: g.isna().mean().max())
keluar = prop[prop > 0.30].index.tolist()  # menghitung proporsi nilai hilang terbesar per wilayah, diatas 30% interpolasi
tulis(f"\nWilayah dengan > 30% nilai hilang (dikeluarkan): {len(keluar)}")
if keluar:
    df = df[~df.set_index(KEY).index.isin(keluar)].copy()
df = df.sort_values(KEY + ["periode"]).reset_index(drop=True)
sebelum = df[FITUR].isna().sum().sum()
df[FITUR] = (df.groupby(KEY)[FITUR]
             .transform(lambda s: s.interpolate(limit_direction="both"))) # di isi dari bulan sebelum dan sesudahnya
tulis(f"Nilai hilang diisi interpolasi temporal per wilayah: {sebelum} sel; sisa: {df[FITUR].isna().sum().sum()}")

# ------------------------------------------------------------------ 5. outlier
batas_fisik = {
    TARGET: (0, 1), "curah_hujan_bulanan": (0, None), "ndvi": (-1, 1),  # batas fisik soil moisture
    "relative_humidity": (0, 100), "wind_speed": (0, None), "solar_radiation": (0, None),
    "slope": (0, 90), "clay_content": (0, 100),
}
latih = df["periode"] <= AKHIR_LATIH
tulis("\nKandidat outlier IQR (kuartil dari data latih) dan validasi batas fisik:")
for v in FITUR + [TARGET]:
    # Kandidat outlier IQR dihitung dari kuartil data latih saja (mencegah kebocoran data), lalu dicek terhadap batas fisik. Tidak ada yang melanggar, sehingga semua dipertahankan.
    q1, q3 = df.loc[latih, v].quantile([0.25, 0.75])
    iqr = q3 - q1
    kand = ((df[v] < q1 - 1.5 * iqr) | (df[v] > q3 + 1.5 * iqr)).sum()
    lo, hi = batas_fisik.get(v, (None, None))
    salah = 0
    if lo is not None:
        salah += (df[v] < lo).sum()
    if hi is not None:
        salah += (df[v] > hi).sum()
    tulis(f"  {v:22s} kandidat {kand:5d}  melanggar batas fisik {salah}")
tulis("  -> Kandidat yang tidak melanggar batas fisik dianggap kondisi nyata (mis. curah hujan puncak\n"
      "     musim hujan, lahan gambut yang sangat basah) dan dipertahankan, sesuai Subbab 2.2.1.11.")

# ------------------------------------------------------------------ 6. kolom tambahan
df["kelompok_wilayah"] = df["ADM1_NAME"].map(PROV_KE_KELOMPOK)  # memberikan kelompok wilayah
assert df["kelompok_wilayah"].notna().all(), "ada provinsi yang belum masuk kelompok"
df["subset"] = np.where(latih, "latih", "uji") # data latih 33 bulan
tulis("\nJumlah kabupaten/kota per kelompok wilayah:")
tulis(df.groupby("kelompok_wilayah")["ADM2_NAME"].nunique().to_string())
tulis(f"\nData latih: {latih.sum():,} baris ({df.loc[latih, 'periode'].nunique()} bulan); "
      f"data uji: {(~latih).sum():,} baris ({df.loc[~latih, 'periode'].nunique()} bulan)")

kolom = KEY + ["kelompok_wilayah", "periode", "tahun", "bulan", "subset"] + FITUR + [TARGET]
df[kolom].to_csv(DATA_PROCESSED / "dataset_bersih.csv", index=False)  # Menyimpan hasil ke data/processed/dataset_bersih.csv. Inilah masukan script 03, 04, 05, dan 06.
(REPORTS / "01_laporan_data.txt").write_text("\n".join(log), encoding="utf-8")
tulis(f"\nTersimpan: {DATA_PROCESSED / 'dataset_bersih.csv'}")
