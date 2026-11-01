"""
02b - Proporsi lahan gambut per kabupaten/kota (Peta Lahan Gambut Indonesia, Kementan 2019)
=========================================================================================
Sumber : Trase, "Indonesia - Peatland area (kabupaten)", diturunkan dari Peta Lahan Gambut
         Indonesia Skala 1:50.000 Edisi Desember 2019 (BBSDLP, Kementerian Pertanian).
         https://trase.earth/open-data/datasets/spatial-metrics-indonesia-peat-area
Masukan: data/geo/gambut_kabupaten_trase.csv   (file unduhan Trase, 514 kabupaten/kota)
         data/geo/batas_kabkota_gaul2025.geojson (hasil script 02, untuk luas wilayah)
         data/geo/penanda_lahan_kabkota.csv     (hasil script 02)
Keluaran: kolom prop_gambut dan penanda_gambut ditambahkan ke penanda_lahan_kabkota.csv
          reports/02b_gambut_per_wilayah.csv    (rincian per wilayah, untuk pengecekan)

Langkah:
1. Ambil luas gambut (hektar) per kabupaten/kota Trase. Luas gambut sama untuk semua tahun
   (peta 2019 yang sama), jadi cukup satu tahun.
2. Cocokkan 514 kabupaten/kota Trase ke 514 wilayah GAUL 2025 berdasarkan nama.
   Pembagian wilayahnya sama, jadi cocok 1:1; hanya 9 nama yang ditulis berbeda (tabel ALIAS).
3. prop_gambut = luas gambut / luas wilayah GAUL 2025 (dihitung dari poligonnya).
4. penanda_gambut = 1 jika prop_gambut >= 20%.
"""
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_PROCESSED, REPORTS, ROOT
from peta import daftar_wilayah

GEO = ROOT / "data" / "geo"
TRASE = GEO / "gambut_kabupaten_trase.csv"
GAUL = GEO / "batas_kabkota_gaul2025.geojson"
PENANDA = GEO / "penanda_lahan_kabkota.csv"
AMBANG = 0.20

# Nama Trase yang ditulis berbeda dengan GAUL 2025 (nama Trase -> ADM2_NAME GAUL 2025)
ALIAS = {
    "ADMINISTRASI KEPULAUAN SERIBU": "Kepulauan Seribu",
    "KOTA ADMINISTRASI JAKARTA BARAT": "Kota Jakarta Barat",
    "KOTA ADMINISTRASI JAKARTA PUSAT": "Kota Jakarta Pusat",
    "KOTA ADMINISTRASI JAKARTA SELATAN": "Kota Jakarta Selatan",
    "KOTA ADMINISTRASI JAKARTA TIMUR": "Kota Jakarta Timur",
    "KOTA ADMINISTRASI JAKARTA UTARA": "Kota Jakarta Utara",
    "KEP. SIAU TAGULANDANG BIARO": "Siau Tagulandang Biaro",
    "MAHAKAM ULU": "Mahakam Hulu",
    "TOBA": "Toba Samosir",
}


def norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


def luas_km2(geom):
    """Luas poligon GeoJSON (km2), proyeksi sinusoidal lokal; cincin pertama = luar, sisanya lubang."""
    def cincin(r):
        lat0 = sum(p[1] for p in r) / len(r)
        k = math.cos(math.radians(lat0))
        xy = [(p[0] * 111.32 * k, p[1] * 110.57) for p in r]
        return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]))) / 2

    def poli(rs):
        return cincin(rs[0]) - sum(cincin(r) for r in rs[1:])
    t = geom["type"]
    if t == "Polygon":
        return poli(geom["coordinates"])
    if t == "MultiPolygon":
        return sum(poli(p) for p in geom["coordinates"])
    if t == "GeometryCollection":
        return sum(luas_km2(g) for g in geom["geometries"])
    return 0.0


