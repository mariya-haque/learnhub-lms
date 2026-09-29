/* ==========================================================================
   LearnHub — file uploads

   Uses XMLHttpRequest rather than fetch for one reason: fetch has no upload
   progress event, and a 400 MB lecture with no progress bar looks like a
   hung page.

   Expects COURSE_ID, MAX_VIDEO_MB and MAX_NOTE_MB to be defined by the page.
   ========================================================================== */

(() => {
  /**
   * Wire a <label class="dropzone"> to its file input: drag-and-drop, a click
   * to browse, and client-side size/type rejection before anything uploads.
   */
  function wireDropzone({ zoneId, inputId, titleId, maxMb, defaultTitle }) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    const title = document.getElementById(titleId);
    if (!zone || !input) return null;

    const state = { file: null };

    const accept = (input.getAttribute('accept') || '')
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);

    function setFile(file) {
      if (!file) return;

      const ext = `.${(file.name.split('.').pop() || '').toLowerCase()}`;
      if (accept.length && !accept.includes(ext)) {
        showToast(`${ext || 'That file type'} isn't allowed here.`, 'error');
        return;
      }
      if (file.size > maxMb * 1024 * 1024) {
        showToast(`That file is ${formatBytes(file.size)} — the limit is ${maxMb} MB.`, 'error');
        return;
      }

      state.file = file;
      zone.classList.add('has-file');
      title.textContent = `${file.name} (${formatBytes(file.size)})`;
    }

    function clear() {
      state.file = null;
      input.value = '';
      zone.classList.remove('has-file');
      title.textContent = defaultTitle;
    }

    input.addEventListener('change', () => setFile(input.files[0]));

    ['dragenter', 'dragover'].forEach((evt) =>
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.add('dragging');
      })
    );
    ['dragleave', 'drop'].forEach((evt) =>
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.remove('dragging');
      })
    );
    zone.addEventListener('drop', (e) => setFile(e.dataTransfer.files[0]));

    return { state, clear };
  }

  /** POST a FormData with a live progress bar. Resolves with the JSON body. */
  function uploadWithProgress(url, formData, ui) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      xhr.setRequestHeader('Accept', 'application/json');

      ui.wrap.classList.add('active');
      ui.bar.style.width = '0%';
      ui.pct.textContent = '0%';
      ui.label.textContent = 'Uploading...';

      xhr.upload.addEventListener('progress', (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.round((event.loaded / event.total) * 100);
        ui.bar.style.width = `${percent}%`;
        ui.pct.textContent = `${percent}%`;
        // The bar hits 100% well before the server has finished writing, so
        // say so rather than appearing stuck.
        if (percent === 100) ui.label.textContent = 'Processing on the server...';
      });

      xhr.addEventListener('load', () => {
        let body = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }

        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body);
        } else if (xhr.status === 401) {
          reject(new Error('Your session expired. Sign in again.'));
        } else {
          reject(new Error((body && (body.message || body.detail)) || `Upload failed (${xhr.status})`));
        }
      });

      xhr.addEventListener('error', () => reject(new Error('Network error during upload.')));
      xhr.addEventListener('abort', () => reject(new Error('Upload cancelled.')));

      xhr.send(formData);
    });
  }

  const progressUi = (prefix) => ({
    wrap: document.getElementById(`${prefix}-progress`),
    bar: document.getElementById(`${prefix}-progress-bar`),
    pct: document.getElementById(`${prefix}-progress-pct`),
    label: document.getElementById(`${prefix}-progress-label`),
  });

  /* ------------------------------- Lectures ------------------------------- */

  const videoZone = wireDropzone({
    zoneId: 'video-drop',
    inputId: 'video-file',
    titleId: 'video-drop-title',
    maxMb: typeof MAX_VIDEO_MB === 'number' ? MAX_VIDEO_MB : 512,
    defaultTitle: 'Drop a video here',
  });

  const uploadForm = document.getElementById('upload-form');
  if (uploadForm && videoZone) {
    uploadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!videoZone.state.file) {
        showToast('Choose a video file first.', 'warning');
        return;
      }

      const btn = uploadForm.querySelector('[type="submit"]');
      setLoading(btn, true);

      const form = new FormData();
      form.append('file', videoZone.state.file);
      form.append('title', document.getElementById('f-title').value.trim());
      form.append('description', document.getElementById('f-desc').value.trim());

      try {
        await uploadWithProgress(
          `/teach/api/courses/${COURSE_ID}/lectures/upload`,
          form,
          progressUi('video')
        );
        showToast('Lecture uploaded.', 'success');
        setTimeout(() => window.location.reload(), 600);
      } catch (error) {
        showToast(error.message, 'error');
        progressUi('video').wrap.classList.remove('active');
        setLoading(btn, false);
      }
    });
  }

  /* --------------------------------- Notes -------------------------------- */

  const noteZone = wireDropzone({
    zoneId: 'note-drop',
    inputId: 'note-file',
    titleId: 'note-drop-title',
    maxMb: typeof MAX_NOTE_MB === 'number' ? MAX_NOTE_MB : 32,
    defaultTitle: 'Drop a file here',
  });

  const noteForm = document.getElementById('note-form');
  if (noteForm && noteZone) {
    noteForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!noteZone.state.file) {
        showToast('Choose a file first.', 'warning');
        return;
      }

      const btn = noteForm.querySelector('[type="submit"]');
      setLoading(btn, true);

      const form = new FormData();
      form.append('file', noteZone.state.file);
      form.append('title', document.getElementById('n-title').value.trim());
      form.append('lecture_id', document.getElementById('n-lecture').value);
      form.append('description', '');

      try {
        await uploadWithProgress(`/teach/api/courses/${COURSE_ID}/notes`, form, progressUi('note'));
        showToast('Note uploaded.', 'success');
        setTimeout(() => window.location.reload(), 600);
      } catch (error) {
        showToast(error.message, 'error');
        progressUi('note').wrap.classList.remove('active');
        setLoading(btn, false);
      }
    });
  }
})();
