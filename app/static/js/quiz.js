/* ==========================================================================
   LearnHub — test runner

   One question at a time, with a palette for jumping around. Answers autosave
   to the server as they change and mirror into localStorage, so a refresh (or
   a closed laptop lid) loses nothing.

   The countdown here is cosmetic. The server stamped `expires_at` when the
   attempt began and re-checks it on every request, so editing this file buys
   nobody extra time -- the worst it can do is show a wrong number.
   ========================================================================== */

(() => {
  const dataEl = document.getElementById('quiz-data');
  if (!dataEl) return;

  const quiz = JSON.parse(dataEl.textContent);
  const questions = quiz.questions;
  const storageKey = `learnhub:attempt:${quiz.attemptId}`;

  const host = document.getElementById('question-host');
  const palette = document.getElementById('palette');
  const timerEl = document.getElementById('timer');
  const timerText = document.getElementById('timer-text');
  const answeredCount = document.getElementById('answered-count');
  const flagLabel = document.getElementById('flag-label');
  const autosaveNote = document.getElementById('autosave-note');

  let current = 0;
  let submitting = false;
  let remaining = quiz.secondsRemaining;
  const revealed = new Map();   // questionId -> practice-mode feedback

  const LETTERS = 'ABCDEFGHIJ';

  /* ------------------------------- Restore ------------------------------- */

  // The server copy is authoritative; the local mirror only fills gaps left by
  // a save that never made it out.
  try {
    const cached = JSON.parse(localStorage.getItem(storageKey) || '{}');
    questions.forEach((q) => {
      const saved = cached[q.id];
      if (!saved) return;
      if (!q.selected.length && Array.isArray(saved.selected)) q.selected = saved.selected;
      if (q.numeric === null && saved.numeric !== undefined) q.numeric = saved.numeric;
    });
  } catch {
    localStorage.removeItem(storageKey);
  }

  function cacheLocally() {
    const snapshot = {};
    questions.forEach((q) => {
      snapshot[q.id] = { selected: q.selected, numeric: q.numeric };
    });
    try {
      localStorage.setItem(storageKey, JSON.stringify(snapshot));
    } catch {
      // Private mode or a full quota. The server copy still holds.
    }
  }

  /* -------------------------------- State -------------------------------- */

  const isAnswered = (q) =>
    (q.selected && q.selected.length > 0) || (q.numeric !== null && q.numeric !== undefined);

  function refreshCounts() {
    answeredCount.textContent = questions.filter(isAnswered).length;
  }

  /* ------------------------------- Palette -------------------------------- */

  function renderPalette() {
    palette.innerHTML = '';
    questions.forEach((q, index) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'palette-btn';
      btn.textContent = index + 1;
      btn.setAttribute('aria-label', `Question ${index + 1}`);

      const feedback = revealed.get(q.id);
      if (feedback) {
        btn.classList.add(feedback.is_correct ? 'correct' : 'incorrect');
      } else if (isAnswered(q)) {
        btn.classList.add('answered');
      }
      if (q.flagged) btn.classList.add('flagged');
      if (index === current) btn.classList.add('current');

      btn.addEventListener('click', () => goTo(index));
      palette.appendChild(btn);
    });
  }

  /* ------------------------------- Question ------------------------------- */

  function renderQuestion() {
    const q = questions[current];
    const feedback = revealed.get(q.id);
    const isMulti = q.type === 'multi';

    const marksLabel = q.negativeMarks
      ? `${q.marks} mark${q.marks === 1 ? '' : 's'} · −${q.negativeMarks} if wrong`
      : `${q.marks} mark${q.marks === 1 ? '' : 's'}`;

    let body = '';

    if (q.type === 'numeric') {
      body = `
        <div class="numeric-answer">
          <label class="label" for="numeric-input">Your answer</label>
          <input class="input nums" type="number" step="any" id="numeric-input"
                 value="${q.numeric ?? ''}" placeholder="Type a number"
                 ${feedback ? 'disabled' : ''} autocomplete="off">
        </div>`;
    } else {
      const rows = q.choices.map((choice, index) => {
        const selected = q.selected.includes(choice.id);
        let stateClass = selected ? 'selected' : '';
        if (feedback) {
          const correct = feedback.correct_choice_ids.includes(choice.id);
          if (correct) stateClass = 'correct';
          else if (selected) stateClass = 'incorrect';
          stateClass += ' revealed';
        }
        return `
          <label class="choice ${stateClass}" data-choice="${choice.id}" data-multi="${isMulti}">
            <span class="choice-key">${isMulti && selected ? '✓' : LETTERS[index] || index + 1}</span>
            <span class="choice-text">${escapeHtml(choice.text)}</span>
          </label>`;
      }).join('');
      body = `<div class="choice-list">${rows}</div>`;
    }

    let explain = '';
    if (feedback) {
      const correctText = q.type === 'numeric'
        ? `The correct answer is <strong>${escapeHtml(feedback.correct_numeric)}</strong>.`
        : '';
      explain = `
        <div class="explain ${feedback.is_correct ? 'correct' : 'incorrect'}">
          <div class="explain-head">
            ${feedback.is_correct ? ICONS.success : ICONS.error}
            ${feedback.is_correct ? 'Correct' : 'Not quite'}
          </div>
          <div>${correctText} ${feedback.explanation ? escapeHtml(feedback.explanation) : ''}</div>
        </div>`;
    }

    // Multi-select can't auto-reveal: a half-built selection isn't an answer
    // yet, so practice mode asks the student to say when they're done.
    const needsCheck = quiz.isPractice && isMulti && !feedback && q.selected.length > 0;
    const checkBtn = needsCheck
      ? `<button type="button" class="btn btn-soft btn-sm mt" id="check-btn">Check my answer</button>`
      : '';

    host.innerHTML = `
      <div class="question-card">
        <div class="question-head">
          <div class="stack">
            <span class="question-num">Question ${current + 1} of ${questions.length}</span>
            <div class="question-text">${escapeHtml(q.text)}</div>
          </div>
          <span class="badge badge-muted nums">${marksLabel}</span>
        </div>
        ${isMulti ? '<p class="tiny faint">Select every option that applies — partial answers score nothing.</p>' : ''}
        ${body}
        ${checkBtn}
        ${explain}
      </div>`;

    wireInputs(q, Boolean(feedback));

    const check = document.getElementById('check-btn');
    if (check) check.addEventListener('click', () => checkAnswer(q));

    if (flagLabel) flagLabel.textContent = q.flagged ? 'Unflag' : 'Flag for review';
    document.getElementById('prev-btn').disabled = current === 0;

    const nextBtn = document.getElementById('next-btn');
    nextBtn.innerHTML = current === questions.length - 1
      ? 'Review answers'
      : `Next <svg width="15" height="15" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><use href="#i-arrow-right"/></svg>`;

    renderPalette();
    refreshCounts();
  }

  function wireInputs(q, locked) {
    if (locked) return;

    if (q.type === 'numeric') {
      const input = document.getElementById('numeric-input');
      const commit = debounce(() => {
        const value = input.value === '' ? null : Number(input.value);
        q.numeric = Number.isFinite(value) ? value : null;
        cacheLocally();
        save(q, { numeric_value: q.numeric });
        renderPalette();
        refreshCounts();
        if (quiz.isPractice && q.numeric !== null) checkAnswer(q);
      }, 700);
      input.addEventListener('input', commit);
      return;
    }

    host.querySelectorAll('.choice').forEach((el) => {
      el.addEventListener('click', () => pick(q, Number(el.dataset.choice)));
    });
  }

  function pick(q, choiceId) {
    if (revealed.has(q.id)) return;

    if (q.type === 'multi') {
      q.selected = q.selected.includes(choiceId)
        ? q.selected.filter((id) => id !== choiceId)
        : [...q.selected, choiceId];
    } else {
      // Clicking the chosen option again clears it, so a wrong tap is undoable.
      q.selected = q.selected[0] === choiceId ? [] : [choiceId];
    }

    cacheLocally();
    save(q, { selected_choice_ids: q.selected });
    renderQuestion();

    // Practice mode reveals as soon as the answer is committed. Multi-select
    // waits for an explicit Check, since a partial selection is not an answer.
    if (quiz.isPractice && q.selected.length && q.type !== 'multi') {
      checkAnswer(q);
    }
  }

  /* --------------------------------- Save --------------------------------- */

  async function save(q, payload) {
    if (submitting) return;
    try {
      await api(`/api/attempts/${quiz.attemptId}/answer/${q.id}`, {
        method: 'POST',
        body: payload,
      });
      if (autosaveNote) autosaveNote.textContent = 'Saved.';
    } catch (error) {
      if (error.status === 409) {
        // The attempt closed underneath us (expired, or submitted elsewhere).
        showToast(error.message, 'warning');
        setTimeout(() => { window.location.href = `/attempts/${quiz.attemptId}/result`; }, 1200);
        return;
      }
      if (autosaveNote) autosaveNote.textContent = 'Saved locally — retrying.';
    }
  }

  async function checkAnswer(q) {
    try {
      const feedback = await api(`/api/attempts/${quiz.attemptId}/check/${q.id}`, { method: 'POST' });
      revealed.set(q.id, feedback);
      renderQuestion();
    } catch {
      // Feedback is a bonus in practice mode; failing to get it must not block
      // the student from continuing.
    }
  }

  /* ------------------------------ Navigation ------------------------------ */

  function goTo(index) {
    current = Math.max(0, Math.min(questions.length - 1, index));
    renderQuestion();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  document.getElementById('prev-btn').addEventListener('click', () => goTo(current - 1));
  document.getElementById('next-btn').addEventListener('click', () => {
    if (current === questions.length - 1) openSubmit();
    else goTo(current + 1);
  });

  document.getElementById('flag-btn').addEventListener('click', () => {
    const q = questions[current];
    q.flagged = !q.flagged;
    save(q, { flagged: q.flagged });
    renderQuestion();
  });

  document.addEventListener('keydown', (event) => {
    const tag = (event.target.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag)) return;
    if (document.querySelector('.modal-overlay.active')) return;

    const q = questions[current];

    if (event.key === 'ArrowRight') { event.preventDefault(); goTo(current + 1); }
    else if (event.key === 'ArrowLeft') { event.preventDefault(); goTo(current - 1); }
    else if (event.key.toLowerCase() === 'f') {
      q.flagged = !q.flagged;
      save(q, { flagged: q.flagged });
      renderQuestion();
    } else if (/^[1-9]$/.test(event.key) && q.type !== 'numeric') {
      const choice = q.choices[Number(event.key) - 1];
      if (choice) pick(q, choice.id);
    }
  });

  /* -------------------------------- Timer --------------------------------- */

  function paintTimer() {
    if (remaining === null || remaining === undefined) return;
    timerText.textContent = formatClock(remaining);
    timerEl.classList.toggle('warn', remaining <= 300 && remaining > 60);
    timerEl.classList.toggle('danger', remaining <= 60);
  }

  if (remaining !== null && remaining !== undefined) {
    paintTimer();
    let warned5 = false;
    let warned1 = false;

    setInterval(() => {
      if (submitting) return;
      remaining -= 1;

      if (remaining <= 300 && !warned5) { warned5 = true; showToast('5 minutes left.', 'warning'); }
      if (remaining <= 60 && !warned1) { warned1 = true; showToast('1 minute left!', 'error'); }

      if (remaining <= 0) {
        remaining = 0;
        paintTimer();
        showToast('Time is up. Submitting...', 'error');
        doSubmit(true);
        return;
      }
      paintTimer();
    }, 1000);
  }

  /* -------------------------------- Submit -------------------------------- */

  function openSubmit() {
    const unanswered = questions.filter((q) => !isAnswered(q)).length;
    const flagged = questions.filter((q) => q.flagged).length;

    document.getElementById('submit-summary').textContent =
      `You've answered ${questions.length - unanswered} of ${questions.length} questions.`;

    const warning = document.getElementById('submit-warning');
    const parts = [];
    if (unanswered) parts.push(`${unanswered} unanswered`);
    if (flagged) parts.push(`${flagged} still flagged`);

    warning.innerHTML = parts.length
      ? `<div class="alert alert-warn">${ICONS.warning}<span>${parts.join(' and ')}. You can't come back after submitting.</span></div>`
      : `<div class="alert alert-success">${ICONS.success}<span>Everything is answered. Good luck.</span></div>`;

    showModal('submit-modal');
  }

  async function doSubmit(auto = false) {
    if (submitting) return;
    submitting = true;

    const btn = document.getElementById('submit-confirm');
    setLoading(btn, true);

    try {
      const result = await api(`/api/attempts/${quiz.attemptId}/submit`, { method: 'POST' });
      localStorage.removeItem(storageKey);
      window.removeEventListener('beforeunload', warnOnLeave);
      window.location.href = result.redirect;
    } catch (error) {
      submitting = false;
      setLoading(btn, false);
      showToast(error.message, 'error');
      if (auto) setTimeout(() => { window.location.href = `/attempts/${quiz.attemptId}/result`; }, 1500);
    }
  }

  document.getElementById('submit-btn').addEventListener('click', openSubmit);
  document.getElementById('submit-btn-2').addEventListener('click', openSubmit);
  document.getElementById('submit-confirm').addEventListener('click', () => doSubmit(false));

  /* ------------------------------ Leave guard ------------------------------ */

  function warnOnLeave(event) {
    if (submitting) return;
    event.preventDefault();
    event.returnValue = '';
  }
  window.addEventListener('beforeunload', warnOnLeave);

  /* --------------------------------- Boot ---------------------------------- */

  // Open on the first unanswered question rather than always question 1 --
  // resuming an attempt should drop you where the work is.
  const firstGap = questions.findIndex((q) => !isAnswered(q));
  current = firstGap === -1 ? 0 : firstGap;

  renderQuestion();
})();
