"""
Membuat atau mengganti akun admin SoilWatch ID.

Jalankan dari folder soilwatch:
    python scripts/buat_admin.py

Hasilnya disimpan di berkas soilwatch/.env (TIDAK ikut ke GitHub karena tercantum di .gitignore):
    ADMIN_USERNAME       nama pengguna admin
    ADMIN_PASSWORD_HASH  kata sandi dalam bentuk hash (kata sandi asli tidak pernah disimpan)
    SECRET_KEY           kunci acak untuk mengamankan sesi login
"""
import getpass
import secrets
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

ENV = Path(__file__).resolve().parents[1] / ".env"


def baca():
    nilai = {}
    if ENV.exists():
        for baris in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in baris and not baris.strip().startswith("#"):
                k, v = baris.split("=", 1)
                nilai[k.strip()] = v.strip()
    return nilai


def main():
    lama = baca()
    print("=== Akun admin SoilWatch ID ===")
    if lama.get("ADMIN_USERNAME"):
        print(f"Akun yang ada sekarang: {lama['ADMIN_USERNAME']} (akan diganti)")
    nama = input("Nama pengguna [admin]: ").strip() or "admin"
    while True:
        sandi = getpass.getpass("Kata sandi (min. 8 karakter, tidak tampil saat diketik): ")
        if len(sandi) < 8:
            print("  Kata sandi terlalu pendek, minimal 8 karakter.")
            continue
        if sandi != getpass.getpass("Ulangi kata sandi: "):
            print("  Kata sandi tidak sama, ulangi.")
            continue
        break
    lama.update({
        "ADMIN_USERNAME": nama,
        "ADMIN_PASSWORD_HASH": generate_password_hash(sandi),
        "SECRET_KEY": lama.get("SECRET_KEY") or secrets.token_hex(32),
    })
    isi = ["# Pengaturan rahasia SoilWatch ID. JANGAN diunggah ke GitHub atau dibagikan.",
           "# Dibuat oleh scripts/buat_admin.py"]
    isi += [f"{k}={v}" for k, v in lama.items()]
    ENV.write_text("\n".join(isi) + "\n", encoding="utf-8")
    print(f"\nTersimpan di {ENV}")
    print("Jalankan ulang aplikasi, lalu buka http://127.0.0.1:5000/admin")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nDibatalkan.")
