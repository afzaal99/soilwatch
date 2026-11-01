"""
Dashboard admin SoilWatch ID: masuk, unggah data bulanan, pantau akurasi, pulihkan cadangan.

Akun admin disimpan di berkas .env (di folder soilwatch, tidak ikut ke GitHub), dibuat dengan:
    python scripts/buat_admin.py
"""
import hmac
import os
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash

import estimasi as est
import latih_ulang as lu
import pembaruan as pb

bp = Blueprint("admin", __name__, url_prefix="/admin")
ENV = est.ROOT / ".env"
_GAGAL = {}                 # ip -> [jumlah gagal, waktu terakhir]; batasi tebak-tebakan kata sandi
MAKS_GAGAL, JEDA = 5, 300   # 5 kali salah -> tunggu 5 menit
MAKS_UKURAN = 20 * 1024 * 1024


def baca_env():
    """Membaca .env sederhana (KUNCI=nilai) tanpa pustaka tambahan; variabel sistem diutamakan."""
    nilai = {}
    if ENV.exists():
        for baris in ENV.read_text(encoding="utf-8").splitlines():
            baris = baris.strip()
            if baris and not baris.startswith("#") and "=" in baris:
                k, v = baris.split("=", 1)
                nilai[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "SECRET_KEY"):
        if os.environ.get(k):
            nilai[k] = os.environ[k]
    return nilai


def siap():
    e = baca_env()
    return bool(e.get("ADMIN_USERNAME") and e.get("ADMIN_PASSWORD_HASH"))


def wajib_masuk(fn):
    @wraps(fn)
    def bungkus(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin.masuk", lanjut=request.path))
        return fn(*a, **kw)
    return bungkus


def token_form():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@bp.before_request
def cek_csrf():
    if request.method == "POST":
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "-")):
            abort(400, "Formulir kedaluwarsa. Muat ulang halaman lalu coba lagi.")


@bp.app_template_filter("waktu_teks")
def waktu_teks(w):
    return pb._waktu_teks(w or "")


@bp.app_context_processor
def konteks_admin():
    return {"csrf_token": token_form}


# ----------------------------------------------------------------------------- masuk/keluar
@bp.route("/masuk", methods=["GET", "POST"])
def masuk():
    if not siap():
        return render_template("admin/belum_siap.html", menu="admin")
    if session.get("admin"):
        return redirect(url_for("admin.dashboard"))
    ip = request.remote_addr or "-"
    gagal, terakhir = _GAGAL.get(ip, [0, 0])
    tunggu = int(JEDA - (time.time() - terakhir)) if gagal >= MAKS_GAGAL else 0
    if request.method == "POST" and tunggu <= 0:
        e = baca_env()
        nama = request.form.get("nama", "").strip()
        sandi = request.form.get("sandi", "")
        if hmac.compare_digest(nama, e["ADMIN_USERNAME"]) and check_password_hash(e["ADMIN_PASSWORD_HASH"], sandi):
            _GAGAL.pop(ip, None)
            session.clear()
            session["admin"] = nama
            session.permanent = True
            lanjut = request.args.get("lanjut", "")
            return redirect(lanjut if lanjut.startswith("/admin") else url_for("admin.dashboard"))
        _GAGAL[ip] = [gagal + 1 if gagal < MAKS_GAGAL else 1, time.time()]
        sisa = MAKS_GAGAL - _GAGAL[ip][0]
        flash("Nama pengguna atau kata sandi salah." +
              (f" Sisa percobaan: {sisa}." if sisa > 0 else " Coba lagi dalam 5 menit."), "galat")
        return redirect(url_for("admin.masuk", **request.args))
    return render_template("admin/masuk.html", menu="admin", tunggu=max(tunggu, 0))


@bp.route("/keluar", methods=["POST"])
def keluar():
    session.clear()
    flash("Anda sudah keluar dari dashboard admin.", "ok")
    return redirect(url_for("admin.masuk"))


