(function () {
  'use strict';

  const PAGE_SIZE = 24;

  // === DOM refs ===
  const galleryContainer = document.getElementById('gallery');
  const filterBar = document.getElementById('filterBar');
  const lightbox = document.getElementById('lightbox');
  const lbImage = lightbox.querySelector('img');
  const lbCounter = lightbox.querySelector('.lightbox-counter');
  const backToTop = document.getElementById('backToTop');
  const loadMoreBtn = document.getElementById('loadMoreBtn');
  const loadMoreWrap = document.getElementById('loadMoreWrap');

  let allImages = [];
  let filteredImages = [];
  let currentPage = 0;
  let activeCategory = 'all';
  let lightboxImages = []; // currently displayed images for lightbox nav

  // === Fetch gallery data ===
  fetch('gallery.json')
    .then(res => res.json())
    .then(data => {
      allImages = data;
      filteredImages = [...allImages];
      buildFilterBar();
      loadNextPage();
    })
    .catch(err => {
      console.error('Failed to load gallery data:', err);
      galleryContainer.innerHTML = '<p style="text-align:center;color:#999;padding:40px">图片数据加载失败，请刷新重试</p>';
    });

  // === Build filter buttons from data ===
  function buildFilterBar() {
    const cats = getCategories();
    cats.forEach(cat => {
      const btn = document.createElement('button');
      btn.className = 'filter-btn' + (cat === 'all' ? ' active' : '');
      btn.textContent = formatCategory(cat);
      btn.dataset.category = cat;
      btn.addEventListener('click', () => filterByCategory(cat, btn));
      filterBar.appendChild(btn);
    });
  }

  function getCategories() {
    const set = new Set(allImages.map(img => img.category));
    return ['all', ...Array.from(set).sort()];
  }

  function formatCategory(cat) {
    const map = {
      all: '全部',
      sunrise: '日出',
      sunset: '日落',
      lotus: '荷花',
      flower: '花',
      landscape: '风光',
      cityscape: '城市',
      star: '星空',
      travel: '旅行',
      automotive: '汽车',
      event: '漫展',
      bird: '鸟类',
      pet: '宠物',
      uncategorized: '其他'
    };
    return map[cat] || cat;
  }

  // === Filter images ===
  function filterByCategory(category, btn) {
    activeCategory = category;
    filterBar.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    filteredImages = category === 'all'
      ? [...allImages]
      : allImages.filter(img => img.category === category);

    currentPage = 0;
    lightboxImages = [];
    galleryContainer.innerHTML = '';
    loadMoreBtn.disabled = false;
    loadMoreWrap.style.display = '';
    loadNextPage();
  }

  // === Pagination ===
  function loadNextPage() {
    const start = currentPage * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    const page = filteredImages.slice(start, end);

    if (page.length === 0) {
      loadMoreBtn.disabled = true;
      loadMoreBtn.textContent = '已展示全部';
      return;
    }

    page.forEach((img, i) => {
      const globalIndex = lightboxImages.length + i; // before adding new ones
      const item = createGalleryItem(img, globalIndex);
      galleryContainer.appendChild(item);
    });

    lightboxImages.push(...page);
    currentPage++;

    if (start + page.length >= filteredImages.length) {
      loadMoreBtn.disabled = true;
      loadMoreBtn.textContent = '已展示全部';
    } else {
      loadMoreBtn.textContent = `加载更多 (${filteredImages.length - lightboxImages.length} 张剩余)`;
    }
  }

  loadMoreBtn.addEventListener('click', loadNextPage);

  // === Create gallery item with loading state ===
  function createGalleryItem(img, index) {
    const item = document.createElement('div');
    item.className = 'gallery-item';
    // thumb (400px WebP) for gallery; full (2560px WebP) for lightbox via data attribute
    item.innerHTML = `
      <img src="${img.thumb}" alt="${img.title}" loading="lazy" data-full="${img.full}">
      <div class="overlay">
        <div class="info">
          <div class="title">${formatTitle(img.title)}</div>
          <div class="date">${formatCategory(img.category)}</div>
        </div>
      </div>
    `;

    const imgEl = item.querySelector('img');
    imgEl.addEventListener('load', () => {
      imgEl.classList.add('loaded');
      item.classList.add('loaded');
    });
    imgEl.addEventListener('error', () => {
      item.classList.add('loaded');
    });
    // In case image is cached and already loaded
    if (imgEl.complete) {
      imgEl.classList.add('loaded');
      item.classList.add('loaded');
    }

    item.addEventListener('click', () => openLightbox(index));
    return item;
  }

  function formatTitle(filename) {
    return filename
      .replace(/[-_]/g, ' ')
      .replace(/^(\d+)/, '')
      .trim();
  }

  // === Lightbox ===
  function openLightbox(index) {
    window._lbIndex = index;
    updateLightboxImage();
    lightbox.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeLightbox() {
    lightbox.classList.remove('open');
    document.body.style.overflow = '';
  }

  function updateLightboxImage() {
    const idx = window._lbIndex;
    const img = lightboxImages[idx];
    if (!img) return;
    // Use full-resolution WebP if available, fallback to src
    lbImage.src = img.full || img.src;
    lbImage.alt = img.title;
    lbCounter.textContent = `${idx + 1} / ${lightboxImages.length}`;
  }

  function showPrev(e) {
    e.stopPropagation();
    window._lbIndex = (window._lbIndex - 1 + lightboxImages.length) % lightboxImages.length;
    updateLightboxImage();
  }

  function showNext(e) {
    e.stopPropagation();
    window._lbIndex = (window._lbIndex + 1) % lightboxImages.length;
    updateLightboxImage();
  }

  // Lightbox events
  document.querySelector('.lightbox-close').addEventListener('click', closeLightbox);
  document.querySelector('.lightbox-prev').addEventListener('click', showPrev);
  document.querySelector('.lightbox-next').addEventListener('click', showNext);

  lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });

  document.addEventListener('keydown', (e) => {
    if (!lightbox.classList.contains('open')) return;
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') showPrev(e);
    if (e.key === 'ArrowRight') showNext(e);
  });

  // === Scroll effects ===
  let ticking = false;
  window.addEventListener('scroll', () => {
    if (!ticking) {
      requestAnimationFrame(() => {
        const scrolled = window.scrollY > 10;
        filterBar.classList.toggle('scrolled', scrolled);
        backToTop.classList.toggle('visible', window.scrollY > 500);
        ticking = false;
      });
      ticking = true;
    }
  });

  backToTop.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // Scroll hint click
  const scrollHint = document.querySelector('.scroll-hint');
  if (scrollHint) {
    scrollHint.addEventListener('click', () => {
      const about = document.querySelector('.about');
      if (about) about.scrollIntoView({ behavior: 'smooth' });
    });
  }
})();
