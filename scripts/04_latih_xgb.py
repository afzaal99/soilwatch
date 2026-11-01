"""
04 - Pelatihan XGBoost nasional dan regional (Subbab 2.2.2.2 dan 2.2.3.4)
==========================================================================
Masukan : data/processed/dataset_bersih.csv  (hasil script 01)
Keluaran: models/xgb_nasional.joblib, models/xgb_<kelompok>.joblib   (8 model)
          reports/04_tuning_xgb.csv, 04_evaluasi_xgb.csv, 04_nasional_vs_regional_xgb.csv,
          reports/04_prediksi_uji_xgb.csv, 04_oof_xgb.csv, 04_gain_xgb_nasional.csv, 04_log_xgb.txt

Skema pembagian data, tuning, dan skenario nasional/regional sama persis dengan script 03,
sehingga RF dan XGBoost dibandingkan secara adil.

Hyperparameter yang disetel (Subbab 2.2.2.2): n_estimators, learning_rate, max_depth,
min_child_weight, subsample, colsample_bytree.

Perlu: pip install xgboost
Perkiraan waktu: 10-30 menit.
"""
import sys
from pathlib import Path

import pandas as pd
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).parent))
from config import FITUR
from umum import SEED, jalankan_pelatihan

GRID = {
    "n_estimators": [300, 600],
    "learning_rate": [0.05, 0.1],
    "max_depth": [4, 6, 8],
    "min_child_weight": [1, 5],
    "subsample": [0.8],
    "colsample_bytree": [0.8],
}


def buat_model(prm):
    return XGBRegressor(objective="reg:squarederror", tree_method="hist",
                        random_state=SEED, n_jobs=-1, **prm)


def simpan_gain(model, reports):
    gain = model.get_booster().get_score(importance_type="gain")
    pd.DataFrame({"variabel": FITUR, "gain": [gain.get(f, 0.0) for f in FITUR]}) \
        .assign(gain_persen=lambda d: 100 * d["gain"] / d["gain"].sum()) \
        .sort_values("gain", ascending=False).to_csv(reports / "04_gain_xgb_nasional.csv", index=False)


if __name__ == "__main__":
    jalankan_pelatihan("xgb", "XGBoost", "04", GRID, buat_model, simpan_gain)
