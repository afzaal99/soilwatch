"""
Fungsi bersama untuk daftar wilayah dan peta SVG (dipakai script 07 dan 08).

Sumber batas wilayah:
1. data/geo/batas_kabkota_gaul2025.geojson (hasil script 02 / GEE) -> dipakai jika ada.
   Batas FAO GAUL 2025 sama dengan dataset, sehingga 514 wilayah dicocokkan 1:1
   berdasarkan ADM2_NAME + ADM1_NAME.
2. Jika belum ada: data/geo/batas_pratinjau_gadm.json (GADM lama, 394 poligon), dicocokkan
   lewat nama yang dinormalkan. Hanya untuk pratinjau.
"""
import json
import math
import re

import pandas as pd

from config import ROOT

GEO_GAUL = ROOT / "data" / "geo" / "batas_kabkota_gaul2025.geojson"
GEO_GADM = ROOT / "data" / "geo" / "batas_pratinjau_gadm.json"
LON0, LON1, LAT0, LAT1 = 94.8, 141.2, -11.2, 6.3

NAMA_PROV = {"Dki Jakarta": "DKI Jakarta", "Daerah Istimewa Yogyakarta": "DI Yogyakarta"}  # nama tampilan
ALIAS = {"bulongan": "bulungan", "yapenwaropen": "yapen", "makassar": "makasar",
         "kepulauansangihetalaud": "kepulauansangihe", "bukittinggi": "bukitinggi",
         "adminkepulauanseribu": "jakartautara"}
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
         "September", "Oktober", "November", "Desember"]


def is_kota(nama):
    return nama.startswith("Kota ") and nama != "Kota Baru"   # Kota Baru = Kab. Kotabaru (Kalimantan Selatan)


LABEL_KHUSUS = {"Kota Baru": "Kab. Kotabaru", "Kepulauan Seribu": "Kab. Adm. Kepulauan Seribu"}


def label(nama):
    return LABEL_KHUSUS.get(nama) or (nama if is_kota(nama) else f"Kab. {nama}")


def norm(s):
    s = re.sub(r"[^a-z]", "", str(s).lower().replace("kota ", "").replace("kabupaten", ""))
    return ALIAS.get(s, s)


def label_periode(p):
    p = pd.Timestamp(p)
    return f"{BULAN[p.month - 1]} {p.year}"


def daftar_wilayah(df):
    """Tabel wilayah dengan id tetap (urut provinsi lalu nama, sama di semua script)."""
    wil = (df[["ADM2_NAME", "ADM1_NAME", "kelompok_wilayah"]].drop_duplicates()
           .sort_values(["ADM1_NAME", "ADM2_NAME"]).reset_index(drop=True))
    wil["id"] = range(len(wil))
    wil["prov"] = wil["ADM1_NAME"].map(lambda p: NAMA_PROV.get(p, p))
    wil["label"] = wil["ADM2_NAME"].map(label)
    return wil


def _cincin(geom):
    """Semua cincin (luar dan lubang) dari Polygon / MultiPolygon / GeometryCollection.
    Lubang (misalnya Pulau Samosir di tengah Danau Toba, atau kota di dalam kabupaten)
    ikut disimpan dan digambar dengan aturan isi 'evenodd' agar tetap berlubang."""
    if not geom:
        return []
    t = geom["type"]
    if t == "Polygon":
        return list(geom["coordinates"])
    if t == "MultiPolygon":
        return [r for p in geom["coordinates"] for r in p]
    if t == "GeometryCollection":
        return [c for g in geom["geometries"] for c in _cincin(g)]
    return []


