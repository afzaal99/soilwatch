// =========================================================================
// 09 - EKSTRAKSI DATA BULANAN SOILWATCH ID (dataset penelitian dan data bulan baru)
// [jalankan di GEE Code Editor: code.earthengine.google.com]
// =========================================================================
// Dipakai untuk:
//   a. membuat dataset penelitian (Januari 2023 - Juni 2026; per tahun, lalu disimpan di data/raw), dan
//   b. mengambil data bulan baru untuk diunggah lewat dashboard admin.
// Perhitungan 12 variabel sama dengan script ekstraksi awal skripsi, dengan tambahan:
//   1. Batas wilayah FAO GAUL 2025 (514 kabupaten/kota, 38 provinsi). Kolom diberi nama
//      ADM1_NAME (provinsi), ADM2_NAME (kabupaten/kota), ADM2_CODE (kode GAUL wilayah).
//   2. Kolom relative_humidity langsung dihitung dengan Persamaan (2.5)-(2.6).
//   3. Sebelum ekspor, dicek kelengkapan data tiap sumber (jumlah citra per bulan),
//      agar bulan yang datanya belum lengkap tidak ikut dipakai.
//   4. Wilayah yang lebih kecil dari piksel 9 km diberi nilai dari area sekitarnya (radius 10 km,
//      atau 30 km jika masih kosong; kolom wilayah_kecil), sehingga semua 514 kabupaten/kota punya data.
//
// Cara pakai:
//   1. Isi BULAN_BARU, misalnya [[2026, 7], [2026, 8]].
//   2. Klik Run. Baca hasil cek kelengkapan di tab Console.
//   3. Jika semua "lengkap", buka tab Tasks lalu klik RUN pada tugas ekspor.
//   4. Unduh CSV dari Google Drive (folder skripsi_gee), unggah di dashboard admin.
// =========================================================================

var BULAN_BARU = [[2026, 7], [2026, 8], [2026, 9], [2026, 10]];
var FOLDER_DRIVE = 'skripsi_gee';


// 1. BATAS WILAYAH (FAO GAUL 2025 level 2: 514 kabupaten/kota)
var adminBoundaries = ee.FeatureCollection('FAO/GAUL/2025/level2')
  .filter(ee.Filter.eq('GAUL0_NAME', 'Indonesia'))
  .select(['GAUL1_NAME', 'GAUL2_NAME', 'GAUL2_CODE'], ['ADM1_NAME', 'ADM2_NAME', 'ADM2_CODE']);
var N_WILAYAH = 514;


// 2. CITRA KOMPOSIT BULANAN (tidak diubah dari script dataset skripsi)
function buildMonthlyComposite(year, month) {
  var monthStart = ee.Date.fromYMD(year, month, 1);
  var monthEnd = monthStart.advance(1, 'month');

  var soilMoisture = ee.ImageCollection('NASA/SMAP/SPL4SMGP/008')
    .filterDate(monthStart, monthEnd).select('sm_surface').mean();

  var curahHujan = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY')
    .filterDate(monthStart, monthEnd).select('precipitation').sum();

  var era5 = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
    .filterDate(monthStart, monthEnd).mean();
  var suhu = era5.select('temperature_2m').subtract(273.15);
  var dewPointCelsius = era5.select('dewpoint_temperature_2m').subtract(273.15);

  var ndvi = ee.ImageCollection('MODIS/061/MOD13A2')
    .filterDate(monthStart, monthEnd).select('NDVI').mean().multiply(0.0001);

  var lst = ee.ImageCollection('MODIS/061/MOD11A2')
    .filterDate(monthStart, monthEnd).select('LST_Day_1km').mean()
    .multiply(0.02).subtract(273.15);

  var elevation = ee.Image('USGS/SRTMGL1_003').select('elevation');
  var slope = ee.Terrain.slope(elevation);

  var solarRadiation = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
    .filterDate(monthStart, monthEnd)
    .select('surface_solar_radiation_downwards_sum').mean().divide(1e6);

  var windSpeed = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR')
    .filterDate(monthStart, monthEnd)
    .map(function(image) {
      var u = image.select('u_component_of_wind_10m');
      var v = image.select('v_component_of_wind_10m');
      return u.pow(2).add(v.pow(2)).sqrt().rename('wind_speed');
    }).mean();

  var soilType = ee.Image('OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02').select('b0');

  var soilTemperature = era5.select('soil_temperature_level_1').subtract(273.15);

  var composite = ee.Image.cat([
    soilMoisture.rename('soil_moisture'),
    curahHujan.rename('curah_hujan_bulanan'),
    suhu.rename('suhu_celsius'),
    dewPointCelsius.rename('dew_point_celsius'),
    ndvi.rename('ndvi'),
    lst.rename('lst_celsius'),
    elevation.rename('elevation'),
    slope.rename('slope'),
    solarRadiation.rename('solar_radiation'),
    windSpeed.rename('wind_speed'),
    soilType.rename('clay_content'),
    soilTemperature.rename('soil_temperature')
  ]);

  return composite.set({
    'tahun': year, 'bulan': month, 'tanggal': monthStart.format('YYYY-MM-01')
  });
}


