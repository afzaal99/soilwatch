"""
03 - Pelatihan Random Forest nasional dan regional (Subbab 2.2.2.1 dan 2.2.3.4)
================================================================================
Masukan : data/processed/dataset_bersih.csv  (hasil script 01)
Keluaran: models/rf_nasional.joblib, models/rf_<kelompok>.joblib   (8 model)
          reports/03_tuning_rf.csv        hasil 5-fold time-series CV setiap kombinasi parameter
          reports/03_evaluasi_rf.csv      R2, MAE, RMSE pada data uji
          reports/03_nasional_vs_regional_rf.csv  aturan 10% RMSE (khusus RF)
          reports/03_prediksi_uji_rf.csv  prediksi per kabupaten/kota per bulan uji
          reports/03_oof_rf.csv           prediksi validasi CV (untuk bobot gabungan di script 05)
          reports/03_mdi_rf_nasional.csv  feature importance MDI (pembanding SHAP)
          reports/03_log_rf.txt

Skema:
- Data latih Jan 2023 - Sep 2025 (33 bulan), data uji Okt 2025 - Jun 2026 (9 bulan).
- Tuning: 5-fold time-series cross-validation berdasarkan urutan bulan (expanding window)
  di dalam data latih; kriteria = rata-rata RMSE terkecil.
- 1 model nasional + 7 model regional.

Perkiraan waktu: 10-40 menit tergantung jumlah core CPU.
"""
import sys
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor

sys.path.insert(0, str(Path(__file__).parent))
from config import FITUR
from umum import SEED, jalankan_pelatihan

N_TREES = 300
GRID = {
    "max_depth": [None, 20, 10],
    "min_samples_leaf": [1, 5],
    "max_features": [1 / 3, 0.5, 1.0],
}


def buat_model(prm):
    return RandomForestRegressor(n_estimators=N_TREES, random_state=SEED, n_jobs=-1, **prm)


def simpan_mdi(model, reports):
    pd.DataFrame({"variabel": FITUR, "mdi": model.feature_importances_}) \
        .sort_values("mdi", ascending=False).to_csv(reports / "03_mdi_rf_nasional.csv", index=False)


if __name__ == "__main__":
    jalankan_pelatihan("rf", "RF", "03", GRID, buat_model, simpan_mdi)
