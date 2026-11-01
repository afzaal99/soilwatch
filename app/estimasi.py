"""
Lapisan estimasi untuk aplikasi web.

Urutan sumber model yang dipakai:
1. models/model_terpilih.json (hasil script 05): pendekatan terbaik (RF, XGBoost, atau gabungan
   w x RF + (1 - w) x XGBoost) dengan pilihan nasional/regional per kelompok wilayah.
2. Jika file itu belum ada tetapi model RF sudah ada: Random Forest (hasil script 03).
3. Jika belum ada model sama sekali: regresi linear sementara (CONTOH) agar tampilan tetap bisa diuji.

Penjelasan lokal SHAP dihitung langsung untuk setiap estimasi jika pustaka shap/xgboost tersedia.
Jika tidak, dipakai penjelasan CONTOH (ditandai di halaman).
"""
import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = Path(__file__).parent / "data" / "soilwatch.db"
if not DB.exists():
    raise SystemExit("Basis data app/data/soilwatch.db belum ada. Jalankan: python scripts/08_data_web.py")


def _query(sql, args=()):
    """Membaca basis data SQLite (koneksi baru per permintaan, aman untuk server Flask)."""
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _muat_awal():
    meta = {k: json.loads(v) for k, v in _query("SELECT kunci, nilai FROM meta")}
    per = _query("SELECT kode, label FROM periode ORDER BY id")
    wil = _query("SELECT id, nama, provinsi_gaul, kelompok, provinsi, label, persen_gambut, "
                 "persen_badan_air, persen_pertanian, danau FROM wilayah ORDER BY id")
    return {**meta,
            "periode": [p[0] for p in per], "periode_label": [p[1] for p in per],
            "wilayah": [{"id": w[0], "nama": w[1], "prov_gaul": w[2], "kelompok": w[3],
                         "prov": w[4], "label": w[5], "danau": w[9]} for w in wil],
            "penanda": [list(w[6:9]) for w in wil]}


DATA = _muat_awal()
FITUR = DATA["fitur"]
STAT = DATA["stat"]

INFO = {  # label, satuan, kelompok form simulasi, langkah input
    "curah_hujan_bulanan": ("Curah hujan", "mm/bulan", "Cuaca", "1"),
    "suhu_celsius": ("Suhu udara", "°C", "Cuaca", "0.1"),
    "dew_point_celsius": ("Suhu titik embun", "°C", "Cuaca", "0.1"),
    "relative_humidity": ("Kelembapan relatif", "%", "Cuaca", "0.1"),
    "solar_radiation": ("Radiasi matahari", "MJ/m²", "Radiasi dan angin", "0.1"),
    "wind_speed": ("Kecepatan angin", "m/s", "Radiasi dan angin", "0.1"),
    "ndvi": ("NDVI", "–", "Vegetasi dan permukaan", "0.01"),
    "lst_celsius": ("LST", "°C", "Vegetasi dan permukaan", "0.1"),
    "clay_content": ("Kandungan liat", "%", "Tanah dan topografi", "0.1"),
    "soil_temperature": ("Suhu tanah", "°C", "Tanah dan topografi", "0.1"),
    "elevation": ("Elevasi", "m", "Tanah dan topografi", "1"),
    "slope": ("Kemiringan lereng", "°", "Tanah dan topografi", "0.01"),
}
# batas fisik mutlak untuk validasi input simulasi
BATAS = {"curah_hujan_bulanan": (0, 2000), "suhu_celsius": (0, 45), "dew_point_celsius": (-5, 35),
         "relative_humidity": (0, 100), "solar_radiation": (0, 40), "wind_speed": (0, 30),
         "ndvi": (-1, 1), "lst_celsius": (0, 70), "clay_content": (0, 100),
         "soil_temperature": (0, 50), "elevation": (-10, 5000), "slope": (0, 90)}
WILAYAH = DATA["wilayah"]
ID_PERIODE = {p: i for i, p in enumerate(DATA["periode"])}


def rh_dari(t, td):
    """Persamaan (2.5)-(2.6) proposal: RH = 100 * es(Td) / es(T)."""
    es = lambda x: 6.112 * math.exp(17.67 * x / (x + 243.5))
    return 100 * es(td) / es(t)


def _baca_konfigurasi():
    f = ROOT / "models" / "model_terpilih.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return None


KONF = _baca_konfigurasi()


def _versi():
    """Penanda versi data: waktu ubah basis data dan berkas model terpilih."""
    f = ROOT / "models" / "model_terpilih.json"
    return (DB.stat().st_mtime_ns, f.stat().st_mtime_ns if f.exists() else 0)


VERSI = _versi()


