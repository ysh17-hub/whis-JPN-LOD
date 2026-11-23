// 地理院タイルの背景地図と、昔の航空写真を重ねて比べる仕組み（地図ページと施設ページで共通）
// 出典：国土地理院（地理院タイル一覧 https://maps.gsi.go.jp/development/ichiran.html）
// ズームの範囲は 2026-11-23 に各タイルの配信を確かめて決めた。
(function () {
  const ICHIRAN = 'https://maps.gsi.go.jp/development/ichiran.html';
  const SRC = `<a href="${ICHIRAN}" target="_blank" rel="noopener">地理院タイル</a>`;
  const tile = (id, ext, o) => L.tileLayer(`https://cyberjapandata.gsi.go.jp/xyz/${id}/{z}/{x}/{y}.${ext}`,
    Object.assign({ attribution: SRC, maxZoom: 18 }, o));

  // 背景地図（どれか1つ）
  function baseLayers() {
    return {
      '淡色地図': tile('pale', 'png', { maxNativeZoom: 18 }),
      '標準地図': tile('std', 'png', { maxNativeZoom: 18 }),
      '航空写真（最新）': tile('seamlessphoto', 'jpg', {
        maxNativeZoom: 18,
        attribution: SRC + '（全国最新写真。一部に Landsat-8 画像・GRUS画像（© Axelspace）を使用）'
      }),
      '色別標高図＋陰影': L.layerGroup([
        tile('relief', 'png', { minZoom: 5, maxNativeZoom: 15,
          attribution: SRC + '（色別標高図：海域部は海上保安庁海洋情報部の資料を使用して作成）' }),
        tile('hillshademap', 'png', { maxNativeZoom: 16, opacity: 0.35 })
      ])
    };
  }

  // 重ねて比べる昔の航空写真
  const OLD = [
    { key: 'p1974', label: '1974〜1978年', id: 'gazo1', ext: 'jpg', minZoom: 10, maxNativeZoom: 17 },
    { key: 'p1961', label: '1961〜1969年', id: 'ort_old10', ext: 'png', minZoom: 2, maxNativeZoom: 17 },
    { key: 'p1945', label: '1945〜1950年', id: 'ort_USA10', ext: 'png', minZoom: 2, maxNativeZoom: 17 }
  ];

  // 地図に背景の切り替えと「昔の写真を重ねる」操作をつける
  // opts.available: その地点で写真があることを確かめた年（['p1974','p1961'] など）。省略するとすべて
  // opts.base: 最初の背景の名前
  function setup(map, opts) {
    opts = opts || {};
    if (!map.getPane('oldphoto')) {
      map.createPane('oldphoto');
      map.getPane('oldphoto').style.zIndex = 250;   // 背景（200）より上、印（400）より下
    }
    const bases = baseLayers();
    const first = bases[opts.base] ? opts.base : '淡色地図';
    bases[first].addTo(map);
    L.control.layers(bases, null, { position: 'topright', collapsed: !!opts.collapsed }).addTo(map);

    const list = OLD.filter(o => !opts.available || opts.available.includes(o.key));
    let current = null;
    const ctl = L.control({ position: 'topright' });
    ctl.onAdd = () => {
      const d = L.DomUtil.create('div', 'leaflet-bar whis-compare');
      d.style.cssText = 'background:#fff;padding:6px 8px;font-size:12px;line-height:1.6;max-width:210px';
      d.innerHTML = '<b>昔の航空写真を重ねる</b><br>' +
        '<select style="font-size:12px;max-width:190px"><option value="">重ねない</option>' +
        list.map(o => `<option value="${o.key}">${o.label}</option>`).join('') + '</select><br>' +
        '<label>濃さ <input type="range" min="0" max="100" value="100" style="width:110px;vertical-align:middle"></label>' +
        '<div class="whis-hint" style="color:#b45309;display:none"></div>';
      L.DomEvent.disableClickPropagation(d);
      L.DomEvent.disableScrollPropagation(d);
      const sel = d.querySelector('select'), rng = d.querySelector('input'), hint = d.querySelector('.whis-hint');
      const showHint = () => {
        const o = OLD.find(x => x.key === sel.value);
        const need = o && map.getZoom() < 10;
        hint.style.display = need ? '' : 'none';
        hint.textContent = need ? 'もっと拡大すると表示されます（ズーム10以上）' : '';
      };
      sel.onchange = () => {
        if (current) { map.removeLayer(current); current = null; }
        const o = OLD.find(x => x.key === sel.value);
        if (o) {
          current = tile(o.id, o.ext, { pane: 'oldphoto', minZoom: o.minZoom, maxNativeZoom: o.maxNativeZoom,
            opacity: rng.value / 100, attribution: SRC + `（${o.label}の空中写真）` }).addTo(map);
        }
        showHint();
      };
      rng.oninput = () => { if (current) current.setOpacity(rng.value / 100); };
      map.on('zoomend', showHint);
      if (!list.length) d.innerHTML = '<b>昔の航空写真</b><br>この地点では見つかりませんでした';
      return d;
    };
    ctl.addTo(map);
    return {
      bases,
      showPhoto(latlng, zoom) {   // 最新の航空写真に切り替えて、その場所へ寄る
        Object.values(bases).forEach(l => { if (map.hasLayer(l)) map.removeLayer(l); });
        bases['航空写真（最新）'].addTo(map);
        map.setView(latlng, zoom || 17);
      }
    };
  }

  // 地理院地図（国土地理院のサイト）で同じ場所を航空写真で開くURL
  function gsiMapsUrl(lat, lon, zoom) {
    return `https://maps.gsi.go.jp/#${zoom || 17}/${(+lat).toFixed(6)}/${(+lon).toFixed(6)}/&base=std&ls=std%7Cseamlessphoto&disp=01`;
  }

  window.WHIS_GSI = { setup, gsiMapsUrl, OLD };
})();
