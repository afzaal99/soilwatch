"""
Latih ulang model dari dashboard admin (champion vs challenger).

Cara kerja (adil dan tanpa kebocoran data):
1. Model aktif ("champion") dilatih dengan data sampai bulan tertentu (data_latih_sampai).
2. Model baru ("challenger") memakai konfigurasi dan hyperparameter yang SAMA dengan model aktif
   (hasil tuning script 03/04/05), lalu dilatih dengan data sampai 3 bulan sebelum data terakhir.
3. Keduanya diuji pada 3 bulan terakhir, yang belum pernah dilihat oleh kedua model.
4. Jika admin memilih model baru, model baru dilatih sekali lagi dengan SELURUH data, lalu dipasang.
   Model lama disimpan di arsip sehingga bisa dikembalikan kapan saja.

Pelatihan berjalan di latar belakang (thread) agar halaman admin tidak menunggu terlalu lama.
"""
import json
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import estimasi as est
import pembaruan as pb

FOLDER = est.ROOT / "instance" / "model"
KANDIDAT = FOLDER / "kandidat"
ARSIP = FOLDER / "arsip"
STATUS = FOLDER / "status.json"
MODELS = est.ROOT / "models"
KONF_F = MODELS / "model_terpilih.json"
N_UJI = 3                    # bulan terakhir yang dipakai menguji model lama vs baru
AKHIR_LATIH_AWAL = "2025-09"  # model hasil skripsi dilatih dengan data Januari 2023 - September 2025
_kunci = threading.Lock()


# ----------------------------------------------------------------------------- status
def _tulis_status(**kw):
    FOLDER.mkdir(parents=True, exist_ok=True)
    s = baca_status()
    s.update(kw, diperbarui=time.time())
    STATUS.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")


def baca_status():
    if STATUS.exists():
        try:
            s = json.loads(STATUS.read_text(encoding="utf-8"))
            # thread mati (mis. server dimatikan) saat berjalan -> anggap gagal setelah 30 menit tanpa kabar
            if s.get("status") == "berjalan" and time.time() - s.get("diperbarui", 0) > 1800:
                s.update(status="gagal", pesan="Proses terhenti (server dimatikan saat pelatihan berjalan).")
            return s
        except ValueError:
            pass
    return {"status": "kosong"}


def akhir_latih():
    return (est.KONF or {}).get("data_latih_sampai", AKHIR_LATIH_AWAL)


def kesiapan():
    """Apakah latih ulang bisa dilakukan sekarang, dan bulan apa saja yang dipakai."""
    per = est.DATA["periode"]
    baru = [p for p in per if p > akhir_latih()]
    siap = len(baru) >= N_UJI and est.KONF is not None
    uji = per[-N_UJI:]
    return {"siap": siap, "n_baru": len(baru), "perlu": N_UJI,
            "akhir_latih": pb.label(akhir_latih()), "data_akhir": est.DATA["periode_label"][-1],
            "uji": f"{pb.label(uji[0])} – {pb.label(uji[-1])}",
            "latih_cek": f"{est.DATA['periode_label'][0]} – {pb.label(pb.geser(uji[0], -1))}",
            "ada_konf": est.KONF is not None}


# ----------------------------------------------------------------------------- data & metrik
def _data():
    fitur = est.FITUR
    rows = est._query(f"SELECT d.wilayah_id, p.kode, w.kelompok, w.danau, w.persen_gambut, d.soil_moisture, "
                      f"{', '.join('d.' + f for f in fitur)} FROM data_bulanan d "
                      "JOIN periode p ON p.id = d.periode_id JOIN wilayah w ON w.id = d.wilayah_id")
    df = pd.DataFrame(rows, columns=["id", "kode", "kelompok", "danau", "gambut", "soil_moisture"] + fitur)
    return df.dropna(subset=["soil_moisture"] + fitur).reset_index(drop=True)