def poligon_wilayah(wil):
    """Mengembalikan (sumber, [(id_wilayah atau None, [cincin, ...]), ...])."""
    if GEO_GAUL.exists():
        geo = json.loads(GEO_GAUL.read_text(encoding="utf-8"))
        idx = {(a, b): i for a, b, i in zip(wil["ADM2_NAME"], wil["ADM1_NAME"], wil["id"])}
        hasil = []
        for f in geo["features"]:
            p = f.get("properties") or {}
            hasil.append((idx.get((p.get("ADM2_NAME"), p.get("ADM1_NAME"))), _cincin(f.get("geometry"))))
        return "GAUL 2025", hasil

    kunci = {}
    for nm, i in zip(wil["ADM2_NAME"], wil["id"]):
        kunci.setdefault((norm(nm), is_kota(nm)), []).append(i)
    geo = json.loads(GEO_GADM.read_text(encoding="utf-8"))
    hasil = []
    for f in geo["features"]:
        p = f["properties"]
        kota = p.get("TYPE_2") == "Kotamadya" or p["NAME_2"].startswith("Kota ")
        ids = kunci.get((norm(p["NAME_2"]), kota)) or kunci.get((norm(p["NAME_2"]), not kota))
        hasil.append((ids[0] if ids else None, _cincin(f.get("geometry"))))
    return "GADM (pratinjau)", hasil


def proyektor(W, H, pad):
    s = min((W - 2 * pad) / (LON1 - LON0), (H - 2 * pad) / (LAT1 - LAT0))
    ox = pad + ((W - 2 * pad) - s * (LON1 - LON0)) / 2
    oy = pad + ((H - 2 * pad) - s * (LAT1 - LAT0)) / 2
    return lambda lon, lat: (ox + (lon - LON0) * s, oy + (LAT1 - lat) * s)


def path_d(cincin, proj, toleransi):
    """Atribut d SVG dari daftar cincin; titik yang terlalu rapat dibuang agar file ringan."""
    d = []
    for ring in cincin:
        pts, last = [], None
        for lon, lat in ring:
            x, y = proj(lon, lat)
            if last is None or abs(x - last[0]) + abs(y - last[1]) > toleransi:
                pts.append((x, y))
                last = (x, y)
        if len(pts) >= 3:
            d.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
    return "".join(d)


# ---------------------------------------------------------------- bentuk asli badan air dan gambut
GEO_AIR = ROOT / "data" / "geo" / "badan_air_besar.geojson"
GEO_GAMBUT = ROOT / "data" / "geo" / "sebaran_gambut.geojson"

# Titik acuan danau/waduk besar untuk memberi nama poligon hasil GEE (lintang, bujur perkiraan).
# Poligon yang memuat (atau sangat dekat dengan) titik ini diberi nama tersebut;
# poligon lain cukup diberi label "Badan air".
DANAU = [
    ("Danau Laut Tawar", 4.61, 96.93), ("Danau Toba", 2.60, 98.85), ("Danau Maninjau", -0.31, 100.20),
    ("Danau Singkarak", -0.62, 100.54), ("Danau Kerinci", -2.13, 101.48), ("Danau Ranau", -4.86, 103.93),
    ("Waduk Koto Panjang", 0.30, 100.78), ("Waduk Batutegi", -5.25, 104.78),
    ("Waduk Jatiluhur", -6.55, 107.37), ("Waduk Jatigede", -6.88, 108.09), ("Waduk Cirata", -6.72, 107.30), ("Waduk Saguling", -6.92, 107.40),
    ("Waduk Kedung Ombo", -7.26, 110.83), ("Rawa Pening", -7.29, 110.44), ("Waduk Gajah Mungkur", -7.88, 110.93),
    ("Danau Sentarum", 0.85, 112.10), ("Danau Sembuluh", -2.60, 112.37), ("Danau Semayang", -0.22, 116.47), ("Danau Melintang", -0.25, 116.32), ("Danau Jempang", -0.55, 116.20),
    ("Danau Tempe", -4.12, 119.93), ("Danau Sidenreng", -3.98, 119.83), ("Danau Lindu", -1.32, 120.08),
    ("Danau Poso", -1.90, 120.60), ("Danau Matano", -2.48, 121.35), ("Danau Mahalona", -2.60, 121.48),
    ("Danau Towuti", -2.78, 121.52), ("Danau Limboto", 0.58, 122.97), ("Danau Tondano", 1.25, 124.90),
    ("Danau Sentani", -2.61, 140.50), ("Danau Paniai", -3.90, 136.32), ("Danau Tage", -3.99, 136.31), ("Danau Tigi", -4.07, 136.27),
    ("Danau Yamur (Jamur)", -3.67, 134.93), ("Danau Rombebai", -1.85, 137.90),
]


