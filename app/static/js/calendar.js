/* ==========================================================================
   LearnHub — calendar
   A month grid of live classes, plus the teacher's scheduling form.

   Every instant crosses the wire as UTC ISO-8601 and is rendered through the
   browser's own locale, so a class at 15:00 in Karachi shows as 11:00 to a
   student in London without the server knowing or caring where anyone is.
   ========================================================================== */

(() => {
  const boot = document.getElementById('calendar-data');
  if (!boot) return;

  const DATA = JSON.parse(boot.textContent || '{}');
  const CAN_SCHEDULE = Boolean(DATA.canSchedule);

  const grid = document.getElementById('cal-grid');
  const monthLabel = document.getElementById('cal-month');
  const upcomingBox = document.getElementById('cal-upcoming');
  const dayBox = document.getElementById('cal-day-detail');

  /** Events for the month currently on screen, keyed by local YYYY-MM-DD. */
  let byDay = new Map();
  let events = [];
  let cursor = startOfMonth(new Date());
  let selectedKey = dayKey(new Date());

  /* ------------------------------- Date utils ------------------------------ */

  function startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  /** Local calendar day as YYYY-MM-DD. Not toISOString — that would shift the
      day for anyone east or west of UTC, which is the whole bug class here. */
  function dayKey(date) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function sameDay(a, b) {
    return dayKey(a) === dayKey(b);
  }

  /** Monday-first weekday index (0 = Monday). */
  function mondayIndex(date) {
    return (date.getDay() + 6) % 7;
  }

  function timeLabel(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function dateLabel(iso) {
    return new Date(iso).toLocaleDateString([], {
      weekday: 'short', day: 'numeric', month: 'short',
    });
  }

  /** UTC ISO -> the value a <input type="datetime-local"> expects (local). */
  function toLocalInput(iso) {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
         + `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  /** Human "in 2 hours" / "in 3 days" / "started 10 min ago". */
  function relative(iso) {
    const diff = new Date(iso).getTime() - Date.now();
    const mins = Math.round(diff / 60000);
    const abs = Math.abs(mins);
    let text;
    if (abs < 60) text = `${abs} min`;
    else if (abs < 1440) text = `${Math.round(abs / 60)} hr`;
    else text = `${Math.round(abs / 1440)} day${Math.round(abs / 1440) === 1 ? '' : 's'}`;
    return mins >= 0 ? `in ${text}` : `${text} ago`;
  }

  /* --------------------------------- Fetch --------------------------------- */

  async function load() {
    // Pad the window either side so events bleeding in from adjacent months
    // still land in the leading and trailing grid cells.
    const from = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1);
    const to = new Date(cursor.getFullYear(), cursor.getMonth() + 2, 1);

    try {
      const res = await api(
        `/calendar/api/events?start=${encodeURIComponent(from.toISOString())}`
        + `&end=${encodeURIComponent(to.toISOString())}`,
      );
      events = res.events || [];
    } catch (error) {
      showToast(error.message, 'error');
      events = [];
    }

    byDay = new Map();
    events.forEach((event) => {
      const key = dayKey(new Date(event.startsAt));
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key).push(event);
    });

    render();
  }

  /* -------------------------------- Rendering ------------------------------ */

  function eventPill(event) {
    const cancelled = event.state === 'cancelled';
    return `
      <button type="button" class="cal-pill accent-${escapeHtml(event.accent)}
              ${event.state === 'live' ? 'is-live' : ''} ${cancelled ? 'is-cancelled' : ''}"
              data-event="${event.id}">
        <span class="cal-pill-time">${escapeHtml(timeLabel(event.startsAt))}</span>
        <span class="cal-pill-title">${escapeHtml(event.title)}</span>
      </button>`;
  }

  function render() {
    monthLabel.textContent = cursor.toLocaleDateString([], {
      month: 'long', year: 'numeric',
    });

    const today = new Date();
    const first = startOfMonth(cursor);
    const lead = mondayIndex(first);
    const start = new Date(first);
    start.setDate(start.getDate() - lead);

    let html = '';
    for (let i = 0; i < 42; i += 1) {
      const day = new Date(start);
      day.setDate(start.getDate() + i);
      const key = dayKey(day);
      const outside = day.getMonth() !== cursor.getMonth();
      const dayEvents = (byDay.get(key) || [])
        .sort((a, b) => new Date(a.startsAt) - new Date(b.startsAt));

      const classes = [
        'cal-day',
        outside ? 'is-outside' : '',
        sameDay(day, today) ? 'is-today' : '',
        key === selectedKey ? 'is-selected' : '',
        dayEvents.length ? 'has-events' : '',
      ].filter(Boolean).join(' ');

      html += `
        <div class="${classes}" data-day="${key}" role="button" tabindex="0">
          <span class="cal-daynum">${day.getDate()}</span>
          <div class="cal-day-events">
            ${dayEvents.slice(0, 3).map(eventPill).join('')}
            ${dayEvents.length > 3
              ? `<span class="cal-more">+${dayEvents.length - 3} more</span>` : ''}
          </div>
        </div>`;
    }
    grid.innerHTML = html;

    renderUpcoming();
    renderDay(selectedKey);
  }

  function summaryRow(event, { showDate = false } = {}) {
    const when = showDate
      ? `${dateLabel(event.startsAt)} · ${timeLabel(event.startsAt)}`
      : timeLabel(event.startsAt);

    const action = event.canJoin
      ? `<a class="btn btn-sm" href="${event.joinPath}">
           ${icon('video', 14)} Join
         </a>`
      : `<span class="tiny muted">${escapeHtml(event.joinReason || relative(event.startsAt))}</span>`;

    return `
      <div class="cal-summary ${event.state === 'cancelled' ? 'is-cancelled' : ''}"
           data-row data-event-row="${event.id}">
        <span class="cal-stripe accent-${escapeHtml(event.accent)}"></span>
        <div class="stack" style="gap:2px;flex:1;min-width:0">
          <span class="strong small ellipsis">${escapeHtml(event.title)}</span>
          <span class="tiny muted ellipsis">${escapeHtml(event.courseTitle)}</span>
          <span class="tiny muted">${escapeHtml(when)} · ${event.durationMinutes} min</span>
        </div>
        <div class="row" style="gap:6px">
          ${event.state === 'live' ? '<span class="badge badge-success">Live</span>' : ''}
          ${action}
          ${event.canManage
            ? `<button type="button" class="btn btn-ghost btn-icon btn-sm"
                       data-edit="${event.id}" aria-label="Edit class">
                 ${icon('edit', 14)}
               </button>`
            : ''}
        </div>
      </div>`;
  }

  function renderUpcoming() {
    const now = Date.now();
    const rows = events
      .filter((e) => e.state === 'live'
        || (e.state === 'upcoming' && new Date(e.startsAt).getTime() > now - 3.6e6))
      .sort((a, b) => new Date(a.startsAt) - new Date(b.startsAt))
      .slice(0, 6);

    const liveBadge = document.getElementById('cal-live-count');
    const liveNow = rows.filter((e) => e.state === 'live').length;
    if (liveBadge) liveBadge.hidden = liveNow === 0;

    upcomingBox.innerHTML = rows.length
      ? rows.map((e) => summaryRow(e, { showDate: true })).join('')
      : `<p class="small muted">Nothing scheduled in this window.${
          CAN_SCHEDULE ? ' Use <em>Schedule a class</em> to add one.' : ''}</p>`;
  }

  function renderDay(key) {
    const rows = (byDay.get(key) || [])
      .sort((a, b) => new Date(a.startsAt) - new Date(b.startsAt));

    const [y, m, d] = key.split('-').map(Number);
    const heading = new Date(y, m - 1, d).toLocaleDateString([], {
      weekday: 'long', day: 'numeric', month: 'long',
    });

    dayBox.innerHTML = `
      <span class="tiny muted">${escapeHtml(heading)}</span>
      ${rows.length
        ? rows.map((e) => summaryRow(e)).join('')
        : `<p class="small muted">No classes on this day.</p>`}
      ${CAN_SCHEDULE
        ? `<button type="button" class="btn btn-outline btn-sm mt" data-add-on="${key}">
             ${icon('plus', 14)} Add a class here
           </button>`
        : ''}`;
  }

  /* --------------------------------- Modal --------------------------------- */

  const modal = document.getElementById('class-modal');
  const form = document.getElementById('class-form');

  function openModal(event = null, presetKey = null) {
    if (!CAN_SCHEDULE || !modal) return;

    document.getElementById('class-modal-title').textContent =
      event ? 'Edit class' : 'Schedule a class';
    document.getElementById('class-save').textContent = event ? 'Save changes' : 'Schedule';
    document.getElementById('class-id').value = event ? event.id : '';
    document.getElementById('class-title').value = event ? event.title : '';
    document.getElementById('class-desc').value = event ? event.description : '';
    document.getElementById('class-duration').value = event ? event.durationMinutes : 60;
    document.getElementById('class-url').value = (event && event.meetingUrl) || '';

    const courseSelect = document.getElementById('class-course');
    if (event) courseSelect.value = String(event.courseId);
    // The course owns the room, so moving a class between courses would strand
    // enrolled students. Editing keeps it fixed.
    courseSelect.disabled = Boolean(event);

    const provider = event ? event.provider : 'builtin';
    form.querySelectorAll('input[name="provider"]').forEach((radio) => {
      radio.checked = radio.value === provider;
    });
    syncProvider();

    // A new class defaults to the next round hour on the day the user clicked.
    let when;
    if (event) {
      when = toLocalInput(event.startsAt);
    } else {
      const base = presetKey ? new Date(`${presetKey}T00:00`) : new Date();
      const now = new Date();
      if (presetKey && dayKey(base) !== dayKey(now)) base.setHours(10, 0, 0, 0);
      else { base.setTime(now.getTime()); base.setHours(now.getHours() + 1, 0, 0, 0); }
      when = toLocalInput(base.toISOString());
    }
    document.getElementById('class-start').value = when;

    document.getElementById('class-delete').hidden = !event;
    document.getElementById('class-delete').dataset.id = event ? event.id : '';

    showModal('class-modal');
  }

  function syncProvider() {
    if (!form) return;
    const chosen = form.querySelector('input[name="provider"]:checked');
    const external = chosen && chosen.value === 'external';
    document.getElementById('external-field').hidden = !external;
    document.getElementById('class-url').required = Boolean(external);
    document.getElementById('provider-hint').textContent = external
      ? 'Students get a Join button that opens your link in a new tab.'
      : 'A private room is created for you — nobody needs an account.';
  }

  async function submitForm(submitEvent) {
    submitEvent.preventDefault();

    const id = document.getElementById('class-id').value;
    const localValue = document.getElementById('class-start').value;
    if (!localValue) {
      showToast('Pick a start time.', 'error');
      return;
    }

    const provider = form.querySelector('input[name="provider"]:checked').value;
    const body = {
      title: document.getElementById('class-title').value.trim(),
      description: document.getElementById('class-desc').value.trim() || null,
      // A datetime-local value is wall-clock in the teacher's zone; Date parses
      // it as local and toISOString converts it to the instant the server wants.
      starts_at: new Date(localValue).toISOString(),
      duration_minutes: Number(document.getElementById('class-duration').value) || 60,
      provider,
      meeting_url: provider === 'external'
        ? document.getElementById('class-url').value.trim()
        : null,
    };

    const save = document.getElementById('class-save');
    setLoading(save, true);
    try {
      if (id) {
        await api(`/teach/api/classes/${id}`, { method: 'PUT', body });
        showToast('Class updated.', 'success');
      } else {
        body.course_id = Number(document.getElementById('class-course').value);
        await api('/teach/api/classes', { method: 'POST', body });
        showToast('Class scheduled.', 'success');
      }
      hideModal('class-modal');
      await load();
    } catch (error) {
      showToast(error.message, 'error');
    } finally {
      setLoading(save, false);
    }
  }

  async function removeClass(id) {
    const ok = await confirmAction({
      title: 'Delete this class?',
      message: 'Students will no longer see it on their calendar. '
             + 'To keep it visible but call it off, cancel it instead.',
      confirmLabel: 'Delete',
    });
    if (!ok) return;

    try {
      await api(`/teach/api/classes/${id}`, { method: 'DELETE' });
      showToast('Class removed.', 'success');
      hideModal('class-modal');
      await load();
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  /* --------------------------------- Wiring -------------------------------- */

  function findEvent(id) {
    return events.find((e) => String(e.id) === String(id));
  }

  document.getElementById('cal-prev').addEventListener('click', () => {
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1);
    load();
  });

  document.getElementById('cal-next').addEventListener('click', () => {
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
    load();
  });

  document.getElementById('cal-today').addEventListener('click', () => {
    cursor = startOfMonth(new Date());
    selectedKey = dayKey(new Date());
    load();
  });

  const newBtn = document.getElementById('cal-new');
  if (newBtn) newBtn.addEventListener('click', () => openModal(null, selectedKey));

  if (form) {
    form.addEventListener('submit', submitForm);
    form.querySelectorAll('input[name="provider"]').forEach((radio) => {
      radio.addEventListener('change', syncProvider);
    });
    document.getElementById('class-delete').addEventListener('click', (e) => {
      removeClass(e.currentTarget.dataset.id);
    });
  }

  // One delegated handler for the grid and both side panels.
  document.addEventListener('click', (clickEvent) => {
    const pill = clickEvent.target.closest('[data-event]');
    if (pill) {
      clickEvent.stopPropagation();
      const event = findEvent(pill.dataset.event);
      if (!event) return;
      if (event.canManage) openModal(event);
      else if (event.canJoin) window.location.href = event.joinPath;
      else showToast(event.joinReason || 'This class is not open yet.', 'info');
      return;
    }

    const edit = clickEvent.target.closest('[data-edit]');
    if (edit) {
      const event = findEvent(edit.dataset.edit);
      if (event) openModal(event);
      return;
    }

    const add = clickEvent.target.closest('[data-add-on]');
    if (add) {
      openModal(null, add.dataset.addOn);
      return;
    }

    const cell = clickEvent.target.closest('[data-day]');
    if (cell) {
      selectedKey = cell.dataset.day;
      grid.querySelectorAll('.cal-day').forEach((el) => {
        el.classList.toggle('is-selected', el.dataset.day === selectedKey);
      });
      renderDay(selectedKey);
    }
  });

  grid.addEventListener('keydown', (keyEvent) => {
    if (keyEvent.key !== 'Enter' && keyEvent.key !== ' ') return;
    const cell = keyEvent.target.closest('[data-day]');
    if (!cell) return;
    keyEvent.preventDefault();
    cell.click();
  });

  // A class going live should not need a manual refresh to show its Join button.
  setInterval(load, 60000);

  load();
})();
