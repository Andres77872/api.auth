/* Magic Auth documentation wiki — progressive enhancement only.
   Every page is fully readable without this script. */
(function () {
  'use strict';

  var body = document.body;
  var BASE = body.getAttribute('data-docs-base') || '/documentation';
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ---------------------------------------------------------------- toast */
  var toast = $('[data-toast]');
  var toastTimer = null;

  function showToast(message) {
    if (!toast) return;
    $('[data-toast-text]', toast).textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('is-visible');
    }, 1800);
  }

  /* ------------------------------------------------------------ clipboard */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Plain-HTTP origins (LAN, staging) have no Clipboard API.
    return new Promise(function (resolve, reject) {
      var area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand('copy') ? resolve() : reject(new Error('copy failed'));
      } catch (error) {
        reject(error);
      } finally {
        document.body.removeChild(area);
      }
    });
  }

  function flash(button, doneLabel) {
    var label = $('span', button);
    var original = label ? label.textContent : null;
    button.classList.add('is-done');
    if (label) label.textContent = doneLabel;
    setTimeout(function () {
      button.classList.remove('is-done');
      if (label) label.textContent = original;
    }, 1600);
  }

  $all('[data-copy-code]').forEach(function (button) {
    button.addEventListener('click', function () {
      var code = button.closest('.code-block').querySelector('code');
      copyText(code.textContent).then(
        function () { flash(button, 'Copied'); },
        function () { showToast('Copy is not available in this browser'); }
      );
    });
  });

  $all('[data-copy-markdown]').forEach(function (button) {
    button.addEventListener('click', function () {
      fetch(button.getAttribute('data-copy-markdown'), { credentials: 'same-origin' })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.text();
        })
        .then(copyText)
        .then(
          function () { flash(button, 'Copied'); showToast('Markdown copied to the clipboard'); },
          function () { showToast('Could not copy the Markdown source'); }
        );
    });
  });

  $all('.prose .anchor').forEach(function (anchor) {
    anchor.addEventListener('click', function () {
      var url = location.href.split('#')[0] + anchor.getAttribute('href');
      copyText(url).then(function () { showToast('Link to section copied'); }, function () {});
    });
  });

  /* ---------------------------------------------------------------- theme */
  var themeButtons = $all('[data-theme-choice]');
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function storedTheme() {
    try {
      return localStorage.getItem('theme');
    } catch (error) {
      return null;
    }
  }

  function applyTheme(choice) {
    var resolved = choice === 'light' || choice === 'dark'
      ? choice
      : choice === 'system' && media && !media.matches ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', resolved);
    themeButtons.forEach(function (button) {
      button.setAttribute('aria-checked', String(button.getAttribute('data-theme-choice') === choice));
    });
  }

  themeButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      var choice = button.getAttribute('data-theme-choice');
      try {
        localStorage.setItem('theme', choice);
      } catch (error) { /* private mode */ }
      applyTheme(choice);
    });
  });
  applyTheme(storedTheme() || 'dark');
  if (media && media.addEventListener) {
    media.addEventListener('change', function () {
      if (storedTheme() === 'system') applyTheme('system');
    });
  }

  /* --------------------------------------------------------- mobile drawer */
  var sidebar = $('#docs-sidebar');
  var scrim = $('[data-scrim]');
  var menuButton = $('[data-menu]');
  var narrow = window.matchMedia('(max-width: 1023px)');

  function setDrawer(open) {
    if (!sidebar || !menuButton) return;
    sidebar.classList.toggle('is-open', open);
    menuButton.setAttribute('aria-expanded', String(open));
    menuButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    if (scrim) scrim.hidden = !open;
    if (narrow.matches) {
      if (open) sidebar.removeAttribute('inert');
      else sidebar.setAttribute('inert', '');
    }
    if (open) {
      var current = $('[aria-current="page"]', sidebar) || $('a', sidebar);
      if (current) current.focus();
    }
  }

  function syncDrawerMode() {
    if (!sidebar) return;
    if (narrow.matches) {
      if (!sidebar.classList.contains('is-open')) sidebar.setAttribute('inert', '');
    } else {
      sidebar.removeAttribute('inert');
      sidebar.classList.remove('is-open');
      if (scrim) scrim.hidden = true;
      if (menuButton) menuButton.setAttribute('aria-expanded', 'false');
    }
  }

  if (menuButton) {
    menuButton.addEventListener('click', function () {
      setDrawer(!sidebar.classList.contains('is-open'));
    });
  }
  if (scrim) scrim.addEventListener('click', function () { setDrawer(false); });
  if (narrow.addEventListener) narrow.addEventListener('change', syncDrawerMode);
  syncDrawerMode();

  // Keep the active page visible in a long sidebar.
  var activeNav = sidebar && $('.nav [aria-current="page"]', sidebar);
  if (activeNav && activeNav.scrollIntoView) {
    var nav = $('.nav', sidebar);
    var navBox = nav.getBoundingClientRect();
    var itemBox = activeNav.getBoundingClientRect();
    if (itemBox.bottom > navBox.bottom - 40 || itemBox.top < navBox.top) {
      nav.scrollTop += itemBox.top - navBox.top - navBox.height / 3;
    }
  }

  /* ----------------------------------------------------------- scroll spy */
  var tocLinks = $all('.toc .toc-list a');
  var inlineToc = $('.toc-inline');
  if (tocLinks.length) {
    var targets = tocLinks
      .map(function (link) {
        return document.getElementById(decodeURIComponent(link.getAttribute('href').slice(1)));
      });
    var ticking = false;

    var updateActive = function () {
      ticking = false;
      var offset = Math.min(window.innerHeight * 0.3, 220);
      var activeIndex = -1;
      for (var i = 0; i < targets.length; i++) {
        if (targets[i] && targets[i].getBoundingClientRect().top <= offset) activeIndex = i;
      }
      var atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      if (atBottom) activeIndex = targets.length - 1;
      tocLinks.forEach(function (link, index) {
        link.classList.toggle('is-active', index === activeIndex);
      });
    };

    window.addEventListener('scroll', function () {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(updateActive);
      }
    }, { passive: true });
    updateActive();
  }
  if (inlineToc) {
    $all('a', inlineToc).forEach(function (link) {
      link.addEventListener('click', function () { inlineToc.open = false; });
    });
  }

  var topButton = $('[data-back-to-top]');
  if (topButton) {
    topButton.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      history.replaceState(null, '', location.pathname + location.search);
    });
  }

  /* --------------------------------------------------------------- search */
  var palette = $('[data-palette]');
  var input = palette && $('[data-palette-input]', palette);
  var results = palette && $('[data-palette-results]', palette);
  var index = null;
  var loading = null;
  var items = [];
  var selected = 0;
  var lastFocus = null;
  var ICONS = {};

  $all('template[data-icon]').forEach(function (template) {
    ICONS[template.getAttribute('data-icon')] = template.innerHTML;
  });

  function glyph(name) {
    return ICONS[name] || ICONS['file-text'] || '';
  }

  function loadIndex() {
    if (index) return Promise.resolve(index);
    if (!loading) {
      loading = fetch(BASE + '/_search.json', { credentials: 'same-origin' })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.json();
        })
        .then(function (data) {
          index = prepare(data);
          return index;
        })
        .catch(function (error) {
          loading = null;
          throw error;
        });
    }
    return loading;
  }

  function fold(text) {
    return (text || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  }

  function prepare(data) {
    data.pages.forEach(function (page) {
      page._t = fold(page.t);
      page._c = fold(page.c);
      page._d = fold(page.d);
      page._k = fold(page.k);
    });
    data.sections.forEach(function (section) {
      section._t = fold(section.t);
      section._k = fold(section.k);
      section._x = fold(section.x);
      section._p = data.pages[section.p];
    });
    return data;
  }

  function fieldScore(haystack, token, weight) {
    if (!haystack) return 0;
    var at = haystack.indexOf(token);
    if (at === -1) return 0;
    var wordStart = at === 0 || /[^a-z0-9]/.test(haystack.charAt(at - 1));
    var exact = haystack === token;
    return weight * (exact ? 3 : wordStart ? 1.6 : 1);
  }

  function scoreFields(fields, tokens, phrase) {
    var total = 0;
    for (var i = 0; i < tokens.length; i++) {
      var best = 0;
      for (var j = 0; j < fields.length; j++) {
        var value = fieldScore(fields[j][0], tokens[i], fields[j][1]);
        if (value > best) best = value;
      }
      if (!best) return 0;
      total += best;
    }
    if (tokens.length > 1 && fields[0][0] && fields[0][0].indexOf(phrase) !== -1) total *= 1.5;
    return total;
  }

  function search(query) {
    var phrase = fold(query).trim();
    var tokens = phrase.split(/\s+/).filter(Boolean);
    if (!tokens.length) return [];
    var pages = [];
    var sections = [];
    index.pages.forEach(function (page) {
      var score = scoreFields([[page._t, 10], [page._c, 4], [page._k, 3], [page._d, 2]], tokens, phrase);
      if (score) pages.push({ kind: 'page', score: score, page: page });
    });
    index.sections.forEach(function (section) {
      var score = scoreFields(
        [[section._t, 8], [section._k, 5], [section._p._t, 2.5], [section._x, 2], [section._p._c, 1]],
        tokens,
        phrase
      );
      if (score) sections.push({ kind: 'section', score: score, section: section });
    });
    pages.sort(function (a, b) { return b.score - a.score; });
    sections.sort(function (a, b) { return b.score - a.score; });
    return pages.slice(0, 6).concat(sections.slice(0, 14));
  }

  function mark(text, tokens) {
    var html = escapeHtml(text);
    if (!tokens.length) return html;
    var pattern = tokens
      .map(function (token) { return token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); })
      .filter(Boolean)
      .join('|');
    if (!pattern) return html;
    return html.replace(new RegExp('(' + pattern + ')', 'gi'), '<mark>$1</mark>');
  }

  function suggestions() {
    return index.pages
      .filter(function (page, position) { return position < 6 || /overview$/i.test(page.c); })
      .slice(0, 12)
      .map(function (page) { return { kind: 'page', page: page }; });
  }

  function render(query) {
    if (!index) return;
    var tokens = fold(query).trim().split(/\s+/).filter(Boolean);
    items = tokens.length ? search(query) : suggestions();
    selected = 0;
    if (!items.length) {
      results.innerHTML = '<p class="palette-empty">No results for “' + escapeHtml(query.trim()) +
        '”. Try an endpoint path, a field name or an error code.</p>';
      input.removeAttribute('aria-activedescendant');
      return;
    }
    var html = '';
    var lastGroup = null;
    items.forEach(function (item, position) {
      var group = !tokens.length ? 'Suggested' : item.kind === 'page' ? 'Pages' : 'Sections';
      if (group !== lastGroup) {
        html += '<div class="palette-group" role="presentation">' + group + '</div>';
        lastGroup = group;
      }
      var url;
      var title;
      var meta;
      var snippet = '';
      var iconName;
      if (item.kind === 'page') {
        url = item.page.u;
        title = mark(item.page.t, tokens);
        meta = escapeHtml(item.page.c);
        iconName = item.page.i || 'file-text';
        if (tokens.length && item.page.d) snippet = mark(item.page.d, tokens);
      } else {
        url = item.section._p.u + '#' + item.section.a;
        title = mark(item.section.t, tokens);
        meta = escapeHtml(item.section._p.t + ' · ' + item.section._p.c);
        iconName = 'hash';
        if (item.section.x) snippet = mark(item.section.x, tokens);
      }
      html +=
        '<a class="palette-item" role="option" id="palette-item-' + position + '" data-index="' + position +
        '" href="' + escapeHtml(url) + '" aria-selected="' + (position === selected) + '">' +
        '<span class="palette-item-icon">' + glyph(iconName) + '</span>' +
        '<span class="palette-item-body"><span class="palette-item-title">' + title + '</span>' +
        '<span class="palette-item-meta">' + meta + '</span>' +
        (snippet ? '<span class="palette-item-snippet">' + snippet + '</span>' : '') +
        '</span><span class="palette-enter">' + glyph('corner-down-left') + '</span></a>';
    });
    results.innerHTML = html;
    input.setAttribute('aria-activedescendant', 'palette-item-0');
  }

  function select(position) {
    if (!items.length) return;
    selected = (position + items.length) % items.length;
    $all('.palette-item', results).forEach(function (element) {
      var active = Number(element.getAttribute('data-index')) === selected;
      element.setAttribute('aria-selected', String(active));
      if (active) {
        element.scrollIntoView({ block: 'nearest' });
        input.setAttribute('aria-activedescendant', element.id);
      }
    });
  }

  function openPalette() {
    if (!palette || !palette.hidden) return;
    lastFocus = document.activeElement;
    palette.hidden = false;
    document.documentElement.style.overflow = 'hidden';
    input.value = '';
    input.focus();
    results.innerHTML = '<p class="palette-empty">Loading the search index…</p>';
    loadIndex().then(
      function () { render(input.value); },
      function () {
        results.innerHTML = '<p class="palette-empty">Search is unavailable right now. Reload the page and try again.</p>';
      }
    );
  }

  function closePalette() {
    if (!palette || palette.hidden) return;
    palette.hidden = true;
    document.documentElement.style.overflow = '';
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (palette) {
    $all('[data-search-open]').forEach(function (button) {
      button.addEventListener('click', openPalette);
    });
    palette.addEventListener('mousedown', function (event) {
      if (event.target === palette) closePalette();
    });
    input.addEventListener('input', function () { render(input.value); });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        select(selected + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        select(selected - 1);
      } else if (event.key === 'Enter') {
        var active = $('.palette-item[aria-selected="true"]', results);
        if (!active) return;
        event.preventDefault();
        if (event.metaKey || event.ctrlKey) window.open(active.href, '_blank');
        else {
          closePalette();
          location.href = active.href;
        }
      } else if (event.key === 'Tab') {
        event.preventDefault();
        select(selected + (event.shiftKey ? -1 : 1));
      }
    });
    results.addEventListener('mousemove', function (event) {
      var item = event.target.closest('.palette-item');
      if (item && Number(item.getAttribute('data-index')) !== selected) {
        select(Number(item.getAttribute('data-index')));
      }
    });
    results.addEventListener('click', function (event) {
      if (event.target.closest('.palette-item') && !(event.metaKey || event.ctrlKey)) closePalette();
    });
    // Warm the index after the page settles so the first search feels instant.
    if ('requestIdleCallback' in window) {
      window.requestIdleCallback(function () { loadIndex().catch(function () {}); });
    }
  }

  $all('[data-shortcut]').forEach(function (element) {
    element.textContent = isMac ? '⌘K' : 'Ctrl K';
  });

  document.addEventListener('keydown', function (event) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (palette && palette.hidden) openPalette();
      else closePalette();
    } else if (event.key === '/' && !typing && palette && palette.hidden) {
      event.preventDefault();
      openPalette();
    } else if (event.key === 'Escape') {
      if (palette && !palette.hidden) closePalette();
      else if (sidebar && sidebar.classList.contains('is-open')) {
        setDrawer(false);
        menuButton.focus();
      }
    }
  });
})();
