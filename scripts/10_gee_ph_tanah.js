// =====================================================================================
// 10_gee_ph_tanah.js - pH tanah per kabupaten/kota (fitur tambahan, masukan UAT Kementan)
// -------------------------------------------------------------------------------------
// Sumber : OpenLandMap Soil pH in H2O (Hengl, 2018), resolusi 250 m, nilai = pH x 10.
//          Band b0 (0 cm), b10 (10 cm), b30 (30 cm): lapisan olah tanah 0-30 cm.
// Batas  : FAO GAUL 2025 level 2, sama dengan script 09 (514 kabupaten/kota).
// Keluaran (Google Drive, folder soilwatch_gee): ph_tanah_kabkota.csv dengan kolom
//          ADM2_CODE, ADM2_NAME, ADM1_NAME, ph_0cm, ph_10cm, ph_30cm, ph_p10, ph_p90
//   ph_0cm..ph_30cm : rata-rata pH di dalam wilayah pada kedalaman tersebut
//   ph_p10, ph_p90  : persentil 10 dan 90 pH lapisan 0-30 cm (sebaran pH di dalam wilayah)
// Data pH ini statis (satu nilai per wilayah), karena pH tanah berubah sangat lambat.
// Cara pakai: tempel di Code Editor GEE -> Run -> tab Tasks -> RUN -> unduh CSV dari Drive
//             -> simpan sebagai app/data/ph_tanah.csv
// =====================================================================================

var FOLDER_DRIVE = 'soilwatch_gee';

var kabkota = ee.FeatureCollection('FAO/GAUL/2025/level2')
  .filter(ee.Filter.eq('GAUL0_NAME', 'Indonesia'))
  .select(['GAUL1_NAME', 'GAUL2_NAME', 'GAUL2_CODE'], ['ADM1_NAME', 'ADM2_NAME', 'ADM2_CODE']);
print('Jumlah kabupaten/kota (harus 514):', kabkota.size());

var ph = ee.Image('OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02').divide(10);   // pH x 10 -> pH
var lapisan = ph.select(['b0', 'b10', 'b30'], ['ph_0cm', 'ph_10cm', 'ph_30cm']);
var olah = ph.select(['b0', 'b10', 'b30']).reduce(ee.Reducer.mean()).rename('ph_olah');   // rata-rata 0-30 cm

// rata-rata per kedalaman
var rata = lapisan.reduceRegions({
  collection: kabkota, reducer: ee.Reducer.mean(), scale: 250, tileScale: 16
});
// sebaran pH lapisan olah di dalam wilayah (persentil 10 dan 90)
var sebar = olah.reduceRegions({
  collection: kabkota, reducer: ee.Reducer.percentile([10, 90]), scale: 250, tileScale: 16
});

var gabung = ee.Join.inner().apply(rata, sebar, ee.Filter.equals({ leftField: 'ADM2_CODE', rightField: 'ADM2_CODE' }))
  .map(function (f) {
    var a = ee.Feature(f.get('primary')), b = ee.Feature(f.get('secondary'));
    return ee.Feature(null, {
      ADM2_CODE: a.get('ADM2_CODE'), ADM2_NAME: a.get('ADM2_NAME'), ADM1_NAME: a.get('ADM1_NAME'),
      ph_0cm: a.get('ph_0cm'), ph_10cm: a.get('ph_10cm'), ph_30cm: a.get('ph_30cm'),
      ph_p10: b.get('p10'), ph_p90: b.get('p90')
    });
  });

print('Contoh hasil (5 wilayah):', gabung.limit(5));
Map.addLayer(olah.clip(kabkota.geometry().bounds()), { min: 4, max: 8, palette: ['#B91C1C', '#F59E0B', '#FDE68A', '#86EFAC', '#2563EB'] }, 'pH lapisan olah 0-30 cm');
Map.setCenter(118, -2, 5);

Export.table.toDrive({
  collection: gabung, description: 'ph_tanah_kabkota', folder: FOLDER_DRIVE, fileNamePrefix: 'ph_tanah_kabkota',
  fileFormat: 'CSV', selectors: ['ADM2_CODE', 'ADM2_NAME', 'ADM1_NAME', 'ph_0cm', 'ph_10cm', 'ph_30cm', 'ph_p10', 'ph_p90']
});