// 3. EKSTRAKSI PER KABUPATEN/KOTA (rata-rata wilayah, skala 9 km mengikuti SMAP)
// Persamaan (2.5)-(2.6): es(T) = 6,112 exp(17,67 T / (T + 243,5)); RH = 100 es(Td) / es(T)
function es(t) {
  return ee.Number(6.112).multiply(t.multiply(17.67).divide(t.add(243.5)).exp());
}

// Wilayah yang lebih kecil dari piksel 9 km (kota kecil di pesisir, gugusan pulau kecil) bisa tidak
// mendapat nilai karena tidak ada piksel daratan yang mengenainya (contoh: Kota Sibolga, Kota Pekalongan,
// Kepulauan Seribu). Untuk wilayah seperti itu, nilai diambil dari area di sekitarnya: batas wilayah
// diperlebar 10 km, dan jika masih kosong 30 km. Kolom wilayah_kecil berisi radius yang dipakai (km), 0 = normal.
var RADIUS_KECIL = [10000, 30000];
var WAJIB = ['soil_moisture', 'curah_hujan_bulanan', 'suhu_celsius', 'dew_point_celsius', 'ndvi',
             'elevation', 'slope', 'solar_radiation', 'wind_speed', 'clay_content', 'soil_temperature'];

function sampleMonth(year, month) {
  var composite = buildMonthlyComposite(year, month);
  var y = composite.get('tahun');
  var m = composite.get('bulan');
  var d = composite.get('tanggal');
  var rata = function (fc) {
    return composite.reduceRegions({collection: fc, reducer: ee.Reducer.mean(), scale: 9000, tileScale: 16});
  };
  var ada = ee.Filter.notNull(WAJIB);

  var r = rata(adminBoundaries);
  var lengkap = r.filter(ada).map(function (f) { return f.set('wilayah_kecil', 0); });
  var kurang = r.filter(ada.not()).aggregate_array('ADM2_CODE');
  RADIUS_KECIL.forEach(function (rad) {
    var lebar = adminBoundaries.filter(ee.Filter.inList('ADM2_CODE', kurang))
      .map(function (f) { return f.buffer(rad, 100); });
    var rr = rata(lebar);
    lengkap = lengkap.merge(rr.filter(ada).map(function (f) { return f.set('wilayah_kecil', rad / 1000); }));
    kurang = rr.filter(ada.not()).aggregate_array('ADM2_CODE');
  });

  return lengkap.map(function(f) {
    var t = ee.Number(f.get('suhu_celsius'));
    var td = ee.Number(f.get('dew_point_celsius'));
    return f.setGeometry(null).set({
      'relative_humidity': es(td).divide(es(t)).multiply(100),
      'tahun': y, 'bulan': m, 'tanggal': d
    });
  });
}


