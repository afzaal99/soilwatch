"""
05 - Model gabungan RF + XGBoost, evaluasi akhir, dan pemilihan model terbaik
==============================================================================
(Subbab 2.2.2.3 model gabungan, 2.2.3 evaluasi, 2.2.3.4 nasional vs regional)

Masukan : hasil script 03 dan 04 (reports/03_*, reports/04_*)
          data/geo/penanda_lahan_kabkota.csv (hasil script 02, opsional)
          data/geo/badan_air_besar.geojson + batas_kabkota_gaul2025.geojson (hasil script 02, opsional)
Keluaran: reports/05_bobot_gabungan_cv.csv     RMSE validasi untuk 11 bobot, per cakupan model
          reports/05_evaluasi_semua.csv        R2, MAE, RMSE data uji: 3 pendekatan x nasional/regional
                                               x (Indonesia, 7 kelompok, wilayah danau, wilayah gambut)
          reports/05_wilayah_danau.csv         daftar kabupaten/kota yang memuat danau/waduk besar
          reports/05_nasional_vs_regional.csv  aturan 10% untuk pendekatan terbaik
          reports/05_prediksi_uji_final.csv    prediksi data uji dari konfigurasi akhir
          reports/05_bobot_gabungan_uji_info.csv  RMSE data uji untuk 11 bobot (INFORMASI saja)
          reports/05_ringkasan.txt
          models/model_terpilih.json           konfigurasi yang dipakai aplikasi web dan script 06

Langkah:
1. Bobot gabungan: prediksi = w x RF + (1 - w) x XGBoost, w = 0; 0,1; ...; 1 (11 bobot).
   Bobot dipilih dari prediksi VALIDASI 5-fold time-series CV (out-of-fold) di data latih,
   untuk setiap cakupan model (nasional dan 7 regional). Data uji TIDAK dipakai untuk memilih
   bobot agar tidak terjadi kebocoran data.
2. Evaluasi data uji untuk RF, XGBoost, dan gabungan, masing-masing skenario nasional dan regional.
3. Pendekatan terbaik = RMSE model nasional terkecil pada data uji seluruh Indonesia.
4. Untuk pendekatan terbaik, aturan 10%: pada setiap kelompok, model nasional dipakai jika
   RMSE-nya <= 1,10 x RMSE model regional; selain itu dipakai model regional kelompok tersebut.

Wilayah khusus (catatan sidang: "Tambahkan prediksi untuk lahan gambut, wilayah danau"):
- Wilayah danau  = kabupaten/kota yang memuat (sebagian) salah satu danau/waduk besar yang
                   ditampilkan di peta web (scripts/peta.py, daftar DANAU).
- Wilayah gambut = kabupaten/kota dengan proporsi gambut >= 20% (setelah data gambut tersedia).

Script ini cepat (tanpa pelatihan ulang), jadi aman dijalankan ulang setelah hasil GEE tersedia.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_PROCESSED, KELOMPOK, MODELS, REPORTS, ROOT, TARGET
from umum import metrik, rmse

BOBOT = [round(w, 1) for w in np.arange(0, 1.01, 0.1)]
AMBANG_10 = 10.0      # persen
AMBANG_PENANDA = 0.20
KEY = ["ADM2_NAME", "ADM1_NAME", "periode"]
LABEL = {"rf": "RF", "xgb": "XGBoost", "gab": "Gabungan"}
catatan = []


def log(s=""):
    print(s)
    catatan.append(str(s))


def pilih_bobot():
    a = pd.read_csv(REPORTS / "03_oof_rf.csv")
    b = pd.read_csv(REPORTS / "04_oof_xgb.csv")
    k = ["cakupan", "lipatan", "baris_latih"]
    m = a.merge(b[k + ["pred"]], on=k, suffixes=("_rf", "_xgb"))
    if len(m) != len(a):
        raise SystemExit("Prediksi validasi RF dan XGBoost tidak sejajar. Jalankan ulang script 03 dan 04.")
    baris = []
    for cak, g in m.groupby("cakupan", sort=False):
        for w in BOBOT:
            p = w * g["pred_rf"] + (1 - w) * g["pred_xgb"]
            per_lipatan = [rmse(h["aktual"], p[h.index]) for _, h in g.groupby("lipatan")]
            baris.append({"cakupan": cak, "bobot_rf": w, "bobot_xgb": round(1 - w, 1),
                          "rmse_cv_rata2": np.mean(per_lipatan), "rmse_cv_std": np.std(per_lipatan)})
    tab = pd.DataFrame(baris)
    tab.round(5).to_csv(REPORTS / "05_bobot_gabungan_cv.csv", index=False)
    terbaik = tab.loc[tab.groupby("cakupan")["rmse_cv_rata2"].idxmin()].set_index("cakupan")
    return {c: float(terbaik.loc[c, "bobot_rf"]) for c in terbaik.index}, tab


def muat_prediksi_uji():
    a = pd.read_csv(REPORTS / "03_prediksi_uji_rf.csv")
    b = pd.read_csv(REPORTS / "04_prediksi_uji_xgb.csv")
    u = a.merge(b[KEY + ["pred_xgb_nasional", "pred_xgb_regional"]], on=KEY)
    if len(u) != len(a):
        raise SystemExit("Prediksi uji RF dan XGBoost tidak sejajar.")
    return u


def wilayah_danau():
    """{(ADM2_NAME, ADM1_NAME): [nama danau, ...]} untuk kabupaten/kota yang memuat danau/waduk besar."""
    try:
        from peta import danau_per_wilayah, daftar_wilayah, lapisan_lahan, poligon_wilayah
    except ImportError:
        return {}
    danau = lapisan_lahan()["air"]
    if not danau:
        return {}
    wil = daftar_wilayah(pd.read_csv(DATA_PROCESSED / "dataset_bersih.csv"))
    _, poli = poligon_wilayah(wil)
    per_id = danau_per_wilayah(poli, danau)
    nama = dict(zip(wil["id"], zip(wil["ADM2_NAME"], wil["ADM1_NAME"])))
    return {nama[i]: d for i, d in per_id.items()}


def tambah_penanda(u):
    """Menandai baris yang termasuk wilayah danau dan wilayah gambut."""
    u["wil_danau"] = False
    u["wil_gambut"] = False
    ada = False

    dw = wilayah_danau()
    if dw:
        ada = True
        kunci = list(zip(u["ADM2_NAME"], u["ADM1_NAME"]))
        u["wil_danau"] = [k in dw for k in kunci]
        tabel = pd.DataFrame([{"ADM2_NAME": a, "ADM1_NAME": b, "danau": ", ".join(d)} for (a, b), d in dw.items()])
        tabel.sort_values(["ADM1_NAME", "ADM2_NAME"]).to_csv(REPORTS / "05_wilayah_danau.csv", index=False)
        log(f"Wilayah danau: {len(dw)} kabupaten/kota memuat danau/waduk besar "
            f"(daftar: reports/05_wilayah_danau.csv)")
    else:
        log("Bentuk danau (data/geo/badan_air_besar.geojson) belum ada: evaluasi wilayah danau dilewati.")

    f = ROOT / "data" / "geo" / "penanda_lahan_kabkota.csv"
    if f.exists():
        p = pd.read_csv(f).drop_duplicates(["ADM2_NAME", "ADM1_NAME"])
        if "prop_gambut" in p:
            ada = True
            u = u.merge(p[["ADM2_NAME", "ADM1_NAME", "prop_gambut"]], on=["ADM2_NAME", "ADM1_NAME"], how="left")
            u["wil_gambut"] = u["prop_gambut"].fillna(0) >= AMBANG_PENANDA
            log(f"Wilayah gambut: {u.loc[u['wil_gambut'], 'ADM2_NAME'].nunique()} kabupaten/kota "
                f"dengan gambut >= {AMBANG_PENANDA:.0%}")
        else:
            log("Kolom prop_gambut belum ada (data gambut belum diisi di script 02): evaluasi wilayah gambut dilewati.")
    return u, ada


def subset_evaluasi(u, ada_penanda):
    """Daftar (nama subset, mask baris) untuk evaluasi."""
    out = [("Indonesia", np.ones(len(u), bool))]
    out += [(k, (u["kelompok_wilayah"] == k).values) for k in KELOMPOK]
    if ada_penanda:
        if u["wil_danau"].any():
            out.append(("Wilayah danau", u["wil_danau"].values))
        if u["wil_gambut"].any():
            out.append(("Wilayah gambut (>=20%)", u["wil_gambut"].values))
        out.append(("Wilayah lainnya", (~u["wil_danau"] & ~u["wil_gambut"]).values))
    return [(n, m) for n, m in out if m.sum() > 1]


def main():
    bobot, tab_cv = pilih_bobot()
    log("Bobot RF terpilih (dari validasi CV, bukan data uji):")
    for c, w in bobot.items():
        log(f"  {c:20s} w_RF = {w:.1f}   w_XGB = {1 - w:.1f}")

    u = muat_prediksi_uji()
    u["pred_gab_nasional"] = bobot["nasional"] * u["pred_rf_nasional"] + (1 - bobot["nasional"]) * u["pred_xgb_nasional"]
    w_reg = u["kelompok_wilayah"].map(bobot)
    u["pred_gab_regional"] = w_reg * u["pred_rf_regional"] + (1 - w_reg) * u["pred_xgb_regional"]
    u, ada_penanda = tambah_penanda(u)
    subset = subset_evaluasi(u, ada_penanda)

    # ---------------- evaluasi semua pendekatan
    ev = []
    for kode in ["rf", "xgb", "gab"]:
        for sken in ["nasional", "regional"]:
            kol = f"pred_{kode}_{sken}"
            for nama, mask in subset:
                ev.append({"pendekatan": LABEL[kode], "skenario": sken, "dievaluasi_pada": nama,
                           **metrik(u.loc[mask, TARGET], u.loc[mask, kol])})
    ev = pd.DataFrame(ev)

    # ---------------- pendekatan terbaik (model nasional, data uji seluruh Indonesia)
    nas_indo = ev[(ev["skenario"] == "nasional") & (ev["dievaluasi_pada"] == "Indonesia")].set_index("pendekatan")
    terbaik = nas_indo["RMSE"].idxmin()
    kode = {v: k for k, v in LABEL.items()}[terbaik]
    log("\nModel nasional pada data uji seluruh Indonesia:")
    log(nas_indo[["R2", "MAE", "RMSE"]].round(4).to_string())
    log(f"Pendekatan terbaik: {terbaik}")

    # ---------------- aturan 10% untuk pendekatan terbaik
    e = ev[ev["pendekatan"] == terbaik].set_index(["skenario", "dievaluasi_pada"])
    banding = pd.DataFrame({k: {"rmse_nasional": e.loc[("nasional", k), "RMSE"],
                                "rmse_regional": e.loc[("regional", k), "RMSE"]} for k in KELOMPOK}).T
    banding["selisih_%"] = 100 * (banding["rmse_nasional"] / banding["rmse_regional"] - 1)
    banding["model_dipakai"] = np.where(banding["selisih_%"] <= AMBANG_10, "nasional", "regional")
    banding.index.name = "kelompok"
    banding.round(4).to_csv(REPORTS / "05_nasional_vs_regional.csv")
    per_kel = banding["model_dipakai"].to_dict()
    log(f"\nAturan 10% ({terbaik}):")
    log(banding.round(4).to_string())

    # ---------------- konfigurasi akhir
    pakai_reg = u["kelompok_wilayah"].map(per_kel).eq("regional")
    u["pred_final"] = np.where(pakai_reg, u[f"pred_{kode}_regional"], u[f"pred_{kode}_nasional"])
    for nama, mask in subset:
        ev = pd.concat([ev, pd.DataFrame([{"pendekatan": f"{terbaik} (konfigurasi akhir)", "skenario": "akhir",
                                           "dievaluasi_pada": nama, **metrik(u.loc[mask, TARGET], u.loc[mask, "pred_final"])}])])
    ev.round(5).to_csv(REPORTS / "05_evaluasi_semua.csv", index=False)
    akhir = ev[ev["skenario"] == "akhir"].set_index("dievaluasi_pada")
    log("\nKonfigurasi akhir pada data uji:")
    log(akhir[["R2", "MAE", "RMSE", "n"]].round(4).to_string())

    # informasi saja: RMSE data uji untuk ke-11 bobot (tidak dipakai untuk memilih)
    info = [{"bobot_rf": w, "rmse_uji_nasional": rmse(u[TARGET], w * u["pred_rf_nasional"] + (1 - w) * u["pred_xgb_nasional"])}
            for w in BOBOT]
    pd.DataFrame(info).round(5).to_csv(REPORTS / "05_bobot_gabungan_uji_info.csv", index=False)

    kol = ["ADM2_NAME", "ADM1_NAME", "kelompok_wilayah", "periode", TARGET, "pred_final"]
    u[kol].to_csv(REPORTS / "05_prediksi_uji_final.csv", index=False)

    w_akhir = {c: (bobot[c] if kode == "gab" else (1.0 if kode == "rf" else 0.0)) for c in bobot}
    konf = {
        "pendekatan": terbaik,
        "bobot_rf": w_akhir,
        "per_kelompok": per_kel,
        "keterangan": "prediksi = bobot_rf x RF + (1 - bobot_rf) x XGBoost; per_kelompok memilih model "
                      "nasional atau regional (aturan 10% RMSE). Mode Simulasi memakai model nasional.",
        "metrik_uji_indonesia": {k: round(float(akhir.loc["Indonesia", k]), 4) for k in ["R2", "MAE", "RMSE"]},
        "metrik_uji_wilayah_khusus": {n: {k: round(float(akhir.loc[n, k]), 4) for k in ["R2", "MAE", "RMSE", "n"]}
                                      for n in akhir.index if n.startswith("Wilayah")},
        "dibuat": datetime.now().isoformat(timespec="seconds"),
    }
    (MODELS / "model_terpilih.json").write_text(json.dumps(konf, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"\nKonfigurasi disimpan ke models/model_terpilih.json")
    (REPORTS / "05_ringkasan.txt").write_text("\n".join(catatan), encoding="utf-8")


if __name__ == "__main__":
    main()