# ----------------------------------------------------------------------------- dashboard
def grafik_mae(evals, mae_uji):
    """Grafik batang MAE per bulan yang dievaluasi (pemantauan akurasi dari waktu ke waktu)."""
    if not evals:
        return None
    W, H, L, R, T, B = 560, 200, 46, 12, 14, 26
    vmax = max([e["mae"] for e in evals] + [mae_uji * pb.AMBANG_MAE if mae_uji else 0]) * 1.15
    lebar = (W - L - R) / max(len(evals), 6)
    Y = lambda v: T + (1 - v / vmax) * (H - T - B)
    batang = []
    for i, e in enumerate(evals):
        perhatian = mae_uji and e["mae"] > mae_uji * pb.AMBANG_MAE
        y = Y(e["mae"])
        batang.append({"x": L + i * lebar + lebar * 0.2, "w": lebar * 0.6, "y": y, "h": H - B - y,
                       "cx": L + i * lebar + lebar / 2, "teks": pb._f(e["mae"], 4),
                       "bulan": pb.label(e["kode"]), "pendek": est.BLN_PENDEK[int(e["kode"][5:]) - 1] +
                       (f" {e['kode'][2:4]}" if e["kode"][5:] == "01" or i == 0 else ""),
                       "kelas": "bad" if perhatian else ""})
    langkah = 0.01 if vmax > 0.03 else 0.005
    gy, v = [], 0.0
    while v <= vmax:
        gy.append({"y": Y(v), "teks": pb._f(v, 3)})
        v += langkah
    garis = []
    if mae_uji:
        garis.append({"y": Y(mae_uji), "teks": "MAE uji", "kelas": "uji"})
        if mae_uji * pb.AMBANG_MAE < vmax:
            garis.append({"y": Y(mae_uji * pb.AMBANG_MAE), "teks": f"batas {pb._f(pb.AMBANG_MAE, 1)}×", "kelas": "batas"})
    return {"W": W, "H": H, "L": L, "R": R, "B": B, "batang": batang, "gy": gy, "garis": garis}


@bp.route("/")
@wajib_masuk
def dashboard():
    mae, r2 = pb.mae_uji()
    evals = pb.evaluasi_tersimpan()
    return render_template(
        "admin/dashboard.html", menu="admin", bagian="dashboard", jadwal=pb.info_jadwal(), riwayat=pb.riwayat(8),
        cadangan=pb.daftar_cadangan()[:5], evals=evals[::-1][:6], grafik=grafik_mae(evals, mae),
        mae_uji=mae, r2_uji=r2, n_bulan=len(est.DATA["periode"]), n_wilayah=len(est.WILAYAH),
        awal=est.DATA["periode_label"][0], akhir=est.DATA["periode_label"][-1], konf=est.KONF or {},
        ambang=pb.AMBANG_MAE, terakhir_perhatian=bool(evals and mae and evals[-1]["mae"] > mae * pb.AMBANG_MAE),
        latih=lu.kesiapan(), status_latih=lu.baca_status(), kand=lu.kandidat())


# ----------------------------------------------------------------------------- unggah
@bp.route("/unggah", methods=["GET", "POST"])
@wajib_masuk
def unggah():
    if request.method == "POST":
        f = request.files.get("berkas")
        if not f or not f.filename:
            flash("Pilih berkas CSV terlebih dahulu.", "galat")
            return redirect(url_for("admin.unggah"))
        if not f.filename.lower().endswith(".csv"):
            flash("Format berkas harus .csv (hasil ekspor script 09 dari Google Drive).", "galat")
            return redirect(url_for("admin.unggah"))
        isi = f.read(MAKS_UKURAN + 1)
        if len(isi) > MAKS_UKURAN:
            flash("Ukuran berkas melebihi 20 MB.", "galat")
            return redirect(url_for("admin.unggah"))
        df, ring = pb.periksa(isi, Path(f.filename).name)
        if df is None:
            return render_template("admin/pratinjau.html", menu="admin", bagian="unggah", r=ring, token=None)
        token = pb.simpan_sementara(df, ring)
        return redirect(url_for("admin.pratinjau", token=token))
    return render_template("admin/unggah.html", menu="admin", bagian="unggah", jadwal=pb.info_jadwal(),
                           sumber=pb.SUMBER_DATA, pilihan_bulan=pb.pilihan_bulan())


