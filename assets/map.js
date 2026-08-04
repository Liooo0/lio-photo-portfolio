(function () {
  'use strict';

  // === 常量 ===
  const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const TILE_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  // 无坐标照片时的兜底视角（用户在深圳）
  const DEFAULT_CENTER = [22.5431, 114.0579];
  const DEFAULT_ZOOM = 11;
  const SINGLE_ZOOM = 14;

  // === DOM refs ===
  const mapEl = document.getElementById('map');
  const statsEl = document.getElementById('mapStats');
  const emptyEl = document.getElementById('mapEmpty');
  const themeBtn = document.getElementById('mapThemeBtn');
  const lightbox = document.getElementById('lightbox');
  const lbImage = lightbox.querySelector('img');
  const lbCounter = lightbox.querySelector('.lightbox-counter');
  const lbInfo = document.getElementById('lightboxInfo');

  let geoPhotos = []; // [{img, geo}]，顺序与 gallery.json 一致
  let lbIndex = 0;

  // === 工具函数 ===
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatTitle(filename) {
    return filename
      .replace(/[-_]/g, ' ')
      .replace(/^(\d+)/, '')
      .trim();
  }

  /**
   * 解析 gallery.json 的 geo 字段，宽容三种手写格式：
   *   {"lat": 22.54, "lng": 114.06} / {"latitude": .., "longitude": ..} / [22.54, 114.06]
   * 非法/越界一律返回 null（该照片不上地图）。
   */
  function parseGeo(raw) {
    if (!raw || typeof raw === 'string') return null;
    let lat, lng;
    if (Array.isArray(raw)) {
      if (raw.length !== 2) return null;
      lat = raw[0];
      lng = raw[1];
    } else if (typeof raw === 'object') {
      lat = raw.lat !== undefined ? raw.lat : raw.latitude;
      lng = raw.lng !== undefined ? raw.lng
        : (raw.lon !== undefined ? raw.lon : raw.longitude);
    } else {
      return null;
    }
    lat = Number(lat);
    lng = Number(lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
    return { lat: lat, lng: lng };
  }

  /** EXIF 参数行 + 细节行（与首页 lightbox 同一口径） */
  function exifLines(img) {
    const e = img.exif;
    const params = [];
    let detail = '';
    if (e && (e.aperture || e.shutter || e.iso || e.focal_mm)) {
      if (e.aperture) params.push(e.aperture);
      if (e.shutter) params.push(e.shutter);
      if (e.iso) params.push('ISO ' + e.iso);
      if (e.focal_mm) {
        const eq = e.focal_equiv_mm;
        params.push(eq && eq !== e.focal_mm
          ? e.focal_mm + 'mm·等效' + eq + 'mm'
          : (eq || e.focal_mm) + 'mm');
      }
      detail = [e.lens, e.camera, e.taken].filter(Boolean).join(' · ');
    }
    return { params: params.join(' · '), detail: detail };
  }

  // === 加载数据 ===
  fetch('gallery.json')
    .then(function (res) { return res.json(); })
    .then(function (data) {
      const all = Array.isArray(data) ? data : [];
      geoPhotos = [];
      all.forEach(function (img) {
        const geo = parseGeo(img && img.geo);
        if (geo) geoPhotos.push({ img: img, geo: geo });
      });
      renderStats(all.length, geoPhotos.length);
      initMap();
    })
    .catch(function (err) {
      console.error('Failed to load gallery data:', err);
      if (statsEl) statsEl.textContent = '图片数据加载失败，请刷新重试';
    });

  function renderStats(total, withGeo) {
    if (!statsEl) return;
    if (withGeo === 0) {
      statsEl.textContent = '共 ' + total + ' 张照片 · 暂无坐标';
    } else {
      const spots = countSpots();
      statsEl.textContent = '共 ' + total + ' 张照片 · ' + withGeo +
        ' 张有坐标 · ' + spots + ' 个机位';
    }
  }

  // === 地图 ===
  let map = null;

  function countSpots() {
    const seen = {};
    let n = 0;
    geoPhotos.forEach(function (p) {
      const key = p.geo.lat + ',' + p.geo.lng;
      if (!seen[key]) { seen[key] = true; n++; }
    });
    return n;
  }

  function groupBySpot() {
    const groups = [];
    const index = {};
    geoPhotos.forEach(function (p) {
      const key = p.geo.lat + ',' + p.geo.lng;
      if (index[key] === undefined) {
        index[key] = groups.length;
        groups.push({ geo: p.geo, items: [] });
      }
      groups[index[key]].items.push(p);
    });
    return groups;
  }

  function cameraIcon(count) {
    const badge = count > 1
      ? '<span class="photo-marker-badge">' + count + '</span>'
      : '';
    return L.divIcon({
      className: 'photo-marker-wrap',
      html: '<div class="photo-marker">' + badge +
        '<span class="photo-marker-glyph">📷</span></div>',
      iconSize: [34, 34],
      iconAnchor: [17, 34],
      popupAnchor: [0, -30],
    });
  }

  function popupHtml(items) {
    const cards = items.map(function (p) {
      const img = p.img;
      const flatIndex = geoPhotos.indexOf(p);
      const lines = exifLines(img);
      const meta = [];
      meta.push('<div class="map-popup-title">' +
        escapeHtml(formatTitle(img.title || '')) + '</div>');
      if (lines.params) {
        meta.push('<div class="map-popup-exif">📷 ' + escapeHtml(lines.params) + '</div>');
      }
      if (lines.detail) {
        meta.push('<div class="map-popup-detail">' + escapeHtml(lines.detail) + '</div>');
      }
      if (img.location) {
        meta.push('<div class="map-popup-loc">📍 ' + escapeHtml(img.location) + '</div>');
      }
      return '<div class="map-popup-photo">' +
        '<img class="map-popup-thumb" src="' + escapeHtml(img.thumb || img.display || '') +
        '" alt="' + escapeHtml(img.title || '') + '" data-index="' + flatIndex + '">' +
        '<div class="map-popup-meta">' + meta.join('') + '</div>' +
        '</div>';
    });
    return '<div class="map-popup">' + cards.join('') + '</div>';
  }

  function initMap() {
    map = L.map('map', { zoomControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    L.tileLayer(TILE_URL, {
      maxZoom: 19,
      attribution: TILE_ATTRIBUTION,
    }).addTo(map);

    if (geoPhotos.length === 0) {
      if (emptyEl) emptyEl.hidden = false;
      return;
    }

    groupBySpot().forEach(function (g) {
      const marker = L.marker([g.geo.lat, g.geo.lng], {
        icon: cameraIcon(g.items.length),
        alt: '机位：' + g.items.length + ' 张照片',
      }).addTo(map);
      marker.bindPopup(popupHtml(g.items), {
        maxWidth: 360,
        minWidth: 250,
        maxHeight: 380,
        className: 'photo-popup',
      });
    });

    // 弹窗打开后给缩略图绑点击（popup DOM 是惰性生成的）
    map.on('popupopen', function (e) {
      const el = e.popup && e.popup.getElement && e.popup.getElement();
      if (!el || !el.querySelectorAll) return;
      el.querySelectorAll('.map-popup-thumb').forEach(function (t) {
        t.addEventListener('click', function () {
          const idx = Number(t.getAttribute('data-index'));
          if (Number.isInteger(idx) && geoPhotos[idx]) openLightbox(idx);
        });
      });
    });

    // 视野自适应
    if (geoPhotos.length === 1) {
      map.setView([geoPhotos[0].geo.lat, geoPhotos[0].geo.lng], SINGLE_ZOOM);
    } else {
      const bounds = L.latLngBounds(geoPhotos.map(function (p) {
        return [p.geo.lat, p.geo.lng];
      }));
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
    }
  }

  // === 底图明暗切换 ===
  if (themeBtn && mapEl && mapEl.classList) {
    themeBtn.addEventListener('click', function () {
      const dark = mapEl.classList.toggle('map-dark');
      themeBtn.textContent = dark ? '☀️' : '🌙';
      themeBtn.setAttribute('aria-label',
        dark ? '切换为浅色底图' : '切换为深色底图');
    });
  }

  // === Lightbox ===
  function openLightbox(index) {
    lbIndex = index;
    updateLightboxImage();
    lightbox.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    lightbox.classList.remove('open');
    document.body.style.overflow = '';
  }

  function updateLightboxImage() {
    const p = geoPhotos[lbIndex];
    if (!p) return;
    const img = p.img;
    lbImage.src = img.display || img.full || img.thumb;
    lbImage.alt = img.title || '';
    lbCounter.textContent = (lbIndex + 1) + ' / ' + geoPhotos.length;
    renderShootingInfo(img, p.geo);
  }

  function renderShootingInfo(img, geo) {
    if (!lbInfo) return;
    const lines = [];

    const e = img.exif;
    if (e && (e.aperture || e.shutter || e.iso || e.focal_mm)) {
      const params = [];
      if (e.aperture) params.push(e.aperture);
      if (e.shutter) params.push(e.shutter);
      if (e.iso) params.push('ISO ' + e.iso);
      if (e.focal_mm) {
        const eq = e.focal_equiv_mm;
        params.push(eq && eq !== e.focal_mm
          ? e.focal_mm + 'mm·等效' + eq + 'mm'
          : (eq || e.focal_mm) + 'mm');
      }
      if (params.length) lines.push('📷 ' + params.join(' · '));

      const detail = [e.lens, e.camera, e.taken].filter(Boolean);
      if (detail.length) lines.push(detail.join(' · '));
    }

    if (img.location) {
      lines.push('📍 ' + img.location);
    } else if (geo) {
      // 没补地点名时至少显示坐标
      lines.push('📍 ' + geo.lat.toFixed(4) + ', ' + geo.lng.toFixed(4));
    }

    if (lines.length) {
      lbInfo.innerHTML = lines
        .map(function (l) { return '<div class="lightbox-info-line">' + escapeHtml(l) + '</div>'; })
        .join('');
      lbInfo.hidden = false;
    } else {
      lbInfo.innerHTML = '';
      lbInfo.hidden = true;
    }
  }

  function showPrev(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    if (!geoPhotos.length) return;
    lbIndex = (lbIndex - 1 + geoPhotos.length) % geoPhotos.length;
    updateLightboxImage();
  }

  function showNext(e) {
    if (e && e.stopPropagation) e.stopPropagation();
    if (!geoPhotos.length) return;
    lbIndex = (lbIndex + 1) % geoPhotos.length;
    updateLightboxImage();
  }

  document.querySelector('.lightbox-close').addEventListener('click', closeLightbox);
  document.querySelector('.lightbox-prev').addEventListener('click', showPrev);
  document.querySelector('.lightbox-next').addEventListener('click', showNext);

  lightbox.addEventListener('click', function (e) {
    if (e.target === lightbox) closeLightbox();
  });

  document.addEventListener('keydown', function (e) {
    if (!lightbox.classList.contains('open')) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') showPrev(e);
    if (e.key === 'ArrowRight') showNext(e);
  });
})();
