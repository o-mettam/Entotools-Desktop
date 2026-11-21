fetch('/api/status/ping').then(r => r.json()).then(d => {
  document.getElementById('status').textContent = d.ok ? 'ok' : 'not responding';
}).catch(() => { document.getElementById('status').textContent = 'not responding'; });
