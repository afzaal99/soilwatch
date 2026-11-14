"""
pH tanah per kabupaten/kota dan kesesuaian tanaman (fitur tambahan berdasarkan masukan UAT Kementan).

Data   : app/data/ph_tanah.csv hasil scripts/10_gee_ph_tanah.js
         (OpenLandMap Soil pH in H2O, Hengl 2018, 250 m; rata-rata per wilayah lapisan 0, 10, 30 cm).
Kelas  : kriteria pH H2O Balai Penelitian Tanah, kini Balai Perakitan dan Pengujian Tanah dan Pupuk
         (Eviati & Sulaeman, 2009, Lampiran 3).
Tanaman: rentang pH kelas S1 (sangat sesuai) dan S2 (cukup sesuai) dari Petunjuk Teknis Evaluasi Lahan
         untuk Komoditas Pertanian (Ritung dkk., 2011, BBSDLP Kementan).

Bagian ini TIDAK memengaruhi model estimasi soil moisture. Bila berkas CSV belum ada, fitur disembunyikan.
"""
import csv
import io
import math
import re
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

BERKAS = Path(__file__).resolve().parent / "data" / "ph_tanah.csv"

# (batas atas inklusif, kelas, warna) - Eviati & Sulaeman (2009), pH H2O satu desimal:
# sangat masam < 4,5; masam 4,5-5,5; agak masam 5,6-6,5; netral 6,6-7,5; agak alkalis 7,6-8,5; alkalis > 8,5
KELAS = [
    (4.4, "sangat masam", "#B91C1C"),
    (5.5, "masam", "#EA580C"),
    (6.5, "agak masam", "#CA8A04"),
    (7.5, "netral", "#15803D"),
    (8.5, "agak alkalis", "#0E7490"),
    (99, "alkalis", "#1D4ED8"),
]


def bulat(ph):
    """pH dibulatkan satu desimal: angka yang tampil di layar sekaligus dasar penentuan kelas dan kesesuaian,
    agar label selalu konsisten dengan nilai yang dilihat pengguna."""
    return round(ph + 1e-9, 1)

# nama, golongan, S1 (bawah, atas), S2 (bawah, atas) - Ritung dkk. (2011), pH H2O
TANAMAN = [
    ("Padi sawah", "Tanaman pangan", (5.5, 7.0), (4.5, 8.0)),
    ("Jagung", "Tanaman pangan", (5.8, 7.8), (5.5, 8.2)),
    ("Kedelai", "Tanaman pangan", (5.5, 7.5), (5.0, 7.8)),
    ("Kacang tanah", "Tanaman pangan", (6.0, 7.0), (5.0, 7.5)),
    ("Ubi kayu", "Tanaman pangan", (5.2, 7.0), (4.8, 7.6)),
    ("Ubi jalar", "Tanaman pangan", (5.2, 8.2), (4.8, 8.4)),
    ("Cabai merah", "Sayuran", (6.0, 7.6), (5.5, 8.0)),
    ("Tomat", "Sayuran", (6.0, 7.5), (5.5, 8.0)),
    ("Bawang merah", "Sayuran", (6.0, 7.8), (5.8, 8.0)),
    ("Kubis", "Sayuran", (6.0, 7.8), (5.8, 8.0)),
    ("Kentang", "Sayuran", (5.6, 7.0), (5.2, 8.0)),
    ("Sawi", "Sayuran", (6.0, 7.0), (5.7, 7.6)),
    ("Bayam", "Sayuran", (5.6, 7.6), (5.4, 8.0)),
    ("Kacang panjang", "Sayuran", (5.6, 7.6), (5.4, 8.0)),
    ("Mentimun", "Sayuran", (5.8, 7.6), (5.5, 8.0)),
    ("Pisang", "Buah-buahan", (5.6, 7.5), (5.2, 8.0)),
    ("Nanas", "Buah-buahan", (5.0, 6.5), (4.3, 7.0)),
    ("Jeruk", "Buah-buahan", (5.5, 7.6), (5.2, 8.0)),
    ("Mangga", "Buah-buahan", (5.5, 7.8), (5.0, 8.0)),
    ("Kelapa sawit", "Perkebunan (tanaman keras)", (5.0, 6.5), (4.2, 7.0)),
    ("Karet", "Perkebunan (tanaman keras)", (5.0, 6.0), (4.5, 6.5)),
    ("Kakao", "Perkebunan (tanaman keras)", (6.0, 7.0), (5.5, 7.6)),
    ("Kopi robusta", "Perkebunan (tanaman keras)", (5.3, 6.0), (5.0, 6.5)),
    ("Kopi arabika", "Perkebunan (tanaman keras)", (5.6, 6.6), (5.6, 7.3)),
    ("Kelapa", "Perkebunan (tanaman keras)", (5.2, 7.5), (4.8, 8.0)),
    ("Tebu", "Perkebunan (tanaman keras)", (5.5, 7.5), (5.0, 8.0)),
    ("Teh", "Perkebunan (tanaman keras)", (4.5, 5.5), (3.8, 5.8)),
    ("Cengkeh", "Perkebunan (tanaman keras)", (5.0, 7.0), (4.0, 8.0)),
]
GOLONGAN = ["Tanaman pangan", "Sayuran", "Buah-buahan", "Perkebunan (tanaman keras)"]


