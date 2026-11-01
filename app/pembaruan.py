"""
Pembaruan data bulanan untuk dashboard admin.

Alur: baca CSV hasil script 09 (GEE) -> periksa dan bersihkan dengan aturan yang sama seperti
script 01 -> evaluasi akurasi model terhadap SMAP pada bulan baru -> simpan ke basis data
(dengan cadangan otomatis) -> perbarui peta Beranda -> aplikasi memuat ulang data.

Modul ini tidak bergantung pada Flask agar mudah diuji dan dipakai ulang.
"""
import importlib
import io
import json
import math
import shutil
import sqlite3
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import estimasi as est

ROOT = est.ROOT
DB = est.DB
INSTANCE = ROOT / "instance"              # tidak ikut ke GitHub (lihat .gitignore)
STAGING = INSTANCE / "unggahan"           # unggahan yang menunggu konfirmasi
CADANGAN = INSTANCE / "cadangan"          # salinan basis data sebelum setiap perubahan
MAKS_CADANGAN = 12

KEY = ["ADM2_NAME", "ADM1_NAME"]
TARGET = "soil_moisture"
STATIS = ["elevation", "slope", "clay_content"]
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
         "September", "Oktober", "November", "Desember"]

# batas fisik (script 01 + validasi aplikasi); nilai di luar batas = data rusak
BATAS_FISIK = {**est.BATAS, TARGET: (0, 1)}
AMBANG_MAE = 1.5        # MAE bulan baru > 1,5 x MAE uji -> perlu perhatian
TANGGAL_AMAN = 25       # data bulan X aman diunggah mulai tanggal 25 bulan X+1

SUMBER_DATA = [  # ditampilkan di panduan
    ("SMAP L4", "soil moisture", "±3 hari setelah akhir bulan"),
    ("ERA5-Land", "suhu, titik embun, radiasi, angin, suhu tanah", "±1–2 minggu"),
    ("MODIS", "NDVI, LST", "±1–2 minggu"),
    ("CHIRPS", "curah hujan", "minggu ke-3 bulan berikutnya (paling lambat)"),
]


# ----------------------------------------------------------------------------- waktu
def label(kode):
    """'2026-07' -> 'Juli 2026'"""
    return f"{BULAN[int(kode[5:7]) - 1]} {kode[:4]}"


