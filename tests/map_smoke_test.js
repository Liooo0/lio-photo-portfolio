// 验证脚本：用 DOM 桩 + Leaflet 桩在 node 里真实执行 assets/map.js。
// 模拟加载带坐标的 gallery.json → 校验：坐标解析/过滤、同机位合并、
// 弹窗内容（缩略图+拍摄信息+XSS转义）、空状态、视野自适应。
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const MAP_JS = path.join(ROOT, 'assets', 'map.js');

// ---------- 可复用的 DOM 桩 ----------
class FakeEl {
  constructor(tag) {
    this.tagName = (tag || 'div').toUpperCase();
    this.children = [];
    this._handlers = {};
    this.classList = {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, force) {
        const on = force === undefined ? !this._set.has(c) : force;
        on ? this._set.add(c) : this._set.delete(c);
        return on;
      },
      contains(c) { return this._set.has(c); },
    };
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.innerHTML = '';
    this.textContent = '';
    this.disabled = false;
    this.hidden = false;
    this.complete = false;
    this.src = '';
    this.alt = '';
  }
  addEventListener(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); }
  fire(type, ev) { (this._handlers[type] || []).forEach(fn => fn(ev || { stopPropagation() {}, key: '' })); }
  appendChild(child) { this.children.push(child); return child; }
  querySelector(sel) { return this._qmap ? (this._qmap[sel] || new FakeEl('div')) : new FakeEl('div'); }
  querySelectorAll(sel) { return this._qmapAll ? (this._qmapAll[sel] || []) : []; }
  scrollIntoView() {}
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k]; }
}

function buildDom() {
  const lbImg = new FakeEl('img');
  const lbCounter = new FakeEl('span');
  const lbInfo = new FakeEl('div');
  lbInfo.hidden = true;

  const lightbox = new FakeEl('div');
  lightbox._qmap = { img: lbImg, '.lightbox-counter': lbCounter, '.lightbox-info': lbInfo };

  const ids = {
    map: new FakeEl(), mapStats: new FakeEl(), mapEmpty: new FakeEl(),
    mapThemeBtn: new FakeEl('button'), lightbox, backToTop: new FakeEl('button'),
    lightboxInfo: lbInfo,
  };
  // HTML 里 mapEmpty 初始带 hidden 属性
  ids.mapEmpty.hidden = true;
  const dotMap = {
    '.lightbox-close': new FakeEl('button'), '.lightbox-prev': new FakeEl('button'),
    '.lightbox-next': new FakeEl('button'),
  };
  const document = {
    getElementById: id => ids[id],
    querySelector: sel => (sel in dotMap ? dotMap[sel] : new FakeEl()),
    addEventListener() {},
    createElement: tag => new FakeEl(tag),
    body: { style: {} },
  };
  return { document, ids, lbImg, lbCounter, lbInfo };
}

// ---------- Leaflet 桩 ----------
function buildLeaflet() {
  const state = { markers: [], tileLayers: [], setView: [], fitBounds: [], mapOpts: null, popupHandler: null };
  const L = {
    map(id, opts) {
      state.mapOpts = { id, opts };
      const map = {
        setView(center, zoom) { state.setView.push({ center, zoom }); return this; },
        fitBounds(bounds, opts) { state.fitBounds.push({ bounds, opts }); return this; },
        on(type, fn) { if (type === 'popupopen') state.popupHandler = fn; },
        addLayer() { return this; },
      };
      return map;
    },
    tileLayer(url, opts) { return { addTo() { state.tileLayers.push({ url, opts }); return this; } }; },
    marker(latlng, opts) {
      const m = {
        latlng, opts, popup: null,
        addTo() { state.markers.push(this); return this; },
        bindPopup(html, opts) { this.popup = { html, opts }; return this; },
      };
      return m;
    },
    divIcon(opts) { return Object.assign({ _divIcon: true }, opts); },
    latLngBounds(points) { return { points }; },
  };
  return { L, state };
}

