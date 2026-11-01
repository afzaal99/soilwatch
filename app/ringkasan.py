"""
Ringkasan kondisi soil moisture (SMAP L4) yang mudah dibaca: nasional dan per wilayah.

Dipakai di Beranda (kartu "Kondisi Indonesia") dan di halaman hasil Mode Otomatis
(kartu "Tren dan riwayat wilayah"). Semua angka dihitung langsung dari basis data, jadi ikut
terbarui otomatis ketika data bulan baru ditambahkan.

Catatan: ringkasan memakai nilai ACUAN SMAP L4, bukan hasil prediksi model.
"""
import estimasi as est

BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
         "September", "Oktober", "November", "Desember"]
BLN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
SETARA = 0.01      # selisih < 0,01 m3/m3 dianggap setara
SEDIKIT = 0.03     # selisih < 0,03 m3/m3 disebut "sedikit"


def seri_nasional():
    """Rata-rata soil moisture seluruh kabupaten/kota per bulan (sejajar dengan est.DATA['periode'])."""
    rata = dict(est._query("SELECT periode_id, AVG(soil_moisture) FROM data_bulanan "
                           "WHERE soil_moisture IS NOT NULL GROUP BY periode_id"))
    return [rata.get(i) for i in range(len(est.DATA["periode"]))]


def _f(v):
    return est.fmt(v, 2)


def _gabung_bulan(bs):
    """[8, 9] -> 'Agustus–September'; [1, 12] -> 'Desember–Januari'; [3, 9] -> 'Maret dan September'."""
    a, b = sorted(bs)
    if b - a == 1:
        return f"{BULAN[a - 1]}–{BULAN[b - 1]}"
    if (a, b) == (1, 12):
        return "Desember–Januari"
    return f"{BULAN[a - 1]} dan {BULAN[b - 1]}"


def _banding(v, acuan):
    d = v - acuan
    if abs(d) < SETARA:
        return "setara dengan", "normal"
    arah = "basah" if d > 0 else "kering"
    return ("sedikit lebih " if abs(d) < SEDIKIT else "jauh lebih ") + arah + " dari", arah