@bp.route("/script09")
@wajib_masuk
def script09():
    """Script GEE 09 dengan daftar BULAN_BARU yang sudah terisi sesuai pilihan admin."""
    try:
        teks = pb.script_gee(request.args.get("dari", ""), request.args.get("sampai", ""))
    except ValueError as e:
        return Response(str(e), status=400, mimetype="text/plain")
    r = Response(teks, mimetype="text/plain; charset=utf-8")
    if request.args.get("unduh"):
        r.headers["Content-Disposition"] = "attachment; filename=09_gee_ekstraksi_bulanan.js"
    return r


@bp.route("/unggah/<token>")
@wajib_masuk
def pratinjau(token):
    df, ring = pb.ambil_sementara(token)
    if df is None:
        flash("Data unggahan tidak ditemukan atau sudah kedaluwarsa. Silakan unggah ulang.", "galat")
        return redirect(url_for("admin.unggah"))
    return render_template("admin/pratinjau.html", menu="admin", bagian="unggah", r=ring, token=token)


@bp.route("/unggah/<token>/simpan", methods=["POST"])
@wajib_masuk
def simpan(token):
    try:
        hasil = pb.simpan(token, timpa=request.form.get("timpa") == "1")
    except ValueError as e:
        flash(str(e), "galat")
        return redirect(url_for("admin.pratinjau", token=token) if pb.ambil_sementara(token)[0] is not None
                        else url_for("admin.unggah"))
    flash(f"Berhasil: {', '.join(hasil['bulan'])} tersimpan. {hasil['peta']} "
          "Seluruh halaman aplikasi sudah memakai data terbaru.", "ok")
    return redirect(url_for("admin.dashboard"))


@bp.route("/unggah/<token>/batal", methods=["POST"])
@wajib_masuk
def batal(token):
    pb.hapus_sementara(token)
    flash("Unggahan dibatalkan. Tidak ada data yang diubah.", "ok")
    return redirect(url_for("admin.unggah"))


# ----------------------------------------------------------------------------- cadangan
@bp.route("/cadangan")
@wajib_masuk
def cadangan():
    return render_template("admin/cadangan.html", menu="admin", bagian="cadangan", daftar=pb.daftar_cadangan(),
                           akhir=est.DATA["periode_label"][-1])


@bp.route("/cadangan/pulihkan", methods=["POST"])
@wajib_masuk
def pulihkan():
    try:
        pb.pulihkan(request.form.get("nama", ""))
    except ValueError as e:
        flash(str(e), "galat")
        return redirect(url_for("admin.cadangan"))
    flash(f"Basis data dipulihkan. Data aplikasi sekarang sampai {est.DATA['periode_label'][-1]}.", "ok")
    return redirect(url_for("admin.dashboard"))


# ----------------------------------------------------------------------------- model
@bp.route("/model")
@wajib_masuk
def model():
    return render_template("admin/model.html", menu="admin", bagian="model", siap=lu.kesiapan(),
                           status=lu.baca_status(), kand=lu.kandidat(), arsip=lu.daftar_arsip(), konf=est.KONF or {})


@bp.route("/model/latih", methods=["POST"])
@wajib_masuk
def model_latih():
    galat = lu.mulai()
    if galat:
        flash(galat, "galat")
    return redirect(url_for("admin.model"))


@bp.route("/model/status")
@wajib_masuk
def model_status():
    return jsonify(lu.baca_status())


@bp.route("/model/pasang", methods=["POST"])
@wajib_masuk
def model_pasang():
    try:
        lu.pasang(request.form.get("id", ""))
    except ValueError as e:
        flash(str(e), "galat")
        return redirect(url_for("admin.model"))
    flash("Model baru sudah dipakai di seluruh aplikasi. Model lama tersimpan di arsip dan bisa dikembalikan.", "ok")
    return redirect(url_for("admin.model"))


@bp.route("/model/kembalikan", methods=["POST"])
@wajib_masuk
def model_kembalikan():
    try:
        lu.kembalikan(request.form.get("id", ""))
    except ValueError as e:
        flash(str(e), "galat")
        return redirect(url_for("admin.model"))
    flash(f"Model dikembalikan. Model aktif sekarang dilatih dengan data sampai {pb.label(lu.akhir_latih())}.", "ok")
    return redirect(url_for("admin.model"))