def main():
    for f in [TRASE, GAUL, PENANDA]:
        if not f.exists():
            raise SystemExit(f"File belum ada: {f}")

    wil = daftar_wilayah(pd.read_csv(DATA_PROCESSED / "dataset_bersih.csv"))
    idx = {norm(a): (a, b) for a, b in zip(wil["ADM2_NAME"], wil["ADM1_NAME"])}

    # luas wilayah GAUL 2025
    luas = {}
    for ft in json.loads(GAUL.read_text(encoding="utf-8"))["features"]:
        p = ft["properties"]
        k = (p["ADM2_NAME"], p["ADM1_NAME"])
        luas[k] = luas.get(k, 0) + luas_km2(ft["geometry"])

    # luas gambut Trase (satu tahun saja; nilainya sama di semua tahun)
    t = pd.read_csv(TRASE)
    t = t[t["year"] == t["year"].max()]
    gambut, tak_cocok = {}, []
    for nama, ha in zip(t["region"], t["peatland_area_hectares"]):
        k = idx.get(norm(ALIAS.get(nama, nama)))
        if k is None:
            tak_cocok.append((nama, ha))
            continue
        gambut[k] = gambut.get(k, 0) + ha / 100          # hektar -> km2

    total = t["peatland_area_hectares"].sum() / 100
    hilang = sum(ha for _, ha in tak_cocok) / 100
    print(f"Total gambut Trase: {total:,.0f} km2; tercocokkan: {total - hilang:,.0f} km2 "
          f"({100 * (1 - hilang / total):.2f}%)")
    bergambut = [(n, ha) for n, ha in tak_cocok if ha > 0]
    if bergambut:
        print("PERINGATAN, kabupaten bergambut belum tercocokkan (tambahkan ke ALIAS):")
        for n, ha in bergambut:
            print(f"   {n}: {ha:,.0f} ha")

    rinci = []
    for a, b in zip(wil["ADM2_NAME"], wil["ADM1_NAME"]):
        g, l = gambut.get((a, b), 0.0), luas.get((a, b), float("nan"))
        rinci.append({"ADM2_NAME": a, "ADM1_NAME": b, "luas_wilayah_km2": l, "luas_gambut_km2": g,
                      "prop_gambut": min(g / l, 1.0) if l else 0.0})
    rinci = pd.DataFrame(rinci)
    rinci["penanda_gambut"] = (rinci["prop_gambut"] >= AMBANG).astype(int)
    lebih = rinci[rinci["luas_gambut_km2"] > 1.05 * rinci["luas_wilayah_km2"]]
    if len(lebih):
        print("Catatan: luas gambut > luas wilayah GAUL (batas berbeda), dipotong ke 100%:")
        print(lebih[["ADM2_NAME", "luas_wilayah_km2", "luas_gambut_km2"]].round(0).to_string(index=False))
    rinci.sort_values("prop_gambut", ascending=False).round(4).to_csv(
        REPORTS / "02b_gambut_per_wilayah.csv", index=False)

    p = pd.read_csv(PENANDA).drop(columns=["prop_gambut", "penanda_gambut"], errors="ignore")
    p = p.merge(rinci[["ADM2_NAME", "ADM1_NAME", "prop_gambut", "penanda_gambut"]],
                on=["ADM2_NAME", "ADM1_NAME"], how="left")
    p[["prop_gambut", "penanda_gambut"]] = p[["prop_gambut", "penanda_gambut"]].fillna(0)
    p.to_csv(PENANDA, index=False)

    print(f"Wilayah bergambut: {(rinci['prop_gambut'] > 0).sum()}; gambut >= {AMBANG:.0%}: "
          f"{rinci['penanda_gambut'].sum()} wilayah")
    print("10 wilayah dengan proporsi gambut terbesar:")
    print(rinci.nlargest(10, "prop_gambut")[["ADM2_NAME", "ADM1_NAME", "prop_gambut"]]
          .assign(prop_gambut=lambda d: (100 * d["prop_gambut"]).round(1).astype(str) + "%").to_string(index=False))
    print(f"-> kolom prop_gambut ditambahkan ke {PENANDA}")


if __name__ == "__main__":
    main()
