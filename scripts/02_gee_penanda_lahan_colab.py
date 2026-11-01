"""
02 - Ekstraksi penanda lahan dari Google Earth Engine (Subbab 2.2.1.8)  [jalankan di Google Colab]
=================================================================================================
Menghitung, untuk setiap kabupaten/kota (batas FAO GAUL 2025 level 2, 514 wilayah, sama dengan dataset utama):
  - prop_badan_air  : proporsi luas badan air darat (kelas 80 "Permanent water bodies" ESA WorldCover
                      v200, 10 m), TANPA laut
  - prop_pertanian  : proporsi luas kelas 40 "Cropland" ESA WorldCover
  - prop_gambut     : proporsi luas Peta Lahan Gambut Indonesia (Kementan) yang diunggah sebagai aset

Catatan laut: kelas 80 WorldCover juga mencakup laut, dan batas GAUL di pesisir ikut memuat
sebagian laut. Piksel air dianggap badan air DARAT jika:
  (a) elevasi SRTM > 0 m, ATAU
  (b) berada di dalam batas daratan kabupaten/kota GAUL dan lebih dari JARAK_PANTAI_M dari laut.
Syarat (b) ditambahkan (versi 2) karena SRTM di atas permukaan air dataran rendah sering bernilai
0 m atau negatif, sehingga danau dataran rendah seperti Danau Rombebai (Mamberamo) ikut terbuang.

Gambut: persentase gambut per kabupaten/kota sekarang dihitung oleh script 02b dari tabel Trase
(Peta Lahan Gambut Indonesia, Kementan 2019). ASET_GAMBUT di bawah cukup dibiarkan None.
SETELAH script ini dijalankan ulang, jalankan lagi script 02b (CSV penanda tertimpa tanpa kolom gambut).

Hasil diekspor ke Google Drive (folder "skripsi_gee"), semuanya ditaruh di soilwatch/data/geo/:
  1. penanda_lahan_kabkota.csv         proporsi lahan per kabupaten/kota
  2. batas_kabkota_gaul2025.geojson    batas 514 kabupaten/kota untuk peta web
  3. badan_air_besar.geojson           bentuk badan air darat >= LUAS_MIN_AIR km2 (danau, waduk)
  4. sebaran_gambut.geojson            bentuk sebaran gambut >= LUAS_MIN_GAMBUT km2 (hanya jika ASET_GAMBUT diisi)

Persiapan:
1. Unggah shapefile peta gambut Kementan ke GEE: Code Editor > Assets > NEW > Shape files
   (pilih .shp, .shx, .dbf, .prj sekaligus). Catat ID asetnya, lalu isi ASET_GAMBUT di bawah.
   Kalau belum punya asetnya, biarkan None: kolom gambut dan file nomor 4 dilewati.
2. Isi PROJECT_ID dengan ID Google Cloud project yang terdaftar di Earth Engine.
3. Jalankan semua sel, lalu pantau tab Tasks di Code Editor GEE (atau perintah status di akhir).
   Ekspor bentuk badan air dan gambut bisa memakan waktu puluhan menit.
"""

# !pip install -q earthengine-api   # biasanya sudah terpasang di Colab
import ee

PROJECT_ID = "analisis-soil-moisture-id"
ASET_GAMBUT = None  # contoh: "projects/ISI-PROJECT-ID/assets/peta_gambut_kementan"
FOLDER_DRIVE = "skripsi_gee"
SKALA = 100            # meter; skala hitung proporsi (WorldCover 10 m dirata-ratakan ke 100 m)
AMBANG_PENANDA = 0.20  # 20%, Subbab 2.2.1.10
SKALA_VEKTOR = 250     # meter; resolusi pembentukan poligon untuk peta (cukup untuk tampilan nasional)
LUAS_MIN_AIR = 25      # km2; badan air lebih kecil tidak tampak pada peta skala nasional
LUAS_MIN_GAMBUT = 25   # km2
JARAK_PANTAI_M = 1000  # meter; air lebih dari 1 km dari laut dan di dalam daratan dianggap air darat

ee.Authenticate()
ee.Initialize(project=PROJECT_ID)

INDONESIA = ee.Geometry.Rectangle([94.5, -11.5, 141.5, 6.5], None, False)

# ----------------------------------------------------------------- batas wilayah
# FAO GAUL 2025: nama kolom huruf besar (GAUL1_NAME, GAUL2_NAME), diganti ke nama yang dipakai
# seluruh script (ADM1_NAME, ADM2_NAME, ADM2_CODE)
kabkota = (ee.FeatureCollection("FAO/GAUL/2025/level2")
           .filter(ee.Filter.eq("GAUL0_NAME", "Indonesia"))
           .select(["GAUL1_NAME", "GAUL2_NAME", "GAUL2_CODE"], ["ADM1_NAME", "ADM2_NAME", "ADM2_CODE"]))
print("Jumlah kabupaten/kota GAUL 2025:", kabkota.size().getInfo())  # harus 514

# ----------------------------------------------------------------- ESA WorldCover
wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
proj_halus = wc.projection()
srtm = ee.Image("USGS/SRTMGL1_003")
# daratan = di dalam batas kabupaten/kota GAUL; "pedalaman" = daratan yang > JARAK_PANTAI_M dari laut
daratan = ee.Image(0).byte().paint(kabkota, 1).reproject(crs="EPSG:4326", scale=SKALA)
pedalaman = daratan.focalMin(radius=JARAK_PANTAI_M, kernelType="circle", units="meters").reproject(
    crs="EPSG:4326", scale=SKALA)
air_darat = wc.eq(80).And(srtm.gt(0).unmask(0).Or(pedalaman))   # laut dan pinggiran pantai dibuang