def _di_dalam(lon, lat, ring):
    """Uji titik di dalam poligon (ray casting)."""
    ada, n = False, len(ring)
    for i in range(n):
        x1, y1 = ring[i][:2]
        x2, y2 = ring[(i + 1) % n][:2]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            ada = not ada
    return ada


def _kotak(cincin):
    xs = [p[0] for r in cincin for p in r]
    ys = [p[1] for r in cincin for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def _nama_danau(cincin):
    """Nama danau untuk satu poligon air. Titik acuan yang berada DI DALAM poligon diutamakan;
    jika tidak ada, dipilih titik acuan TERDEKAT (maksimal 0,08 derajat dari tepi poligon).
    Dengan begitu dua danau yang berdekatan (mis. Semayang dan Melintang) tidak tertukar."""
    x0, y0, x1, y1 = _kotak(cincin)
    terdekat, jarak_min = None, 0.08
    for nama, lat, lon in DANAU:
        if not (x0 - 0.08 <= lon <= x1 + 0.08 and y0 - 0.08 <= lat <= y1 + 0.08):
            continue
        if any(_di_dalam(lon, lat, r) for r in cincin):
            return nama
        jarak = min(abs(p[0] - lon) + abs(p[1] - lat) for r in cincin for p in r)
        if jarak < jarak_min:
            terdekat, jarak_min = nama, jarak
    return terdekat


def _daratan():
    """Poligon daratan (batas GAUL) beserta kotak pembatasnya, untuk uji 'di darat atau di laut'."""
    if not GEO_GAUL.exists():
        return None
    geo = json.loads(GEO_GAUL.read_text(encoding="utf-8"))
    return [(_kotak(c), c) for f in geo["features"] if (c := _cincin(f.get("geometry")))]


def _di_darat(x, y, darat):
    return any(x0 <= x <= x1 and y0 <= y <= y1 and sum(_di_dalam(x, y, r) for r in rr) % 2 == 1
               for (x0, y0, x1, y1), rr in darat)


JARAK_PANTAI = 0.05   # derajat (~5,5 km)
ARAH = [(1, 0), (-1, 0), (0, 1), (0, -1), (0.71, 0.71), (0.71, -0.71), (-0.71, 0.71), (-0.71, -0.71)]


def _porsi_laut(cincin, darat):
    """Porsi titik 'pengintai' yang jatuh di laut. Dari titik-titik tepi poligon air, dilihat 8 arah
    sejauh JARAK_PANTAI; titik yang tidak berada di daratan Indonesia mana pun dianggap laut
    (atau negara tetangga). Danau pedalaman -> 0; tambak, muara, pinggiran pantai -> > 0."""
    titik = cincin[0][:: max(1, len(cincin[0]) // 30)]
    uji = [(x + dx * JARAK_PANTAI, y + dy * JARAK_PANTAI) for x, y in titik for dx, dy in ARAH]
    uji = [(x, y) for x, y in uji if not any(_di_dalam(x, y, r) for r in cincin)]   # bukan di danau itu
    if not uji:
        return 0
    return sum(not _di_darat(x, y, darat) for x, y in uji) / len(uji)


HANYA_BERNAMA = True  # peta hanya menampilkan danau/waduk yang sudah dikenali namanya (daftar DANAU)
LEBAR_MIN_KM = 1.0   # badan air tak bernama dengan lebar rata-rata < 1 km dianggap sungai


def _lebar_km(cincin, luas):
    """Lebar rata-rata = 2 x luas / keliling. Sungai: panjang dan sempit (< 1 km);
    danau/waduk: lebar beberapa km (contoh Danau Sembuluh 78 km2 / 35,7 km ~ 2 km)."""
    kel = 0.0
    for r in cincin:
        for (x1, y1), (x2, y2) in zip([p[:2] for p in r], [p[:2] for p in r[1:]]):
            dx = (x2 - x1) * 111.32 * math.cos(math.radians((y1 + y2) / 2))
            kel += math.hypot(dx, (y2 - y1) * 110.57)
    return 2 * luas / kel if kel else 0


# Danau yang poligonnya ikut menempel ke sungai di sekitarnya (dataran banjir). Lengan sempit
# (< ~2 x RADIUS_LENGAN_KM) dibuang dan hanya badan air utamanya yang disimpan.
BERSIHKAN_LENGAN = {"Danau Rombebai"}
RADIUS_LENGAN_KM = 0.6


def _buang_lengan(cincin, radius_km=RADIUS_LENGAN_KM, piksel_km=0.1):
    """Membuang lengan sempit (sungai) dari poligon danau dengan 'opening' morfologi:
    poligon dijadikan raster halus, dikikis lalu ditebalkan kembali, komponen terbesar diambil,
    lalu dijadikan poligon lagi. Mengembalikan (cincin_baru, luas_km2) atau None jika gagal."""
    try:
        import numpy as np
        from contourpy import contour_generator
        from matplotlib.path import Path as MPath
        from scipy import ndimage
    except ImportError:
        return None
    x0, y0, x1, y1 = _kotak(cincin)
    lat0 = (y0 + y1) / 2
    dx = piksel_km / (111.32 * math.cos(math.radians(lat0)))
    dy = piksel_km / 110.57
    xs = np.arange(x0 - 2 * dx, x1 + 2 * dx, dx)
    ys = np.arange(y0 - 2 * dy, y1 + 2 * dy, dy)
    gx, gy = np.meshgrid(xs, ys)
    titik = np.column_stack([gx.ravel(), gy.ravel()])
    isi = np.zeros(len(titik), dtype=int)
    for r in cincin:                                    # aturan evenodd: lubang ikut terhitung
        isi += MPath(np.asarray(r)[:, :2]).contains_points(titik)
    m = (isi % 2 == 1).reshape(gx.shape)
    n = max(1, round(radius_km / piksel_km))
    yy, xx = np.ogrid[-n:n + 1, -n:n + 1]
    m = ndimage.binary_opening(m, structure=(xx * xx + yy * yy) <= n * n)
    lab, k = ndimage.label(m)
    if k == 0:
        return None
    ukuran = ndimage.sum(m, lab, range(1, k + 1))
    utama = lab == (1 + int(np.argmax(ukuran)))
    garis = contour_generator(x=xs, y=ys, z=utama.astype(float)).lines(0.5)
    baru = [[[float(a), float(b)] for a, b in g] for g in garis if len(g) >= 4]
    if not baru:
        return None
    return baru, float(utama.sum() * piksel_km ** 2)


def lapisan_lahan(laporan=False):
    """Bentuk asli badan air besar dan sebaran gambut (jika file hasil script 02 ada).
    Mengembalikan {'air': [(nama, luas_km2, cincin)], 'gambut': [(None, luas_km2, cincin)]}.

    Badan air tak bernama yang berada di laut atau dalam ~5,5 km dari laut dibuang. Ini menyaring
    tambak, muara/alur pasang surut, pinggiran pantai, terumbu, dan danau di negara tetangga,
    yang oleh WorldCover dikelaskan air. Lapisan ini khusus danau/waduk pedalaman.
    Badan air tak bernama yang memanjang dan sempit (lebar rata-rata < LEBAR_MIN_KM) dianggap
    SUNGAI lebar (mis. Kapuas, Landak) dan juga dibuang.
    Danau yang namanya dikenal (daftar DANAU) selalu dipertahankan."""
    hasil = {"air": [], "gambut": []}
    sungai, lain = [], []
    darat = _daratan()
    dibuang = []
    for jenis, f in [("air", GEO_AIR), ("gambut", GEO_GAMBUT)]:
        if not f.exists():
            continue
        for ft in json.loads(f.read_text(encoding="utf-8"))["features"]:
            cincin = _cincin(ft.get("geometry"))
            if not cincin:
                continue
            luas = float((ft.get("properties") or {}).get("luas_km2") or 0)
            nama = _nama_danau(cincin) if jenis == "air" else None
            if jenis == "air" and not nama and darat:
                porsi = _porsi_laut(cincin, darat)
                if porsi > 0:
                    x0, y0, x1, y1 = _kotak(cincin)
                    dibuang.append((round((y0 + y1) / 2, 2), round((x0 + x1) / 2, 2), round(luas), porsi))
                    continue
                lebar = _lebar_km(cincin, luas)
                if lebar < LEBAR_MIN_KM:
                    x0, y0, x1, y1 = _kotak(cincin)
                    sungai.append((round((y0 + y1) / 2, 2), round((x0 + x1) / 2, 2), round(luas), lebar))
                    continue
                if HANYA_BERNAMA:
                    lain.append((round((_kotak(cincin)[1] + _kotak(cincin)[3]) / 2, 2),
                                 round((_kotak(cincin)[0] + _kotak(cincin)[2]) / 2, 2), round(luas), lebar))
                    continue
            if nama in BERSIHKAN_LENGAN:
                bersih = _buang_lengan(cincin)
                if bersih:
                    if laporan:
                        print(f"{nama}: lengan sungai dibuang, luas {luas:.0f} -> {bersih[1]:.0f} km2")
                    cincin, luas = bersih
            hasil[jenis].append((nama, luas, cincin))
        hasil[jenis].sort(key=lambda t: -t[1])
    if laporan and dibuang:
        print(f"{len(dibuang)} badan air pesisir/laut dibuang (lintang, bujur, luas km2, porsi pengintai di laut):")
        for d in dibuang:
            print(f"   {d[0]:>6}, {d[1]:>7}  {d[2]:>5} km2  {d[3]:.0%}")
    if laporan and sungai:
        print(f"{len(sungai)} sungai lebar dibuang (lintang, bujur, luas km2, lebar rata-rata km):")
        for d in sungai:
            print(f"   {d[0]:>6}, {d[1]:>7}  {d[2]:>5} km2  {d[3]:.2f}")
    if laporan and lain:
        print(f"{len(lain)} badan air pedalaman tak bernama TIDAK ditampilkan (lintang, bujur, luas km2, lebar km):")
        for x in lain:
            print(f"   {x[0]:>6}, {x[1]:>7}  {x[2]:>5} km2  {x[3]:.2f}")
    if laporan:
        print("Danau bernama (nama, lintang, bujur, luas km2):")
        for nama, luas, c in hasil["air"]:
            if nama:
                x0, y0, x1, y1 = _kotak(c)
                print(f"   {nama:<22} {(y0 + y1) / 2:>6.2f}, {(x0 + x1) / 2:>7.2f}  {luas:>5.0f} km2")
        sisa = [t for t in hasil["air"] if not t[0]]
        print(f"{len(sisa)} badan air tak bernama dipertahankan (lintang, bujur, luas km2, lebar km):")
        for _, luas, c in sisa:
            x0, y0, x1, y1 = _kotak(c)
            print(f"   {(y0 + y1) / 2:>6.2f}, {(x0 + x1) / 2:>7.2f}  {luas:>5.0f} km2  {_lebar_km(c, luas):.2f}")
    return hasil


def danau_per_wilayah(poli, danau):
    """Nama danau yang (sebagian) berada di dalam setiap wilayah: {id_wilayah: [nama, ...]}."""
    kotak = {}
    for wid, cincin in poli:
        if wid is not None and cincin:
            kotak.setdefault(wid, []).append((_kotak(cincin), cincin))
    hasil = {}
    for nama, _, cincin in danau:
        if not nama:
            continue
        titik = [p for r in cincin for p in r]
        titik = titik[:: max(1, len(titik) // 60)]
        for wid, daftar in kotak.items():
            for (x0, y0, x1, y1), rr in daftar:
                if any(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and any(_di_dalam(p[0], p[1], r) for r in rr)
                       for p in titik):
                    if nama not in hasil.setdefault(wid, []):
                        hasil[wid].append(nama)
                    break
    return hasil