def _f(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _baca():
    """{(nama kabupaten GAUL, provinsi GAUL): baris} dari ph_tanah.csv (kosong bila berkas belum ada)."""
    if not BERKAS.exists():
        return {}
    hasil = {}
    with BERKAS.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            lap = [_f(r.get(k)) for k in ("ph_0cm", "ph_10cm", "ph_30cm")]
            lap = [v for v in lap if v is not None]
            if not lap:
                continue
            hasil[(r["ADM2_NAME"], r["ADM1_NAME"])] = {
                "ph": sum(lap) / len(lap), "ph_0": _f(r.get("ph_0cm")),
                "p10": _f(r.get("ph_p10")), "p90": _f(r.get("ph_p90"))}
    return hasil


def tersedia():
    return bool(_baca())


def kelas(ph):
    r = bulat(ph)
    for atas, nama, warna in KELAS:
        if r <= atas:
            return nama, warna
    return KELAS[-1][1], KELAS[-1][2]


def _kesesuaian(ph):
    """Kelompokkan tanaman: sangat sesuai (S1), cukup sesuai (S2), perlu penyesuaian pH (di luar S2)."""
    ph = bulat(ph)
    s1, s2, atur = {g: [] for g in GOLONGAN}, {g: [] for g in GOLONGAN}, []
    for nama, gol, (a1, b1), (a2, b2) in TANAMAN:
        if a1 <= ph <= b1:
            s1[gol].append(nama)
        elif a2 <= ph <= b2:
            s2[gol].append(nama)
        else:
            atur.append({"nama": nama, "arah": "naik" if ph < a1 else "turun",
                         "target": f"{a1:.1f}–{b1:.1f}".replace(".", ",")})
    rapikan = lambda d: [{"golongan": g, "tanaman": d[g]} for g in GOLONGAN if d[g]]
    return rapikan(s1), rapikan(s2), atur


def arahan(ph):
    """Arahan umum penyesuaian pH (bukan dosis; dosis ditentukan dari uji tanah laboratorium)."""
    ph = bulat(ph)
    if ph <= 5.5:
        return ("naik", "Tanah bersifat masam. Untuk tanaman yang membutuhkan pH lebih tinggi, pH dapat dinaikkan dengan "
                "pengapuran (kapur pertanian atau dolomit) yang disertai penambahan bahan organik seperti pupuk kandang atau kompos.")
    if ph <= 6.5:
        return ("naik", "Tanah agak masam dan sesuai untuk banyak tanaman. Untuk sayuran yang membutuhkan pH mendekati netral, "
                "dapat dilakukan pengapuran ringan dan penambahan bahan organik.")
    if ph <= 7.5:
        return ("tetap", "pH tanah netral dan sesuai untuk sebagian besar tanaman. Kondisi ini dapat dipertahankan dengan "
                "penambahan bahan organik secara berkala.")
    return ("turun", "Tanah bersifat alkalis. pH dapat diturunkan secara bertahap dengan bahan organik, belerang (sulfur), "
            "atau pupuk yang bersifat masam seperti ZA.")


def info(wilayah, persen_gambut=0):
    """Ringkasan pH untuk satu wilayah (dict est.WILAYAH), atau None bila data belum tersedia."""
    d = _baca().get((wilayah["nama"], wilayah["prov_gaul"]))
    if not d:
        return None
    ph = bulat(d["ph"])                                      # satu desimal, sama dengan yang tampil
    nama_kelas, warna = kelas(ph)
    s1, s2, atur = _kesesuaian(ph)
    arah, teks = arahan(ph)
    return {"ph": ph, "kelas": nama_kelas, "warna": warna, "p10": d["p10"], "p90": d["p90"],
            "posisi": max(0.0, min(1.0, (ph - 4.0) / 5.0)),           # posisi penanda pada skala pH 4-9
            "s1": s1, "s2": s2, "atur": atur, "arah": arah, "arahan": teks,
            "gambut": (persen_gambut or 0) >= 20}


def ringkas_semua(wilayah):
    """[[pH dibulatkan, kelas]] untuk peta/panel Mode Otomatis (urut id wilayah)."""
    if not tersedia():
        return None
    data = _baca()
    out = []
    for w in wilayah:
        d = data.get((w["nama"], w["prov_gaul"]))
        out.append(None if not d else [bulat(d["ph"]), kelas(d["ph"])[0]])
    return out


def muat_ulang():
    _baca.cache_clear()


# ============================================================================ pH hasil uji tanah lapangan (bulanan)
# pH tidak dapat diukur satelit, sehingga pH bulanan hanya tersedia bila pengelola aplikasi (admin) mengunggah
# hasil uji tanah lapangan yang diambil berkala. Berkas: app/data/ph_lapangan.csv (dibuat lewat Dashboard Admin).
BERKAS_LAP = Path(__file__).resolve().parent / "data" / "ph_lapangan.csv"
KOLOM_LAP = ["periode", "kabupaten_kota", "provinsi", "ph", "jumlah_sampel", "sumber"]
BATAS_PH = (3.0, 10.0)
NAMA_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
              "September", "Oktober", "November", "Desember"]


