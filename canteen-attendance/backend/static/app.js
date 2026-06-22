/*
  app.js
  ------
  Vanilla JS, no build step, no framework. This app is small enough
  that React/Vue would add ceremony without adding value — and a
  zero-dependency frontend is also one less thing that can break on
  a canteen PC that might not get regular maintenance.

  Polling, not WebSockets: the live feed polls /api/attendance/recent-events
  every 3 seconds. For a single local kiosk with a handful of scans per
  day, this is simpler and more robust than maintaining a socket
  connection, at a negligible cost in "real-time-ness."
*/

const POLL_INTERVAL_MS = 3000;

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------
// Device status
// ---------------------------------------------------------------------

async function refreshDeviceStatus() {
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  try {
    const status = await fetchJSON('/api/device/status');
    if (status.connected) {
      dot.className = 'status-dot online';
      text.textContent = 'Sensor connected';
    } else {
      dot.className = 'status-dot offline';
      text.textContent = 'Sensor not connected';
    }
  } catch {
    dot.className = 'status-dot offline';
    text.textContent = 'Server unreachable';
  }
}

// ---------------------------------------------------------------------
// Today panel
// ---------------------------------------------------------------------

function formatTime(isoString) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function statusFor(row) {
  if (row.time_in && !row.time_out) return { label: 'Present', cls: 'present' };
  if (row.time_in && row.time_out) return { label: 'Done for the day', cls: 'done' };
  return { label: 'Not in yet', cls: 'absent' };
}

async function refreshToday() {
  const tbody = document.getElementById('todayTableBody');
  try {
    const rows = await fetchJSON('/api/attendance/today');
    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-row">No employees enrolled yet. Add one below.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map(row => {
      const status = statusFor(row);
      return `
        <tr data-employee-id="${row.employee_id}" data-employee-name="${escapeHtml(row.full_name)}">
          <td class="employee-name">${escapeHtml(row.full_name)}</td>
          <td>${escapeHtml(row.role || '—')}</td>
          <td>${formatTime(row.time_in)}</td>
          <td>${formatTime(row.time_out)}</td>
          <td><span class="status-pill ${status.cls}">${status.label}</span></td>
        </tr>
      `;
    }).join('');

    tbody.querySelectorAll('tr[data-employee-id]').forEach(tr => {
      tr.addEventListener('click', () => {
        openHistory(tr.dataset.employeeId, tr.dataset.employeeName);
      });
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-row">Couldn't load attendance: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function setTodayDate() {
  const el = document.getElementById('todayDate');
  const today = new Date();
  el.textContent = today.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
}

// ---------------------------------------------------------------------
// Live feed
// ---------------------------------------------------------------------

function feedEntryHTML(event) {
  const time = formatTime(event.timestamp);
  if (event.type === 'ATTENDANCE_LOGGED') {
    const cls = event.event_type === 'IN' ? 'event-in' : 'event-out';
    const verb = event.event_type === 'IN' ? 'checked in' : 'checked out';
    return `<li class="${cls}">${escapeHtml(event.full_name)} ${verb}<span class="feed-time">${time}</span></li>`;
  }
  if (event.type === 'UNKNOWN_FINGERPRINT') {
    return `<li class="event-unknown">Unrecognized fingerprint scanned<span class="feed-time">${time}</span></li>`;
  }
  if (event.type === 'NO_MATCH') {
    return `<li class="event-unknown">Scan not recognized — try again<span class="feed-time">${time}</span></li>`;
  }
  return null; // DEVICE_MESSAGE entries are handled by the enrollment flow, not the feed
}

async function pollFeed() {
  try {
    const events = await fetchJSON('/api/attendance/recent-events');
    const relevant = events.map(feedEntryHTML).filter(Boolean);
    if (relevant.length > 0) {
      const list = document.getElementById('feedList');
      const emptyState = list.querySelector('.feed-empty');
      if (emptyState) emptyState.remove();
      list.insertAdjacentHTML('afterbegin', relevant.reverse().join(''));

      // Cap the visible feed so it doesn't grow unbounded over a long day
      while (list.children.length > 40) {
        list.removeChild(list.lastChild);
      }

      // An attendance event means today's table is stale — refresh it.
      refreshToday();
    }
  } catch {
    // Silently skip — the device status indicator already communicates
    // connectivity problems; no need to also spam the feed with errors.
  }
}

// ---------------------------------------------------------------------
// Roster
// ---------------------------------------------------------------------

async function refreshRoster() {
  const list = document.getElementById('rosterList');
  const count = document.getElementById('rosterCount');
  try {
    const employees = await fetchJSON('/api/employees');
    count.textContent = `${employees.length} enrolled`;
    if (employees.length === 0) {
      list.innerHTML = `<li class="empty-row">No employees yet.</li>`;
      return;
    }
    list.innerHTML = employees.map(emp => `
      <li>
        <span>${escapeHtml(emp.full_name)}</span>
        <span class="roster-role">${escapeHtml(emp.role || '')}</span>
      </li>
    `).join('');
  } catch (err) {
    list.innerHTML = `<li class="empty-row">Couldn't load employees.</li>`;
  }
}

// ---------------------------------------------------------------------
// Enrollment
// ---------------------------------------------------------------------

document.getElementById('enrollForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const nameInput = document.getElementById('enrollName');
  const roleInput = document.getElementById('enrollRole');
  const submitBtn = document.getElementById('enrollSubmit');
  const statusEl = document.getElementById('enrollStatus');

  const full_name = nameInput.value.trim();
  if (!full_name) return;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Place finger on sensor…';
  statusEl.textContent = 'Ask the employee to place their finger on the sensor when prompted, then lift and place it again.';
  statusEl.className = 'enroll-status';

  try {
    const result = await fetchJSON('/api/employees/enroll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_name, role: roleInput.value.trim() }),
    });

    statusEl.textContent = `${full_name} enrolled successfully.`;
    statusEl.className = 'enroll-status success';
    nameInput.value = '';
    roleInput.value = '';
    refreshRoster();
    refreshToday();
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = 'enroll-status error';
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Start enrollment';
  }
});