// ---------- 场景加载器 ----------
function loadScenario(galleryData) {
  // 清掉 map.js 的 require 缓存，保证每个场景干净
  delete require.cache[MAP_JS];

  const dom = buildDom();
  const leaf = buildLeaflet();
  global.document = dom.document;
  global.window = { addEventListener() {} };
  global.L = leaf.L;
  global.fetch = url => {
    if (String(url).includes('gallery.json')) {
      return Promise.resolve({ json: () => Promise.resolve(galleryData) });
    }
    return Promise.reject(new Error('unexpected fetch: ' + url));
  };

  require(MAP_JS);
  // fetch().then 是微任务，等宏任务一拍后 DOM/标记都已就绪
  return new Promise(resolve => setTimeout(() => resolve({ dom, state: leaf.state }), 30));
}

function baseEntry(o) {
  const t = (o && o.title) || 'x';
  return Object.assign({
    title: t, category: 'sunset',
    thumb: `optimized/thumb/${t}.webp`,
    display: `optimized/display/${t}.webp`,
    full: `optimized/full/${t}.webp`,
  }, o);
}

let failures = 0;
function check(name, cond, extra) {
  console.log((cond ? '  ✅' : '  ❌') + ' ' + name + (extra ? `  → ${extra}` : ''));
  if (!cond) failures++;
}
const strip = h => String(h).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

process.on('unhandledRejection', err => { console.error('❌ unhandled rejection:', err); process.exit(1); });