// 4. CEK KELENGKAPAN DATA SEBELUM EKSPOR
// Jumlah citra minimum agar satu bulan dianggap lengkap:
//   SMAP L4 (3 jam-an): >= 8 per hari; CHIRPS & ERA5-Land harian: 1 per hari;
//   MODIS NDVI 16 hari: >= 1; MODIS LST 8 hari: >= 3.
function cekKelengkapan(year, month) {
  var a = ee.Date.fromYMD(year, month, 1);
  var b = a.advance(1, 'month');
  var hari = b.difference(a, 'day');
  var n = function(id) { return ee.ImageCollection(id).filterDate(a, b).size(); };
  return ee.Dictionary({
    'SMAP': [n('NASA/SMAP/SPL4SMGP/008'), hari.multiply(8)],
    'CHIRPS': [n('UCSB-CHG/CHIRPS/DAILY'), hari],
    'ERA5-Land': [n('ECMWF/ERA5_LAND/DAILY_AGGR'), hari],
    'MODIS NDVI': [n('MODIS/061/MOD13A2'), 1],
    'MODIS LST': [n('MODIS/061/MOD11A2'), 3]
  });
}

var NAMA_BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
                  'Agustus', 'September', 'Oktober', 'November', 'Desember'];
var semuaLengkap = true;

BULAN_BARU.forEach(function(ym) {
  var hasil = cekKelengkapan(ym[0], ym[1]).getInfo();
  var baris = [];
  var lengkap = true;
  Object.keys(hasil).forEach(function(sumber) {
    var ada = hasil[sumber][0], perlu = hasil[sumber][1];
    if (ada < perlu) { lengkap = false; }
    baris.push(sumber + ' ' + ada + '/' + perlu);
  });
  if (!lengkap) { semuaLengkap = false; }
  print((lengkap ? '✅ ' : '⚠️ BELUM LENGKAP: ') + NAMA_BULAN[ym[1] - 1] + ' ' + ym[0] +
        ' (' + baris.join(', ') + ')');
});


// 5. EKSPOR SATU CSV UNTUK SEMUA BULAN DI DAFTAR
var data = ee.FeatureCollection(BULAN_BARU.map(function(ym) {
  return sampleMonth(ym[0], ym[1]);
})).flatten();

var awal = BULAN_BARU[0], akhir = BULAN_BARU[BULAN_BARU.length - 1];
var nama = 'SoilMoisture_' + awal[0] + '_' + ('0' + awal[1]).slice(-2) +
           (BULAN_BARU.length > 1 ? '_sd_' + akhir[0] + '_' + ('0' + akhir[1]).slice(-2) : '');

Export.table.toDrive({
  collection: data,
  description: nama,
  folder: FOLDER_DRIVE,
  fileFormat: 'CSV',
  selectors: ['ADM2_CODE', 'ADM2_NAME', 'ADM1_NAME', 'soil_moisture', 'curah_hujan_bulanan', 'suhu_celsius',
              'dew_point_celsius', 'ndvi', 'lst_celsius', 'elevation', 'slope', 'solar_radiation',
              'wind_speed', 'clay_content', 'soil_temperature', 'relative_humidity',
              'wilayah_kecil', 'tahun', 'bulan', 'tanggal']
});

print(semuaLengkap
  ? 'Semua bulan lengkap. Buka tab Tasks, klik RUN pada "' + nama + '".'
  : 'Ada bulan yang datanya belum lengkap. Sebaiknya hapus bulan itu dari BULAN_BARU ' +
    'dan ekspor lagi beberapa minggu kemudian.');
print('Baris yang diharapkan: ' + (N_WILAYAH * BULAN_BARU.length) + ' (' + N_WILAYAH +
      ' kabupaten/kota x ' + BULAN_BARU.length + ' bulan).');
