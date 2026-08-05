(function () {
  'use strict';

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('zui-theme', theme); } catch (e) {}
  }

  function toggleTheme() {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }

  var toggle = document.getElementById('theme-toggle-landing');
  if (toggle) toggle.addEventListener('click', toggleTheme);

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function animateCount(el) {
    var target = parseFloat(el.getAttribute('data-count')) || 0;
    var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
    var suffix = el.getAttribute('data-suffix') || '';
    if (reduceMotion) {
      el.textContent = target.toFixed(decimals) + suffix;
      return;
    }
    var start = performance.now();
    var duration = 1100;
    function frame(now) {
      var t = Math.min(1, (now - start) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = (target * eased).toFixed(decimals) + suffix;
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  var observed = new WeakSet();
  function revealOnce(entries, observer) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting || observed.has(entry.target)) return;
      observed.add(entry.target);
      entry.target.classList.add('in');
      entry.target.querySelectorAll('[data-count]').forEach(function (el) {
        animateCount(el);
      });
      observer.unobserve(entry.target);
    });
  }

  var heroCounts = document.querySelectorAll('.hero-mock [data-count]');
  heroCounts.forEach(function (el) {
    if (observed.has(el)) return;
    observed.add(el);
    animateCount(el);
  });

  if ('IntersectionObserver' in window && !reduceMotion) {
    var io = new IntersectionObserver(revealOnce, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    document.querySelectorAll('.reveal').forEach(function (el) { io.observe(el); });
  } else {
    document.querySelectorAll('.reveal').forEach(function (el) {
      el.classList.add('in');
    });
    document.querySelectorAll('[data-count]').forEach(animateCount);
  }
})();