def analisis(seri, pilih=None):
    """Ringkasan dari deret bulanan. pilih = indeks bulan yang disorot (default: bulan terakhir)."""
    per, lab = est.DATA["periode"], est.DATA["periode_label"]
    ada = [i for i, v in enumerate(seri) if v is not None]
    if not ada:
        return None
    pilih = ada[-1] if pilih is None or seri[pilih] is None else pilih

    # rata-rata per tahun (tahun yang belum lengkap diberi keterangan bulannya)
    tahun = {}
    for i in ada:
        tahun.setdefault(per[i][:4], []).append(i)
    tahunan = []
    for t, idx in tahun.items():
        bulan = [int(per[i][5:]) for i in idx]
        penuh = len(idx) == 12
        tahunan.append({"tahun": t, "rata": sum(seri[i] for i in idx) / len(idx), "penuh": penuh,
                        "ket": "" if penuh else f"{BLN[min(bulan) - 1]}–{BLN[max(bulan) - 1]}"})

    # pola musiman: rata-rata tiap bulan kalender
    kal = {}
    for i in ada:
        kal.setdefault(int(per[i][5:]), []).append(seri[i])
    pola = {b: sum(v) / len(v) for b, v in kal.items()}
    urut = sorted(pola, key=pola.get)

    i_min = min(ada, key=lambda i: seri[i])
    i_max = max(ada, key=lambda i: seri[i])

    # bulan yang disorot dibanding bulan yang sama pada tahun-tahun lain
    b_pilih = int(per[pilih][5:])
    idx_lain = [i for i in ada if int(per[i][5:]) == b_pilih and i != pilih]
    rentang = f"{lab[ada[0]][-4:]}–{lab[ada[-1]][-4:]}"
    status = status_teks = None
    kalimat = []
    if idx_lain:
        lain = [seri[i] for i in idx_lain]
        acuan = sum(lain) / len(lain)
        th = sorted(per[i][:4] for i in idx_lain)
        th_teks = th[0] if len(th) == 1 else (f"{th[0]}–{th[-1]}" if int(th[-1]) - int(th[0]) == len(th) - 1
                                              else ", ".join(th))
        pembanding = f"rata-rata {BULAN[b_pilih - 1]} {th_teks}"
        d = seri[pilih] - acuan
        persen = abs(d) / acuan * 100 if acuan else 0
        if abs(d) < SETARA:
            status = "normal"
            status_teks = f"setara dengan {pembanding} (selisih < 0,01 m³/m³)"
            kalimat.append(f"<b>{lab[pilih]}</b>: {_f(seri[pilih])} m³/m³, <b>setara</b> dengan {pembanding} "
                           f"({_f(acuan)} m³/m³; selisih kurang dari 0,01 m³/m³).")
        else:
            status = "basah" if d > 0 else "kering"
            arah = "lebih tinggi (lebih basah)" if d > 0 else "lebih rendah (lebih kering)"
            status_teks = f"{_f(abs(d))} m³/m³ {'di atas' if d > 0 else 'di bawah'} {pembanding}"
            kalimat.append(f"<b>{lab[pilih]}</b>: {_f(seri[pilih])} m³/m³, <b>{arah}</b> "
                           f"{_f(abs(d))} m³/m³ ({persen:.0f}%) dibanding {pembanding} ({_f(acuan)} m³/m³).")
    else:
        kalimat.append(f"<b>{lab[pilih]}</b>: {_f(seri[pilih])} m³/m³.")
    sebelum = pilih - 1
    if sebelum >= 0 and seri[sebelum] is not None:
        d = seri[pilih] - seri[sebelum]
        arah = ("relatif tetap (selisih kurang dari 0,01 m³/m³)" if abs(d) < SETARA
                else f"{'naik' if d > 0 else 'turun'} {_f(abs(d))} m³/m³")
        kalimat.insert(1, f"Dibanding bulan sebelumnya ({lab[sebelum]}, {_f(seri[sebelum])} m³/m³), nilai {arah}.")
    if len(pola) >= 6:
        kalimat.append(f"Berdasarkan rata-rata bulanan {rentang}, nilai terendah terjadi pada "
                       f"<b>{_gabung_bulan(urut[:2])}</b> dan tertinggi pada <b>{_gabung_bulan(urut[-2:])}</b>.")
    kalimat.append(f"Nilai bulanan terendah selama {rentang}: {lab[i_min]} ({_f(seri[i_min])} m³/m³); "
                   f"tertinggi: {lab[i_max]} ({_f(seri[i_max])} m³/m³).")
    penuh = [t for t in tahunan if t["penuh"]]
    if len(penuh) >= 2:
        basah = max(penuh, key=lambda t: t["rata"])
        kering = min(penuh, key=lambda t: t["rata"])
        if basah["rata"] - kering["rata"] < SETARA:
            kalimat.append("Rata-rata tahunan setara antar tahun penuh "
                           f"({', '.join(t['tahun'] for t in penuh)}; selisih kurang dari 0,01 m³/m³).")
        else:
            kalimat.append(f"Di antara tahun penuh (Januari–Desember), rata-rata tahunan tertinggi pada "
                           f"{basah['tahun']} ({_f(basah['rata'])} m³/m³) dan terendah pada "
                           f"{kering['tahun']} ({_f(kering['rata'])} m³/m³).")

    return {"kalimat": kalimat, "status": status, "status_teks": status_teks, "tahunan": tahunan,
            "pola": [{"bulan": BLN[b - 1], "rata": pola.get(b)} for b in range(1, 13)],
            "rendah": _gabung_bulan(urut[:2]) if len(pola) >= 2 else "-",
            "tinggi": _gabung_bulan(urut[-2:]) if len(pola) >= 2 else "-",
            "awal": lab[ada[0]], "akhir": lab[ada[-1]], "pilih": lab[pilih]}


def grafik_pola(rk, W=560, H=200, L=40, R=12, T=14, B=26):
    """Koordinat diagram batang pola musiman (12 bulan)."""
    vals = [p["rata"] for p in rk["pola"] if p["rata"] is not None]
    lo = max(0.0, (int(min(vals) * 20) - 1) / 20)
    hi = (int(max(vals) * 20) + 1) / 20
    lebar = (W - L - R) / 12
    Y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    batang = []
    v_min, v_max = min(vals), max(vals)
    for k, p in enumerate(rk["pola"]):
        if p["rata"] is None:
            continue
        y = Y(p["rata"])
        jenis = "min" if p["rata"] == v_min else "max" if p["rata"] == v_max else ""
        batang.append({"x": L + k * lebar + lebar * 0.18, "w": lebar * 0.64, "y": y, "h": H - B - y,
                       "cx": L + k * lebar + lebar / 2, "bulan": p["bulan"], "teks": _f(p["rata"]),
                       "jenis": jenis})
    gy = []
    v = lo
    while v <= hi + 1e-9:
        gy.append({"y": Y(v), "teks": _f(v)})
        v += 0.05
    return {"W": W, "H": H, "L": L, "R": R, "B": B, "batang": batang, "gy": gy}


