/* Card Console front end -- read-only bench dashboard. */

const $ = (id) => document.getElementById(id);

async function getJSON(url, options) {
  const res = await fetch(url, Object.assign({ cache: 'no-store' }, options || {}));
  return res.json();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function deviceRow(primary, secondary, kind) {
  const row = el('div', 'row');
  if (kind) row.appendChild(el('span', 'tag ' + kind, kind));
  row.appendChild(el('div', 'row-main', primary));
  if (secondary) row.appendChild(el('div', 'row-sub', secondary));
  return row;
}

function setDot(state) {
  $('dot').className = 'dot ' + state;
}

async function loadEnvironment() {
  try {
    const env = await getJSON('/api/environment');
    $('env').textContent = `${env.platform} \u00b7 py ${env.python_version} \u00b7 ${env.host}:${env.port}`;
    setDot('ok');
  } catch (err) {
    $('env').textContent = 'server unreachable';
    setDot('bad');
  }
}

function renderChameleon(devices) {
  const box = $('chameleon');
  box.replaceChildren();
  const info = devices && devices.chameleon;
  $('chameleon-state').textContent = info ? '\u00b7 detected' : '\u00b7 not detected';
  if (!info) {
    box.appendChild(deviceRow('Not detected', 'Plug the Chameleon Ultra in, then Refresh.'));
    return;
  }
  const tag = el('span', 'tag chameleon', 'chameleon');
  const head = el('div', 'row');
  head.appendChild(tag);
  head.appendChild(el('div', 'row-main', info.model || 'Chameleon Ultra'));
  head.appendChild(el('div', 'row-sub', `port ${info.port || '\u2014'}  \u00b7  ${info.raw || ''}`));
  box.appendChild(head);

  const meta = el('div', 'row');
  meta.appendChild(el('div', 'row-main', `hardware ${info.hardware ? 'v' + info.hardware : 'unknown'}`));
  meta.appendChild(el('div', 'row-sub', `firmware ${info.firmware ? 'v' + info.firmware : 'unknown'}`));
  box.appendChild(meta);
}

async function loadDevices() {
  const box = $('devices');
  box.replaceChildren();
  try {
    const { devices } = await getJSON('/api/devices');
    $('devices-source').textContent = devices.source ? `(${devices.source})` : '';
    renderChameleon(devices);

    const serial = devices.serial || [];
    if (!serial.length) {
      box.appendChild(deviceRow('No serial devices detected', 'Plug in a board or reader, then Refresh.'));
    }
    for (const d of serial) {
      const cls = d.classification || {};
      const primary = cls.label || d.description || d.port || 'serial device';
      const parts = [
        d.port,
        d.bus_reported_desc,
        d.description && d.description !== primary ? d.description : null,
        d.manufacturer,
        d.vid ? `VID:${d.vid}` : null,
        d.pid ? `PID:${d.pid}` : null,
      ].filter(Boolean);
      box.appendChild(deviceRow(primary, parts.join('  \u00b7  '), cls.kind));
    }

    const usb = (devices.usb || []).filter((u) => u.classification);
    if (usb.length) {
      const details = el('details');
      details.appendChild(el('summary', null, `${usb.length} recognised USB device(s)`));
      for (const u of usb) {
        const parts = [u.bus_reported_desc, u.vid ? `VID:${u.vid}` : null, u.pid ? `PID:${u.pid}` : null].filter(Boolean);
        details.appendChild(deviceRow(u.classification.label || u.name, parts.join('  \u00b7  '), u.classification.kind));
      }
      box.appendChild(details);
    }
  } catch (err) {
    box.appendChild(deviceRow('Device scan failed', String(err)));
    renderChameleon(null);
  }
}

async function loadReaders() {
  const box = $('reader');
  box.replaceChildren();
  try {
    const info = await getJSON('/api/readers');
    if (!info.available) {
      box.appendChild(deviceRow('PC/SC unavailable', info.reason || 'install pyscard'));
    } else if (!info.readers.length) {
      box.appendChild(deviceRow('No PC/SC readers present', 'Connect a reader and present a card.'));
    } else {
      for (const name of info.readers) box.appendChild(deviceRow(name, 'PC/SC reader', 'pcsc-reader'));
    }
  } catch (err) {
    box.appendChild(deviceRow('Reader probe failed', String(err)));
  }
}

async function loadTools() {
  const tbody = document.querySelector('#tools tbody');
  tbody.replaceChildren();
  try {
    const { tools } = await getJSON('/api/tools');
    for (const t of tools) {
      const tr = el('tr');
      tr.appendChild(el('td', null, t.name));
      tr.appendChild(el('td', 'muted', t.role));
      const stateCell = el('td');
      stateCell.appendChild(el('span', t.present ? 'ok' : 'miss', t.present ? 'present' : 'missing'));
      tr.appendChild(stateCell);
      tr.appendChild(el('td', 'muted', t.version || '\u2014'));
      tr.title = t.path || '';
      tbody.appendChild(tr);
    }
  } catch (err) {
    const tr = el('tr');
    tr.appendChild(el('td', 'miss', 'tool probe failed'));
    tbody.appendChild(tr);
  }
}

async function scan() {
  const out = $('scan-out');
  out.textContent = 'reading\u2026';
  try {
    const result = await getJSON('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reader_index: 0 }),
    });
    out.textContent = JSON.stringify(result, null, 2);
  } catch (err) {
    out.textContent = String(err);
  }
}

function refreshAll() {
  loadEnvironment();
  loadDevices();
  loadReaders();
  loadTools();
}

$('refresh').addEventListener('click', refreshAll);
$('scan').addEventListener('click', scan);

refreshAll();
setInterval(refreshAll, 8000);
