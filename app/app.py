"""
SoilWatch ID - aplikasi web estimasi soil moisture tingkat kabupaten/kota.

Menjalankan secara lokal:
    pip install flask
    python app/app.py
lalu buka http://127.0.0.1:5000
"""
import json
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup

import estimasi as est
import ringkasan as rkn

BASE = Path(__file__).resolve().parent
app = Flask(__name__)
app.jinja_env.filters["angka"] = est.fmt


def ringkasan():
    """Angka ringkas untuk Beranda, dibuat oleh scripts/07_peta_beranda.py."""
    f = BASE / "static" / "data" / "ringkasan_beranda.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"periode_terbaru": "-", "periode_awal": "-", "jumlah_wilayah": 0,
            "jumlah_bulan": 0, "rata2_nasional": None}


def svg(nama):
    """SVG disisipkan langsung (inline) agar bisa diwarnai dan diklik lewat JavaScript."""
    f = BASE / "static" / "img" / nama
    return Markup(f.read_text(encoding="utf-8")) if f.exists() else ""


def info_fitur():
    """Daftar variabel untuk form simulasi, dikelompokkan seperti rancangan L4.4."""
    grup = {}
    for f in est.FITUR:
        lab, sat, kel, step = est.INFO[f]
        s = est.STAT[f]
        grup.setdefault(kel, []).append({
            "kode": f, "label": lab, "satuan": sat, "step": step,
            "min": est.BATAS[f][0], "max": est.BATAS[f][1],
            "dmin": s["min"], "dmax": s["max"], "median": s["median"],
        })
    urutan = ["Cuaca", "Radiasi dan angin", "Vegetasi dan permukaan", "Tanah dan topografi"]
    return [(k, grup[k]) for k in urutan]


def periode_default():
    return est.DATA["periode"][-1]


@app.route("/")
def beranda():
    return render_template("beranda.html", menu="beranda", r=ringkasan(), peta=svg("peta_beranda.svg"),
                           rk=rkn.nasional(), pk=rkn.peringkat(), sb=rkn.sebaran_status(),
                           tahun_data=rkn.tahun_tersedia())


@app.route("/prediksi")
def prediksi():
    return render_template("prediksi.html", menu="prediksi", peta=svg("peta_beranda.svg"))


@app.route("/prediksi/otomatis")
def otomatis():
    return render_template("otomatis.html", menu="prediksi", peta=svg("peta_wilayah.svg"),
                           tahun=sorted({p[:4] for p in est.DATA["periode"]}), pilih_id=request.args.get("id", ""),
                           pilih_periode=request.args.get("periode", periode_default()))


@app.route("/prediksi/simulasi", methods=["GET", "POST"])
def simulasi():
    nilai, galat = {}, {}
    if request.method == "POST":
        for f in est.FITUR:
            mentah = request.form.get(f, "").strip().replace(",", ".")
            try:
                v = float(mentah)
                lo, hi = est.BATAS[f]
                if not lo <= v <= hi:
                    galat[f] = f"Harus di antara {est.fmt(lo, 0)} dan {est.fmt(hi, 0)}"
                nilai[f] = v
            except ValueError:
                galat[f] = "Wajib diisi dengan angka"
        if "suhu_celsius" in nilai and "dew_point_celsius" in nilai:
            if nilai["dew_point_celsius"] > nilai["suhu_celsius"]:
                galat["dew_point_celsius"] = "Titik embun tidak boleh lebih tinggi dari suhu udara"
            nilai["relative_humidity"] = est.rh_dari(nilai["suhu_celsius"], nilai["dew_point_celsius"])
            galat.pop("relative_humidity", None)
        if not galat:
            return hasil_simulasi(nilai)
    else:
        # isian awal: dari wilayah tertentu (tombol "Coba Skenario") atau dari query string
        wid, per = request.args.get("dari"), request.args.get("periode")
        if wid is not None and wid.isdigit() and per in est.ID_PERIODE and int(wid) < len(est.WILAYAH):
            nilai = est.nilai_wilayah(int(wid), per)
        for f in est.FITUR:
            if request.args.get(f):
                try:
                    nilai[f] = float(request.args[f])
                except ValueError:
                    pass
    return render_template("simulasi.html", menu="prediksi", grup=info_fitur(), nilai=nilai, galat=galat)