def grafik_garis(seri, W=560, H=200, L=40, R=12, T=14, B=26, pilih=None):
    """Koordinat grafik garis bulanan (sama gayanya dengan grafik tren wilayah)."""
    per = est.DATA["periode"]
    vals = [v for v in seri if v is not None]
    lo = int(min(vals) * 20) / 20
    hi = (int(max(vals) * 20) + 1) / 20
    n = len(seri)
    X = lambda i: L + i * (W - L - R) / max(n - 1, 1)
    Y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    pts = [(X(i), Y(v)) for i, v in enumerate(seri) if v is not None]
    garis = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pts[0][0]:.1f},{H - B} " + garis + f" {pts[-1][0]:.1f},{H - B}"
    gy = []
    v = lo
    while v <= hi + 1e-9:
        gy.append({"y": Y(v), "teks": _f(v)})
        v += 0.05
    centang, gx, titik = est.sumbu_bulan(X, Y, seri, setiap=6)
    ip = max(i for i, v in enumerate(seri) if v is not None) if pilih is None else pilih
    sorot = {"x": X(ip), "y": Y(seri[ip]), "teks": f"{est.DATA['periode_label'][ip]}: {_f(seri[ip])}"}
    return {"W": W, "H": H, "L": L, "R": R, "B": B, "T": T, "garis": garis, "area": area, "gy": gy, "gx": gx,
            "centang": centang, "titik_bulan": titik, "titik": sorot}


def nasional():
    seri = seri_nasional()
    rk = analisis(seri)
    if rk:
        rk["garis"] = grafik_garis(seri)
        rk["grafik_pola"] = grafik_pola(rk)
    return rk


def wilayah(wid, periode):
    seri = est.sm_wilayah(wid)
    rk = analisis(seri, est.ID_PERIODE.get(periode))
    if rk:
        rk["grafik_pola"] = grafik_pola(rk)
    return rk


# ---------------------------------------------------------------- peringkat dan unduhan
RAMP = ["#8c510a", "#bf812d", "#dfc27d", "#f1e5c4", "#c7eae5", "#80cdc1", "#35978f", "#01665e"]


def _warna(v, vmin=0.10, vmax=0.50):
    t = min(max((v - vmin) / (vmax - vmin), 0), 0.999)
    return RAMP[int(t * len(RAMP))]


def peringkat(n=5):
    """n kabupaten/kota paling kering dan paling basah pada bulan terbaru (nilai acuan SMAP L4)."""
    pid = len(est.DATA["periode"]) - 1
    baris = est._query("SELECT wilayah_id, soil_moisture FROM data_bulanan "
                       "WHERE periode_id = ? AND soil_moisture IS NOT NULL ORDER BY soil_moisture", (pid,))
    if not baris:
        return None

    def isi(wid, v, k):
        w = est.WILAYAH[wid]
        return {"no": k, "id": wid, "label": w["label"], "prov": w["prov"], "nilai": v, "warna": _warna(v),
                "gambut": est.DATA["penanda"][wid][0] >= 20}
    return {"periode": est.DATA["periode"][pid], "label": est.DATA["periode_label"][pid],
            "kering": [isi(w, v, k + 1) for k, (w, v) in enumerate(baris[:n])],
            "basah": [isi(w, v, k + 1) for k, (w, v) in enumerate(reversed(baris[-n:]))]}


def _angka(v, d=4):
    return "" if v is None else f"{v:.{d}f}".replace(".", ",")


def nama_berkas(teks):
    """'Kab. Pulang Pisau' -> 'Kab_Pulang_Pisau' (untuk nama kolom dan nama file)."""
    return "_".join("".join(c if c.isalnum() else " " for c in teks).split())


def _waktu(kode):
    """Kolom waktu: kode periode (2023-04) dan nama bulan saja (April).
    Nama bulan ditulis tanpa tahun, karena 'April 2023' dalam satu sel dibaca Excel sebagai tanggal 'Apr-23'."""
    return [kode, BULAN[int(kode[5:]) - 1]]


def csv_wilayah(wid):
    """CSV bulanan satu wilayah: nilai acuan SMAP, estimasi model, dan 12 variabel lingkungan.
    Pemisah titik koma dan desimal koma agar langsung terbaca di Excel berbahasa Indonesia."""
    w = est.WILAYAH[wid]
    nm = nama_berkas(w["label"])
    sm = est.sm_wilayah(wid)
    kol = (["periode", "bulan", "kabupaten_kota", "provinsi",
            f"soil_moisture_smap_{nm}_m3m3", f"estimasi_model_{nm}_m3m3"] + est.FITUR)
    baris = [";".join(kol)]
    for i, kode in enumerate(est.DATA["periode"]):
        x = est.nilai_wilayah(wid, kode)
        pred = est.prediksi(x, w["kelompok"])[0] if all(v is not None for v in x.values()) else None
        baris.append(";".join(_waktu(kode) + [w["label"], w["prov"], _angka(sm[i]), _angka(pred)]
                              + [_angka(x.get(f)) for f in est.FITUR]))
    return "\ufeff" + "\r\n".join(baris) + "\r\n"


