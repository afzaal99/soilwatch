/* SoilWatch ID - Mode Otomatis: peta interaktif, pencarian, dan panel wilayah */
(function () {
  const akar = document.querySelector('.oto');
  const svg = document.getElementById('peta');
  const lapisan = document.getElementById('lapisan');
  const kotak = document.getElementById('mapbox');
  const tip = document.getElementById('tip');
  const selBulan = document.getElementById('bulan');
  const selTahun = document.getElementById('tahun');
  const cari = document.getElementById('cari');
  const saran = document.getElementById('saran');
  const RAMP = ['#8c510a', '#bf812d', '#dfc27d', '#f1e5c4', '#c7eae5', '#80cdc1', '#35978f', '#01665e'];
  const VMIN = 0.10, VMAX = 0.50, AMBANG = 20;
  const NS = 'http://www.w3.org/2000/svg';

  let D = null, iPer = 0, pilih = null;
  const pathById = {};
  lapisan.querySelectorAll('path[data-id]').forEach(p => { pathById[p.dataset.id] = p; });

  const angka = (v, d = 2) => v.toFixed(d).replace('.', ',');
  const warna = v => v == null ? '#E2E8F0'
    : RAMP[Math.floor(Math.min(Math.max((v - VMIN) / (VMAX - VMIN), 0), 0.999) * RAMP.length)];

  fetch(akar.dataset.sumber).then(r => r.json()).then(data => {
    D = data;
    const awal = D.periode.indexOf(akar.dataset.pilihPeriode);
    setPeriode(awal >= 0 ? awal : D.periode.length - 1);
    buatPenanda();
    if (akar.dataset.pilihId !== '') pilihWilayah(+akar.dataset.pilihId);
  });

  /* ---------- periode ---------- */
  function setPeriode(i) {
    iPer = i;
    const [t, b] = D.periode[i].split('-');
    selTahun.value = t;
    selBulan.value = b;
    aturBulanTersedia();
    for (const id in pathById) pathById[id].setAttribute('fill', warna(D.sm[id][i]));
    isiPeringkat();
    if (pilih != null) isiPanel();
  }

  /* ---------- 5 wilayah terkering dan terbasah pada bulan terpilih (kartu di bawah peta) ---------- */
  function isiPeringkat() {
    const urut = D.sm.map((s, id) => [id, s[iPer]]).filter(([, v]) => v != null).sort((a, b) => a[1] - b[1]);
    if (!urut.length) return;
    document.getElementById('pk-oto').hidden = false;
    document.getElementById('pk-oto-per').textContent = D.periode_label[iPer];
    const isi = (ol, daftar) => {
      ol.innerHTML = '';
      daftar.forEach(([id, v], k) => {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.type = 'button';
        const gambut = D.penanda[id][0] >= AMBANG ? ' · gambut' : '';
        b.innerHTML = `<span class="pk-no">${k + 1}</span><span class="pk-nama"><b></b><small></small></span>`
          + `<span class="pk-nilai"><i style="background:${warna(v)}"></i>${angka(v)}</span>`;
        b.querySelector('b').textContent = D.wilayah[id][0];
        b.querySelector('small').textContent = D.wilayah[id][1] + gambut;
        b.addEventListener('click', () => {
          ambil(id);
          kotak.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        li.appendChild(b);
        ol.appendChild(li);
      });
    };
    isi(document.getElementById('pk-kering'), urut.slice(0, 5));
    isi(document.getElementById('pk-basah'), urut.slice(-5).reverse());
  }
  function aturBulanTersedia() {
    [...selBulan.options].forEach(o => { o.disabled = !D.periode.includes(selTahun.value + '-' + o.value); });
  }
  function ubahPeriode() {
    aturBulanTersedia();
    let p = selTahun.value + '-' + selBulan.value;
    if (!D.periode.includes(p)) p = D.periode.filter(x => x.startsWith(selTahun.value)).pop();
    setPeriode(D.periode.indexOf(p));
  }
  selBulan.addEventListener('change', ubahPeriode);
  selTahun.addEventListener('change', ubahPeriode);

  /* ---------- penanda gambut dan badan air ----------
     Jika peta memuat bentuk asli (hasil GEE: #air-asli, #gambut-asli), itu yang ditampilkan.
     Jika belum, wilayah dengan gambut >= 20% diarsir dan wilayah dengan badan air >= 20% diberi ikon. */
  const airAsli = svg.querySelector('#air-asli');
  const gambutAsli = svg.querySelector('#gambut-asli');
  const gArsir = gambutAsli || document.createElementNS(NS, 'g');
  const gAir = airAsli || document.createElementNS(NS, 'g');
  // arsiran gambut digambar DI BAWAH danau, supaya danau tetap terlihat utuh berwarna biru
  if (!gambutAsli) { gArsir.setAttribute('class', 'lap-arsir'); svg.insertBefore(gArsir, airAsli || null); }
  if (!airAsli) { gAir.setAttribute('class', 'lap-air'); svg.appendChild(gAir); }
  function buatPenanda() {
    for (const id in pathById) {
      const [g, a] = D.penanda[id];
      if (!gambutAsli && g >= AMBANG) {
        const c = pathById[id].cloneNode();
        c.removeAttribute('data-id');
        c.setAttribute('fill', 'url(#arsir)');
        gArsir.appendChild(c);
      }
      if (!airAsli && a >= AMBANG) {
        const bb = pathById[id].getBBox();
        const u = document.createElementNS(NS, 'path');
        u.setAttribute('d', 'M0,-9C0,-9 -5,-2 -5,1.5A5,5 0 0 0 5,1.5C5,-2 0,-9 0,-9Z');
        u.setAttribute('transform', `translate(${bb.x + bb.width / 2},${bb.y + bb.height / 2})`);
        u.setAttribute('class', 'ikon-air');
        gAir.appendChild(u);
      }
    }
  }
  document.getElementById('t-gambut').addEventListener('change', e => { gArsir.style.display = e.target.checked ? '' : 'none'; });
  document.getElementById('t-air').addEventListener('change', e => { gAir.style.display = e.target.checked ? '' : 'none'; });

  /* ---------- tooltip & klik ---------- */
  function tampilTip(e, html) {
    tip.innerHTML = html;
    const r = kotak.getBoundingClientRect();
    tip.hidden = false;
    let x = e.clientX - r.left + 14, y = e.clientY - r.top + 14;
    if (x + tip.offsetWidth > r.width - 8) x = e.clientX - r.left - tip.offsetWidth - 14;
    if (y + tip.offsetHeight > r.height - 8) y = e.clientY - r.top - tip.offsetHeight - 14;
    x = Math.max(8, Math.min(x, r.width - tip.offsetWidth - 8));   // tetap di dalam kotak peta
    y = Math.max(8, y);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  svg.addEventListener('mousemove', e => {
    if (!D) return;
    const danau = e.target.closest('#air-asli path');
    if (danau) {
      tampilTip(e, `<b>${danau.dataset.nama}</b><span>Badan air · ±${danau.dataset.luas} km²</span>`);
      return;
    }
    const p = e.target.closest('path[data-id]');
    if (!p) { tip.hidden = true; return; }
    const id = +p.dataset.id, v = D.sm[id][iPer];
    tampilTip(e, `<b>${D.wilayah[id][0]}</b><span>${D.wilayah[id][1]} · ${v == null ? 'tidak ada data' : angka(v) + ' m³/m³'}</span>`);
  });
  svg.addEventListener('mouseleave', () => { tip.hidden = true; });
  svg.addEventListener('click', e => {
    if (geser.pindah) return;
    let p = e.target.closest('path[data-id]');
    if (!p && e.target.closest('#air-asli path')) {   // klik di danau: pilih wilayah di bawahnya
      p = document.elementsFromPoint(e.clientX, e.clientY).find(el => el.matches && el.matches('path[data-id]'));
    }
    if (p) pilihWilayah(+p.dataset.id);
  });
  for (const t of [svg.querySelector('#air-asli'), svg.querySelector('#gambut-asli')]) {
    if (t) t.querySelectorAll('title').forEach(x => x.remove());   // tooltip sendiri sudah ada
  }

  /* ---------- panel wilayah ---------- */
  function pilihWilayah(id) {
    if (!D || !D.wilayah[id]) return;
    if (pilih != null && pathById[pilih]) pathById[pilih].classList.remove('pilih');
    pilih = id;
    const p = pathById[id];
    if (p) { p.classList.add('pilih'); lapisan.appendChild(p); }
    isiPanel();
  }
  const WARNA_PH = { 'sangat masam': '#B91C1C', 'masam': '#EA580C', 'agak masam': '#CA8A04',
                     'netral': '#15803D', 'agak alkalis': '#0E7490', 'alkalis': '#1D4ED8' };
  function isiPanel() {
    const [nama, prov, danau] = D.wilayah[pilih];
    const [g, a, t] = D.penanda[pilih];
    const v = D.sm[pilih][iPer];
    document.getElementById('kosong').hidden = true;
    document.getElementById('isi').hidden = false;
    document.getElementById('w-nama').textContent = nama;
    document.getElementById('w-prov').textContent = prov;
    document.getElementById('w-per').textContent = D.periode_label[iPer];
    const st = document.getElementById('w-status');
    st.textContent = v == null ? 'Data tidak tersedia' : 'Data tersedia';
    st.className = 'chip ' + (v == null ? 'bad' : 'ok');
    [['gambut', g], ['air', a], ['tani', t]].forEach(([k, n]) => {
      document.getElementById('v-' + k).textContent = n + ' %';
      document.getElementById('b-' + k).style.width = Math.max(n, 1) + '%';
    });
    const rPh = document.getElementById('r-ph');
    const ph = D.ph && D.ph[pilih];
    rPh.hidden = !ph;
    if (ph) {
      document.getElementById('v-ph').textContent = `${String(ph[0]).replace('.', ',')} · ${ph[1]}`;
      document.getElementById('s-ph').style.background = WARNA_PH[ph[1]] || '#94A3B8';
    }
    const tanda = [g >= AMBANG && 'gambut', a >= AMBANG && 'badan air'].filter(Boolean);
    let cat = tanda.length
      ? `Wilayah ini <b>ditandai</b> sebagai wilayah ${tanda.join(' dan ')}. Hasil estimasi perlu ditafsirkan dengan hati-hati.`
      : 'Wilayah ini <b>tidak</b> ditandai sebagai wilayah gambut atau badan air.';
    if (danau) {
      cat += a >= AMBANG
        ? `<br>Badan air utama: <b>${danau}</b>.`
        : `<br>Sebagian <b>${danau}</b> berada di wilayah ini, tetapi luasnya di bawah 20% wilayah.`;
    }
    if (!pathById[pilih]) cat += '<br><span class="muted">Batas wilayah ini belum tergambar terpisah pada peta pratinjau.</span>';
    document.getElementById('w-catatan').innerHTML = cat;
    const btn = document.getElementById('ke-hasil');
    btn.href = `${akar.dataset.hasil}?id=${pilih}&periode=${D.periode[iPer]}`;
    btn.classList.toggle('off', v == null);
    history.replaceState(null, '', `?id=${pilih}&periode=${D.periode[iPer]}`);
  }

  /* ---------- pencarian ---------- */
  const normal = s => s.toLowerCase().replace(/^(kab\.|kota)\s*/, '').replace(/[^a-z]/g, '');
  let aktif = -1;
  cari.addEventListener('input', () => {
    const q = normal(cari.value);
    saran.innerHTML = '';
    aktif = -1;
    if (!q || !D) { tutupSaran(); return; }
    const hasil = D.wilayah.map((w, i) => [i, w]).filter(([, w]) => normal(w[0]).includes(q)).slice(0, 8);
    hasil.forEach(([i, w]) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'option');
      li.dataset.id = i;
      li.innerHTML = `${w[0]}<span>${w[1]}</span>`;
      li.addEventListener('mousedown', e => { e.preventDefault(); ambil(i); });
      saran.appendChild(li);
    });
    if (!hasil.length) saran.innerHTML = '<li class="nihil">Tidak ditemukan</li>';
    saran.hidden = false;
    cari.setAttribute('aria-expanded', 'true');
  });
  cari.addEventListener('keydown', e => {
    const item = [...saran.querySelectorAll('li[data-id]')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      aktif = (aktif + (e.key === 'ArrowDown' ? 1 : -1) + item.length) % item.length;
      item.forEach((li, k) => li.classList.toggle('on', k === aktif));
    } else if (e.key === 'Enter' && item.length) {
      e.preventDefault();
      ambil(+item[Math.max(aktif, 0)].dataset.id);
    } else if (e.key === 'Escape') tutupSaran();
  });
  cari.addEventListener('blur', tutupSaran);
  function tutupSaran() { saran.hidden = true; cari.setAttribute('aria-expanded', 'false'); }
  function ambil(id) {
    cari.value = D.wilayah[id][0];
    tutupSaran();
    pilihWilayah(id);
    if (pathById[id]) fokusKe(pathById[id].getBBox());
  }

  /* ---------- zoom & geser ---------- */
  const vb0 = svg.viewBox.baseVal;
  const awal = [vb0.x, vb0.y, vb0.width, vb0.height];
  let vb = awal.slice();
  const pasang = () => {
    svg.setAttribute('viewBox', vb.join(' '));
    svg.style.setProperty('--sw', (vb[2] / awal[2]).toFixed(3));
  };
  function zoom(f, cx, cy) {
    const w = Math.min(Math.max(vb[2] * f, awal[2] / 60), awal[2]);   // perbesaran maksimum 60x
    const k = w / vb[2];
    if (cx == null) { cx = vb[0] + vb[2] / 2; cy = vb[1] + vb[3] / 2; }
    vb = [cx - (cx - vb[0]) * k, cy - (cy - vb[1]) * k, w, vb[3] * k];
    batasi();
    pasang();
  }
  function batasi() {
    vb[0] = Math.min(Math.max(vb[0], awal[0]), awal[0] + awal[2] - vb[2]);
    vb[1] = Math.min(Math.max(vb[1], awal[1]), awal[1] + awal[3] - vb[3]);
  }
  function fokusKe(bb) {
    const w = Math.min(Math.max(bb.width * 3, awal[2] / 30), awal[2]);
    const h = w * awal[3] / awal[2];
    vb = [bb.x + bb.width / 2 - w / 2, bb.y + bb.height / 2 - h / 2, w, h];
    batasi();
    pasang();
  }
  document.getElementById('zin').addEventListener('click', () => zoom(0.7));
  document.getElementById('zout').addEventListener('click', () => zoom(1 / 0.7));
  document.getElementById('zreset').addEventListener('click', () => { vb = awal.slice(); pasang(); });

  /* ---------- layar penuh (terutama untuk HP) ---------- */
  const tPenuh = document.getElementById('zpenuh');
  function aturPenuh(on) {
    kotak.classList.toggle('penuh', on);
    document.body.classList.toggle('peta-penuh', on);
    tPenuh.setAttribute('aria-label', on ? 'Keluar dari layar penuh' : 'Layar penuh');
    tPenuh.title = tPenuh.getAttribute('aria-label');
    tip.hidden = true;
  }
  tPenuh.addEventListener('click', () => aturPenuh(!kotak.classList.contains('penuh')));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && kotak.classList.contains('penuh')) aturPenuh(false); });
  const keSvg = e => {
    const r = svg.getBoundingClientRect();
    return [vb[0] + (e.clientX - r.left) / r.width * vb[2], vb[1] + (e.clientY - r.top) / r.height * vb[3]];
  };
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const [x, y] = keSvg(e);
    zoom(e.deltaY < 0 ? 0.85 : 1 / 0.85, x, y);
  }, { passive: false });
  const geser = { aktif: false, pindah: false };
  const jari = new Map();                                  // pointer aktif (layar sentuh: bisa dua jari)
  let cubit = null;                                        // {jarak} saat dua jari menyentuh peta
  const jarakJari = () => { const [a, b] = [...jari.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  const tengahJari = () => { const [a, b] = [...jari.values()]; return { clientX: (a.x + b.x) / 2, clientY: (a.y + b.y) / 2 }; };
  svg.addEventListener('pointerdown', e => {
    jari.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (jari.size === 2) {                                 // mulai cubit: hentikan geser satu jari
      cubit = { jarak: jarakJari() };
      geser.aktif = false; geser.pindah = true;
      return;
    }
    geser.aktif = true; geser.pindah = false; geser.x = e.clientX; geser.y = e.clientY; geser.vb = vb.slice();
  });
  window.addEventListener('pointermove', e => {
    if (jari.has(e.pointerId)) jari.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (cubit && jari.size === 2) {
      const d = jarakJari();
      if (d > 0 && cubit.jarak > 0) {
        const [x, y] = keSvg(tengahJari());
        zoom(cubit.jarak / d, x, y);                       // jari menjauh = perbesar, mendekat = perkecil
        cubit.jarak = d;
        tip.hidden = true;
      }
      return;
    }
    if (!geser.aktif) return;
    const dx = e.clientX - geser.x, dy = e.clientY - geser.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) geser.pindah = true;
    if (!geser.pindah) return;
    const r = svg.getBoundingClientRect();
    vb[0] = geser.vb[0] - dx / r.width * vb[2];
    vb[1] = geser.vb[1] - dy / r.height * vb[3];
    batasi();
    pasang();
    tip.hidden = true;
  });
  const lepas = e => {
    jari.delete(e.pointerId);
    if (jari.size < 2) cubit = null;
    geser.aktif = false;
    setTimeout(() => { if (!jari.size) geser.pindah = false; }, 0);
  };
  window.addEventListener('pointerup', lepas);
  window.addEventListener('pointercancel', lepas);
})();
