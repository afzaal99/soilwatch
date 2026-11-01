"""
06 - Interpretasi model terbaik dengan SHAP (Subbab 2.2.4)
===========================================================
Masukan : models/model_terpilih.json (hasil script 05) dan model .joblib terkait, data uji
Keluaran: reports/06_shap_global.csv               rata-rata |SHAP| per variabel (Global Feature Importance)
          reports/06_shap_global_per_kelompok.csv  idem, per kelompok wilayah
          reports/06_shap_nilai_sampel.csv         nilai SHAP setiap baris sampel (untuk analisis lanjut)
          reports/06_cek_pola.csv                  pemeriksaan arah pengaruh SHAP vs pola data asli
          reports/06_shap_global_bar.png           grafik batang kepentingan global
          reports/06_shap_beeswarm.png             grafik beeswarm (sebaran SHAP per variabel)
          reports/06_shap_lokal_contoh.png         contoh waterfall satu estimasi
          reports/06_log_shap.txt

Cara kerja:
- SHAP dihitung pada DATA UJI, memakai model yang sama dengan yang dipakai aplikasi
  (nasional atau regional per kelompok, sesuai model_terpilih.json).
- XGBoost: TreeSHAP bawaan XGBoost (pred_contribs). RF: shap.TreeExplainer.
- Model gabungan: karena prediksi gabungan = w x RF + (1 - w) x XGB dan SHAP bersifat aditif,
  nilai SHAP gabungan = w x SHAP_RF + (1 - w) x SHAP_XGB, dan nilai dasar juga digabung dengan bobot yang sama.
  Script memeriksa bahwa nilai dasar + jumlah SHAP = prediksi (sifat aditif).
- TreeSHAP untuk Random Forest dengan pohon dalam cukup lambat, sehingga secara bawaan dipakai
  sampel acak 1.000 baris data uji yang proporsional per kelompok wilayah. Ubah dengan argumen, misal:
      python scripts/06_shap.py 3978     (seluruh data uji)
      python scripts/06_shap.py 300      (uji coba cepat)

Perlu: pip install shap xgboost matplotlib
"""
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import FITUR, LABEL_FITUR, MODELS, REPORTS, TARGET
from umum import SEED, muat_data, nama_file

SAMPEL = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
catatan = []


def log(s=""):
    print(s, flush=True)
    catatan.append(str(s))


_cache = {}


def muat(jenis, cakupan):
    kunci = (jenis, cakupan)
    if kunci not in _cache:
        nama = "nasional" if cakupan == "nasional" else nama_file(cakupan)
        _cache[kunci] = joblib.load(MODELS / f"{jenis}_{nama}.joblib")
    return _cache[kunci]


def shap_satu_model(obj, X):
    """Mengembalikan (nilai_dasar, matriks SHAP n x p, prediksi)."""
    m = obj["model"]
    X = X[obj["fitur"]]
    if obj.get("jenis") == "xgb":
        import xgboost as xgb
        kontrib = m.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)
        return float(kontrib[0, -1]), kontrib[:, :-1], m.predict(X)
    import shap
    ex = shap.TreeExplainer(m)
    sv = np.asarray(ex.shap_values(X, check_additivity=False))
    return float(np.ravel(ex.expected_value)[0]), sv, m.predict(X)


def ambil_sampel(uji):
    if SAMPEL >= len(uji):
        return uji.copy()
    return (uji.groupby("kelompok_wilayah").sample(frac=SAMPEL / len(uji), random_state=SEED)
            .reset_index(drop=True))


