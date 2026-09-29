/* ==========================================================================
   LearnHub — test builder

   Holds the whole test in one array and re-renders on change. A test is a few
   dozen fields at most, so a full re-render is cheaper to reason about than
   surgical DOM updates -- except for text inputs, which read their values
   straight from the DOM on save so typing never gets interrupted.
   ========================================================================== */

(() => {
  const dataEl = document.getElementById('test-data');
  if (!dataEl) return;

  const test = JSON.parse(dataEl.textContent);
  const list = document.getElementById('question-list');
  const locked = Boolean(test.locked);

  let questions = test.questions.map(normalise);

  const TYPE_LABELS = {
    single: 'Multiple choice',
    multi: 'Select many',
    truefalse: 'True / false',
    numeric: 'Numeric',
  };

  function normalise(q) {
    return {
      text: q.text || '',
      qtype: q.qtype || 'single',
      marks: q.marks ?? 1,
      negativeMarks: q.negativeMarks ?? 0,
      explanation: q.explanation || '',
      numericAnswer: q.numericAnswer ?? null,
      numericTolerance: q.numericTolerance ?? 0,
      choices: (q.choices || []).map((c) => ({ text: c.text || '', isCorrect: Boolean(c.isCorrect) })),
    };
  }

  function blank(qtype) {
    const base = normalise({ qtype });
    if (qtype === 'truefalse') {
      base.choices = [{ text: 'True', isCorrect: true }, { text: 'False', isCorrect: false }];
    } else if (qtype !== 'numeric') {
      base.choices = [
        { text: '', isCorrect: true }, { text: '', isCorrect: false },
        { text: '', isCorrect: false }, { text: '', isCorrect: false },
      ];
    }
    return base;
  }

  /* ------------------------- Read the DOM back in ------------------------- */

  // Text inputs are uncontrolled so typing is never interrupted by a re-render;
  // this pulls their current values into the model before anything else runs.
  function syncFromDom() {
    list.querySelectorAll('[data-q]').forEach((card) => {
      const index = Number(card.dataset.q);
      const q = questions[index];
      if (!q) return;

      const get = (sel) => card.querySelector(sel);
      q.text = get('[data-field="text"]')?.value ?? q.text;
      q.explanation = get('[data-field="explanation"]')?.value ?? q.explanation;
      q.marks = Number(get('[data-field="marks"]')?.value) || 1;

      const neg = get('[data-field="negative"]');
      if (neg) q.negativeMarks = Number(neg.value) || 0;

      if (q.qtype === 'numeric') {
        const answer = get('[data-field="numeric"]')?.value;
        q.numericAnswer = answer === '' || answer === undefined ? null : Number(answer);
        q.numericTolerance = Number(get('[data-field="tolerance"]')?.value) || 0;
      } else {
        card.querySelectorAll('[data-choice]').forEach((input) => {
          const c = Number(input.dataset.choice);
          if (q.choices[c]) q.choices[c].text = input.value;
        });
      }
    });
  }

  /* -------------------------------- Render -------------------------------- */

  function render() {
    list.innerHTML = '';

    if (!questions.length) {
      list.innerHTML = `
        <div class="card empty">
          <div class="empty-icon">
            <svg width="22" height="22" class="icon icon-lg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-linecap="round" stroke-linejoin="round"><use href="#i-clipboard"/></svg>
          </div>
          <div class="empty-title">No questions yet</div>
          <p class="empty-desc">${locked
            ? 'This test has no questions and can no longer be edited.'
            : 'Add your first question with the buttons below.'}</p>
        </div>`;
      updateTotals();
      return;
    }

    questions.forEach((q, index) => {
      const card = document.createElement('div');
      card.className = 'builder-question';
      card.dataset.q = index;
      card.innerHTML = questionMarkup(q, index);
      list.appendChild(card);
    });

    wire();
    updateTotals();
  }

  function questionMarkup(q, index) {
    const dis = locked ? 'disabled' : '';

    const answerBlock = q.qtype === 'numeric'
      ? `
        <div class="field-row">
          <div class="field">
            <label class="label">Correct answer</label>
            <input class="input nums" type="number" step="any" data-field="numeric"
                   value="${q.numericAnswer ?? ''}" placeholder="e.g. 6" ${dis}>
          </div>
          <div class="field">
            <label class="label">Tolerance <span class="hint">(± allowed)</span></label>
            <input class="input nums" type="number" step="any" min="0" data-field="tolerance"
                   value="${q.numericTolerance ?? 0}" ${dis}>
          </div>
        </div>`
      : `
        <span class="label">Options ${q.qtype === 'multi' ? '— tick every correct one' : '— tick the correct one'}</span>
        <div style="margin-top:8px">
          ${q.choices.map((choice, c) => `
            <div class="builder-choice">
              <button type="button" class="builder-correct ${choice.isCorrect ? 'on' : ''}"
                      data-correct="${c}" title="Mark as correct" ${dis}>
                <svg width="15" height="15" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-linecap="round" stroke-linejoin="round"><use href="#i-check"/></svg>
              </button>
              <input class="input" data-choice="${c}" value="${escapeHtml(choice.text)}"
                     placeholder="Option ${String.fromCharCode(65 + c)}"
                     ${q.qtype === 'truefalse' || locked ? 'disabled' : ''}>
              ${q.qtype === 'truefalse' || locked ? '' : `
                <button type="button" class="btn btn-icon btn-ghost" data-remove-choice="${c}" title="Remove">
                  <svg width="14" height="14" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-linecap="round" stroke-linejoin="round"><use href="#i-close"/></svg>
                </button>`}
            </div>`).join('')}
        </div>
        ${q.qtype === 'truefalse' || locked ? '' : `
          <button type="button" class="btn btn-ghost btn-sm" data-add-choice>
            <svg width="14" height="14" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-linecap="round" stroke-linejoin="round"><use href="#i-plus"/></svg>
            Add option
          </button>`}`;

    const negativeField = document.getElementById('s-negative')?.checked
      ? `<div class="field">
           <label class="label">Negative marks</label>
           <input class="input nums" type="number" min="0" step="0.25" data-field="negative"
                  value="${q.negativeMarks}" ${dis}>
         </div>`
      : '';

    return `
      <div class="builder-head">
        <span class="builder-num">${index + 1}</span>
        <span class="strong small">${TYPE_LABELS[q.qtype] || q.qtype}</span>
        <div class="spacer"></div>
        ${locked ? '' : `
          <button type="button" class="btn btn-icon btn-ghost" data-move="-1" title="Move up">
            <svg width="15" height="15" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-linecap="round" stroke-linejoin="round"><use href="#i-chevron-up"/></svg>
          </button>
          <button type="button" class="btn btn-icon btn-ghost" data-move="1" title="Move down">
            <svg width="15" height="15" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-linecap="round" stroke-linejoin="round"><use href="#i-chevron-down"/></svg>
          </button>
          <button type="button" class="btn btn-icon btn-ghost" data-duplicate title="Duplicate">
            <svg width="15" height="15" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-linecap="round" stroke-linejoin="round"><use href="#i-copy"/></svg>
          </button>
          <button type="button" class="btn btn-icon btn-ghost" data-delete-q title="Delete">
            <svg width="15" height="15" class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-linecap="round" stroke-linejoin="round"><use href="#i-trash"/></svg>
          </button>`}
      </div>

      <div class="builder-body">
        <div class="field">
          <label class="label">Question</label>
          <textarea class="textarea" data-field="text" style="min-height:64px"
                    placeholder="What do you want to ask?" ${dis}>${escapeHtml(q.text)}</textarea>
        </div>

        ${answerBlock}

        <div class="field-row mt">
          <div class="field">
            <label class="label">Marks</label>
            <input class="input nums" type="number" min="0.25" step="0.25" data-field="marks"
                   value="${q.marks}" ${dis}>
          </div>
          ${negativeField}
        </div>

        <div class="field">
          <label class="label">Explanation <span class="hint">(shown after answering)</span></label>
          <textarea class="textarea" data-field="explanation" style="min-height:56px"
                    placeholder="Why is that the answer?" ${dis}>${escapeHtml(q.explanation)}</textarea>
        </div>
      </div>`;
  }

  /* -------------------------------- Wiring -------------------------------- */

  function wire() {
    if (locked) return;

    list.querySelectorAll('[data-q]').forEach((card) => {
      const index = Number(card.dataset.q);

      card.querySelectorAll('[data-correct]').forEach((btn) => {
        btn.addEventListener('click', () => {
          syncFromDom();
          const c = Number(btn.dataset.correct);
          const q = questions[index];
          if (q.qtype === 'multi') {
            q.choices[c].isCorrect = !q.choices[c].isCorrect;
          } else {
            q.choices.forEach((choice, i) => { choice.isCorrect = i === c; });
          }
          render();
        });
      });

      const addChoice = card.querySelector('[data-add-choice]');
      if (addChoice) {
        addChoice.addEventListener('click', () => {
          syncFromDom();
          questions[index].choices.push({ text: '', isCorrect: false });
          render();
        });
      }

      card.querySelectorAll('[data-remove-choice]').forEach((btn) => {
        btn.addEventListener('click', () => {
          syncFromDom();
          const q = questions[index];
          if (q.choices.length <= 2) {
            showToast('A question needs at least two options.', 'warning');
            return;
          }
          q.choices.splice(Number(btn.dataset.removeChoice), 1);
          if (!q.choices.some((c) => c.isCorrect)) q.choices[0].isCorrect = true;
          render();
        });
      });

      card.querySelectorAll('[data-move]').forEach((btn) => {
        btn.addEventListener('click', () => {
          syncFromDom();
          const target = index + Number(btn.dataset.move);
          if (target < 0 || target >= questions.length) return;
          [questions[index], questions[target]] = [questions[target], questions[index]];
          render();
        });
      });

      const dup = card.querySelector('[data-duplicate]');
      if (dup) {
        dup.addEventListener('click', () => {
          syncFromDom();
          questions.splice(index + 1, 0, JSON.parse(JSON.stringify(questions[index])));
          render();
          showToast('Question duplicated.', 'success');
        });
      }

      const del = card.querySelector('[data-delete-q]');
      if (del) {
        del.addEventListener('click', async () => {
          syncFromDom();
          const ok = await confirmAction({
            title: `Delete question ${index + 1}?`,
            message: 'It will be removed when you save.',
          });
          if (!ok) return;
          questions.splice(index, 1);
          render();
        });
      }

      // Live totals as marks are typed.
      const marks = card.querySelector('[data-field="marks"]');
      if (marks) marks.addEventListener('input', () => { syncFromDom(); updateTotals(); });
    });
  }

  /* -------------------------------- Totals -------------------------------- */

  function updateTotals() {
    const total = questions.reduce((sum, q) => sum + (Number(q.marks) || 0), 0);
    const label = `${questions.length} question${questions.length === 1 ? '' : 's'} · ${total} mark${total === 1 ? '' : 's'}`;
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    set('marks-note', label);
    set('toolbar-summary', label);
    set('count-badge', questions.length);
    set('marks-badge', total);
  }

  /* ------------------------------- Settings ------------------------------- */

  const kindSelect = document.getElementById('s-kind');
  const durationField = document.getElementById('s-duration-field');
  const attemptsField = document.getElementById('s-attempts-field');
  const negativeToggle = document.getElementById('s-negative');
  const kindNote = document.getElementById('kind-note');

  function paintKind() {
    const grand = kindSelect.value === 'grand';
    durationField.style.display = grand ? '' : 'none';
    attemptsField.style.display = grand ? '' : 'none';
    negativeToggle.disabled = !grand;
    if (!grand) negativeToggle.checked = false;
    kindNote.textContent = grand
      ? 'Grand tests are timed and default to a single attempt. Answers stay hidden until submitted.'
      : 'Practice tests are always untimed and unlimited, and reveal the answer as the student goes.';
  }

  kindSelect.addEventListener('change', () => { paintKind(); render(); });
  negativeToggle.addEventListener('change', () => { syncFromDom(); render(); });
  paintKind();

  /* --------------------------------- Save --------------------------------- */

  window.addQuestion = (qtype) => {
    syncFromDom();
    questions.push(blank(qtype));
    render();
    // Land on the new question rather than leaving it below the fold.
    setTimeout(() => {
      const cards = list.querySelectorAll('[data-q]');
      const last = cards[cards.length - 1];
      if (last) {
        last.scrollIntoView({ behavior: 'smooth', block: 'center' });
        last.querySelector('[data-field="text"]')?.focus();
      }
    }, 60);
  };

  const saveBtn = document.getElementById('save-btn');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      syncFromDom();

      const grand = kindSelect.value === 'grand';
      const attemptsRaw = document.getElementById('s-attempts').value;

      const payload = {
        title: document.getElementById('s-title').value.trim(),
        description: document.getElementById('s-desc').value.trim() || null,
        kind: kindSelect.value,
        duration_minutes: grand ? Number(document.getElementById('s-duration').value) || 30 : null,
        pass_percent: Number(document.getElementById('s-pass').value) || 0,
        max_attempts: grand ? (attemptsRaw ? Number(attemptsRaw) : 1) : (attemptsRaw ? Number(attemptsRaw) : null),
        negative_marking: negativeToggle.checked,
        shuffle_questions: document.getElementById('s-shuffle').checked,
        is_published: document.getElementById('s-published').checked,
        questions: questions.map((q) => ({
          text: q.text.trim(),
          qtype: q.qtype,
          marks: Number(q.marks) || 1,
          negative_marks: Number(q.negativeMarks) || 0,
          explanation: q.explanation.trim() || null,
          numeric_answer: q.qtype === 'numeric' ? q.numericAnswer : null,
          numeric_tolerance: Number(q.numericTolerance) || 0,
          choices: q.qtype === 'numeric'
            ? []
            : q.choices.filter((c) => c.text.trim()).map((c) => ({
                text: c.text.trim(),
                is_correct: c.isCorrect,
              })),
        })),
      };

      setLoading(saveBtn, true);
      try {
        const result = await api(`/teach/api/tests/${test.id}`, { method: 'PUT', body: payload });
        showToast(`Saved — ${result.questions} questions, ${result.totalMarks} marks.`, 'success');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setLoading(saveBtn, false);
      }
    });

    // Ctrl/Cmd+S saves, as it does in every other editor.
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        saveBtn.click();
      }
    });
  }

  render();
})();
