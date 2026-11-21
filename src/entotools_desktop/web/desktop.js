/* EntoTools desktop bridge — loaded FIRST on every page (before theme.js).
 *
 * The pages come from the website (tools/import_web.py). This file supplies
 * what the website got from the browser or from its account/Drive scripts:
 *
 *   EntoKV       stand-in for localStorage, stored in the app's database.
 *                The collection key (entoLabelSheetV2) is routed to the
 *                collection table, so backups and imports see every change.
 *                Writes are synchronous so nothing is lost when a page
 *                navigates away straight after saving.
 *   EntoFlags    the three always-on features (D3), announced with the same
 *                `entoflags:updated` event account.js used to fire.
 *   EntoDesktop  Save As… for exports, an in-page prompt(), toasts, import,
 *                and the Settings → "Data & backups" section.
 * Plus: outside links open in the user's browser, and an offline banner.
 */
(function () {
  'use strict';

  var COLLECTION_KEY = 'entoLabelSheetV2';

  function request(method, url, body) {
    var x = new XMLHttpRequest();
    x.open(method, url, false); // synchronous on purpose (see above); the server is local
    if (body !== undefined) x.setRequestHeader('Content-Type', 'application/json');
    x.send(body === undefined ? null : JSON.stringify(body));
    var data = null;
    try { data = JSON.parse(x.responseText); } catch (e) { /* not JSON */ }
    if (x.status < 200 || x.status >= 300) {
      var err = new Error((data && data.error) || ('HTTP ' + x.status));
      err.status = x.status;
      throw err;
    }
    return data;
  }

  function api(method, url, body) {
    return fetch(url, {
      method: method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
        return d;
      });
    });
  }

  // ── Page errors → the app's local log ────────────────────────────
  // Uncaught errors, failed promises, console.error and anything the
  // Content-Security-Policy blocks are sent to the app (POST /api/client-log),
  // which writes them to its log file for troubleshooting. Capped per page.
  var reported = 0;
  function report(level, message, source) {
    if (reported++ >= 50) return;
    try {
      fetch('/api/client-log', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: level, page: location.pathname, message: String(message).slice(0, 500), source: source || '' }) })
        .catch(function () { /* app closing */ });
    } catch (e) { /* never break the page over logging */ }
  }
  window.addEventListener('error', function (e) {
    report('error', e.message, (e.filename || '') + ':' + (e.lineno || 0));
  });
  window.addEventListener('unhandledrejection', function (e) {
    report('error', 'Unhandled rejection: ' + (e.reason && e.reason.message || e.reason), '');
  });
  document.addEventListener('securitypolicyviolation', function (e) {
    report('csp', 'blocked ' + e.violatedDirective + ' ' + (e.blockedURI || '(inline)'), (e.sourceFile || '') + ':' + (e.lineNumber || 0));
  });
  var origError = console.error;
  console.error = function () {
    var parts = Array.prototype.map.call(arguments, function (a) {
      if (a && a.message) return a.message;
      try { return typeof a === 'string' ? a : JSON.stringify(a); } catch (err) { return String(a); }
    });
    report('console', parts.join(' '), '');
    return origError.apply(console, arguments);
  };

  // ── Boot: everything the page needs, in one request ─────────────
  var boot = { version: 'desktop', flags: [], kv: {}, collection: null, backup: null };
  try { boot = request('GET', '/api/boot'); }
  catch (e) { console.error('[EntoDesktop] could not load saved data:', e.message); }
  window.ENTO_DESKTOP_VERSION = boot.version;

  // ── EntoKV ──────────────────────────────────────────────────────
  var items = {};
  function absorb(b) {
    items = Object.assign({}, b.kv || {});
    if (b.collection) items[COLLECTION_KEY] = JSON.stringify(b.collection);
  }
  absorb(boot);

  var EntoKV = {
    getItem: function (k) {
      k = String(k);
      return Object.prototype.hasOwnProperty.call(items, k) ? items[k] : null;
    },
    setItem: function (k, v) {
      k = String(k); v = String(v);
      try {
        if (k === COLLECTION_KEY) request('PUT', '/api/collection', JSON.parse(v));
        else request('PUT', '/api/kv/' + encodeURIComponent(k), { value: v });
      } catch (e) {
        console.error('[EntoDesktop] save failed for', k, '-', e.message);
        if (k === COLLECTION_KEY) toast('Your collection could not be saved: ' + e.message, 'error', 10000);
        throw e;
      }
      items[k] = v;
    },
    removeItem: function (k) {
      k = String(k);
      if (k === COLLECTION_KEY) return; // never deleted wholesale; entries carry tombstones
      try { request('DELETE', '/api/kv/' + encodeURIComponent(k)); }
      catch (e) { console.error('[EntoDesktop] remove failed for', k, '-', e.message); }
      delete items[k];
    },
    key: function (i) { var ks = Object.keys(items); return i < ks.length ? ks[i] : null; },
    get length() { return Object.keys(items).length; },
    keys: function () { return Object.keys(items); },
    reload: function () { absorb(request('GET', '/api/boot')); },
  };
  window.EntoKV = EntoKV;

  // ── Feature flags ───────────────────────────────────────────────
  window.EntoFlags = new Set(boot.flags || []);
  document.addEventListener('DOMContentLoaded', function () {
    document.dispatchEvent(new CustomEvent('entoflags:updated'));
  });

  // ── Toasts ──────────────────────────────────────────────────────
  function toast(message, kind, ms) {
    var show = function () {
      var host = document.getElementById('ento-d-toasts');
      if (!host) {
        host = document.createElement('div');
        host.id = 'ento-d-toasts';
        host.setAttribute('role', 'status');
        host.setAttribute('aria-live', 'polite');
        document.body.appendChild(host);
      }
      var t = document.createElement('div');
      t.className = 'ento-d-toast' + (kind === 'error' ? ' ento-d-toast-error' : '');
      t.textContent = message;
      host.appendChild(t);
      setTimeout(function () { t.remove(); }, ms || 4000);
    };
    if (document.body) show(); else document.addEventListener('DOMContentLoaded', show);
  }

  // ── In-page prompt() replacement ───────────────────────────────
  function promptDialog(message, defaultValue) {
    return new Promise(function (resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'ento-d-overlay';
      var box = document.createElement('form');
      box.className = 'ento-d-dialog';
      box.setAttribute('role', 'dialog');
      box.setAttribute('aria-modal', 'true');
      var label = document.createElement('label');
      label.className = 'ento-d-dialog-label';
      label.textContent = message;
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'ento-d-input';
      input.value = defaultValue || '';
      input.maxLength = 200;
      label.appendChild(input);
      var row = document.createElement('div');
      row.className = 'ento-d-dialog-buttons';
      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'ento-d-btn';
      cancel.textContent = 'Cancel';
      var ok = document.createElement('button');
      ok.type = 'submit';
      ok.className = 'ento-d-btn ento-d-btn-primary';
      ok.textContent = 'OK';
      row.appendChild(cancel);
      row.appendChild(ok);
      box.appendChild(label);
      box.appendChild(row);
      overlay.appendChild(box);
      document.body.appendChild(overlay);
      input.focus();
      input.select();
      function done(value) { overlay.remove(); resolve(value); }
      box.addEventListener('submit', function (e) { e.preventDefault(); done(input.value); });
      cancel.addEventListener('click', function () { done(null); });
      overlay.addEventListener('keydown', function (e) { if (e.key === 'Escape') done(null); });
    });
  }

  // ── Save As… ────────────────────────────────────────────────────
  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result).split(',')[1] || ''); };
      r.onerror = function () { reject(r.error); };
      r.readAsDataURL(blob);
    });
  }

  function reportSave(result) {
    if (result && result.saved) toast('Saved to ' + result.path);
    return result;
  }

  function saveBlob(blob, filename) {
    return blobToBase64(blob)
      .then(function (b64) { return api('POST', '/api/save', { filename: filename, data_b64: b64 }); })
      .then(reportSave)
      .catch(function (e) { toast('Could not save the file: ' + e.message, 'error', 8000); });
  }

  function saveCollectionCsv(filename, layout) {
    return api('POST', '/api/save', { filename: filename, collection_layout: layout || 'full' })
      .then(reportSave)
      .catch(function (e) { toast('Could not save the file: ' + e.message, 'error', 8000); });
  }

  // ── PDF labels / field notes (Phase 4) ─────────────────────────
  // which: both | label1 | label2 | notes. Opens the PDF in the system's PDF
  // viewer (print or save from there); saveLabelsPdf shows Save As instead.
  function printLabels(items, which) {
    return api('POST', '/api/labels/pdf', { items: items, which: which || 'both', action: 'open' })
      .then(function (r) { toast('Opened the PDF \u2014 print it from your PDF viewer.'); return r; })
      .catch(function (e) { toast('Could not create the PDF: ' + e.message, 'error', 8000); });
  }
  function saveLabelsPdf(items, which, filename) {
    return api('POST', '/api/labels/pdf', { items: items, which: which || 'both', action: 'save', filename: filename })
      .then(reportSave)
      .catch(function (e) { toast('Could not save the PDF: ' + e.message, 'error', 8000); });
  }

  // ── Import (CSV or JSON, desktop or website exports) ───────────
  function importFile(file) {
    var kind = /\.json$/i.test(file.name) ? 'json' : 'csv';
    return file.text().then(function (text) {
      return api('POST', '/api/collection/import', { kind: kind, text: text });
    }).then(function (result) {
      EntoKV.reload();
      return result;
    });
  }

  // ── Outside links open in the user's browser ──────────────────
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    var url;
    try { url = new URL(a.getAttribute('href'), location.href); } catch (err) { return; }
    if (url.origin === location.origin) return;
    e.preventDefault();
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      api('POST', '/api/open-url', { url: url.href }).catch(function (err) { toast('Could not open the link: ' + err.message, 'error'); });
    }
  }, true);

  // ── Offline banner ──────────────────────────────────────────────
  var offlineShown = false;
  function setOffline(off) {
    if (off === offlineShown) return;
    offlineShown = off;
    var bar = document.getElementById('ento-d-offline');
    if (off && !bar) {
      bar = document.createElement('div');
      bar.id = 'ento-d-offline';
      bar.setAttribute('role', 'status');
      bar.textContent = 'You’re offline. Weather lookups are unavailable; your collection, labels, CSV backups and PDF printing still work.';
      document.body.prepend(bar);
    } else if (!off && bar) {
      bar.remove();
    }
  }
  function checkOnline() {
    api('GET', '/api/connectivity').then(function (d) { setOffline(!d.online); }).catch(function () { /* server busy */ });
  }

  // ── Settings → "Data & backups" ────────────────────────────────
  function fmtWhen(iso) {
    if (!iso) return 'never';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function renderBackupSection(panel, settings) {
    var section = document.getElementById('ento-d-backups') || el('div', 'ento-d-section');
    section.id = 'ento-d-backups';
    section.textContent = '';
    section.appendChild(el('div', 'ento-d-section-title', 'Data & backups'));
    section.appendChild(el('p', 'ento-d-note',
      settings.auto ? 'A CSV backup is saved automatically after each change.' : 'Automatic backups are off.'));
    var where = el('p', 'ento-d-note ento-d-path', settings.dir);
    where.title = settings.dir;
    section.appendChild(where);
    section.appendChild(el('p', 'ento-d-note', 'Last backup: ' + fmtWhen(settings.last_backup_at)));

    var row = el('div', 'ento-d-row');
    function button(label, onClick) {
      var b = el('button', 'ento-d-btn ento-d-btn-small', label);
      b.type = 'button';
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        b.disabled = true;
        Promise.resolve(onClick()).finally(function () { b.disabled = false; });
      });
      row.appendChild(b);
      return b;
    }
    button('Back up now', function () {
      return api('POST', '/api/backup/now').then(function (r) { toast('Backup saved: ' + r.file); refreshBackups(panel); })
        .catch(function (e) { toast('Backup failed: ' + e.message, 'error', 8000); });
    });
    button('Change folder…', function () {
      return api('POST', '/api/backup/choose-folder').then(function (r) { if (r.changed) toast('Backups will be saved in ' + r.dir); renderBackupSection(panel, r); })
        .catch(function (e) { toast(e.message, 'error'); });
    });
    button('Open folder', function () {
      return api('POST', '/api/backup/open-folder').catch(function (e) { toast(e.message, 'error'); });
    });
    section.appendChild(row);

    var auto = el('label', 'ento-d-check');
    var box = el('input');
    box.type = 'checkbox';
    box.checked = !!settings.auto;
    box.addEventListener('change', function (e) {
      e.stopPropagation();
      api('PUT', '/api/backup', { auto: box.checked }).then(function (r) { renderBackupSection(panel, r); })
        .catch(function (err) { toast(err.message, 'error'); });
    });
    auto.appendChild(box);
    auto.appendChild(document.createTextNode(' Back up automatically (keeps the newest ' + settings.keep + ')'));
    section.appendChild(auto);
    section.appendChild(el('p', 'ento-d-note ento-d-version', 'EntoTools desktop ' + (boot.version || '')));
    if (!section.parentNode) panel.appendChild(section);
  }

  function refreshBackups(panel) {
    api('GET', '/api/backup').then(function (s) { renderBackupSection(panel, s); }).catch(function () { /* ignore */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var panel = document.getElementById('settings-panel');
    if (panel && boot.backup) renderBackupSection(panel, boot.backup);
    if (panel) document.getElementById('settings-btn') && document.getElementById('settings-btn')
      .addEventListener('click', function () { refreshBackups(panel); });
    checkOnline();
    setInterval(checkOnline, 60000);
    if (boot.selftest) {
      // Test harness only (ENTOTOOLS_SELFTEST=1): run the flow script, if any.
      var st = document.createElement('script');
      st.src = '/api/selftest.js';
      document.body.appendChild(st);
      // …and describe this page's state.
      setTimeout(function () {
        var map = document.getElementById('collection-map-section');
        report('selftest', JSON.stringify({
          title: document.title,
          kv: typeof window.EntoKV,
          flags: Array.from(window.EntoFlags || []),
          backups: !!document.getElementById('ento-d-backups'),
          font: getComputedStyle(document.body).fontFamily.slice(0, 40),
          fontLoaded: document.fonts ? document.fonts.check('16px Inter') : null,
          mapHidden: map ? map.classList.contains('hidden') : null,
          charts: typeof window.Chart,
          version: (document.getElementById('app-version') || document.querySelector('footer') || {}).textContent ? 'footer-ok' : 'no-footer',
        }));
      }, 1200);
    }
    window.addEventListener('online', checkOnline);
    window.addEventListener('offline', function () { setOffline(true); });
  });

  window.EntoDesktop = {
    version: boot.version,
    prompt: promptDialog,
    toast: toast,
    saveBlob: saveBlob,
    saveCollectionCsv: saveCollectionCsv,
    importFile: importFile,
    printLabels: printLabels,
    saveLabelsPdf: saveLabelsPdf,
    api: api,
  };
})();
