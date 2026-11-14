"""
Titik masuk Vercel untuk aplikasi Flask SoilWatch ID.
Vercel menjalankan berkas ini sebagai serverless function; seluruh permintaan diarahkan ke sini (lihat vercel.json).
"""
import os
import sys
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR / "scripts"))
sys.path.insert(0, str(AKAR / "app"))
os.environ.setdefault("SOILWATCH_INSTANCE", "/tmp/soilwatch")   # di Vercel hanya /tmp yang bisa ditulisi

from app import app  # noqa: E402,F401  (objek Flask bernama "app" dipakai Vercel)
