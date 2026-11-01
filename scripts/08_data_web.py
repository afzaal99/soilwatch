"""
08 - Basis data dan peta untuk aplikasi web (Arsitektur Data, Bab 1)
====================================================================
Memindahkan data hasil pra-pemrosesan ke basis data SQLite yang dibaca aplikasi Flask.
Aplikasi mengambil seluruh data (peta, estimasi otomatis, tren) dari basis data ini,
tanpa koneksi langsung ke Google Earth Engine.

Keluaran:
  app/data/soilwatch.db           basis data SQLite:
      wilayah        514 kabupaten/kota (FAO GAUL 2025) + penanda lahan (gambut, badan air, pertanian)
      periode        42 bulan
      data_bulanan   soil moisture SMAP + 12 variabel per wilayah per bulan (514 x 42 = 21.588 baris)
      meta           statistik data latih, kepentingan variabel (SHAP), pilihan model, dll.
  app/static/img/peta_wilayah.svg peta interaktif, setiap poligon diberi data-id wilayah, ditambah
                                  bentuk asli danau/waduk besar dan sebaran gambut (jika file hasil
                                  script 02 badan_air_besar.geojson / sebaran_gambut.geojson ada)

Penanda lahan:
  Jika data/geo/penanda_lahan_kabkota.csv (hasil script 02 / GEE) sudah ada, nilainya dipakai
  (kolom prop_gambut boleh tidak ada, prop_badan_air, prop_pertanian).
  Jika belum, dibuat NILAI CONTOH sementara (ditandai penanda_contoh = 1).

Jalankan ulang setiap kali data, hasil SHAP (script 06), atau hasil GEE berubah.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_PROCESSED, FITUR, REPORTS, ROOT, TARGET
from peta import (danau_per_wilayah, daftar_wilayah, label_periode, lapisan_lahan, path_d,
                  poligon_wilayah, proyektor)

PENANDA = ROOT / "data" / "geo" / "penanda_lahan_kabkota.csv"
OUT_DB = ROOT / "app" / "data" / "soilwatch.db"
OUT_SVG = ROOT / "app" / "static" / "img" / "peta_wilayah.svg"
W, H, PAD = 1200, 600, 6


def r(x, n=4):
    return None if pd.isna(x) else round(float(x), n)


def penanda_contoh(nama, prov, sm_rata):
    """Nilai sementara sebelum hasil GEE tersedia. BUKAN data sebenarnya."""
    h = int(hashlib.md5(nama.encode()).hexdigest(), 16)
    prov_gambut = {"Riau", "Jambi", "Sumatera Selatan", "Kalimantan Barat", "Kalimantan Tengah",
                   "Kalimantan Selatan", "Papua"}
    gambut = max(0.0, min(80.0, (sm_rata - 0.40) * 300)) if prov in prov_gambut else 0.0
    air = (h % 9) + (25 if sm_rata > 0.55 and h % 3 == 0 else 0)
    tani = 10 + (h // 9) % 55
    return round(gambut), round(air), round(tani)


def hitung_penanda(wil, df):
    contoh = not PENANDA.exists()
    sm_rata = df.groupby("id")[TARGET].mean()
    if not contoh:
        pl = pd.read_csv(PENANDA).drop_duplicates(["ADM2_NAME", "ADM1_NAME"]).set_index(["ADM2_NAME", "ADM1_NAME"])
    hasil, hilang = [], 0
    for _, w in wil.iterrows():
        if contoh:
            hasil.append(penanda_contoh(w["ADM2_NAME"], w["prov"], float(sm_rata[w["id"]])))
        elif (w["ADM2_NAME"], w["ADM1_NAME"]) in pl.index:
            row = pl.loc[(w["ADM2_NAME"], w["ADM1_NAME"])]
            hasil.append(tuple(0 if pd.isna(row.get(c, 0)) else round(100 * float(row.get(c, 0)))
                               for c in ["prop_gambut", "prop_badan_air", "prop_pertanian"]))
        else:
            hilang += 1
            hasil.append((0, 0, 0))
    if hilang:
        print(f"Peringatan: {hilang} wilayah tidak ditemukan di file penanda (nama berbeda).")
    return hasil, contoh


def meta_model(latih):
    stat = {}
    for f in FITUR + [TARGET]:
        s = latih[f]
        stat[f] = {"mean": r(s.mean()), "std": r(s.std()), "min": r(s.min()), "max": r(s.max()),
                   "median": r(s.median())}
    stat[TARGET]["p33"] = r(latih[TARGET].quantile(1 / 3))
    stat[TARGET]["p67"] = r(latih[TARGET].quantile(2 / 3))

    # model cadangan sementara (dipakai aplikasi hanya jika belum ada model sama sekali)
    X = (latih[FITUR] - latih[FITUR].mean()) / latih[FITUR].std()
    A = np.column_stack([np.ones(len(X)), X.values])
    koef, *_ = np.linalg.lstsq(A, latih[TARGET].values, rcond=None)

    pilihan = {}
    for f_pilih, kol in [(REPORTS / "05_nasional_vs_regional.csv", "kelompok"),
                         (REPORTS / "03_nasional_vs_regional_rf.csv", "dievaluasi_pada")]:
        if f_pilih.exists():
            t = pd.read_csv(f_pilih)
            pilihan = dict(zip(t[kol], t["model_dipakai"]))
            break

    f_shap, f_mdi = REPORTS / "06_shap_global.csv", REPORTS / "03_mdi_rf_nasional.csv"
    if f_shap.exists():
        kepentingan = pd.read_csv(f_shap).set_index("variabel")["mean_abs_shap"].round(6).to_dict()
        sumber = "shap"
    elif f_mdi.exists():
        kepentingan = pd.read_csv(f_mdi).set_index("variabel")["mdi"].round(4).to_dict()
        sumber = "mdi"
    else:
        kepentingan, sumber = {f: round(1 / len(FITUR), 4) for f in FITUR}, "contoh"

    return {"fitur": FITUR, "stat": stat,
            "linear": {"intercept": float(koef[0]), "koef": [float(k) for k in koef[1:]]},
            "pilihan_model": pilihan, "kepentingan": kepentingan, "sumber_kepentingan": sumber}


def tulis_db(wil, penanda, contoh, periode, df, meta, danau_w):
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DB.exists():
        OUT_DB.unlink()
    con = sqlite3.connect(OUT_DB)
    kol_fitur = ", ".join(f"{f} REAL" for f in FITUR)
    con.executescript(f"""
        CREATE TABLE wilayah (
            id INTEGER PRIMARY KEY, nama TEXT NOT NULL, provinsi_gaul TEXT NOT NULL,
            provinsi TEXT NOT NULL, label TEXT NOT NULL, kelompok TEXT NOT NULL,
            persen_gambut INTEGER, persen_badan_air INTEGER, persen_pertanian INTEGER,
            danau TEXT, UNIQUE (nama, provinsi_gaul));
        CREATE TABLE periode (id INTEGER PRIMARY KEY, kode TEXT UNIQUE NOT NULL, label TEXT NOT NULL);
        CREATE TABLE data_bulanan (
            wilayah_id INTEGER NOT NULL REFERENCES wilayah(id),
            periode_id INTEGER NOT NULL REFERENCES periode(id),
            soil_moisture REAL, {kol_fitur},
            PRIMARY KEY (wilayah_id, periode_id));
        CREATE TABLE meta (kunci TEXT PRIMARY KEY, nilai TEXT NOT NULL);
    """)
    con.executemany("INSERT INTO wilayah VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(int(w["id"]), w["ADM2_NAME"], w["ADM1_NAME"], w["prov"], w["label"],
                      w["kelompok_wilayah"], *pn, ", ".join(danau_w.get(int(w["id"]), [])) or None)
                     for (_, w), pn in zip(wil.iterrows(), penanda)])
    con.executemany("INSERT INTO periode VALUES (?,?,?)",
                    [(i, pd.Timestamp(p).strftime("%Y-%m"), label_periode(p)) for i, p in enumerate(periode)])
    pid = {p: i for i, p in enumerate(periode)}
    baris = [(int(a), pid[p], *(r(v) for v in vals))
             for a, p, *vals in df[["id", "periode", TARGET] + FITUR].itertuples(index=False)]
    con.executemany(f"INSERT INTO data_bulanan VALUES ({','.join('?' * (3 + len(FITUR)))})", baris)
    meta["penanda_contoh"] = contoh
    con.executemany("INSERT INTO meta VALUES (?,?)",
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM data_bulanan").fetchone()[0]
    con.close()
    return n


def tulis_peta(poli, lapis):
    proj = proyektor(W, H, PAD)
    per_wilayah, kosong = {}, []
    for wid, cincin in poli:              # satu wilayah bisa terdiri dari beberapa fitur: digabung
        (kosong if wid is None else per_wilayah.setdefault(wid, [])).extend(cincin)
    paths, cocok = [], set()
    for wid, cincin in per_wilayah.items():
        # wilayah sangat kecil (mis. Kota Sibolga ~11 km2) bisa hilang saat titik dirampingkan -> tanpa perampingan
        d = path_d(cincin, proj, 0.5) or path_d(cincin, proj, 0)
        if d:
            cocok.add(wid)
            paths.append(f'<path data-id="{wid}" d="{d}"/>')
    d = path_d(kosong, proj, 0.5)
    if d:
        paths.insert(0, f'<path class="kosong" d="{d}"/>')
    gambut = "".join(f'<path d="{d}"/>' for _, _, c in lapis["gambut"] if (d := path_d(c, proj, 0.4)))
    air = []
    for nama, luas, c in lapis["air"]:
        d = path_d(c, proj, 0.4)
        if d:
            judul = nama or "Badan air"
            luas_teks = f"{luas:,.0f}".replace(",", ".")
            air.append(f'<path class="danau" d="{d}" data-nama="{judul}" data-luas="{luas_teks}">'
                       f'<title>{judul} (±{luas_teks} km²)</title></path>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" id="peta" '
           f'role="img" aria-label="Peta kabupaten/kota Indonesia">'
           f'<defs><pattern id="arsir" width="2.4" height="2.4" patternUnits="userSpaceOnUse" '
           f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="2.4" stroke="#1f2937" '
           f'stroke-width="0.6" stroke-opacity=".6"/></pattern></defs>'
           f'<g id="lapisan">{"".join(paths)}</g>'
           + (f'<g id="gambut-asli">{gambut}</g>' if gambut else "")
           + (f'<g id="air-asli">{"".join(air)}</g>' if air else "") + '</svg>')
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    return len(paths), len(cocok)


def main():
    df = pd.read_csv(DATA_PROCESSED / "dataset_bersih.csv", parse_dates=["periode"])
    periode = sorted(pd.Timestamp(p) for p in df["periode"].unique())
    wil = daftar_wilayah(df)
    df = df.merge(wil[["ADM2_NAME", "ADM1_NAME", "id"]], on=["ADM2_NAME", "ADM1_NAME"])

    penanda, contoh = hitung_penanda(wil, df)
    sumber, poli = poligon_wilayah(wil)
    lapis = lapisan_lahan(laporan=True)
    danau_w = danau_per_wilayah(poli, lapis["air"])
    meta = meta_model(df[df["subset"] == "latih"])
    meta["lapisan_air"] = len(lapis["air"])
    meta["lapisan_gambut"] = len(lapis["gambut"])
    n = tulis_db(wil, penanda, contoh, periode, df, meta, danau_w)
    n_poli, n_cocok = tulis_peta(poli, lapis)

    print(f"kepentingan variabel global: {meta['sumber_kepentingan']}")
    print(f"basis data: {len(wil)} wilayah, {len(periode)} bulan, {n:,} baris data bulanan; "
          f"penanda lahan {'CONTOH' if contoh else 'GEE'}")
    print(f"peta ({sumber}): {n_poli} poligon, {n_cocok} dari {len(wil)} wilayah punya poligon sendiri")
    bernama = sorted({nm for nm, _, _ in lapis["air"] if nm})
    print(f"bentuk asli: {len(lapis['air'])} badan air besar ({len(bernama)} bernama: {', '.join(bernama[:8])}"
          f"{'...' if len(bernama) > 8 else ''}), {len(lapis['gambut'])} poligon gambut")
    print(f"-> {OUT_DB}\n-> {OUT_SVG}")


if __name__ == "__main__":
    main()
