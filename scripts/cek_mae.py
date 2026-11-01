"""Diagnostik: kenapa MAE model lama Jul-Sep berbeda antara halaman Unggah dan halaman Model.

Jalankan dari folder soilwatch:
    python scripts/cek_mae.py "C:\\path\\ke\\SoilMoisture_2026_07_sd_2026_09.csv"
(path CSV boleh dikosongkan; bagian B dilewati)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import estimasi as est  # noqa: E402
import pembaruan as pb  # noqa: E402
import latih_ulang as lu  # noqa: E402

BULAN = sys.argv[2].split(",") if len(sys.argv) > 2 else ["2026-07", "2026-08", "2026-09"]


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def per_bulan(df, kol="pred"):
    return {k: round(mae(g["soil_moisture"], g[kol]), 4) for k, g in df.groupby("kode")}


print("Pendekatan model:", est.KONF.get("pendekatan") if est.KONF else None)

# A. evaluasi yang tersimpan waktu upload
print("\nA. Tersimpan di evaluasi_bulanan (dihitung waktu upload):")
for r in est._query("SELECT * FROM evaluasi_bulanan ORDER BY 1"):
    print("  ", r[:5])

# B. hitung ulang dari basis data (cara halaman Model)
d = lu._data()
nbaris = est._query("SELECT COUNT(*) FROM data_bulanan d JOIN periode p ON p.id=d.periode_id "
                    f"WHERE p.kode IN ({','.join('?' * len(BULAN))})", BULAN)[0][0]
u = d[d["kode"].isin(BULAN)].copy()
u["pred"], _ = pb._prediksi(u)
print(f"\nB. Dari basis data: {len(u)} baris dipakai (di DB ada {nbaris}).")
print("   MAE total", round(mae(u["soil_moisture"], u["pred"]), 4), "per bulan", per_bulan(u))

# C. laporan kandidat
for f in sorted((ROOT / "instance" / "model" / "kandidat").glob("*/laporan.json")):
    j = json.loads(f.read_text(encoding="utf-8"))
    print(f"\nC. Kandidat {j['id']}: uji {j['uji']}")
    print("   lama per bulan", {k: round(v["MAE"], 4) for k, v in j["lama"]["per_bulan"].items()},
          "total", round(j["lama"]["Indonesia"]["MAE"], 4), "n", j["lama"]["Indonesia"]["n"])

# D. ulangi pemeriksaan CSV (cara halaman Unggah) dan bandingkan nilainya dengan DB
if len(sys.argv) > 1:
    isi = Path(sys.argv[1]).read_bytes()
    bersih, ring = pb.periksa(isi, Path(sys.argv[1]).name)
    if bersih is None:
        print("\nD. CSV gagal diperiksa:", ring["laporan"]["galat"])
    else:
        b = bersih[bersih["kode"].isin(BULAN)].copy()
        b["pred"], _ = pb._prediksi(b)
        print(f"\nD. Dari CSV: {len(b)} baris. MAE total", round(mae(b["soil_moisture"], b["pred"]), 4),
              "per bulan", per_bulan(b))
        m = b.merge(u, on=["id", "kode"], suffixes=("_csv", "_db"))
        print(f"   Baris yang cocok dengan DB: {len(m)}")
        for v in ["soil_moisture"] + est.FITUR:
            x = (m[v + "_csv"] - m[v + "_db"]).abs()
            print(f"   {v:22s} selisih maks {x.max():.5f}  rata {x.mean():.6f}  baris beda>1e-3: {(x > 1e-3).sum()}")
        x = (m["pred_csv"] - m["pred_db"]).abs()
        print(f"   {'PREDIKSI':22s} selisih maks {x.max():.5f}  rata {x.mean():.6f}")
        print("   Contoh baris dengan prediksi paling beda:")
        print(m.loc[x.sort_values(ascending=False).index[:5], ["id", "kode", "pred_csv", "pred_db"]].to_string())