# cek cepat: Danau Rombebai (Mamberamo Raya) harus terbaca sebagai air darat
_cek = (ee.Image.cat(wc.eq(80).rename("air_worldcover"), air_darat.rename("air_darat"))
        .reduceRegion(ee.Reducer.mean(), ee.Geometry.Point([137.90, -1.85]).buffer(3000), scale=30).getInfo())
print("Cek Danau Rombebai (porsi piksel air dalam radius 3 km):", {k: round(v or 0, 2) for k, v in _cek.items()})
pertanian = wc.eq(40)


def proporsi(biner, skala):
    """Citra 0/1 dirata-ratakan ke `skala` meter (nilai = proporsi luas)."""
    return (biner.unmask(0).rename("p")
            .reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
            .reproject(crs=proj_halus.crs(), scale=skala))


citra = proporsi(air_darat, SKALA).rename("prop_badan_air").addBands(
    proporsi(pertanian, SKALA).rename("prop_pertanian"))

# ----------------------------------------------------------------- peta gambut
if ASET_GAMBUT:
    gambut_fc = ee.FeatureCollection(ASET_GAMBUT)
    gambut_biner = ee.Image(0).byte().paint(gambut_fc, 1)          # 1 = gambut, 0 = bukan
    gambut_img = (gambut_biner.reproject(crs="EPSG:4326", scale=30)
                  .reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
                  .reproject(crs="EPSG:4326", scale=SKALA)
                  .rename("prop_gambut"))
    citra = citra.addBands(gambut_img)

# ----------------------------------------------------------------- 1. ringkas per wilayah
hasil = citra.reduceRegions(collection=kabkota, reducer=ee.Reducer.mean(), scale=SKALA, tileScale=16)


def tambah_penanda(f):
    f = f.set("penanda_badan_air", ee.Number(f.get("prop_badan_air")).gte(AMBANG_PENANDA))
    if ASET_GAMBUT:
        f = f.set("penanda_gambut", ee.Number(f.get("prop_gambut")).gte(AMBANG_PENANDA))
    return f.setGeometry(None)


hasil = hasil.map(tambah_penanda)
kolom = ["ADM1_NAME", "ADM2_NAME", "ADM2_CODE", "prop_badan_air", "prop_pertanian",
         "penanda_badan_air"] + (["prop_gambut", "penanda_gambut"] if ASET_GAMBUT else [])
tugas = [ee.batch.Export.table.toDrive(
    collection=hasil, description="penanda_lahan_kabkota", folder=FOLDER_DRIVE,
    fileNamePrefix="penanda_lahan_kabkota", fileFormat="CSV", selectors=kolom)]

# ----------------------------------------------------------------- 2. batas untuk peta web
# Batas disederhanakan (toleransi 500 m) agar file peta web ringan. Wilayah kecil (< 200 km2, mis. kota
# pesisir seperti Kota Sibolga) memakai toleransi 50 m supaya bentuknya tidak hilang saat disederhanakan.
def sederhanakan(f):
    g = f.geometry()
    return f.setGeometry(ee.Geometry(ee.Algorithms.If(
        g.area(maxError=10).lt(2e8), g.simplify(maxError=50), g.simplify(maxError=500))))


batas_web = kabkota.map(sederhanakan)
tugas.append(ee.batch.Export.table.toDrive(
    collection=batas_web, description="batas_kabkota_gaul2025", folder=FOLDER_DRIVE,
    fileNamePrefix="batas_kabkota_gaul2025", fileFormat="GeoJSON"))


# ----------------------------------------------------------------- 3 & 4. bentuk asli untuk peta web
def jadi_poligon(biner, luas_min, nama_kelas):
    """Piksel 1 -> poligon; hanya yang luasnya >= luas_min km2; bentuk disederhanakan."""
    vektor = biner.selfMask().reduceToVectors(
        geometry=INDONESIA, scale=SKALA_VEKTOR, geometryType="polygon", eightConnected=True,
        labelProperty="kelas", maxPixels=1e10, tileScale=16)
    vektor = vektor.map(lambda f: f.set(
        "luas_km2", f.geometry().area(maxError=100).divide(1e6), "jenis", nama_kelas))
    return (vektor.filter(ee.Filter.gte("luas_km2", luas_min))
            .map(lambda f: f.setGeometry(f.geometry().simplify(maxError=SKALA_VEKTOR)))
            .select(["luas_km2", "jenis"]))


air_kasar = proporsi(air_darat, SKALA_VEKTOR).gte(0.5)          # piksel 250 m: minimal separuhnya air
danau = jadi_poligon(air_kasar, LUAS_MIN_AIR, "badan_air")
tugas.append(ee.batch.Export.table.toDrive(
    collection=danau, description="badan_air_besar", folder=FOLDER_DRIVE,
    fileNamePrefix="badan_air_besar", fileFormat="GeoJSON"))

if ASET_GAMBUT:
    gambut_kasar = gambut_biner.reproject(crs="EPSG:4326", scale=SKALA_VEKTOR)
    sebaran = jadi_poligon(gambut_kasar, LUAS_MIN_GAMBUT, "gambut")
    tugas.append(ee.batch.Export.table.toDrive(
        collection=sebaran, description="sebaran_gambut", folder=FOLDER_DRIVE,
        fileNamePrefix="sebaran_gambut", fileFormat="GeoJSON"))

for t in tugas:
    t.start()
print(f"{len(tugas)} tugas ekspor dikirim. Pantau di tab Tasks pada Code Editor GEE, atau jalankan:")
print("[(t.config['description'], t.status()['state']) for t in tugas]")
