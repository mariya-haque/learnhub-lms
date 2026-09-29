/* ==========================================================================
   LearnHub — shared UI layer
   Toasts, modals, the confirm dialog, the API helper and the nav shell.
   Loaded on every page; feature scripts build on top of it.
   ========================================================================== */

/* ---------------------------------- Icons -------------------------------- */

const SVG = (path, size = 16) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;

const ICONS = {
  success: SVG('<path d="M20 6 9 17l-5-5"/>'),
  error: SVG('<path d="M18 6 6 18M6 6l12 12"/>'),
  warning: SVG('<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'),
  info: SVG('<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>'),
};

/** Reference the shared sprite in `_icons.html`. */
function icon(name, size = 16, className = 'icon') {
  return `<svg width="${size}" height="${size}" class="${className}" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><use href="#i-${name}"/></svg>`;
}

/* --------------------------------- Helpers ------------------------------- */

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function formatDate(dateStr) {
  if (!dateStr) return '--';
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

/** Seconds to mm:ss, or h:mm:ss past an hour. Used by the quiz timer. */
function formatClock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${unit === 0 ? size : size.toFixed(1)} ${units[unit]}`;
}

/** Show a spinner inside a button while an async action runs. */
function setLoading(btn, loading) {
  if (!btn) return;
  btn.classList.toggle('is-loading', loading);
  btn.disabled = loading;
}

function debounce(fn, wait = 400) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

/* ----------------------------------- API --------------------------------- */

/**
 * fetch() wrapper that turns every failure into a thrown Error with a usable
 * message. A 401 means the session died, and since fetch follows the 307 to
 * /login transparently, the server sends JSON 401s on /api routes instead --
 * this is where that contract is cashed in.
 */
async function api(url, options = {}) {
  const config = { headers: { Accept: 'application/json' }, ...options };

  if (config.body && !(config.body instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
    if (typeof config.body !== 'string') config.body = JSON.stringify(config.body);
  }

  let response;
  try {
    response = await fetch(url, config);
  } catch {
    throw new Error('Network error. Check your connection and try again.');
  }

  if (response.status === 401) {
    showToast('Your session expired. Redirecting to sign in...', 'error');
    setTimeout(() => { window.location.href = '/login'; }, 1400);
    throw new Error('Session expired');
  }

  let data = null;
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) {
    data = await response.json().catch(() => null);
  }

  if (!response.ok) {
    const message = (data && (data.message || data.detail)) || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

/* --------------------------------- Toasts -------------------------------- */

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.innerHTML = `<span class="toast-icon">${ICONS[type] || ICONS.success}</span><div>${escapeHtml(message)}</div>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 260);
  }, 3400);
}

/* --------------------------------- Modals -------------------------------- */

let lastFocused = null;

function showModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  lastFocused = document.activeElement;
  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
  const field = modal.querySelector('input:not([type="hidden"]):not([disabled]), select, textarea');
  if (field) setTimeout(() => field.focus(), 120);
}

function hideModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove('active');
  if (!document.querySelector('.modal-overlay.active')) document.body.style.overflow = '';
  if (lastFocused && lastFocused.focus) lastFocused.focus();
}

function closeAllModals() {
  document.querySelectorAll('.modal-overlay.active').forEach((m) => m.classList.remove('active'));
  document.body.style.overflow = '';
}

/**
 * Promise-based replacement for window.confirm, styled like the rest of the
 * app. Resolves true when the user accepts.
 */
function confirmAction({
  title = 'Are you sure?',
  message = 'This action cannot be undone.',
  confirmLabel = 'Delete',
  danger = true,
} = {}) {
  const modal = document.getElementById('confirm-modal');
  if (!modal) return Promise.resolve(window.confirm(message));

  const titleEl = document.getElementById('confirm-title');
  const msgEl = document.getElementById('confirm-message');
  const acceptBtn = document.getElementById('confirm-accept');
  const cancelBtn = document.getElementById('confirm-cancel');

  titleEl.textContent = title;
  msgEl.textContent = message;
  acceptBtn.textContent = confirmLabel;
  acceptBtn.className = danger ? 'btn btn-danger-solid' : 'btn';

  return new Promise((resolve) => {
    const done = (result) => {
      acceptBtn.removeEventListener('click', onAccept);
      cancelBtn.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      hideModal('confirm-modal');
      resolve(result);
    };
    const onAccept = () => done(true);
    const onCancel = () => done(false);
    const onBackdrop = (event) => { if (event.target === modal) done(false); };

    acceptBtn.addEventListener('click', onAccept);
    cancelBtn.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);

    showModal('confirm-modal');
    setTimeout(() => acceptBtn.focus(), 130);
  });
}

/* -------------------------------- Nav shell ------------------------------- */

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!sidebar) return;
  const open = sidebar.classList.toggle('open');
  if (backdrop) backdrop.classList.toggle('active', open);
  document.body.style.overflow = open ? 'hidden' : '';
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (sidebar) sidebar.classList.remove('open');
  if (backdrop) backdrop.classList.remove('active');
  document.body.style.overflow = '';
}

function startClock() {
  const el = document.getElementById('live-clock');
  if (!el) return;
  const tick = () => {
    el.textContent = new Date().toLocaleTimeString('en-GB', {
      hour: '2-digit', minute: '2-digit',
    });
  };
  tick();
  setInterval(tick, 20000);
}

/* ------------------------------ Delete buttons ---------------------------- */

/**
 * Any element with data-delete="<url>" gets a confirm dialog and a DELETE.
 * Saves wiring an onclick for every row in every list.
 */
function wireDeleteButtons() {
  document.addEventListener('click', async (event) => {
    const trigger = event.target.closest('[data-delete]');
    if (!trigger) return;
    event.preventDefault();

    const ok = await confirmAction({
      title: trigger.dataset.confirmTitle || 'Delete this item?',
      message: trigger.dataset.confirmMessage || 'This cannot be undone.',
      confirmLabel: trigger.dataset.confirmLabel || 'Delete',
    });
    if (!ok) return;

    setLoading(trigger, true);
    try {
      await api(trigger.dataset.delete, { method: 'DELETE' });
      showToast(trigger.dataset.successMessage || 'Deleted.', 'success');
      if (trigger.dataset.redirect) {
        window.location.href = trigger.dataset.redirect;
      } else {
        const row = trigger.closest('[data-row]');
        if (row) {
          row.style.opacity = '0';
          setTimeout(() => { row.remove(); }, 180);
        } else {
          window.location.reload();
        }
      }
    } catch (error) {
      showToast(error.message, 'error');
      setLoading(trigger, false);
    }
  });
}

/* -------------------------------- Password -------------------------------- */

function togglePassword(button) {
  const wrapper = button.closest('.input-group');
  const input = wrapper && wrapper.querySelector('input');
  if (!input) return;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  button.innerHTML = icon(show ? 'eye-off' : 'eye', 16);
  button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
}

/* ---------------------------------- Boot ---------------------------------- */

document.addEventListener('DOMContentLoaded', () => {
  startClock();
  wireDeleteButtons();

  // Escape closes whatever is on top.
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (document.querySelector('.modal-overlay.active')) {
      closeAllModals();
    } else {
      closeSidebar();
    }
  });

  // Clicking a modal's backdrop closes it, but clicking inside must not.
  document.querySelectorAll('.modal-overlay').forEach((overlay) => {
    if (overlay.id === 'confirm-modal') return;   // handled by confirmAction
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) hideModal(overlay.id);
    });
  });
});
