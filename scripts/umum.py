"""Fungsi bersama untuk script pelatihan (03 RF, 04 XGBoost, 05 gabungan, 06 SHAP)."""
import itertools
import time

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from config import DATA_PROCESSED, FITUR, TARGET

SEED = 42


def muat_data():
    # memisahkan data latih dam uji 
    """Data bersih hasil script 01, dipisah menjadi data latih dan data uji."""
    df = pd.read_csv(DATA_PROCESSED / "dataset_bersih.csv", parse_dates=["periode"])
    latih = df[df["subset"] == "latih"].reset_index(drop=True)
    uji = df[df["subset"] == "uji"].reset_index(drop=True)
    return latih, uji


def metrik(y, p):
    # menghitung R2 dan RMSE
    y, p = np.asarray(y), np.asarray(p)
    return {"R2": r2_score(y, p), "MAE": mean_absolute_error(y, p),
            "RMSE": float(np.sqrt(mean_squared_error(y, p))), "n": len(y)}


def rmse(y, p):
    return float(np.sqrt(mean_squared_error(y, p)))


def nama_file(kelompok):
    """'Bali-Nusa Tenggara' -> 'bali_nusa_tenggara' (dipakai untuk nama file model)."""
    return kelompok.lower().replace(" ", "_").replace("-", "_")


def lipatan_waktu(periode, k=5):
    # 
    """5-fold time-series CV: bulan diurutkan, lalu dibagi k+1 blok berurutan.
    Lipatan ke-i melatih blok 1..i dan memvalidasi blok i+1 (expanding window)."""
    bulan = np.sort(periode.unique())
    blok = np.array_split(bulan, k + 1)
    for i in range(1, k + 1):
        latih_b = np.concatenate(blok[:i])
        val_b = blok[i]
        yield i, periode.isin(latih_b).values, periode.isin(val_b).values


def tuning(df_latih, label, grid, buat_model, log=print):
    """Grid search dengan 5-fold time-series CV.

    buat_model(prm) harus mengembalikan model baru yang belum dilatih.
    Mengembalikan:
      tabel  : rata-rata dan simpangan RMSE CV setiap kombinasi parameter
      terbaik: kombinasi dengan rata-rata RMSE CV terkecil
      oof    : prediksi validasi (out-of-fold) kombinasi terbaik, dipakai script 05
               untuk memilih bobot model gabungan tanpa menyentuh data uji
    """
    hasil, t0 = [], time.time()
    terbaik, rmse_terbaik, oof_terbaik = None, np.inf, None
    kombinasi = list(itertools.product(*grid.values()))
    for n, v in enumerate(kombinasi, 1):
        prm = dict(zip(grid, v))
        skor, oof = [], []
        for i, tr, va in lipatan_waktu(df_latih["periode"]):
            m = buat_model(prm)
            m.fit(df_latih.loc[tr, FITUR], df_latih.loc[tr, TARGET])
            p = m.predict(df_latih.loc[va, FITUR])
            skor.append(rmse(df_latih.loc[va, TARGET], p))
            oof.append(pd.DataFrame({"baris": np.flatnonzero(va), "lipatan": i, "pred": p}))
        hasil.append({"model": label, **{k: str(x) for k, x in prm.items()},
                      "rmse_cv_rata2": np.mean(skor), "rmse_cv_std": np.std(skor)})
        if np.mean(skor) < rmse_terbaik:
            terbaik, rmse_terbaik, oof_terbaik = prm, np.mean(skor), pd.concat(oof)
        log(f"  {label}: kombinasi {n}/{len(kombinasi)} selesai ({time.time() - t0:.0f} s)")
    return pd.DataFrame(hasil).sort_values("rmse_cv_rata2"), terbaik, oof_terbaik