def geser(kode, n):
    y, m = int(kode[:4]), int(kode[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def aman_mulai(kode):
    """Tanggal paling awal data bulan `kode` aman diunggah."""
    k = geser(kode, 1)
    return date(int(k[:4]), int(k[5:7]), TANGGAL_AMAN)


def tgl_teks(d):
    return f"{d.day} {BULAN[d.month - 1]} {d.year}"


def info_jadwal(hari_ini=None):
    """Bulan terakhir yang sudah aman diunggah hari ini dan bulan berikutnya yang ditunggu."""
    h = hari_ini or date.today()
    kini = f"{h.year:04d}-{h.month:02d}"
    terakhir_aman = geser(kini, -1 if h.day >= TANGGAL_AMAN else -2)
    data_akhir = est.DATA["periode"][-1]
    berikut = geser(data_akhir, 1)
    belum = []
    k = berikut
    while k <= terakhir_aman:
        belum.append(k)
        k = geser(k, 1)
    return {
        "hari_ini": tgl_teks(h),
        "terakhir_aman": label(terakhir_aman),
        "berikut_aman": label(geser(terakhir_aman, 1)),
        "berikut_aman_mulai": tgl_teks(aman_mulai(geser(terakhir_aman, 1))),
        "data_akhir": label(data_akhir),
        "siap": [label(k) for k in belum],            # bulan yang sudah bisa diunggah sekarang
        "bulan_berikut": label(berikut),
        "bulan_berikut_mulai": tgl_teks(aman_mulai(berikut)),
        "contoh_bulan_baru": ", ".join(f"[{k[:4]}, {int(k[5:7])}]" for k in belum) or
                             f"[{berikut[:4]}, {int(berikut[5:7])}]",
    }


def pilihan_bulan():
    """Pilihan bulan untuk membuat script GEE: 24 bulan terakhir sampai bulan lalu, plus nilai bawaan."""
    j = info_jadwal()
    h = date.today()
    kini = f"{h.year:04d}-{h.month:02d}"
    akhir = geser(kini, -1)
    daftar = [geser(akhir, -i) for i in range(24)][::-1]
    berikut = geser(est.DATA["periode"][-1], 1)
    aman = geser(kini, -1 if h.day >= TANGGAL_AMAN else -2)
    dari = berikut if berikut <= akhir else akhir
    sampai = aman if aman >= dari else dari
    return {"daftar": [(k, label(k)) for k in daftar], "dari": dari, "sampai": sampai,
            "ada": set(est.DATA["periode"]), "aman": aman, "jadwal": j}


def script_gee(dari, sampai):
    """Isi script 09 dengan BULAN_BARU = bulan dari..sampai (maksimal 12 bulan)."""
    import re
    for k in (dari, sampai):
        if not re.fullmatch(r"\d{4}-\d{2}", k or "") or not 1 <= int(k[5:]) <= 12:
            raise ValueError("Format bulan tidak valid.")
    if sampai < dari:
        dari, sampai = sampai, dari
    bulan, k = [], dari
    while k <= sampai:
        bulan.append(k)
        k = geser(k, 1)
    if len(bulan) > 12:
        raise ValueError("Maksimal 12 bulan sekali ambil.")
    f = ROOT / "scripts" / "09_gee_ekstraksi_bulanan.js"
    if not f.exists():
        raise ValueError("Berkas scripts/09_gee_ekstraksi_bulanan.js tidak ditemukan.")
    isi = ", ".join(f"[{b[:4]}, {int(b[5:])}]" for b in bulan)
    teks, n = re.subn(r"var BULAN_BARU = \[.*?\];", f"var BULAN_BARU = [{isi}];", f.read_text(encoding="utf-8"), count=1)
    if not n:
        raise ValueError("Baris BULAN_BARU tidak ditemukan di script 09.")
    return teks


# ----------------------------------------------------------------------------- basis data
def _tulis():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS riwayat (
            id INTEGER PRIMARY KEY AUTOINCREMENT, waktu TEXT NOT NULL, jenis TEXT NOT NULL,
            keterangan TEXT NOT NULL, berkas TEXT, cadangan TEXT);
        CREATE TABLE IF NOT EXISTS evaluasi_bulanan (
            periode_kode TEXT PRIMARY KEY, mae REAL, rmse REAL, r2 REAL, n INTEGER,
            mae_uji REAL, model TEXT, waktu TEXT NOT NULL);
    """)
    return con


def riwayat(n=20):
    con = _tulis()
    try:
        return [{**dict(zip(["waktu", "jenis", "keterangan", "berkas", "cadangan"], r)),
                 "waktu_teks": _waktu_teks(r[0])} for r in con.execute(
            "SELECT waktu, jenis, keterangan, berkas, cadangan FROM riwayat ORDER BY id DESC LIMIT ?", (n,))]
    finally:
        con.close()


def evaluasi_tersimpan():
    con = _tulis()
    try:
        return [{**dict(zip(["kode", "mae", "rmse", "r2", "n", "mae_uji", "model"], r)), "label": label(r[0])}
                for r in con.execute("SELECT periode_kode, mae, rmse, r2, n, mae_uji, model "
                                     "FROM evaluasi_bulanan ORDER BY periode_kode")]
    finally:
        con.close()


def _waktu_teks(w):
    try:
        t = datetime.strptime(w, "%Y-%m-%d %H:%M")
        return f"{tgl_teks(t)}, {t:%H:%M}"
    except ValueError:
        return w


def _catat(con, jenis, ket, berkas=None, cadangan=None):
    con.execute("INSERT INTO riwayat (waktu, jenis, keterangan, berkas, cadangan) VALUES (?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M"), jenis, ket, berkas, cadangan))


def buat_cadangan(alasan):
    """Salin basis data ke instance/cadangan sebelum diubah; simpan paling banyak MAKS_CADANGAN."""
    CADANGAN.mkdir(parents=True, exist_ok=True)
    nama = f"soilwatch_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(CADANGAN / nama)
    with dst:
        src.backup(dst)          # salinan utuh dan konsisten walau aplikasi sedang membaca
    src.close()
    dst.close()
    (CADANGAN / (nama + ".json")).write_text(json.dumps({
        "alasan": alasan, "periode_akhir": est.DATA["periode"][-1],
        "jumlah_bulan": len(est.DATA["periode"])}, ensure_ascii=False), encoding="utf-8")
    for f in sorted(CADANGAN.glob("soilwatch_*.db"))[:-MAKS_CADANGAN]:
        f.unlink(missing_ok=True)
        Path(str(f) + ".json").unlink(missing_ok=True)
    return nama


def daftar_cadangan():
    hasil = []
    for f in sorted(CADANGAN.glob("soilwatch_*.db"), reverse=True) if CADANGAN.exists() else []:
        info = {}
        j = Path(str(f) + ".json")
        if j.exists():
            info = json.loads(j.read_text(encoding="utf-8"))
        t = datetime.strptime(f.stem[10:], "%Y%m%d_%H%M%S")
        hasil.append({"nama": f.name, "waktu": f"{tgl_teks(t)}, {t:%H:%M}",
                      "alasan": info.get("alasan", "-"),
                      "data_akhir": label(info["periode_akhir"]) if info.get("periode_akhir") else "-",
                      "ukuran": f"{f.stat().st_size / 1e6:.1f} MB"})
    return hasil


def pulihkan(nama):
    f = CADANGAN / Path(nama).name
    if not f.exists() or not f.name.startswith("soilwatch_"):
        raise ValueError("Cadangan tidak ditemukan.")
    sebelum = buat_cadangan(f"Sebelum dipulihkan ke {f.name}")
    src = sqlite3.connect(f"file:{f.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(DB)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    est.muat_ulang()
    con = _tulis()
    with con:
        _catat(con, "Pemulihan", f"Basis data dipulihkan dari cadangan {f.name}. "
                                 f"Data sekarang sampai {label(est.DATA['periode'][-1])}.", cadangan=sebelum)
    con.close()
    perbarui_beranda()
    est.muat_ulang()


# ----------------------------------------------------------------------------- baca & periksa
class Laporan:
    """Kumpulan temuan pemeriksaan: galat (menghentikan), peringatan, dan info."""

    def __init__(self):
        self.galat, self.peringatan, self.info = [], [], []

    def as_dict(self):
        return {"galat": self.galat, "peringatan": self.peringatan, "info": self.info}


def _baca(isi):
    teks = isi.decode("utf-8-sig", errors="replace")
    baris1 = teks.split("\n", 1)[0]
    if baris1.count(";") > baris1.count(","):          # CSV yang sudah dibuka/disimpan ulang di Excel
        return pd.read_csv(io.StringIO(teks), sep=";", decimal=",")
    return pd.read_csv(io.StringIO(teks))


def _rh(t, td):
    es = lambda x: 6.112 * np.exp(17.67 * x / (x + 243.5))
    return 100 * es(td) / es(t)


def _f(v, d=4):
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else \
        f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def periksa(isi, nama_berkas):
    """Membaca CSV dan menyiapkan data bulan baru. Mengembalikan (DataFrame siap simpan | None, ringkasan)."""
    lap = Laporan()
    fitur = est.FITUR
    try:
        df = _baca(isi)
    except Exception as e:
        lap.galat.append(f"Berkas tidak dapat dibaca sebagai CSV ({e}).")
        return None, {"laporan": lap.as_dict()}

    df.columns = [c.strip() for c in df.columns]
    if "relative_humidity" not in df.columns and {"suhu_celsius", "dew_point_celsius"} <= set(df.columns):
        df["relative_humidity"] = _rh(df["suhu_celsius"], df["dew_point_celsius"])
        lap.info.append("Kolom relative_humidity tidak ada di berkas, jadi dihitung otomatis dari suhu udara "
                        "dan titik embun (Persamaan 2.5–2.6).")
    wajib = KEY + [TARGET] + fitur
    kurang = [c for c in wajib if c not in df.columns]
    if not ("tanggal" in df.columns or {"tahun", "bulan"} <= set(df.columns)):
        kurang.append("tanggal (atau tahun dan bulan)")
    if kurang:
        lap.galat.append("Kolom berikut tidak ditemukan: " + ", ".join(kurang) +
                         ". Pastikan berkas berasal dari script 09_gee_ekstraksi_bulanan.js.")
        return None, {"laporan": lap.as_dict()}

    if "tanggal" in df.columns:
        per = pd.to_datetime(df["tanggal"], errors="coerce")
    else:
        per = pd.to_datetime(dict(year=df["tahun"], month=df["bulan"], day=1), errors="coerce")
    if per.isna().any():
        lap.galat.append(f"{int(per.isna().sum())} baris memiliki tanggal yang tidak valid.")
        return None, {"laporan": lap.as_dict()}
    df["kode"] = per.dt.strftime("%Y-%m")
    for c in [TARGET] + fitur:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---- wilayah: harus sama persis dengan kabupaten/kota di basis data (514, FAO GAUL 2025)
    wil = pd.DataFrame([(w["id"], w["nama"], w["prov_gaul"], w["kelompok"]) for w in est.WILAYAH],
                       columns=["id", "ADM2_NAME", "ADM1_NAME", "kelompok"])
    df = df.merge(wil, on=KEY, how="left")
    asing = df[df["id"].isna()]
    if len(asing):
        contoh = ", ".join(sorted({f"{a} ({b})" for a, b in asing[KEY].itertuples(index=False)})[:6])
        lap.galat.append(f"{asing[KEY].drop_duplicates().shape[0]} nama wilayah tidak dikenal: {contoh}. "
                         "Batas wilayah harus FAO GAUL 2025 level 2 (script 09), sama dengan data latih.")
    df = df[df["id"].notna()].copy()
    df["id"] = df["id"].astype(int)
    dup = df.duplicated(["id", "kode"])
    if dup.any():
        lap.galat.append(f"{int(dup.sum())} baris ganda (wilayah dan bulan yang sama muncul dua kali).")

    bulan_baru = sorted(df["kode"].unique())
    ada = set(est.DATA["periode"])
    akhir = est.DATA["periode"][-1]
    ringkas = []
    for k in bulan_baru:
        sub = df[df["kode"] == k]
        n = sub["id"].nunique()
        ringkas.append({"kode": k, "label": label(k), "wilayah": n, "sudah_ada": k in ada,
                        "hilang": int(sub[fitur].isna().sum().sum()),
                        "aman_mulai": tgl_teks(aman_mulai(k)), "belum_aman": date.today() < aman_mulai(k)})
        if n < len(est.WILAYAH):
            lap.galat.append(f"{label(k)}: hanya {n} dari {len(est.WILAYAH)} kabupaten/kota. Setiap bulan harus "
                             "lengkap; ekspor ulang dari GEE setelah semua sumber data tersedia.")
        if sub[TARGET].isna().any():
            lap.galat.append(f"{label(k)}: soil moisture SMAP kosong di {int(sub[TARGET].isna().sum())} wilayah.")
        hujan = sub["curah_hujan_bulanan"]
        if hujan.isna().all() or (hujan.fillna(0) == 0).all():
            lap.galat.append(f"{label(k)}: curah hujan kosong untuk semua wilayah. Kemungkinan data CHIRPS v2 belum "
                             "tersedia atau sudah tidak diperbarui. Jika CHIRPS v2 sudah dihentikan, sumber curah hujan "
                             "perlu diganti ke CHIRPS v3 dan model dilatih ulang (lihat Panduan).")

    # ---- urutan bulan: harus menyambung dengan data yang sudah ada (tanpa bulan bolong)
    baru = [k for k in bulan_baru if k not in ada]
    if baru:
        harap = geser(akhir, 1)
        for k in baru:
            if k != harap:
                lap.galat.append(f"Bulan harus diunggah berurutan. Data tersimpan sampai {label(akhir)}, "
                                 f"jadi bulan berikutnya harus {label(harap)}, bukan {label(k)}.")
                break
            harap = geser(harap, 1)
        if any(k < akhir for k in baru):
            lap.galat.append("Ada bulan sebelum data terakhir yang belum ada di basis data.")

    if lap.galat:
        return None, {"laporan": lap.as_dict(), "bulan": ringkas, "berkas": nama_berkas}

    # ---- bandingkan dengan data tersimpan: variabel statis dan bulan yang sudah ada
    lama = pd.DataFrame(est._query(f"SELECT d.wilayah_id, p.kode, d.{TARGET}, {', '.join('d.' + f for f in fitur)} "
                                   "FROM data_bulanan d JOIN periode p ON p.id = d.periode_id"),
                        columns=["id", "kode", TARGET] + fitur)
    statis_lama = lama.groupby("id")[STATIS].first()
    for v in STATIS:
        sel = (df.set_index("id")[v] - statis_lama[v].reindex(df["id"]).values).abs()
        if sel.max() > max(1e-3, 1e-3 * statis_lama[v].abs().max()):
            lap.peringatan.append(f"Variabel statis {est.INFO[v][0].lower()} berbeda dari data lama (selisih maks "
                                  f"{_f(float(sel.max()), 3)}). Kemungkinan script ekstraksi atau sumber datanya berbeda.")
    selisih = []
    tumpang = [k for k in bulan_baru if k in ada]
    if tumpang:
        a = df[df["kode"].isin(tumpang)].set_index(["id", "kode"])
        b = lama[lama["kode"].isin(tumpang)].set_index(["id", "kode"]).reindex(a.index)
        for v in [TARGET] + fitur:
            d = (a[v] - b[v]).abs()
            selisih.append({"var": "Soil moisture (SMAP)" if v == TARGET else est.INFO[v][0],
                            "maks": _f(float(d.max()), 4), "rata": _f(float(d.mean()), 4),
                            "sama": bool(d.max() < 1e-3 * max(1.0, float(b[v].abs().mean())))})

    # ---- pembersihan seperti script 01
    sejarah = lama[["id", "kode"] + fitur].copy()
    gabung = pd.concat([sejarah[~sejarah["kode"].isin(bulan_baru)], df[["id", "kode"] + fitur]],
                       ignore_index=True).sort_values(["id", "kode"])
    med = gabung.groupby("id")["solar_radiation"].transform("median")
    artefak = gabung["kode"].isin(bulan_baru) & (gabung["solar_radiation"] < 0.5 * med)
    if artefak.any():
        lap.info.append(f"Radiasi matahari di {int(artefak.sum())} baris kurang dari 50% median wilayahnya "
                        "(artefak pesisir/pulau kecil), jadi dianggap nilai hilang seperti pada data latih.")
        gabung.loc[artefak, "solar_radiation"] = np.nan
    hilang = int(gabung.loc[gabung["kode"].isin(bulan_baru), fitur].isna().sum().sum())
    if hilang:
        gabung[fitur] = gabung.groupby("id")[fitur].transform(lambda s: s.interpolate(limit_direction="both"))
        lap.info.append(f"{hilang} nilai variabel yang kosong diisi interpolasi temporal per wilayah "
                        "(aturan yang sama dengan data latih).")
    bersih = gabung[gabung["kode"].isin(bulan_baru)].merge(
        df[["id", "kode", TARGET, "kelompok"]], on=["id", "kode"])

    for v, (lo, hi) in BATAS_FISIK.items():
        if v not in bersih:
            continue
        salah = (bersih[v] < lo) | (bersih[v] > hi)
        if salah.any():
            lap.galat.append(f"{int(salah.sum())} nilai {('soil moisture' if v == TARGET else est.INFO[v][0].lower())} "
                             f"di luar batas fisik ({lo}–{hi}).")
    for v in fitur:  # nilai jauh di luar rentang data latih: model tidak pernah melihatnya
        s = est.STAT[v]
        luar = (bersih[v] < s["min"] - 0.1 * (s["max"] - s["min"])) | (bersih[v] > s["max"] + 0.1 * (s["max"] - s["min"]))
        if luar.sum() > 0:
            lap.peringatan.append(f"{int(luar.sum())} nilai {est.INFO[v][0].lower()} berada jauh di luar rentang data "
                                  f"latih ({_f(s['min'], 2)}–{_f(s['max'], 2)}); estimasi di wilayah tersebut kurang andal.")
    if lap.galat:
        return None, {"laporan": lap.as_dict(), "bulan": ringkas, "berkas": nama_berkas}

    if not [k for k in bulan_baru if k not in ada]:
        lap.info.append("Semua bulan di berkas ini sudah ada di basis data. Data hanya akan disimpan jika Anda "
                        "memilih untuk menimpa data lama.")
    lap.info.insert(0, f"{len(df):,} baris dibaca: {len(bulan_baru)} bulan × {len(est.WILAYAH)} kabupaten/kota."
                    .replace(",", "."))
    return bersih, {"laporan": lap.as_dict(), "bulan": ringkas, "selisih": selisih, "berkas": nama_berkas,
                    "eval": evaluasi(bersih)}


# ----------------------------------------------------------------------------- evaluasi model
def _prediksi(df):
    """Prediksi model aktif untuk banyak baris sekaligus (pilihan model per kelompok sama dengan aplikasi)."""
    hasil = pd.Series(np.nan, index=df.index)
    nama_model = set()
    for kel, g in df.groupby("kelompok"):
        cak, rencana = est._rencana(kel)
        try:
            total = np.zeros(len(g))
            for jenis, bobot in rencana:
                obj = est._model(jenis, cak)
                if obj is None:
                    raise LookupError
                total += bobot * obj["model"].predict(g[obj["fitur"]])
            hasil.loc[g.index] = total
            nama_model.add(est._sumber(cak, rencana))
        except Exception:
            for i, row in g.iterrows():
                v, s = est.prediksi({f: row[f] for f in est.FITUR}, kel)
                hasil.loc[i] = v
                nama_model.add(s)
    return hasil, nama_model


def _metrik(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    e = p - y
    ss = ((y - y.mean()) ** 2).sum()
    return {"mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e ** 2).mean())),
            "r2": float(1 - (e ** 2).sum() / ss) if ss > 0 else float("nan"), "n": int(len(y))}


def mae_uji():
    m = (est.KONF or {}).get("metrik_uji_indonesia") or {}
    return m.get("MAE"), m.get("R2")


def evaluasi(df):
    """Akurasi model aktif pada bulan baru dibanding nilai acuan SMAP L4."""
    pred, model = _prediksi(df)
    acuan, r2_uji = mae_uji()
    contoh = any("contoh" in m for m in model)
    per = []
    for k, g in df.groupby("kode"):
        m = _metrik(g[TARGET], pred[g.index])
        rasio = m["mae"] / acuan if acuan else None
        per.append({"kode": k, "label": label(k), **m, "rasio": rasio,
                    "status": "-" if rasio is None else ("perhatian" if rasio > AMBANG_MAE else "normal")})
    total = _metrik(df[TARGET], pred)
    rasio = total["mae"] / acuan if acuan else None
    return {"per_bulan": per, "total": total, "mae_uji": acuan, "r2_uji": r2_uji, "rasio": rasio,
            "perhatian": rasio is not None and rasio > AMBANG_MAE, "model": ", ".join(sorted(model)),
            "contoh": contoh, "ambang": AMBANG_MAE}


# ----------------------------------------------------------------------------- simpan
def simpan_sementara(df, ringkasan):
    STAGING.mkdir(parents=True, exist_ok=True)
    for f in STAGING.glob("*"):          # bersihkan unggahan lama yang tidak jadi disimpan (> 1 hari)
        if (datetime.now().timestamp() - f.stat().st_mtime) > 86400:
            f.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    df.to_pickle(STAGING / f"{token}.pkl")
    (STAGING / f"{token}.json").write_text(json.dumps(ringkasan, ensure_ascii=False, default=float),
                                           encoding="utf-8")
    return token


def ambil_sementara(token):
    if not token.isalnum():
        return None, None
    f, j = STAGING / f"{token}.pkl", STAGING / f"{token}.json"
    if not (f.exists() and j.exists()):
        return None, None
    return pd.read_pickle(f), json.loads(j.read_text(encoding="utf-8"))


def hapus_sementara(token):
    for ext in ("pkl", "json"):
        (STAGING / f"{token}.{ext}").unlink(missing_ok=True)


def simpan(token, timpa=False):
    """Simpan data bulan baru ke basis data. Mengembalikan pesan ringkas."""
    df, ring = ambil_sementara(token)
    if df is None:
        raise ValueError("Data unggahan tidak ditemukan atau sudah kedaluwarsa. Silakan unggah ulang berkasnya.")
    fitur = est.FITUR
    ada = set(est.DATA["periode"])
    bulan = sorted(df["kode"].unique())
    tulis = [k for k in bulan if k not in ada or timpa]
    if not tulis:
        raise ValueError("Tidak ada bulan baru untuk disimpan. Centang 'timpa data lama' jika ingin mengganti data.")
    nama_cad = buat_cadangan("Sebelum unggah " + ", ".join(label(k) for k in tulis))

    con = _tulis()
    try:
        with con:
            kode_ke_id = dict(con.execute("SELECT kode, id FROM periode"))
            for k in tulis:
                if k not in kode_ke_id:
                    pid = con.execute("SELECT COALESCE(MAX(id), -1) + 1 FROM periode").fetchone()[0]
                    con.execute("INSERT INTO periode VALUES (?,?,?)", (pid, k, label(k)))
                    kode_ke_id[k] = pid
            sub = df[df["kode"].isin(tulis)]
            baris = [(int(r.id), kode_ke_id[r.kode], *(None if pd.isna(getattr(r, c)) else round(float(getattr(r, c)), 4)
                                                        for c in [TARGET] + fitur))
                     for r in sub.itertuples(index=False)]
            con.executemany(f"INSERT OR REPLACE INTO data_bulanan (wilayah_id, periode_id, {TARGET}, "
                            f"{', '.join(fitur)}) VALUES ({','.join('?' * (3 + len(fitur)))})", baris)
            ev = ring.get("eval") or {}
            waktu = datetime.now().strftime("%Y-%m-%d %H:%M")
            for e in ev.get("per_bulan", []):
                if e["kode"] in tulis:
                    con.execute("INSERT OR REPLACE INTO evaluasi_bulanan VALUES (?,?,?,?,?,?,?,?)",
                                (e["kode"], e["mae"], e["rmse"], e["r2"], e["n"], ev.get("mae_uji"),
                                 ev.get("model"), waktu))
            akurasi = ""
            if ev.get("total"):
                akurasi = f" MAE {_f(ev['total']['mae'], 4)}, R² {_f(ev['total']['r2'], 3)}."
            _catat(con, "Unggah data", f"{len(tulis)} bulan disimpan: {', '.join(label(k) for k in tulis)}"
                   f"{' (menimpa data lama)' if any(k in ada for k in tulis) else ''}.{akurasi}",
                   berkas=ring.get("berkas"), cadangan=nama_cad)
    finally:
        con.close()
    hapus_sementara(token)
    est.muat_ulang()
    pesan_peta = perbarui_beranda()
    est.muat_ulang()
    return {"bulan": [label(k) for k in tulis], "cadangan": nama_cad, "peta": pesan_peta}


# ----------------------------------------------------------------------------- peta Beranda
def perbarui_beranda():
    """Gambar ulang peta pratinjau dan angka ringkas Beranda (logika script 07) dari basis data."""
    rows = est._query(f"SELECT w.nama, w.provinsi_gaul, w.kelompok, p.kode, d.{TARGET} FROM data_bulanan d "
                      "JOIN wilayah w ON w.id = d.wilayah_id JOIN periode p ON p.id = d.periode_id")
    df = pd.DataFrame(rows, columns=["ADM2_NAME", "ADM1_NAME", "kelompok_wilayah", "kode", TARGET])
    df["periode"] = pd.to_datetime(df["kode"] + "-01")
    skrip = str(ROOT / "scripts")
    if skrip not in sys.path:
        sys.path.insert(0, skrip)
    try:
        modul = importlib.import_module("07_peta_beranda")
        r = modul.buat(df, cetak=lambda *a: None)
        return f"Peta Beranda diperbarui ke {r['periode_terbaru']}."
    except Exception as e:  # peta gagal tidak membatalkan data yang sudah tersimpan
        return f"Data tersimpan, tetapi peta Beranda gagal diperbarui: {e}"