def label_periode(p):
    th, bl = p.split("-")
    return f"{NAMA_BULAN[int(bl) - 1]} {th}"


def _kunci(nama, prov):
    return (" ".join(str(nama).split()).lower(), " ".join(str(prov).split()).lower())


@lru_cache(maxsize=4)
def _baca_lap(_versi):
    if not BERKAS_LAP.exists():
        return {}
    data = {}
    with BERKAS_LAP.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            ph = _f(r.get("ph"))
            if ph is None:
                continue
            data.setdefault(_kunci(r["kabupaten_kota"], r["provinsi"]), []).append(
                {"periode": r["periode"], "ph": ph, "n": r.get("jumlah_sampel") or "", "sumber": r.get("sumber") or ""})
    for v in data.values():
        v.sort(key=lambda x: x["periode"])
    return data


def data_lapangan():
    versi = BERKAS_LAP.stat().st_mtime if BERKAS_LAP.exists() else 0
    return _baca_lap(versi)


def lapangan(wilayah):
    """Riwayat pH lapangan satu wilayah, beserta koordinat grafik sederhana (None bila belum ada)."""
    baris = data_lapangan().get(_kunci(wilayah["label"], wilayah["prov"]))
    if not baris:
        return None
    W, H, L, R, T, B = 640, 200, 40, 34, 14, 30
    lo, hi = 4.0, 9.0
    for b in baris:
        lo, hi = min(lo, math.floor(b["ph"])), max(hi, math.ceil(b["ph"]))
    n = len(baris)
    # posisi x mengikuti jarak waktu (bulan), bukan urutan baris: bulan tanpa pengukuran tetap memberi jarak
    urut = lambda per: int(per[:4]) * 12 + int(per[5:7]) - 1
    m0, m1 = urut(baris[0]["periode"]), urut(baris[-1]["periode"])
    X = lambda i: L + ((urut(baris[i]["periode"]) - m0) * (W - L - R) / (m1 - m0) if m1 > m0 else (W - L - R) / 2)
    Y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    titik = [{"x": X(i), "y": Y(b["ph"]), "teks": f"{label_periode(b['periode'])} · pH {bulat(b['ph']):.1f}".replace(".", ","),
              "warna": kelas(b["ph"])[1]} for i, b in enumerate(baris)]
    langkah = max(1, n // 6)
    sumbu = [{"x": X(i), "teks": label_periode(b["periode"])[:3] + " " + b["periode"][2:4]}
             for i, b in enumerate(baris) if i % langkah == 0 or i == n - 1]
    gy = [{"y": Y(v), "teks": str(v)} for v in range(int(lo), int(hi) + 1)]
    pita = {"y_atas": Y(7.5), "y_bawah": Y(6.6)}                     # kelas netral
    # ruas garis antartitik; putus-putus bila ada bulan tanpa pengukuran di antaranya
    ruas = [{"x1": titik[i]["x"], "y1": titik[i]["y"], "x2": titik[i + 1]["x"], "y2": titik[i + 1]["y"],
             "putus": urut(baris[i + 1]["periode"]) - urut(baris[i]["periode"]) > 1} for i in range(n - 1)]
    akhir = baris[-1]
    return {"W": W, "H": H, "L": L, "R": R, "B": B, "titik": titik, "sumbu": sumbu, "gy": gy, "pita": pita,
            "ruas": ruas, "ada_jeda": any(r["putus"] for r in ruas), "baris": baris[::-1],
            "akhir": {**akhir, "label": label_periode(akhir["periode"]), "kelas": kelas(akhir["ph"])[0]},
            "awal_label": label_periode(baris[0]["periode"]), "n": n,
            "rentang": rentang_bulan([b["periode"] for b in baris])}


def ringkas_lapangan():
    d = data_lapangan()
    semua = [b for v in d.values() for b in v]
    if not semua:
        return None
    per = sorted({b["periode"] for b in semua})
    waktu = datetime.fromtimestamp(BERKAS_LAP.stat().st_mtime)
    return {"baris": len(semua), "wilayah": len(d), "awal": label_periode(per[0]), "akhir": label_periode(per[-1]),
            "diperbarui": f"{waktu.day} {NAMA_BULAN[waktu.month - 1]} {waktu.year}, {waktu:%H:%M}"}


# urutan provinsi menurut kode wilayah BPS (11 Aceh ... 97 Papua Pegunungan): dari Sabang sampai Merauke
URUT_PROVINSI = [
    "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Jambi", "Sumatera Selatan", "Bengkulu", "Lampung",
    "Kepulauan Bangka Belitung", "Kepulauan Riau", "DKI Jakarta", "Jawa Barat", "Jawa Tengah", "DI Yogyakarta",
    "Jawa Timur", "Banten", "Bali", "Nusa Tenggara Barat", "Nusa Tenggara Timur", "Kalimantan Barat",
    "Kalimantan Tengah", "Kalimantan Selatan", "Kalimantan Timur", "Kalimantan Utara", "Sulawesi Utara",
    "Sulawesi Tengah", "Sulawesi Selatan", "Sulawesi Tenggara", "Gorontalo", "Sulawesi Barat", "Maluku",
    "Maluku Utara", "Papua Barat", "Papua Barat Daya", "Papua", "Papua Selatan", "Papua Tengah", "Papua Pegunungan",
]


def urut_wilayah(wilayah):
    """Provinsi dari barat ke timur (urutan kode BPS), di dalamnya kabupaten dahulu lalu kota, masing-masing A-Z."""
    posisi = {p: i for i, p in enumerate(URUT_PROVINSI)}
    return sorted(wilayah, key=lambda x: (posisi.get(x["prov"], 99), x["label"].startswith("Kota"), x["label"]))


def templat_csv(wilayah, periode_contoh):
    """Templat isian untuk admin: satu baris per kabupaten/kota (Sabang sampai Merauke), periode terisi contoh,
    pH dikosongkan."""
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow(KOLOM_LAP)
    for x in urut_wilayah(wilayah):
        w.writerow([periode_contoh, x["label"], x["prov"], "", "", ""])
    return "\ufeff" + out.getvalue()


def periksa_lapangan(isi, wilayah):
    """Validasi berkas unggahan admin. Mengembalikan (baris_valid, galat, ringkasan)."""
    try:
        teks = isi.decode("utf-8-sig")
    except UnicodeDecodeError:
        teks = isi.decode("latin-1")
    pemisah = ";" if teks.split("\n", 1)[0].count(";") >= teks.split("\n", 1)[0].count(",") else ","
    rd = csv.DictReader(io.StringIO(teks), delimiter=pemisah)
    kolom = [c.strip().lower() for c in (rd.fieldnames or [])]
    kurang = [c for c in ["periode", "kabupaten_kota", "provinsi", "ph"] if c not in kolom]
    if kurang:
        return [], [f"Kolom wajib tidak ditemukan: {', '.join(kurang)}. Gunakan template yang disediakan."], None
    resmi = {_kunci(x["label"], x["prov"]): (x["label"], x["prov"]) for x in wilayah}
    valid, galat, kosong = {}, [], 0
    for no, r in enumerate(rd, start=2):
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        if not r.get("ph"):
            kosong += 1                                       # baris templat yang tidak diisi: dilewati
            continue
        masalah = []
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", r.get("periode", "")):
            masalah.append("periode harus berformat TTTT-BB, misalnya 2026-10")
        k = _kunci(r.get("kabupaten_kota", ""), r.get("provinsi", ""))
        if k not in resmi:
            masalah.append(f"wilayah '{r.get('kabupaten_kota')}, {r.get('provinsi')}' tidak dikenal")
        ph = _f(r.get("ph"))
        if ph is None:
            masalah.append(f"pH '{r.get('ph')}' bukan angka")
        elif not BATAS_PH[0] <= ph <= BATAS_PH[1]:
            masalah.append(f"pH {r.get('ph')} di luar rentang wajar {BATAS_PH[0]:.0f}–{BATAS_PH[1]:.0f}")
        n = r.get("jumlah_sampel", "")
        if n and not n.isdigit():
            masalah.append("jumlah_sampel harus bilangan bulat")
        if masalah:
            galat.append(f"Baris {no}: " + "; ".join(masalah))
            continue
        nama, prov = resmi[k]
        valid[(r["periode"], nama, prov)] = [r["periode"], nama, prov, f"{ph:.2f}".replace(".", ","), n, r.get("sumber", "")]
    ring = {"valid": len(valid), "dilewati": kosong, "wilayah": len({(v[1], v[2]) for v in valid.values()}),
            "periode": sorted({v[0] for v in valid.values()})}
    if not valid and not galat:
        galat.append("Tidak ada baris yang berisi nilai pH. Isi kolom ph pada template sebelum mengunggah.")
    return list(valid.values()), galat, ring


def _baca_mentah():
    if not BERKAS_LAP.exists():
        return {}
    with BERKAS_LAP.open(encoding="utf-8-sig") as fh:
        return {(r["periode"], r["kabupaten_kota"], r["provinsi"]): [r.get(c, "") for c in KOLOM_LAP]
                for r in csv.DictReader(fh, delimiter=";")}


def _tulis_mentah(data):
    BERKAS_LAP.parent.mkdir(parents=True, exist_ok=True)
    with BERKAS_LAP.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";", lineterminator="\r\n")
        w.writerow(KOLOM_LAP)
        posisi = {p: i for i, p in enumerate(URUT_PROVINSI)}
        for k in sorted(data, key=lambda k: (posisi.get(k[2], 99), k[1].startswith("Kota"), k[1], k[0])):
            w.writerow(data[k])


