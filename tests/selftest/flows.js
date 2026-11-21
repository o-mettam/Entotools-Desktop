/* Real-window flow test (tests/selftest/run_window_flows.py). Runs inside the
   app window only when ENTOTOOLS_SELFTEST=1; each page does its part and
   reports through /api/client-log (level "flow"). */
(function () {
  'use strict';
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  function flow(step, data) {
    return fetch('/api/client-log', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: 'flow', page: location.pathname, message: JSON.stringify(Object.assign({ step: step }, data)) }) });
  }
  async function waitFor(fn, ms) {
    for (var t = 0; t < ms; t += 250) { try { if (fn()) return true; } catch (e) { /* keep waiting */ } await sleep(250); }
    return false;
  }
  async function kv() { return (await (await fetch('/api/kv')).json()).items; }

  var pages = {
    '/degree-day-calculator/': async function () {
      restoreSearchState({ tab: 'latlon', city: '', state: '', country: '', lat: '38.9072', lon: '-77.0369',
        dateRanges: [{ label: 'Selftest 2025', startDate: '2025-03-01', endDate: '2025-06-30', useToday: false }],
        gddBase: '50', gddMax: '86', gddMonth: '03', gddDay: '1', gddThresholds: [], dateMarkers: [],
        includeTempForecast: true, includeGddForecast: true, stationId: '' });
      doSearch();
      var shown = await waitFor(function () { return !document.getElementById('results').classList.contains('hidden') && document.querySelectorAll('#results canvas').length > 0; }, 45000);
      await sleep(500);
      var items = await kv();
      await flow('search', { resultsShown: shown, canvases: document.querySelectorAll('#results canvas').length,
        resultCacheSaved: !!items.ento_result_cache, error: (document.getElementById('error-message') || {}).textContent || '' });

      promptSaveSearch();
      var dialog = await waitFor(function () { return document.querySelector('.ento-d-dialog input'); }, 3000);
      var input = document.querySelector('.ento-d-dialog input');
      if (input) { input.value = 'Selftest DC'; document.querySelector('.ento-d-dialog').requestSubmit(); }
      await sleep(600);
      items = await kv();
      await flow('save-search', { dialogShown: dialog, saved: (items.ento_saved_searches || '').indexOf('Selftest DC') >= 0 });

      var before = document.documentElement.classList.contains('dark');
      toggleTheme();
      await sleep(300);
      items = await kv();
      await flow('theme', { toggled: document.documentElement.classList.contains('dark') !== before, darkNow: document.documentElement.classList.contains('dark'), storedKeys: Object.keys(items) });
    },

    '/sample-collection/': async function () {
      await flow('theme-persisted', { dark: document.documentElement.classList.contains('dark') });
      var sheet = EntoStore.load();
      sheet.push({ data: { siteName: 'Selftest site', dateStart: '2025-06-14', dateEnd: '2025-06-14', isRange: false,
        lat: 35.8301, lon: -78.7639, inputMode: 'latlon', location: 'Raleigh, NC', collector: 'Selftest', specimenId: 'ST-1',
        identification: 'Photinus pyralis', gddStart: 1234.5, gddEnd: 1234.5, humidity: { atTime: 71, avg: 64 } } });
      EntoStore.saveActiveList(sheet);
      var col = await (await fetch('/api/collection')).json();
      await flow('add-to-collection', { entries: col.json ? col.json.entries.length : 0 });
      await EntoDesktop.saveBlob(new Blob(['a,b\n1,2\n'], { type: 'text/csv' }), 'selftest-label.csv');
      await flow('save-blob', {});
    },

    '/collection-database/': async function () {
      await sleep(500);
      await flow('table', { rows: document.querySelectorAll('#table-body tr').length });
      // A website export: guarded negative longitude (finding F9) must survive.
      var csv = '﻿"Specimen ID","Site Name","Latitude","Longitude","Date Start","Coordinates Estimated"\n"ST-2","Web export site","38.9","\'-77.03","2025-07-01","No"\n';
      var r = await EntoDesktop.importFile(new File([csv], 'web-export.csv', { type: 'text/csv' }));
      renderTable();
      await flow('import', { result: r, rows: document.querySelectorAll('#table-body tr').length });
      await EntoDesktop.saveCollectionCsv('selftest-collection.csv', 'full');
      await flow('export', {});
      await toggleCollectionMap();
      var tiles = await waitFor(function () { return document.querySelectorAll('#collection-map img.leaflet-tile-loaded').length > 0; }, 15000);
      await flow('map', { leaflet: typeof L, tilesLoaded: document.querySelectorAll('#collection-map img.leaflet-tile-loaded').length, ok: tiles });
    },
  };
  var run = pages[location.pathname];
  if (run) setTimeout(function () { run().catch(function (e) { flow('exception', { error: String(e && e.stack || e) }); }); }, 800);
})();