def csv_nasional():
    """CSV rata-rata nasional per bulan (rata-rata seluruh kabupaten/kota, nilai acuan SMAP L4)."""
    seri = seri_nasional()
    baris = ["periode;bulan;soil_moisture_rata_rata_nasional_m3m3"]
    for kode, v in zip(est.DATA["periode"], seri):
        baris.append(";".join(_waktu(kode) + [_angka(v)]))
    return "\ufeff" + "\r\n".join(baris) + "\r\n"


def _semua_nilai():
    """{wilayah_id: [nilai per periode]} untuk seluruh kabupaten/kota (nilai acuan SMAP L4)."""
    n = len(est.DATA["periode"])
    sm = {w["id"]: [None] * n for w in est.WILAYAH}
    for wid, pid, v in est._query("SELECT wilayah_id, periode_id, soil_moisture FROM data_bulanan"):
        sm[wid][pid] = v
    return sm


def sebaran_status(pid=None):
    """Berapa kabupaten/kota yang nilainya di bawah, setara, atau di atas rata-rata bulan yang sama
    pada tahun-tahun lain (bulan terbaru bila pid kosong)."""
    per = est.DATA["periode"]
    pid = len(per) - 1 if pid is None else pid
    b = per[pid][5:]
    lain = [i for i, p in enumerate(per) if p[5:] == b and i != pid]
    if not lain:
        return None
    hit = {"bawah": 0, "setara": 0, "atas": 0}
    for seri in _semua_nilai().values():
        v = seri[pid]
        acuan = [seri[i] for i in lain if seri[i] is not None]
        if v is None or not acuan:
            continue
        d = v - sum(acuan) / len(acuan)
        hit["setara" if abs(d) < SETARA else ("atas" if d > 0 else "bawah")] += 1
    total = sum(hit.values())
    th = sorted(per[i][:4] for i in lain)
    return {"total": total, "label": est.DATA["periode_label"][pid],
            "pembanding": f"{BULAN[int(b) - 1]} {th[0]}" + (f"–{th[-1]}" if len(th) > 1 else ""),
            "bagian": [{"kunci": k, "jumlah": hit[k], "persen": 100 * hit[k] / total if total else 0,
                        "teks": {"bawah": "di bawah rata-rata", "setara": "setara", "atas": "di atas rata-rata"}[k]}
                       for k in ["bawah", "setara", "atas"]]}


def tahun_tersedia():
    return sorted({p[:4] for p in est.DATA["periode"]})


def csv_semua(jenis="bulanan", tahun=None):
    """CSV seluruh kabupaten/kota (nilai acuan SMAP L4).
    jenis='bulanan': satu baris per wilayah per bulan (bisa dibatasi satu tahun).
    jenis='tahunan': satu baris per wilayah, satu kolom rata-rata per tahun."""
    per = est.DATA["periode"]
    sm = _semua_nilai()
    if jenis == "tahunan":
        ths = tahun_tersedia()
        jml = {t: sum(1 for p in per if p.startswith(t)) for t in ths}
        kol = [f"rata_rata_{t}_m3m3" + ("" if jml[t] == 12 else f"_{jml[t]}_bulan") for t in ths]
        baris = [";".join(["kabupaten_kota", "provinsi", "kelompok_wilayah"] + kol)]
        for w in est.WILAYAH:
            nilai = []
            for t in ths:
                v = [sm[w["id"]][i] for i, p in enumerate(per) if p.startswith(t) and sm[w["id"]][i] is not None]
                nilai.append(_angka(sum(v) / len(v)) if v else "")
            baris.append(";".join([w["label"], w["prov"], w["kelompok"]] + nilai))
    else:
        baris = ["periode;bulan;kabupaten_kota;provinsi;kelompok_wilayah;soil_moisture_smap_m3m3"]
        for i, kode in enumerate(per):
            if tahun and not kode.startswith(tahun):
                continue
            for w in est.WILAYAH:
                baris.append(";".join(_waktu(kode) + [w["label"], w["prov"], w["kelompok"], _angka(sm[w["id"]][i])]))
    return "\ufeff" + "\r\n".join(baris) + "\r\n"