def per_periode():
    """Ringkasan data pH lapangan per bulan untuk tabel 'Data tersimpan' di halaman admin (terbaru di atas)."""
    hit = {}
    for (per, nama, prov), r in _baca_mentah().items():
        h = hit.setdefault(per, {"periode": per, "label": label_periode(per), "wilayah": 0, "sumber": set()})
        h["wilayah"] += 1
        if r[5]:
            h["sumber"].add(r[5])
    hasil = []
    for _, h in sorted(hit.items(), reverse=True):
        su = sorted(h["sumber"])
        hasil.append({**h, "sumber": su, "sumber_semua": ", ".join(su),
                      "sumber_ringkas": ", ".join(su[:2]) or "–", "sumber_lebih": max(0, len(su) - 2)})
    return hasil


def rentang_bulan(periode):
    """Gabungkan bulan berurutan jadi rentang: ['2026-01','2026-02','2026-03','2026-05'] -> 'Januari–Maret dan Mei 2026'."""
    urut = sorted({int(p[:4]) * 12 + int(p[5:7]) - 1 for p in periode})
    if not urut:
        return ""
    ruas, a = [], urut[0]
    for x, y in zip(urut, urut[1:] + [None]):
        if y != x + 1:
            ruas.append((a, x))
            a = y
    satu_tahun = urut[0] // 12 == urut[-1] // 12
    nm = lambda m, th=True: NAMA_BULAN[m % 12] + (f" {m // 12}" if th else "")
    teks = []
    for a, b in ruas:
        if a == b:
            teks.append(nm(a, not satu_tahun))
        elif a // 12 == b // 12:
            teks.append(f"{nm(a, False)}–{nm(b, not satu_tahun)}")
        else:
            teks.append(f"{nm(a)} – {nm(b)}")
    gabung = teks[0] if len(teks) == 1 else ", ".join(teks[:-1]) + " dan " + teks[-1]
    return gabung + (f" {urut[0] // 12}" if satu_tahun else "")


