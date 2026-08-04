// 验证脚本：用 DOM 桩在 node 里真实执行 assets/script.js，
// 模拟加载 gallery.json → 点开 lightbox → 检查拍摄信息区渲染。
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');

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
  querySelector() { return new FakeEl('div'); }
  querySelectorAll() { return []; }
  scrollIntoView() {}
  setAttribute(k, v) { this.attributes[k] = v; }
}

// --- lightbox 内部元素 ---
const lbImg = new FakeEl('img');
const lbCounter = new FakeEl('span');
const lbInfo = new FakeEl('div');
lbInfo.hidden = true;

const lightbox = new FakeEl('div');
lightbox._map = { img: lbImg, '.lightbox-counter': lbCounter, '.lightbox-info': lbInfo };
lightbox.querySelector = sel => lightbox._map[sel] || new FakeEl('div');

const ids = {
  gallery: new FakeEl(), filterBar: new FakeEl(), lightbox,
  backToTop: new FakeEl(), loadMoreBtn: new FakeEl('button'), loadMoreWrap: new FakeEl(),
};
const dotMap = {
  '.lightbox-close': new FakeEl('button'), '.lightbox-prev': new FakeEl('button'),
  '.lightbox-next': new FakeEl('button'), '.scroll-hint': null, '.about': null,
};

global.document = {
  getElementById: id => ids[id],
  querySelector: sel => (sel in dotMap ? dotMap[sel] : new FakeEl()),
  addEventListener() {},
  createElement: tag => new FakeEl(tag),
  body: { style: {} },
};
global.window = {
  addEventListener() {}, scrollTo() {},
};
global.requestAnimationFrame = fn => fn();

const galleryData = JSON.parse(fs.readFileSync(path.join(ROOT, 'gallery.json'), 'utf8'));
global.fetch = url => {
  if (String(url).includes('gallery.json')) {
    return Promise.resolve({ json: () => Promise.resolve(galleryData) });
  }
  return Promise.reject(new Error('unexpected fetch: ' + url));
};

process.on('unhandledRejection', err => { console.error('❌ unhandled rejection:', err); process.exit(1); });

require(path.join(ROOT, 'assets', 'script.js'));

setTimeout(() => {
  let fail = 0;
  const check = (name, cond, extra) => {
    console.log((cond ? '  ✅' : '  ❌') + ' ' + name + (extra ? `  → ${extra}` : ''));
    if (!cond) fail++;
  };

  check('画廊渲染 13 个条目', ids.gallery.children.length === 13, `实际 ${ids.gallery.children.length}`);

  const openAt = i => ids.gallery.children[i].fire('click');
  const strip = h => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

  // 1) bird01 —— 有 EXIF 无地点
  openAt(0);
  let text = strip(lbInfo.innerHTML);
  check('bird01 信息区可见', lbInfo.hidden === false);
  check('bird01 参数行', text.includes('f/7.1') && text.includes('1/800s') && text.includes('ISO 4000') && text.includes('257mm'), text);
  check('bird01 镜头/机身/时间行', text.includes('Sigma 100-400mm') && text.includes('Panasonic S5II') && text.includes('2023-07-04'), text);
  check('bird01 无 📍（location 为空不显示）', !text.includes('📍'));
  check('计数器 1 / 13', lbCounter.textContent === '1 / 13', lbCounter.textContent);
  check('lightbox src 指向 full 大图', lbImg.src.includes('optimized/full/bird01.webp'), lbImg.src);

  // 2) flower —— 无 EXIF（索引 2）
  const flowerIdx = galleryData.findIndex(g => g.title === 'flower');
  openAt(flowerIdx);
  check('flower 信息区整块隐藏', lbInfo.hidden === true && lbInfo.innerHTML === '');

  // 3) 模拟手动补了 location 的条目 → 只显示 📍
  const starIdx = galleryData.findIndex(g => g.title === 'star01');
  galleryData[starIdx].location = '深圳·梧桐山';
  // 重新走一遍 fetch 流：直接改内存数据后重开
  openAt(starIdx);
  text = strip(lbInfo.innerHTML);
  check('star01（无EXIF+手补地点）只显示 📍', lbInfo.hidden === false && text.includes('📍 深圳·梧桐山') && !text.includes('📷'), text);

  // 4) HTML 转义防注入
  galleryData[starIdx].location = '<img src=x onerror=alert(1)>';
  openAt(starIdx);
  check('location 注入被转义', !lbInfo.innerHTML.includes('<img'), lbInfo.innerHTML.slice(0, 80));

  // 5) 左右切换不报错
  dotMap['.lightbox-next'].fire('click');
  dotMap['.lightbox-prev'].fire('click');
  check('前后切换正常', true);

  console.log(fail === 0 ? '\n全部通过 ✅' : `\n${fail} 项失败 ❌`);
  process.exit(fail === 0 ? 0 : 1);
}, 100);
