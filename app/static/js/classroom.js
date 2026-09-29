/* ==========================================================================
   LearnHub — classroom
   Renders any UTC timestamp on the page in the viewer's own zone, and turns
   the waiting room into a live room the moment the server says it may.
   ========================================================================== */

(() => {
  // Any badge carrying a UTC instant becomes local text. The server-rendered
  // "… UTC" is the no-JavaScript fallback, not the intended reading.
  document.querySelectorAll('[data-local-time]').forEach((el) => {
    const date = new Date(el.dataset.localTime);
    if (Number.isNaN(date.getTime())) return;
    el.textContent = date.toLocaleString([], {
      weekday: 'short', day: 'numeric', month: 'short',
      hour: '2-digit', minute: '2-digit',
    });
  });

  const waiting = document.getElementById('waiting-room');
  if (!waiting) return;

  const startsAt = new Date(waiting.dataset.starts);
  const sessionId = waiting.dataset.session;
  const countdown = document.getElementById('waiting-countdown');

  function tick() {
    const remaining = Math.floor((startsAt.getTime() - Date.now()) / 1000);
    if (remaining <= 0 || Number.isNaN(remaining)) {
      countdown.hidden = true;
      return;
    }
    countdown.hidden = false;
    countdown.textContent = formatClock(remaining);
  }

  /**
   * Ask the server whether the room has opened. The server owns the decision --
   * a student whose clock is fast must not be let in early, and one whose clock
   * is slow must not be locked out.
   */
  async function poll() {
    try {
      const status = await api(`/classes/${sessionId}/status`);
      if (status.canJoin) {
        showToast('The room is open. Joining…', 'success');
        setTimeout(() => window.location.reload(), 900);
        return;
      }
      const title = document.getElementById('waiting-title');
      if (title && status.reason) title.textContent = status.reason;
    } catch {
      // A blip in connectivity is not worth a toast; the next tick retries.
    }
  }

  tick();
  setInterval(tick, 1000);
  setInterval(poll, 20000);
})();
