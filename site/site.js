// The landing page's behavior. Nothing loads from outside, and there is no library.
// 1. The language (English first, Japanese) and the theme (dark or light) go on <html> before the page draws.
// 2. The layers: the scroll position pulls the eight layers apart and picks the current one, its number, and its
//    lines. Under prefers-reduced-motion, or on a short screen (a phone on its side), <html> gets no .motion and
//    the layers stand still in a column (site.css).
// 3. The moving picture plays on its own only when motion is allowed. Otherwise it waits for its play button.
(() => {
  const root = document.documentElement;
  const LANG_KEY = 'task-hub-site-lang';
  const THEME_KEY = 'task-hub-site-theme';
  const TITLES = {
    en: 'task-hub: Your local coding agents turn each GitHub Project card you move to Ready into a reviewed PR.',
    ja: 'task-hub: Ready に移した GitHub Project のカードを、手元のエージェントがレビュー済みの PR にする。',
  };
  // The attributes that change with the language. The HTML holds English; Japanese is in data-ja-<attribute>
  const ATTRS = ['alt', 'aria-label', 'title', 'href'];
  // Where the layers are fully apart (a share of the scroll); the rest is split evenly among the eight layers
  const SPLIT = 0.1;
  // The review layer (5) shows needs changes for the first half of its share, then pass
  const REVIEW = 4;
  // On a screen shorter than this, a layer and its lines do not fit, so nothing moves
  const MIN_HEIGHT = 560;

  // Some browsers refuse localStorage (file://, or a setting): the switches still work for this page
  function stored(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }
  function store(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // not kept, but this page has switched
    }
  }

  const asked = new URLSearchParams(location.search).get('lang');
  root.lang = asked === 'en' || asked === 'ja' ? asked : stored(LANG_KEY) === 'ja' ? 'ja' : 'en';
  const theme = stored(THEME_KEY);
  if (theme === 'dark' || theme === 'light') root.dataset.theme = theme;

  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const tall = matchMedia(`(min-height: ${MIN_HEIGHT}px)`);
  // The 3D sizes itself with container query units (cqw, cqh): a browser without them gets the still column
  const sized = typeof CSS !== 'undefined' && CSS.supports('container-type: size');
  const moving = () => sized && !reduce.matches && tall.matches;

  function applyLang(lang) {
    root.lang = lang;
    document.title = TITLES[lang];
    for (const attr of ATTRS) {
      for (const el of document.querySelectorAll(`[data-ja-${attr}]`)) {
        if (!el.hasAttribute(`data-en-${attr}`)) el.setAttribute(`data-en-${attr}`, el.getAttribute(attr) ?? '');
        el.setAttribute(attr, el.getAttribute(`data-${lang}-${attr}`));
      }
    }
    const toggle = document.getElementById('lang-toggle');
    toggle.textContent = lang === 'ja' ? 'English' : '日本語';
    toggle.lang = lang === 'ja' ? 'en' : 'ja';
  }

  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  const clamp = (value) => Math.min(1, Math.max(0, value));

  function setupLayers() {
    const track = document.querySelector('.layers-track');
    const stage = document.querySelector('.layers-stage');
    const stack = document.querySelector('.layers-stack');
    const layers = [...document.querySelectorAll('.layer')];
    const now = document.querySelector('.layer-now');
    const text = document.querySelector('.layer-text');
    let active = -1;
    let frame = 0;

    function show(index) {
      if (index === active) return;
      active = index;
      layers.forEach((layer, i) => layer.classList.toggle('is-active', i === index));
      now.textContent = String(index + 1).padStart(2, '0');
      // The current layer's name and two lines are a copy of its figcaption, in both languages
      text.replaceChildren(...layers[index].querySelector('figcaption').cloneNode(true).childNodes);
      stage.dataset.active = String(index + 1);
    }

    function update() {
      frame = 0;
      const range = track.offsetHeight - stage.offsetHeight;
      const progress = range > 0 ? clamp(-track.getBoundingClientRect().top / range) : 0;
      const sep = clamp(progress / SPLIT);
      stack.style.setProperty('--sep', sep.toFixed(3));
      stage.classList.toggle('is-split', sep > 0.5);
      const at = progress < SPLIT ? 0 : ((progress - SPLIT) / (1 - SPLIT)) * layers.length;
      show(Math.min(layers.length - 1, Math.floor(at)));
      stage.dataset.review = at < REVIEW ? '' : at < REVIEW + 0.5 ? 'changes' : 'pass';
    }

    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    function setMotion(on) {
      root.classList.toggle('motion', on);
      if (on) {
        addEventListener('scroll', onScroll, { passive: true });
        addEventListener('resize', onScroll);
        active = -1;
        update();
      } else {
        removeEventListener('scroll', onScroll);
        removeEventListener('resize', onScroll);
        cancelAnimationFrame(frame);
        frame = 0;
        stack.style.removeProperty('--sep');
        stage.classList.remove('is-split');
        delete stage.dataset.review;
        layers.forEach((layer) => layer.classList.remove('is-active'));
      }
    }

    const follow = () => setMotion(moving());
    follow();
    reduce.addEventListener('change', follow);
    tall.addEventListener('change', follow);
  }

  function setupDemo() {
    const video = document.getElementById('demo-video');
    const follow = () => {
      if (reduce.matches) {
        video.autoplay = false;
        video.pause();
      } else {
        video.autoplay = true;
        video.play().catch(() => {
          // the browser wants a click first: the controls are there
        });
      }
    };
    follow();
    reduce.addEventListener('change', follow);
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyLang(root.lang);
    document.getElementById('lang-toggle').addEventListener('click', () => {
      const lang = root.lang === 'ja' ? 'en' : 'ja';
      applyLang(lang);
      store(LANG_KEY, lang);
      // a ?lang= in the address would win again on the next load: the button's choice replaces it
      const url = new URL(location.href);
      if (url.searchParams.has('lang')) {
        url.searchParams.delete('lang');
        history.replaceState(null, '', url);
      }
    });
    document.getElementById('theme-toggle').addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      store(THEME_KEY, next);
    });
    setupLayers();
    setupDemo();
  });
})();
