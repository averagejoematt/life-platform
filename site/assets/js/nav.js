/**
 * nav.js — Shared navigation component for averagejoematt.com
 * Handles: hamburger menu, bottom nav active state, theme toggle
 * v1.0.0 — 2026-03-21
 */
(function() {
  'use strict';

  // ── Hamburger toggle ──────────────────────────────────────
  var hamburger = document.querySelector('.nav__hamburger');
  var overlay = document.querySelector('.nav-overlay');
  var overlayClose = document.querySelector('.nav-overlay__close');
  var body = document.body;

  function openMenu() {
    if (overlay) {
      overlay.classList.add('is-open');
      body.style.overflow = 'hidden';
    }
  }
  function closeMenu() {
    if (overlay) {
      overlay.classList.remove('is-open');
      body.style.overflow = '';
    }
  }

  if (hamburger) hamburger.addEventListener('click', openMenu);
  if (overlayClose) overlayClose.addEventListener('click', closeMenu);
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeMenu();
    });
  }

  // ── Bottom nav active state ───────────────────────────────
  var path = window.location.pathname;
  var bottomLinks = document.querySelectorAll('.bottom-nav__link');
  bottomLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if (href === '/' && path === '/') {
      link.classList.add('active');
    } else if (href !== '/' && path.startsWith(href)) {
      link.classList.add('active');
    }
  });

  // ── Top nav active state ──────────────────────────────────
  var navLinks = document.querySelectorAll('.nav__link:not(.nav__cta)');
  navLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if (href !== '/' && path.startsWith(href)) {
      link.classList.add('active');
    }
  });

  // ── Overlay nav active state ──────────────────────────────
  var overlayLinks = document.querySelectorAll('.nav-overlay__link');
  overlayLinks.forEach(function(link) {
    var href = link.getAttribute('href');
    if ((href === '/' && path === '/') || (href !== '/' && path.startsWith(href))) {
      link.classList.add('active');
    }
  });

  // ── Theme toggle ──────────────────────────────────────────
  var themeToggle = document.querySelector('.theme-toggle');
  if (themeToggle) {
    var saved = localStorage.getItem('amj-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);

    themeToggle.addEventListener('click', function() {
      var current = document.documentElement.getAttribute('data-theme') || 'dark';
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('amj-theme', next);
    });
  }

  // ── Keyboard: Escape closes overlay ───────────────────────
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeMenu();
  });
})();