def _m(y, p):
    m = pb._metrik(y, p)
    return {"MAE": m["mae"], "RMSE": m["rmse"], "R2": m["r2"], "n": m["n"]}


def _ringkas(df, kol):
    """Metrik untuk seluruh Indonesia, per bulan, per kelompok, dan wilayah khusus."""
    hasil = {"Indonesia": _m(df["soil_moisture"], df[kol])}
    hasil["per_bulan"] = {pb.label(k): _m(g["soil_moisture"], g[kol]) for k, g in df.groupby("kode")}
    hasil["per_kelompok"] = {k: _m(g["soil_moisture"], g[kol]) for k, g in df.groupby("kelompok")}
    danau = df["danau"].notna()
    gambut = df["gambut"].fillna(0) >= 20
    khusus = {}
    if danau.any():
        khusus["Wilayah danau"] = _m(df.loc[danau, "soil_moisture"], df.loc[danau, kol])
    if gambut.any():
        khusus["Wilayah gambut (>=20%)"] = _m(df.loc[gambut, "soil_moisture"], df.loc[gambut, kol])
    lain = ~danau & ~gambut
    khusus["Wilayah lainnya"] = _m(df.loc[lain, "soil_moisture"], df.loc[lain, kol])
    hasil["khusus"] = khusus
    return hasil


def _rencana_aktif():
    """{kelompok: (cakupan, [(jenis, bobot)])} dan daftar model (jenis, cakupan) yang perlu dilatih."""
    kelompok = sorted({w["kelompok"] for w in est.WILAYAH})
    rencana = {k: est._rencana(k) for k in kelompok}
    perlu = sorted({(j, cak) for cak, r in rencana.values() for j, _ in r})
    return rencana, perlu


# ----------------------------------------------------------------------------- pelatihan
def mulai():
    """Mulai latih ulang di latar belakang. Mengembalikan pesan galat (str) jika tidak bisa."""
    from sklearn.base import clone  # noqa: F401  (memastikan scikit-learn tersedia sebelum thread jalan)
    if not kesiapan()["siap"]:
        return "Latih ulang belum bisa dilakukan: data baru sejak model terakhir dilatih belum cukup."
    with _kunci:
        if baca_status().get("status") == "berjalan":
            return "Pelatihan sedang berjalan."
        _tulis_status(status="berjalan", persen=2, tahap="Menyiapkan data", mulai=datetime.now().strftime("%Y-%m-%d %H:%M"),
                      pesan="", kandidat=None)
    threading.Thread(target=_kerja, daemon=True).start()
    return None


def _kerja():
    try:
        _latih()
    except Exception as e:
        traceback.print_exc()
        _tulis_status(status="gagal", pesan=f"{type(e).__name__}: {e}")


