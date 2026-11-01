/* Tooltip nilai bulanan pada grafik tren (Beranda dan halaman hasil).
   Desktop: arahkan kursor ke titik. HP: ketuk titik. */
(function () {
  document.querySelectorAll('.hit').forEach(function (g) {
    var kartu = g.closest('.trend, .rk-nas');
    var tip = kartu && kartu.querySelector('.tip-grafik');
    if (!tip) return;
    function tampil(c) {
      g.querySelectorAll('circle.on').forEach(function (x) { x.classList.remove('on'); });
      c.classList.add('on');
      var r = c.getBoundingClientRect(), k = kartu.getBoundingClientRect();
      tip.textContent = c.dataset.tip;
      tip.style.left = Math.min(Math.max(r.left + r.width / 2 - k.left, 70), k.width - 70) + 'px';
      tip.style.top = (r.top - k.top) + 'px';
      tip.hidden = false;
    }
    function sembunyi() { tip.hidden = true; g.querySelectorAll('circle.on').forEach(function (x) { x.classList.remove('on'); }); }
    g.querySelectorAll('circle').forEach(function (c) {
      c.querySelector('title') && c.querySelector('title').remove();   // pakai tooltip sendiri
      c.addEventListener('mouseenter', function () { tampil(c); });
      c.addEventListener('mouseleave', sembunyi);
      c.addEventListener('click', function (e) { e.stopPropagation(); tampil(c); });
    });
    document.addEventListener('click', sembunyi);
  });
})();

/* Di HP grafik lebih lebar dari layar: geser otomatis supaya bulan terpilih ada di tengah. */
(function () {
  function tengahkan() {
    document.querySelectorAll('.trend-gulir').forEach(function (w) {
      if (w.scrollWidth <= w.clientWidth) return;
      var t = w.querySelector('circle.pt');
      if (!t) return;
      var r = t.getBoundingClientRect(), k = w.getBoundingClientRect();
      w.scrollLeft += (r.left + r.width / 2) - (k.left + k.width / 2);
    });
  }
  if (document.readyState === 'complete') tengahkan(); else window.addEventListener('load', tengahkan);
})();