def muat_ulang():
    """Membaca ulang basis data dan konfigurasi model (dipanggil setelah admin mengunggah data,
    memulihkan cadangan, atau melatih ulang model). Semua cache ikut dikosongkan."""
    global DATA, FITUR, STAT, WILAYAH, ID_PERIODE, KONF, VERSI
    DATA = _muat_awal()
    FITUR, STAT, WILAYAH = DATA["fitur"], DATA["stat"], DATA["wilayah"]
    ID_PERIODE = {p: i for i, p in enumerate(DATA["periode"])}
    KONF = _baca_konfigurasi()
    for fn in (_model, _penjelas_rf, data_peta):
        fn.cache_clear()
    VERSI = _versi()


def cek_versi():
    """Muat ulang jika basis data/model berubah (mis. diperbarui oleh proses server lain)."""
    if _versi() != VERSI:
        muat_ulang()


def galat_gambut(v):
    """Galat model pada wilayah gambut (data uji, dari script 05) dan rentang perkiraan v +- MAE."""
    m = next((d for n, d in ((KONF or {}).get("metrik_uji_wilayah_khusus") or {}).items()
              if n.startswith("Wilayah gambut")), None)
    if not m:
        return None
    return {"mae": m["MAE"], "r2": m["R2"], "bawah": max(v - m["MAE"], 0), "atas": v + m["MAE"]}
NAMA_JENIS = {"rf": "Random Forest", "xgb": "XGBoost"}


def _nama_file(cakupan):
    return "nasional" if cakupan == "nasional" else cakupan.lower().replace("-", "_").replace(" ", "_")


@lru_cache(maxsize=None)
def _model(jenis, cakupan):
    try:
        import joblib
        f = ROOT / "models" / f"{jenis}_{_nama_file(cakupan)}.joblib"
        if not f.exists():
            return None
        obj = joblib.load(f)   # disimpan script 03/04 sebagai {"model", "fitur", "parameter", "jenis"}
        obj = obj if isinstance(obj, dict) else {"model": obj, "fitur": FITUR}
        obj.setdefault("jenis", jenis)
        return obj
    except Exception:
        return None


def _rencana(kelompok):
    """Model yang dipakai untuk suatu kelompok: (cakupan, [(jenis, bobot), ...]).
    Mode Simulasi (kelompok None) selalu memakai model nasional."""
    if KONF:
        cak = "nasional" if kelompok is None or KONF["per_kelompok"].get(kelompok) != "regional" else kelompok
        w = float(KONF["bobot_rf"].get(cak, 1.0))
        return cak, [(j, b) for j, b in [("rf", w), ("xgb", 1 - w)] if b > 1e-9]
    cak = "nasional" if kelompok is None or DATA["pilihan_model"].get(kelompok) != "regional" else kelompok
    return cak, [("rf", 1.0)]


def _baris(obj, x):
    urutan = obj["fitur"]
    baris = [[x[f] for f in urutan]]
    try:
        import pandas as pd
        return pd.DataFrame(baris, columns=urutan)
    except ImportError:
        return baris


def _sumber(cak, rencana):
    lingkup = "nasional" if cak == "nasional" else f"regional {cak}"
    if len(rencana) == 1:
        return f"{NAMA_JENIS[rencana[0][0]]} {lingkup}"
    w = dict(rencana)
    return (f"model gabungan {lingkup} ({fmt(w['rf'], 1)} × Random Forest + "
            f"{fmt(w['xgb'], 1)} × XGBoost)")


def prediksi(x, kelompok=None):
    """x: dict 12 variabel. Mengembalikan (nilai, keterangan sumber model)."""
    cak, rencana = _rencana(kelompok)
    try:
        total = 0.0
        for jenis, bobot in rencana:
            obj = _model(jenis, cak)
            if obj is None:
                raise LookupError
            total += bobot * float(obj["model"].predict(_baris(obj, x))[0])
        return total, _sumber(cak, rencana)
    except Exception:
        pass
    lin = DATA["linear"]
    z = [(x[f] - STAT[f]["mean"]) / STAT[f]["std"] for f in FITUR]
    v = lin["intercept"] + sum(k * zi for k, zi in zip(lin["koef"], z))
    return max(0.02, min(0.85, v)), "model sementara (contoh)"


@lru_cache(maxsize=None)
def _penjelas_rf(cakupan):
    import shap
    return shap.TreeExplainer(_model("rf", cakupan)["model"])