def _latih():
    from sklearn.base import clone
    df = _data()
    per = sorted(df["kode"].unique())
    uji_bln = per[-N_UJI:]
    is_uji = df["kode"].isin(uji_bln)
    rencana, perlu = _rencana_aktif()

    model_lama = {}
    for jenis, cak in perlu:
        obj = est._model(jenis, cak)
        if obj is None:
            raise FileNotFoundError(f"Berkas model {jenis}_{est._nama_file(cak)}.joblib tidak ditemukan di folder models.")
        model_lama[(jenis, cak)] = obj

    langkah = 2 * len(perlu)
    selesai = 0
    cek, akhir = {}, {}
    for (jenis, cak), obj in model_lama.items():
        baris = df if cak == "nasional" else df[df["kelompok"] == cak]
        nama = f"{est.NAMA_JENIS[jenis]} {'nasional' if cak == 'nasional' else 'regional ' + cak}"
        _tulis_status(tahap=f"Melatih {nama} untuk pengujian", persen=5 + 85 * selesai / langkah)
        m = clone(obj["model"])
        lt = baris[~baris["kode"].isin(uji_bln)]
        m.fit(lt[obj["fitur"]], lt["soil_moisture"])
        cek[(jenis, cak)] = m
        selesai += 1
        _tulis_status(tahap=f"Melatih {nama} dengan seluruh data", persen=5 + 85 * selesai / langkah)
        m2 = clone(obj["model"])
        m2.fit(baris[obj["fitur"]], baris["soil_moisture"])
        akhir[(jenis, cak)] = m2
        selesai += 1

    _tulis_status(tahap="Membandingkan model lama dan model baru", persen=92)
    u = df[is_uji].copy()
    u["pred_lama"], _ = pb._prediksi(u)
    u["pred_baru"] = np.nan
    for kel, g in u.groupby("kelompok"):
        cak, r = rencana[kel]
        u.loc[g.index, "pred_baru"] = sum(b * cek[(j, cak)].predict(g[model_lama[(j, cak)]["fitur"]]) for j, b in r)
    lama, baru = _ringkas(u, "pred_lama"), _ringkas(u, "pred_baru")

    kid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    folder = KANDIDAT / kid
    folder.mkdir(parents=True, exist_ok=True)
    import joblib
    for (jenis, cak), m in akhir.items():
        obj = model_lama[(jenis, cak)]
        joblib.dump({"model": m, "fitur": obj["fitur"], "parameter": obj.get("parameter"), "jenis": jenis,
                     "data_sampai": per[-1], "dilatih": datetime.now().isoformat(timespec="minutes")},
                    folder / f"{jenis}_{est._nama_file(cak)}.joblib", compress=3)
    mae_l, mae_b = lama["Indonesia"]["MAE"], baru["Indonesia"]["MAE"]
    laporan = {"id": kid, "dibuat": datetime.now().strftime("%Y-%m-%d %H:%M"), "uji": uji_bln,
               "uji_label": f"{pb.label(uji_bln[0])} – {pb.label(uji_bln[-1])}",
               "latih_cek_sampai": pb.geser(uji_bln[0], -1), "data_sampai": per[-1],
               "model": sorted(f"{j}_{est._nama_file(c)}" for j, c in akhir), "lama": lama, "baru": baru,
               "lebih_baik": mae_b < mae_l, "perubahan_persen": 100 * (mae_b - mae_l) / mae_l if mae_l else None,
               "n_baris_latih": int(len(df))}
    (folder / "laporan.json").write_text(json.dumps(laporan, ensure_ascii=False, indent=1), encoding="utf-8")
    for lama_k in sorted(KANDIDAT.glob("*"))[:-3]:      # simpan 3 kandidat terakhir saja
        shutil.rmtree(lama_k, ignore_errors=True)
    _tulis_status(status="selesai", persen=100, tahap="Selesai", kandidat=kid)


# ----------------------------------------------------------------------------- kandidat, pasang, kembalikan
def kandidat(kid=None):
    if kid is None:
        kid = baca_status().get("kandidat")
    if not kid or not (KANDIDAT / kid / "laporan.json").exists():
        return None
    lap = json.loads((KANDIDAT / kid / "laporan.json").read_text(encoding="utf-8"))
    lap["sudah_dipasang"] = (est.KONF or {}).get("kandidat_id") == kid
    return lap


def _arsipkan(alasan, nama_berkas):
    """Salin model aktif (berkas yang akan diganti + model_terpilih.json) ke arsip."""
    aid = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = ARSIP / aid
    folder.mkdir(parents=True, exist_ok=True)
    for n in set(nama_berkas) | {"model_terpilih.json"}:
        if (MODELS / n).exists():
            shutil.copy2(MODELS / n, folder / n)
    konf = est.KONF or {}
    (folder / "info.json").write_text(json.dumps({
        "alasan": alasan, "waktu": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_latih_sampai": konf.get("data_latih_sampai", AKHIR_LATIH_AWAL),
        "mae": (konf.get("metrik_uji_indonesia") or {}).get("MAE"),
        "periode_uji": konf.get("periode_uji", "Oktober 2025 – Juni 2026")}, ensure_ascii=False), encoding="utf-8")
    return aid