def main():
    t0 = time.time()
    f_konf = MODELS / "model_terpilih.json"
    if not f_konf.exists():
        raise SystemExit("models/model_terpilih.json belum ada. Jalankan script 05 terlebih dahulu.")
    konf = json.loads(f_konf.read_text(encoding="utf-8"))
    log(f"Model terbaik: {konf['pendekatan']}")

    _, uji = muat_data()
    s = ambil_sampel(uji)
    log(f"SHAP dihitung pada {len(s):,} baris data uji (dari {len(uji):,})")

    s["cakupan"] = [("nasional" if konf["per_kelompok"][k] == "nasional" else k) for k in s["kelompok_wilayah"]]
    SV = np.zeros((len(s), len(FITUR)))
    s["nilai_dasar"], s["prediksi"] = np.nan, np.nan
    for cak, idx in s.groupby("cakupan").groups.items():
        idx = np.asarray(list(idx))
        w = konf["bobot_rf"][cak]
        X = s.loc[idx, FITUR]
        base, sv, pred = 0.0, np.zeros((len(idx), len(FITUR))), np.zeros(len(idx))
        for jenis, bobot in [("rf", w), ("xgb", 1 - w)]:
            if bobot <= 0:
                continue
            t1 = time.time()
            b, v, p = shap_satu_model(muat(jenis, cak), X)
            base, sv, pred = base + bobot * b, sv + bobot * v, pred + bobot * p
            log(f"  {cak:20s} {jenis.upper():3s} bobot {bobot:.1f}: {len(idx)} baris, {time.time() - t1:.0f} s")
        SV[idx] = sv
        s.loc[idx, "nilai_dasar"] = base
        s.loc[idx, "prediksi"] = pred

    galat = np.abs(s["nilai_dasar"] + SV.sum(1) - s["prediksi"]).max()
    log(f"Pemeriksaan aditif: |nilai dasar + jumlah SHAP - prediksi| maks = {galat:.2e}")

    # ---------------- Global Feature Importance
    rata = np.abs(SV).mean(0)
    glob = pd.DataFrame({"variabel": FITUR, "label": [LABEL_FITUR[f] for f in FITUR],
                         "mean_abs_shap": rata, "persen": 100 * rata / rata.sum()}) \
        .sort_values("mean_abs_shap", ascending=False)
    glob["peringkat"] = range(1, len(glob) + 1)
    glob.round(6).to_csv(REPORTS / "06_shap_global.csv", index=False)
    log("\nGlobal Feature Importance (rata-rata |SHAP| pada data uji):")
    log(glob[["peringkat", "label", "mean_abs_shap", "persen"]].round(4).to_string(index=False))

    per_kel = (pd.DataFrame(np.abs(SV), columns=FITUR).assign(kelompok=s["kelompok_wilayah"].values)
               .groupby("kelompok").mean())
    (per_kel.div(per_kel.sum(axis=1), axis=0) * 100).round(2).rename(columns=LABEL_FITUR) \
        .to_csv(REPORTS / "06_shap_global_per_kelompok.csv")

    nilai = s[["ADM2_NAME", "ADM1_NAME", "kelompok_wilayah", "periode", TARGET, "prediksi", "nilai_dasar"] + FITUR].copy()
    for j, f in enumerate(FITUR):
        nilai[f"shap_{f}"] = SV[:, j]
    nilai.to_csv(REPORTS / "06_shap_nilai_sampel.csv", index=False)

    # ---------------- pemeriksaan pola: arah SHAP vs arah hubungan pada data asli
    cek = []
    for j, f in enumerate(FITUR):
        r_data = s[f].corr(s[TARGET], method="spearman")
        r_shap = pd.Series(SV[:, j]).corr(s[f].reset_index(drop=True), method="spearman")
        cek.append({"variabel": LABEL_FITUR[f], "spearman_data_vs_target": r_data,
                    "spearman_nilai_vs_shap": r_shap,
                    "arah_sama": bool(np.sign(r_data) == np.sign(r_shap)) if abs(r_data) >= 0.1 else "lemah"})
    cek = pd.DataFrame(cek)
    cek.round(3).to_csv(REPORTS / "06_cek_pola.csv", index=False)
    log("\nPemeriksaan pola (arah hubungan pada data asli vs arah pengaruh menurut SHAP):")
    log(cek.round(3).to_string(index=False))

    gambar(s, SV, glob)
    log(f"\nSelesai dalam {time.time() - t0:.0f} s")
    (REPORTS / "06_log_shap.txt").write_text("\n".join(catatan), encoding="utf-8")


def gambar(s, SV, glob):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import shap
    except ImportError:
        log("matplotlib/shap tidak tersedia: grafik dilewati.")
        return
    nama = [LABEL_FITUR[f] for f in FITUR]

    g = glob.iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 4.6))
    ax.barh(g["label"], g["mean_abs_shap"], color="#0F766E")
    for y, (v, p) in enumerate(zip(g["mean_abs_shap"], g["persen"])):
        ax.text(v, y, f"  {p:.1f}%", va="center", fontsize=9)
    ax.set_xlabel("Rata-rata |nilai SHAP| (m³/m³)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(REPORTS / "06_shap_global_bar.png", dpi=200)
    plt.close(fig)

    plt.figure()
    shap.summary_plot(SV, s[FITUR].values, feature_names=nama, show=False, plot_size=(7, 5))
    plt.xlabel("Nilai SHAP (dampak terhadap estimasi soil moisture, m³/m³)")
    plt.tight_layout()
    plt.savefig(REPORTS / "06_shap_beeswarm.png", dpi=200)
    plt.close("all")

    # contoh lokal: baris dengan prediksi terendah pada bulan terakhir (wilayah kering)
    akhir = s[s["periode"] == s["periode"].max()]
    i = (akhir if len(akhir) else s)["prediksi"].idxmin()
    ex = shap.Explanation(values=SV[i], base_values=s.loc[i, "nilai_dasar"],
                          data=s.loc[i, FITUR].values.astype(float), feature_names=nama)
    plt.figure()
    shap.plots.waterfall(ex, max_display=8, show=False)
    plt.title(f"{s.loc[i, 'ADM2_NAME']} ({s.loc[i, 'ADM1_NAME']}), {pd.Timestamp(s.loc[i, 'periode']):%m/%Y}", fontsize=10)
    plt.tight_layout()
    plt.savefig(REPORTS / "06_shap_lokal_contoh.png", dpi=200, bbox_inches="tight")
    plt.close("all")
    log("Grafik disimpan: 06_shap_global_bar.png, 06_shap_beeswarm.png, 06_shap_lokal_contoh.png")


if __name__ == "__main__":
    main()