def hasil_simulasi(x):
    v, sumber = est.prediksi(x)
    return render_template(
        "hasil.html", menu="prediksi", mode="simulasi", judul="Hasil Simulasi Skenario",
        sub="Skenario hipotetis berdasarkan nilai variabel yang Anda masukkan",
        v=v, sumber=sumber, kategori=est.kategori(v), wf=est.waterfall(x, v),
        glob=est.kepentingan_global(), x=x, info=est.INFO, fitur=est.FITUR,
        kembali=url_for("simulasi", **{f: round(x[f], 4) for f in est.FITUR if f != "relative_humidity"}),
        stat=est.STAT["soil_moisture"])


@app.route("/hasil")
def hasil():
    try:
        wid = int(request.args.get("id", ""))
        w = est.WILAYAH[wid]
    except (ValueError, IndexError):
        return redirect(url_for("otomatis"))
    per = request.args.get("periode", periode_default())
    if per not in est.ID_PERIODE:
        abort(404)
    x = est.nilai_wilayah(wid, per)
    if any(v is None for v in x.values()):
        abort(404)
    v, sumber = est.prediksi(x, w["kelompok"])
    i = est.ID_PERIODE[per]
    return render_template(
        "hasil.html", menu="prediksi", mode="otomatis", judul=w["label"],
        sub=f'{w["prov"]} · {est.DATA["periode_label"][i]}', w=w, wid=wid, periode=per,
        v=v, sumber=sumber, kategori=est.kategori(v), wf=est.waterfall(x, v, w["kelompok"]),
        glob=est.kepentingan_global(), tren=est.tren(wid, per), smap=est.sm_wilayah(wid)[i],
        penanda=est.DATA["penanda"][wid], stat=est.STAT["soil_moisture"],
        gambut=est.galat_gambut(v) if est.DATA["penanda"][wid][0] >= 20 else None,
        rk=rkn.wilayah(wid, per))


def _csv(teks, nama):
    return Response(teks, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{nama}"'})


@app.route("/unduh/wilayah/<int:wid>.csv")
def unduh_wilayah(wid):
    """Data bulanan satu kabupaten/kota (SMAP, estimasi model, 12 variabel) sebagai CSV."""
    if not 0 <= wid < len(est.WILAYAH):
        abort(404)
    return _csv(rkn.csv_wilayah(wid), f"soilwatch_{rkn.nama_berkas(est.WILAYAH[wid]['label'])}.csv")


@app.route("/unduh/semua.csv")
def unduh_semua():
    """Data seluruh kabupaten/kota: bulanan (semua atau satu tahun) atau rata-rata tahunan."""
    jenis = request.args.get("jenis", "bulanan")
    tahun = request.args.get("tahun", "")
    if jenis == "nasional":
        return _csv(rkn.csv_nasional(), "soilwatch_rata_rata_nasional.csv")
    if jenis not in ("bulanan", "tahunan") or (tahun and tahun not in rkn.tahun_tersedia()):
        abort(400)
    nama = "rata_rata_tahunan" if jenis == "tahunan" else f"bulanan_{tahun or 'semua_tahun'}"
    return _csv(rkn.csv_semua(jenis, tahun or None), f"soilwatch_seluruh_kabkota_{nama}.csv")


@app.route("/unduh/nasional.csv")
def unduh_nasional():
    """Rata-rata soil moisture nasional per bulan sebagai CSV."""
    return _csv(rkn.csv_nasional(), "soilwatch_rata_rata_nasional.csv")


@app.route("/api/peta")
def api_peta():
    """Data peta Mode Otomatis, diambil dari basis data."""
    return jsonify(est.data_peta())


@app.route("/informasi")
def informasi():
    return render_template("informasi.html", menu="informasi")


@app.context_processor
def umum():
    return {"penanda_contoh": est.DATA["penanda_contoh"],
            "lapisan_air": est.DATA.get("lapisan_air", 0), "lapisan_gambut": est.DATA.get("lapisan_gambut", 0),
            "sumber_kepentingan": est.DATA.get("sumber_kepentingan", "contoh"),
            "konf": est.KONF or {}}


if __name__ == "__main__":
    app.run(debug=True)
