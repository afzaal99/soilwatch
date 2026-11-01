/* SoilWatch ID - Mode Simulasi: validasi input dan perhitungan kelembapan relatif */
(function () {
  const form = document.getElementById('form-sim');
  const input = [...form.querySelectorAll('.inp input')];
  const rh = document.getElementById('relative_humidity');
  const T = document.getElementById('suhu_celsius');
  const Td = document.getElementById('dew_point_celsius');
  // terima format Indonesia (1.234,5) maupun titik desimal (1234.5)
  const baca = el => {
    let s = el.value.trim();
    if (!s) return null;
    if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
    return isFinite(+s) ? +s : NaN;
  };
  const tulis = (v, d) => v.toFixed(d).replace('.', ',');
  const es = x => 6.112 * Math.exp(17.67 * x / (x + 243.5));   // Persamaan (2.5)

  function hitungRH() {
    const t = baca(T), td = baca(Td);
    rh.value = (t != null && td != null && !isNaN(t) && !isNaN(td)) ? tulis(100 * es(td) / es(t), 1) : '';
  }

  function periksa(tampilkan) {
    hitungRH();
    let terisi = 0;
    const salah = [], luar = [];
    input.forEach(el => {
      const f = el.closest('.field');
      const msg = f.querySelector('.msg');
      const v = baca(el);
      let pesan = '';
      f.classList.remove('err', 'out');
      if (v != null) {
        if (isNaN(v)) pesan = 'Masukkan angka yang valid';
        else if (v < +el.dataset.min || v > +el.dataset.max)
          pesan = `${el.dataset.label} harus di antara ${tulis(+el.dataset.min, 0)} dan ${tulis(+el.dataset.max, 0)}`;
        else if (el === Td && baca(T) != null && v > baca(T))
          pesan = 'Titik embun tidak boleh lebih tinggi dari suhu udara';
        else {
          terisi++;
          if (v < +el.dataset.dmin || v > +el.dataset.dmax) { luar.push(el.dataset.label); f.classList.add('out'); }
        }
      }
      if (pesan) salah.push(el.dataset.label);
      if (pesan && (tampilkan || el.dataset.disentuh)) { f.classList.add('err'); msg.textContent = pesan; }
      else msg.textContent = '';
    });
    document.getElementById('terisi').textContent = terisi;
    document.getElementById('prog').style.width = (terisi / input.length * 100) + '%';
    const kg = document.getElementById('kotak-galat');
    kg.hidden = !salah.length;
    kg.innerHTML = salah.length ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l10 18H2L12 3z"/><path d="M12 10v4M12 17h.01"/></svg><span>${salah.length} nilai belum valid. Periksa kembali kolom <b>${salah.join(', ')}</b>.</span>` : '';
    const kl = document.getElementById('kotak-luar');
    kl.hidden = !luar.length || salah.length > 0;
    kl.innerHTML = luar.length ? `<span><b>${luar.join(', ')}</b> di luar rentang data latih. Hasil estimasi mungkin kurang andal.</span>` : '';
    document.getElementById('hitung').disabled = !(terisi === input.length && !salah.length);
  }

  input.forEach(el => {
    el.addEventListener('input', () => periksa(false));
    el.addEventListener('blur', () => { el.dataset.disentuh = 1; periksa(false); });
  });
  document.getElementById('kosongkan').addEventListener('click', () => {
    input.forEach(el => { el.value = ''; delete el.dataset.disentuh; });
    periksa(false);
    input[0].focus();
  });
  document.getElementById('contoh').addEventListener('click', () => {
    input.forEach(el => { if (el !== rh) el.value = el.placeholder; });
    periksa(false);
  });
  form.addEventListener('submit', e => {
    // kirim dengan titik desimal agar dibaca server
    input.forEach(el => { const v = baca(el); if (v != null && !isNaN(v)) el.value = String(v); });
  });
  periksa(document.querySelector('.field.err') != null);
})();