def shap_lokal(x, kelompok=None):
    """Nilai SHAP sebenarnya untuk satu estimasi: (nilai_dasar, {variabel: kontribusi}).
    Model gabungan: SHAP = w x SHAP_RF + (1 - w) x SHAP_XGB. Mengembalikan None jika tidak bisa."""
    cak, rencana = _rencana(kelompok)
    try:
        base, kontrib = 0.0, {f: 0.0 for f in FITUR}
        for jenis, bobot in rencana:
            obj = _model(jenis, cak)
            X = _baris(obj, x)
            if jenis == "xgb":
                import xgboost as xgb
                v = obj["model"].get_booster().predict(xgb.DMatrix(X), pred_contribs=True)[0]
                b, nilai = float(v[-1]), v[:-1]
            else:
                ex = _penjelas_rf(cak)
                nilai = ex.shap_values(X, check_additivity=False)[0]
                b = float(sum(ex.expected_value) if hasattr(ex.expected_value, "__len__") else ex.expected_value)
            base += bobot * b
            for f, v in zip(obj["fitur"], nilai):
                kontrib[f] += bobot * float(v)
        return base, kontrib
    except Exception:
        return None


def kategori(v):
    s = STAT["soil_moisture"]
    if v < s["p33"]:
        return "rendah"
    if v > s["p67"]:
        return "tinggi"
    return "sedang"


def shap_contoh(x, nilai):
    """Kontribusi per variabel versi CONTOH: arah dari z-score x kepentingan variabel,
    lalu disesuaikan agar jumlahnya = nilai - rata-rata model (sifat aditif SHAP)."""
    base = STAT["soil_moisture"]["mean"]
    imp = DATA["kepentingan"]
    lin = dict(zip(FITUR, DATA["linear"]["koef"]))
    mentah = {f: imp.get(f, 0) * (x[f] - STAT[f]["mean"]) / STAT[f]["std"] *
              (1 if lin[f] >= 0 else -1) * 0.08 for f in FITUR}
    sisa = (nilai - base) - sum(mentah.values())
    kontrib = {f: v + sisa / len(FITUR) for f, v in mentah.items()}
    return base, kontrib


def waterfall(x, nilai, kelompok=None, top=5):
    """Baris-baris grafik kontribusi (posisi dalam persen lebar area grafik).
    Memakai SHAP sebenarnya jika tersedia, jika tidak memakai versi contoh."""
    asli = shap_lokal(x, kelompok)
    base, k = asli if asli else shap_contoh(x, nilai)
    urut = sorted(FITUR, key=lambda f: -abs(k[f]))
    baris = [(f, k[f]) for f in urut[:top]]
    lain = sum(k[f] for f in urut[top:])
    titik = [base]
    for _, v in baris + [("lain", lain)]:
        titik.append(titik[-1] + v)
    lo, hi = min(titik), max(titik)
    pad = (hi - lo) * 0.22 or 0.02
    lo, hi = lo - pad, hi + pad
    pos = lambda v: (v - lo) / (hi - lo) * 100
    rows, cur = [], base
    for f, v in baris + [("lain", lain)]:
        a, b = cur, cur + v
        lab, sat = (INFO[f][0], INFO[f][1]) if f != "lain" else (f"{len(FITUR) - top} variabel lainnya", "")
        rows.append({
            "label": lab, "nilai_x": None if f == "lain" else fmt(x[f], 2 if f in ("ndvi", "slope") else 1),
            "satuan": "" if sat == "–" else sat, "v": v, "teks": ("+" if v >= 0 else "−") + fmt(abs(v), 3),
            "kiri": pos(min(a, b)), "lebar": max(abs(pos(b) - pos(a)), 0.6), "naik": v >= 0,
        })
        cur = b
    utama = rows[0] if rows else None
    return {"base": base, "base_pos": pos(base), "hasil_pos": pos(nilai), "rows": rows, "utama": utama,
            "asli": asli is not None}


def kepentingan_global(top=6):
    imp = DATA["kepentingan"]
    tot = sum(imp.values()) or 1
    urut = sorted(imp.items(), key=lambda kv: -kv[1])
    rows = [(INFO[f][0], v / tot * 100) for f, v in urut[:top]]
    rows.append(("Lainnya", sum(v for _, v in urut[top:]) / tot * 100))
    mx = max(p for _, p in rows)
    return [{"label": l, "persen": p, "lebar": p / mx * 100, "lain": l == "Lainnya"} for l, p in rows]


def fmt(v, d=2):
    """Format angka Indonesia: koma desimal, titik ribuan."""
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def nilai_wilayah(wid, periode):
    """12 variabel suatu wilayah pada satu bulan, diambil dari basis data."""
    baris = _query(f"SELECT {', '.join(FITUR)} FROM data_bulanan WHERE wilayah_id = ? AND periode_id = ?",
                   (wid, ID_PERIODE[periode]))
    return dict(zip(FITUR, baris[0])) if baris else {f: None for f in FITUR}