def jalankan_pelatihan(kode, label, nomor, grid, buat_model, simpan_importance=None):
    """Alur pelatihan yang sama untuk RF (script 03) dan XGBoost (script 04).

    kode  : "rf" atau "xgb" (awalan nama file model dan kolom prediksi)
    label : "RF" atau "XGBoost" (dipakai di laporan)
    nomor : "03" atau "04" (awalan nama file laporan)

    Skenario 1: model nasional dilatih dengan seluruh Indonesia, dievaluasi nasional dan per kelompok.
    Skenario 2: satu model per kelompok wilayah, dilatih dan diuji pada kelompoknya sendiri.
    """
    import joblib
    from config import KELOMPOK, MODELS, REPORTS

    MODELS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    catatan = []

    def log(s=""):
        print(s, flush=True)
        catatan.append(str(s))

    t0 = time.time()
    latih, uji = muat_data()
    log(f"{label}: latih {len(latih):,} baris, uji {len(uji):,} baris")
    semua_tuning, evaluasi, semua_oof = [], [], []

    def simpan(model, prm, nama):
        joblib.dump({"model": model, "fitur": FITUR, "parameter": prm, "jenis": kode},
                    MODELS / f"{kode}_{nama}.joblib", compress=3)

    # ---------------- skenario 1: nasional
    tab, prm, oof = tuning(latih, f"{label} nasional", grid, buat_model, log)
    semua_tuning.append(tab)
    oof["cakupan"] = "nasional"
    oof["baris_latih"] = oof["baris"]
    semua_oof.append(oof)
    log(f"[nasional] parameter terbaik {prm}  RMSE CV {tab.iloc[0]['rmse_cv_rata2']:.4f}  ({time.time()-t0:.0f} s)")
    m_nas = buat_model(prm)
    m_nas.fit(latih[FITUR], latih[TARGET])
    simpan(m_nas, prm, "nasional")
    kol_nas, kol_reg = f"pred_{kode}_nasional", f"pred_{kode}_regional"
    uji[kol_nas] = m_nas.predict(uji[FITUR])
    evaluasi.append({"model": f"{label} nasional", "dievaluasi_pada": "Indonesia",
                     **metrik(uji[TARGET], uji[kol_nas])})
    for kel, g in uji.groupby("kelompok_wilayah"):
        evaluasi.append({"model": f"{label} nasional", "dievaluasi_pada": kel,
                         **metrik(g[TARGET], g[kol_nas])})
    if simpan_importance:
        simpan_importance(m_nas, REPORTS)

    # ---------------- skenario 2: regional
    uji[kol_reg] = np.nan
    for kel in KELOMPOK:
        idx_latih = np.flatnonzero(latih["kelompok_wilayah"].values == kel)
        lt = latih.iloc[idx_latih].reset_index(drop=True)
        uj_idx = uji["kelompok_wilayah"] == kel
        tab, prm, oof = tuning(lt, f"{label} regional {kel}", grid, buat_model, log)
        semua_tuning.append(tab)
        oof["cakupan"] = kel
        oof["baris_latih"] = idx_latih[oof["baris"].values]   # indeks pada seluruh data latih
        semua_oof.append(oof)
        m = buat_model(prm)
        m.fit(lt[FITUR], lt[TARGET])
        simpan(m, prm, nama_file(kel))
        uji.loc[uj_idx, kol_reg] = m.predict(uji.loc[uj_idx, FITUR])
        evaluasi.append({"model": f"{label} regional", "dievaluasi_pada": kel,
                         **metrik(uji.loc[uj_idx, TARGET], uji.loc[uj_idx, kol_reg])})
        log(f"[{kel}] parameter terbaik {prm}  RMSE CV {tab.iloc[0]['rmse_cv_rata2']:.4f}  ({time.time()-t0:.0f} s)")

    ev = pd.DataFrame(evaluasi)
    ev.to_csv(REPORTS / f"{nomor}_evaluasi_{kode}.csv", index=False)
    pd.concat(semua_tuning).to_csv(REPORTS / f"{nomor}_tuning_{kode}.csv", index=False)

    # prediksi validasi (out-of-fold) untuk memilih bobot model gabungan di script 05
    oof = pd.concat(semua_oof)
    oof = oof.assign(periode=latih.loc[oof["baris_latih"], "periode"].values,
                     aktual=latih.loc[oof["baris_latih"], TARGET].values)
    oof[["cakupan", "lipatan", "baris_latih", "periode", "aktual", "pred"]] \
        .to_csv(REPORTS / f"{nomor}_oof_{kode}.csv", index=False)

    # aturan 10% RMSE (perbandingan awal untuk pendekatan ini saja; keputusan akhir di script 05)
    nas = ev[ev["model"] == f"{label} nasional"].set_index("dievaluasi_pada")
    reg = ev[ev["model"] == f"{label} regional"].set_index("dievaluasi_pada")
    banding = pd.DataFrame({"rmse_nasional": nas.loc[reg.index, "RMSE"], "rmse_regional": reg["RMSE"]})
    banding["selisih_%"] = 100 * (banding["rmse_nasional"] / banding["rmse_regional"] - 1)
    banding["model_dipakai"] = np.where(banding["selisih_%"] <= 10, "nasional", "regional")
    banding.round(4).to_csv(REPORTS / f"{nomor}_nasional_vs_regional_{kode}.csv")

    kol = ["ADM2_NAME", "ADM1_NAME", "kelompok_wilayah", "periode", TARGET, kol_nas, kol_reg]
    uji[kol].to_csv(REPORTS / f"{nomor}_prediksi_uji_{kode}.csv", index=False)

    log("\nEvaluasi pada data uji:")
    log(ev.round(4).to_string(index=False))
    log("\nNasional vs regional (aturan 10% RMSE):")
    log(banding.round(4).to_string())
    log(f"\nSelesai dalam {time.time()-t0:.0f} s")
    (REPORTS / f"{nomor}_log_{kode}.txt").write_text("\n".join(catatan), encoding="utf-8")
