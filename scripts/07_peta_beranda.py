"""
07 - Peta pratinjau dan angka ringkas untuk halaman Beranda
============================================================
Mewarnai setiap kabupaten/kota dengan soil moisture SMAP L4 bulan terbaru di dataset.

Batas wilayah: FAO GAUL 2025 (data/geo/batas_kabkota_gaul2025.geojson, hasil script 02)

Keluaran: app/static/img/peta_beranda.svg, app/static/data/ringkasan_beranda.json

Fungsi buat(df) juga dipanggil dashboard admin setiap kali data bulan baru disimpan,
dengan data yang dibaca dari basis data aplikasi.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_PROCESSED, ROOT, TARGET
from peta import daftar_wilayah, label_periode, lapisan_lahan, path_d, poligon_wilayah, proyektor

OUT_SVG = ROOT / "app" / "static" / "img" / "peta_beranda.svg"
OUT_JSON = ROOT / "app" / "static" / "data" / "ringkasan_beranda.json"
W, H, PAD = 760, 300, 4
RAMP = ["#8c510a", "#bf812d", "#dfc27d", "#f1e5c4", "#c7eae5", "#80cdc1", "#35978f", "#01665e"]
VMIN, VMAX = 0.10, 0.50  # skala legenda (m3/m3)


def warna(v):
    if v is None or pd.isna(v):
        return "#E2E8F0"
    t = min(max((v - VMIN) / (VMAX - VMIN), 0), 0.999)
    return RAMP[int(t * len(RAMP))]


def buat(df, cetak=print):
    """df: kolom ADM2_NAME, ADM1_NAME, kelompok_wilayah, periode (datetime), soil_moisture."""
    akhir = df["periode"].max()
    wil = daftar_wilayah(df)
    terakhir = df[df["periode"] == akhir].merge(wil, on=["ADM2_NAME", "ADM1_NAME"])
    nilai = dict(zip(terakhir["id"], terakhir[TARGET]))
    lab = dict(zip(wil["id"], wil["label"]))

    sumber, poli = poligon_wilayah(wil)
    proj = proyektor(W, H, PAD)
    paths = []
    for wid, cincin in poli:
        # wilayah sangat kecil (mis. Kota Sibolga ~11 km2) bisa hilang saat titik dirampingkan -> tanpa perampingan
        d = path_d(cincin, proj, 0.6) or path_d(cincin, proj, 0)
        if not d:
            continue
        v = nilai.get(wid) if wid is not None else None
        judul = f"{lab[wid]}: {v:.2f} m³/m³".replace(f"{v:.2f}", f"{v:.2f}".replace(".", ",")) \
            if v is not None else lab.get(wid, "")
        paths.append(f'<path d="{d}" fill="{warna(v)}"><title>{judul}</title></path>')
    # danau/waduk besar (bentuk asli dari script 02, jika ada)
    danau = []
    for nama, luas, cincin in lapisan_lahan()["air"]:
        d = path_d(cincin, proj, 0.4)
        if d:
            danau.append(f'<path d="{d}"><title>{nama or "Badan air"}</title></path>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Peta soil moisture Indonesia {label_periode(akhir)}">'
           f'<g stroke="#fff" stroke-width="0.3" stroke-linejoin="round" fill-rule="evenodd">{"".join(paths)}</g>'
           + (f'<g fill="#2563EB" stroke="#fff" stroke-width="0.2" fill-rule="evenodd">{"".join(danau)}</g>' if danau else "")
           + '</svg>')
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")

    ringkasan = {
        "periode_terbaru": label_periode(akhir),
        "periode_awal": label_periode(df["periode"].min()),
        "jumlah_wilayah": int(len(wil)),
        "jumlah_bulan": int(df["periode"].nunique()),
        "rata2_nasional": round(float(df.loc[df["periode"] == akhir, TARGET].mean()), 3),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(ringkasan, ensure_ascii=False, indent=1), encoding="utf-8")
    cetak(ringkasan)
    cetak(f"batas wilayah: {sumber}, {len(paths)} poligon -> {OUT_SVG}")
    return ringkasan


def main():
    buat(pd.read_csv(DATA_PROCESSED / "dataset_bersih.csv", parse_dates=["periode"]))


if __name__ == "__main__":
    main()