def sm_wilayah(wid):
    """Deret soil moisture bulanan (SMAP L4) suatu wilayah, urut periode."""
    return [v for (v,) in _query("SELECT soil_moisture FROM data_bulanan WHERE wilayah_id = ? "
                                 "ORDER BY periode_id", (wid,))]


@lru_cache(maxsize=1)
def data_peta():
    """Data untuk peta Mode Otomatis: soil moisture semua wilayah x bulan + penanda lahan."""
    n_per = len(DATA["periode"])
    sm = [[None] * n_per for _ in WILAYAH]
    for wid, pid, v in _query("SELECT wilayah_id, periode_id, soil_moisture FROM data_bulanan"):
        sm[wid][pid] = None if v is None else round(v, 3)
    return {"periode": DATA["periode"], "periode_label": DATA["periode_label"],
            "wilayah": [[w["label"], w["prov"], w["danau"]] for w in WILAYAH], "sm": sm,
            "penanda": DATA["penanda"], "penanda_contoh": DATA["penanda_contoh"]}


BULAN_PANJANG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
                 "Oktober", "November", "Desember"]


def label_bulan(kode):
    """'2026-09' -> 'September 2026'"""
    return f"{BULAN_PANJANG[int(kode[5:7]) - 1]} {kode[:4]}"


BLN_PENDEK = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def sumbu_bulan(X, Y, sm, setiap=3):
    """Sumbu waktu grafik bulanan: garis kecil di setiap bulan, tulisan tiap `setiap` bulan
    (tahun hanya ditulis di Januari), dan titik-titik tak terlihat untuk tooltip nilai bulanan."""
    centang, label, titik = [], [], []
    for i, p in enumerate(DATA["periode"]):
        b = int(p[5:])
        centang.append({"x": X(i), "besar": b == 1})
        if (b - 1) % setiap == 0:
            label.append({"x": X(i), "teks": f"{BLN_PENDEK[b - 1]} {p[:4]}" if b == 1 else BLN_PENDEK[b - 1],
                          "tahun": b == 1})
        if sm[i] is not None:
            titik.append({"x": X(i), "y": Y(sm[i]), "teks": f"{DATA['periode_label'][i]}: {fmt(sm[i], 2)} m³/m³"})
    return centang, label, titik


def tren(wid, pilih):
    """Grafik garis SVG soil moisture bulanan suatu wilayah (koordinat sudah dihitung)."""
    sm = sm_wilayah(wid)
    W, H, L, R, T, B = 1000, 200, 40, 12, 14, 26   # tinggi dan margin sama dengan grafik ringkasan
    vals = [v for v in sm if v is not None]
    lo = math.floor(min(vals) * 20) / 20
    hi = math.ceil(max(vals) * 20) / 20
    if hi - lo < 0.1:
        hi = lo + 0.1
    n = len(sm)
    X = lambda i: L + i * (W - L - R) / (n - 1)
    Y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    pts = [(X(i), Y(v)) for i, v in enumerate(sm) if v is not None]
    garis = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pts[0][0]:.1f},{H - B} " + garis + f" {pts[-1][0]:.1f},{H - B}"
    gy = []
    v = lo
    while v <= hi + 1e-9:
        gy.append({"y": Y(v), "teks": fmt(v, 2)})
        v += 0.05 if hi - lo <= 0.3 else 0.1
    centang, gx, titik_bulan = sumbu_bulan(X, Y, sm, setiap=3)
    ip = ID_PERIODE[pilih]
    titik = {"x": X(ip), "y": Y(sm[ip]), "teks": f"{DATA['periode_label'][ip]}: {fmt(sm[ip], 2)}"}
    # bulan terendah & tertinggi rata-rata
    rata = {}
    for i, p in enumerate(DATA["periode"]):
        if sm[i] is not None:
            rata.setdefault(int(p[5:]), []).append(sm[i])
    rata = {b: sum(v) / len(v) for b, v in rata.items()}
    nm = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    rendah = sorted(rata, key=rata.get)[:2]
    tinggi = sorted(rata, key=rata.get, reverse=True)[:2]
    def teks(bs):
        a, b = sorted(bs)
        return f"{nm[a - 1]}–{nm[b - 1]}" if b - a == 1 else ("Des–Jan" if (a, b) == (1, 12) else f"{nm[a - 1]} & {nm[b - 1]}")
    return {"W": W, "H": H, "B": B, "L": L, "R": R, "garis": garis, "area": area, "gy": gy, "gx": gx,
            "titik": titik, "rendah": teks(rendah), "tinggi": teks(tinggi),
            "centang": centang, "titik_bulan": titik_bulan,
            "awal": DATA["periode_label"][0], "akhir": DATA["periode_label"][-1]}