def hapus_lapangan(periode=None):
    """Hapus data pH lapangan satu bulan (atau semua bila periode None); data lama disalin ke .bak dulu."""
    data = _baca_mentah()
    if not data:
        return 0
    shutil.copy2(BERKAS_LAP, BERKAS_BAK)
    sisa = {k: v for k, v in data.items() if periode is not None and k[0] != periode}
    n = len(data) - len(sisa)
    if sisa:
        _tulis_mentah(sisa)
    else:
        BERKAS_LAP.unlink()
    return n


BERKAS_BAK = BERKAS_LAP.with_suffix(".bak.csv")


def info_cadangan():
    """Salinan data pH lapangan sebelum perubahan terakhir (dibuat otomatis saat simpan/hapus)."""
    if not BERKAS_BAK.exists():
        return None
    with BERKAS_BAK.open(encoding="utf-8-sig") as fh:
        baris = [r for r in csv.DictReader(fh, delimiter=";") if _f(r.get("ph")) is not None]
    if not baris:
        return None
    waktu = datetime.fromtimestamp(BERKAS_BAK.stat().st_mtime)
    return {"baris": len(baris), "wilayah": len({(r["kabupaten_kota"], r["provinsi"]) for r in baris}),
            "periode": rentang_bulan([r["periode"] for r in baris]),
            "waktu": f"{waktu.day} {NAMA_BULAN[waktu.month - 1]} {waktu.year}, {waktu:%H:%M}"}


def pulihkan_cadangan():
    """Tukar data saat ini dengan salinan .bak, sehingga pemulihan juga dapat dibatalkan dengan cara yang sama."""
    if not info_cadangan():
        return False
    sementara = BERKAS_LAP.with_suffix(".tukar.csv")
    if BERKAS_LAP.exists():
        BERKAS_LAP.replace(sementara)
    else:                                              # data saat ini kosong: simpan sebagai berkas tanpa isi
        sementara.write_text(";".join(KOLOM_LAP) + "\r\n", encoding="utf-8-sig")
    BERKAS_BAK.replace(BERKAS_LAP)
    sementara.replace(BERKAS_BAK)
    return True


def simpan_lapangan(baris):
    """Gabungkan dengan data lama (periode + wilayah yang sama ditimpa); data lama disalin ke .bak."""
    lama = _baca_mentah()
    if lama:
        shutil.copy2(BERKAS_LAP, BERKAS_BAK)
    ganti = sum(1 for b in baris if (b[0], b[1], b[2]) in lama)
    for b in baris:
        lama[(b[0], b[1], b[2])] = b
    _tulis_mentah(lama)
    return {"baru": len(baris) - ganti, "diganti": ganti}