(async () => {
  // ============ 场景 1：常规数据（有坐标 / 无坐标 / 非法坐标 / 同机位合并） ============
  console.log('\n[场景1] 常规数据');
  const data1 = [
    baseEntry({ title: 'sunset-a', geo: { lat: 22.5431, lng: 114.0579 },
      exif: { aperture: 'f/2.8', shutter: '1/2000s', iso: 100, focal_mm: 70, focal_equiv_mm: 98,
              lens: 'Sigma 28-70mm F2.8', camera: 'Panasonic S5II', taken: '2025-06-25 19:05' },
      location: '深圳湾公园' }),
    // 同机位第二张（不同 EXIF 写法：latitude/longitude）
    baseEntry({ title: 'sunset-b', geo: { latitude: 22.5431, longitude: 114.0579 } }),
    // 数组写法
    baseEntry({ title: 'bird', geo: [30.5728, 104.0668] }),
    baseEntry({ title: 'no-geo' }),                    // 无坐标 → 不上图
    baseEntry({ title: 'bad-lat', geo: { lat: 95, lng: 114 } }),   // 纬度越界
    baseEntry({ title: 'bad-lng', geo: { lat: 22, lng: 999 } }),   // 经度越界
    baseEntry({ title: 'bad-type', geo: '深圳' }),      // 非数字
    baseEntry({ title: 'nan', geo: { lat: 'abc', lng: 114 } }),     // NaN
    baseEntry({ title: 'xss', geo: { lat: 31.2304, lng: 121.4737 },
      location: '<img src=x onerror=alert(1)>' }),
  ];
  const s1 = await loadScenario(data1);

  // 有效坐标：sunset-a, sunset-b(同机位), bird, xss → 4 张，机位 3 个（sunset 合并）
  check('标记数 = 3 个机位', s1.state.markers.length === 3, `实际 ${s1.state.markers.length}`);
  const sunsetSpot = s1.state.markers.find(m => m.latlng[0] === 22.5431);
  check('同机位合并成一个标记', !!sunsetSpot);
  check('合并标记带 2 张角标', sunsetSpot && sunsetSpot.opts.icon.html.includes('>2<'),
    sunsetSpot && sunsetSpot.opts.icon.html);
  check('瓦片图层使用 OSM', s1.state.tileLayers.length === 1 &&
    s1.state.tileLayers[0].url.includes('openstreetmap.org'), s1.state.tileLayers[0] && s1.state.tileLayers[0].url);
  check('多点位调用 fitBounds', s1.state.fitBounds.length === 1);
  check('XSS location 被转义', (() => {
    const m = s1.state.markers.find(mk => mk.latlng[0] === 31.2304);
    return m && m.popup.html.includes('&lt;img') && !m.popup.html.includes('<img src=x');
  })());
  check('弹窗含缩略图与拍摄参数', (() => {
    return sunsetSpot && sunsetSpot.popup.html.includes('optimized/thumb/sunset-a.webp') &&
      sunsetSpot.popup.html.includes('f/2.8') && sunsetSpot.popup.html.includes('1/2000s') &&
      sunsetSpot.popup.html.includes('深圳湾公园');
  })());
  check('空状态隐藏（有坐标照片）', s1.dom.ids.mapEmpty.hidden === true);
  check('统计文案含坐标数', /4 张有坐标/.test(s1.dom.ids.mapStats.textContent), s1.dom.ids.mapStats.textContent);

  // 弹窗缩略图点击 → 打开 lightbox（通过 popupopen 绑定）
  const thumb = new FakeEl('img');
  thumb.attributes['data-index'] = '0';
  let clicked = null;
  thumb.addEventListener = function (t, fn) { if (t === 'click') clicked = fn; };
  const popupEl = new FakeEl('div');
  popupEl._qmapAll = { '.map-popup-thumb': [thumb] };
  s1.state.popupHandler({ popup: { getElement: () => popupEl } });
  check('popupopen 绑定了缩略图点击', typeof clicked === 'function');
  clicked();
  check('点缩略图打开 lightbox 并载入 display 图',
    s1.dom.lbImg.src.includes('optimized/display/sunset-a.webp'), s1.dom.lbImg.src);
  const infoTxt = strip(s1.dom.lbInfo.innerHTML);
  check('lightbox 信息区含参数与地点', infoTxt.includes('f/2.8') && infoTxt.includes('深圳湾公园'), infoTxt);

  // ============ 场景 2：全无坐标 → 空状态 ============
  console.log('\n[场景2] 全无坐标');
  const data2 = [baseEntry({ title: 'a' }), baseEntry({ title: 'b' })];
  const s2 = await loadScenario(data2);
  check('无标记', s2.state.markers.length === 0, `实际 ${s2.state.markers.length}`);
  check('空状态显示', s2.dom.ids.mapEmpty.hidden === false);
  check('统计文案为暂无坐标', /暂无坐标/.test(s2.dom.ids.mapStats.textContent), s2.dom.ids.mapStats.textContent);
  check('空数据不调 fitBounds', s2.state.fitBounds.length === 0);

  // ============ 场景 3：单张坐标 → setView 定点 ============
  console.log('\n[场景3] 单张坐标');
  const data3 = [baseEntry({ title: 'only', geo: { lat: 22.5431, lng: 114.0579 } })];
  const s3 = await loadScenario(data3);
  check('单标记', s3.state.markers.length === 1);
  check('单点位用 setView 定点', s3.state.setView.length >= 1 && s3.state.fitBounds.length === 0);

  // ============ 场景 4：真实 gallery.json（当前全无 GPS） ============
  console.log('\n[场景4] 真实 gallery.json');
  const real = JSON.parse(fs.readFileSync(path.join(ROOT, 'gallery.json'), 'utf8'));
  const s4 = await loadScenario(real);
  const realWithGeo = real.filter(e => e && e.geo).length;
  check('真实数据无坐标 → 空状态', realWithGeo === 0 && s4.dom.ids.mapEmpty.hidden === false,
    `带坐标 ${realWithGeo} 张`);

  console.log(failures === 0 ? '\n全部通过 ✅' : `\n${failures} 项失败 ❌`);
  process.exit(failures === 0 ? 0 : 1);
})().catch(err => { console.error('❌ 测试崩溃:', err); process.exit(1); });