// ---------------------------------------------------------------------
// History view
// ---------------------------------------------------------------------

async function openHistory(employeeId, employeeName) {
  document.querySelector('.today-panel').hidden = true;
  document.querySelector('.enroll-panel').hidden = true;
  document.querySelector('.roster-panel').hidden = true;

  const panel = document.getElementById('historyPanel');
  const list = document.getElementById('historyList');
  document.getElementById('historyName').textContent = `History — ${employeeName}`;
  panel.hidden = false;
  list.innerHTML = `<li class="empty-row">Loading…</li>`;

  try {
    const logs = await fetchJSON(`/api/attendance/logs?employee_id=${employeeId}`);
    if (logs.length === 0) {
      list.innerHTML = `<li class="empty-row">No attendance history yet.</li>`;
      return;
    }
    list.innerHTML = logs.map(log => {
      const d = new Date(log.timestamp);
      const dateStr = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const verb = log.event_type === 'IN' ? 'Checked in' : 'Checked out';
      return `<li><span class="h-date">${dateStr}</span><span>${verb} at ${timeStr}</span></li>`;
    }).join('');
  } catch (err) {
    list.innerHTML = `<li class="empty-row">Couldn't load history.</li>`;
  }
}

document.getElementById('closeHistory').addEventListener('click', () => {
  document.getElementById('historyPanel').hidden = true;
  document.querySelector('.today-panel').hidden = false;
  document.querySelector('.enroll-panel').hidden = false;
  document.querySelector('.roster-panel').hidden = false;
});

// ---------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------

setTodayDate();
refreshDeviceStatus();
refreshToday();
refreshRoster();

setInterval(refreshDeviceStatus, POLL_INTERVAL_MS);
setInterval(pollFeed, POLL_INTERVAL_MS);
