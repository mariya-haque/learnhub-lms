/* ==========================================================================
   LearnHub — lecture player
   Resume-where-you-left-off, periodic progress pings, and completion.

   Only uploaded/direct files get progress tracking: a YouTube or Vimeo iframe
   is a cross-origin document, so its currentTime is not readable without
   loading their SDK. Those lectures rely on the manual "Mark as complete"
   button instead, which is why the button is always visible.
   ========================================================================== */

(() => {
  const dataEl = document.getElementById('lecture-data');
  if (!dataEl) return;

  const data = JSON.parse(dataEl.textContent);
  const video = document.getElementById('lecture-video');
  const completeBtn = document.getElementById('complete-btn');
  const completeLabel = document.getElementById('complete-label');
  const ring = document.getElementById('course-ring');
  const ringPct = document.getElementById('course-ring-pct');

  const PING_SECONDS = 15;
  let lastPingAt = 0;
  let completed = Boolean(data.completed);
  let autoAdvanced = false;

  /* ------------------------------ Progress ------------------------------- */

  async function ping(position, duration, force = false) {
    try {
      const result = await api(`/learn/api/${data.lectureId}/progress`, {
        method: 'POST',
        body: {
          position_seconds: Math.max(0, position || 0),
          duration_seconds: duration || null,
          completed: force || null,
        },
      });
      applyProgress(result);
    } catch {
      // A dropped ping is not worth interrupting playback over; the next one
      // carries the newer position anyway.
    }
  }

  function applyProgress(result) {
    if (!result) return;
    if (result.completed && !completed) {
      completed = true;
      paintCompleteButton();
      showToast('Lecture marked complete.', 'success');
    }
    if (ring && typeof result.course_percent === 'number') {
      ring.style.setProperty('--pct', result.course_percent);
      if (ringPct) ringPct.textContent = `${result.course_percent}%`;
    }
  }

  function paintCompleteButton() {
    if (!completeBtn) return;
    completeBtn.classList.toggle('btn-success', completed);
    completeBtn.classList.toggle('btn-soft', !completed);
    completeBtn.dataset.completed = String(completed);
    if (completeLabel) completeLabel.textContent = completed ? 'Completed' : 'Mark as complete';
  }

  /* -------------------------------- Video -------------------------------- */

  if (video && data.isFile) {
    // Resume, but not within the last 15 seconds -- landing on the credits and
    // having it end immediately feels broken.
    video.addEventListener('loadedmetadata', () => {
      const resume = Number(data.resumeAt) || 0;
      if (resume > 5 && resume < video.duration - 15) {
        video.currentTime = resume;
        showToast(`Resumed at ${formatClock(resume)}.`, 'info');
      }
      if (video.duration) ping(video.currentTime, video.duration);
    });

    video.addEventListener('timeupdate', () => {
      const now = video.currentTime;
      if (now - lastPingAt >= PING_SECONDS || lastPingAt - now > 30) {
        lastPingAt = now;
        ping(now, video.duration);
      }
    });

    video.addEventListener('pause', () => ping(video.currentTime, video.duration));

    video.addEventListener('ended', () => {
      ping(video.duration, video.duration, true);
      if (data.nextUrl && !autoAdvanced) {
        autoAdvanced = true;
        showToast('Next lecture in 5 seconds...', 'info');
        const timer = setTimeout(() => { window.location.href = data.nextUrl; }, 5000);
        // Any interaction cancels the auto-advance; nobody likes being moved
        // on while they are still reading.
        ['click', 'keydown', 'scroll'].forEach((evt) =>
          window.addEventListener(evt, () => clearTimeout(timer), { once: true })
        );
      }
    });

    // Best-effort final position when the tab closes.
    window.addEventListener('pagehide', () => {
      if (!video.currentTime) return;
      const blob = new Blob(
        [JSON.stringify({
          position_seconds: video.currentTime,
          duration_seconds: video.duration || null,
        })],
        { type: 'application/json' }
      );
      navigator.sendBeacon(`/learn/api/${data.lectureId}/progress`, blob);
    });

    // Space plays/pauses unless the user is typing.
    document.addEventListener('keydown', (event) => {
      const tag = (event.target.tagName || '').toLowerCase();
      if (['input', 'textarea', 'select'].includes(tag)) return;
      if (event.code === 'Space') {
        event.preventDefault();
        video.paused ? video.play() : video.pause();
      } else if (event.key === 'ArrowRight' && event.shiftKey) {
        video.currentTime = Math.min(video.duration, video.currentTime + 10);
      } else if (event.key === 'ArrowLeft' && event.shiftKey) {
        video.currentTime = Math.max(0, video.currentTime - 10);
      }
    });
  }

  /* ------------------------------ Completion ------------------------------ */

  if (completeBtn) {
    completeBtn.addEventListener('click', async () => {
      setLoading(completeBtn, true);
      try {
        const result = await api(`/learn/api/${data.lectureId}/complete`, { method: 'POST' });
        completed = result.completed;
        paintCompleteButton();
        if (ring && typeof result.course_percent === 'number') {
          ring.style.setProperty('--pct', result.course_percent);
          if (ringPct) ringPct.textContent = `${result.course_percent}%`;
        }
        showToast(completed ? 'Marked complete.' : 'Marked as not watched.', completed ? 'success' : 'info');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setLoading(completeBtn, false);
      }
    });
  }
})();