def pasang(kid):
    lap = kandidat(kid)
    if lap is None:
        raise ValueError("Model baru tidak ditemukan. Jalankan latih ulang lagi.")
    if lap["sudah_dipasang"]:
        raise ValueError("Model ini sudah dipakai.")
    if lap["data_sampai"] != est.DATA["periode"][-1]:
        raise ValueError("Data sudah berubah sejak model ini dilatih. Jalankan latih ulang lagi.")
    berkas = [f"{m}.joblib" for m in lap["model"]]
    aid = _arsipkan(f"Sebelum diganti model baru ({pb.label(lap['data_sampai'])})", berkas)
    for b in berkas:
        shutil.copy2(KANDIDAT / kid / b, MODELS / b)
    konf = dict(est.KONF or {})
    if "metrik_awal_skripsi" not in konf:            # simpan hasil uji skripsi sebagai catatan
        konf["metrik_awal_skripsi"] = {"periode_uji": konf.get("periode_uji", "Oktober 2025 – Juni 2026"),
                                       "Indonesia": konf.get("metrik_uji_indonesia"),
                                       "khusus": konf.get("metrik_uji_wilayah_khusus")}
    b = lap["baru"]
    konf.update({
        "metrik_uji_indonesia": {k: round(v, 4) for k, v in b["Indonesia"].items() if k != "n"},
        "metrik_uji_wilayah_khusus": {n: {k: round(v, 4) for k, v in d.items() if k != "n"} | {"n": d["n"]}
                                      for n, d in b["khusus"].items()},
        "periode_uji": lap["uji_label"], "data_latih_sampai": lap["data_sampai"],
        "dilatih_ulang": lap["dibuat"], "kandidat_id": kid,
        "keterangan": (konf.get("keterangan", "") + f" | Dilatih ulang {lap['dibuat']} dengan data sampai "
                       f"{pb.label(lap['data_sampai'])}, hyperparameter sama.").strip(" |"),
    })
    KONF_F.write_text(json.dumps(konf, ensure_ascii=False, indent=1), encoding="utf-8")
    est.muat_ulang()
    con = pb._tulis()
    with con:
        pb._catat(con, "Model diperbarui",
                  f"Model baru (data sampai {pb.label(lap['data_sampai'])}) dipasang. MAE uji {lap['uji_label']}: "
                  f"{pb._f(b['Indonesia']['MAE'], 4)} (model lama {pb._f(lap['lama']['Indonesia']['MAE'], 4)}).",
                  cadangan=f"arsip model {aid}")
    con.close()
    return aid


def daftar_arsip():
    hasil = []
    for f in sorted(ARSIP.glob("*"), reverse=True) if ARSIP.exists() else []:
        info = json.loads((f / "info.json").read_text(encoding="utf-8")) if (f / "info.json").exists() else {}
        hasil.append({"id": f.name, "waktu": pb._waktu_teks(info.get("waktu", "")), "alasan": info.get("alasan", "-"),
                      "latih_sampai": pb.label(info["data_latih_sampai"]) if info.get("data_latih_sampai") else "-",
                      "mae": info.get("mae"), "periode_uji": info.get("periode_uji", "-")})
    return hasil


def kembalikan(aid):
    folder = ARSIP / Path(aid).name
    if not folder.is_dir() or not (folder / "model_terpilih.json").exists():
        raise ValueError("Arsip model tidak ditemukan.")
    berkas = [f.name for f in folder.glob("*.joblib")]
    sebelum = _arsipkan("Sebelum dikembalikan ke arsip " + folder.name, berkas)
    for b in berkas + ["model_terpilih.json"]:
        shutil.copy2(folder / b, MODELS / b)
    est.muat_ulang()
    con = pb._tulis()
    with con:
        pb._catat(con, "Model dikembalikan", f"Model dikembalikan ke versi arsip {folder.name} (data latih sampai "
                  f"{pb.label(akhir_latih())}).", cadangan=f"arsip model {sebelum}")
    con.close()
