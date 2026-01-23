const state = {
  labels: [],
  images: [],
  currentIndex: -1,
  currentImage: null,
  pendingPointDisplay: null,
  activeLabel: null,
  annotations: [],
  newTraversal: false,
  isSaving: false,
  imageMeta: null, // { image_size:{width,height}, exif_orientation, display_size, point_space }
};

const dom = {};

document.addEventListener('DOMContentLoaded', () => {
  dom.imageList = document.getElementById('imageList');
  dom.imageMain = document.getElementById('imageMain');
  dom.imageWrapper = document.getElementById('imageWrapper');
  dom.pendingMarker = document.getElementById('pendingMarker');
  dom.markersLayer = document.getElementById('markersLayer');
  dom.labelBar = document.getElementById('labelBar');
  dom.annotationChips = document.getElementById('annotationChips');
  dom.saveStatus = document.getElementById('saveStatus');
  dom.statusLine = document.getElementById('statusLine');
  dom.imageTitle = document.getElementById('imageTitle');
  dom.imageMeta = document.getElementById('imageMeta');
  dom.prevBtn = document.getElementById('prevBtn');
  dom.nextBtn = document.getElementById('nextBtn');
  dom.newTraverseBtn = document.getElementById('newTraverseBtn');
  dom.traverseCount = document.getElementById('traverseCount');

  dom.prevBtn.addEventListener('click', () => navigate(-1));
  dom.nextBtn.addEventListener('click', () => navigate(1));

  dom.newTraverseBtn.addEventListener('click', () => {
    state.newTraversal = !state.newTraversal;
    // Reflect immediately in the list (traversal count is computed from list state).
    const img = state.images[state.currentIndex];
    if (img) {
      img.result = img.result || { file: img.file, new_traversal: false, annotations: [] };
      img.result.new_traversal = state.newTraversal;
    }
    applyNewTraverseButton();
    updateTraverseCount();
    markDirty('New traverse toggled.');
  });

  dom.imageMain.addEventListener('click', handleImageClick);
  dom.imageMain.addEventListener('load', () => {
    applyPendingMarker();
    renderMarkers();
  });
  dom.imageMain.addEventListener('error', () => {
    setStatus('Failed to load image.');
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      navigate(-1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      navigate(1);
    } else if (event.key === 'Escape') {
      clearPending();
    }
  });

  window.addEventListener('beforeunload', () => {
    // Best-effort; navigation already saves reliably.
    if (state.currentImage && !state.isSaving) {
      navigator.sendBeacon?.(
        `/api/images/${encodeURIComponent(state.currentImage.id)}/annotation`,
        new Blob(
          [
            JSON.stringify({
              new_traversal: state.newTraversal,
              annotations: serializeAnnotations(),
            }),
          ],
          { type: 'application/json' },
        ),
      );
    }
  });

  bootstrap();
});

async function bootstrap() {
  setStatus('Loading…');
  try {
    const [labelsRes, imagesRes] = await Promise.all([fetch('/api/labels'), fetch('/api/images')]);
    if (!labelsRes.ok || !imagesRes.ok) {
      throw new Error('Failed to load');
    }
    state.labels = await labelsRes.json();
    state.images = await imagesRes.json();
    renderLabelBar();
    renderImageList();
    if (state.images.length > 0) {
      await loadImageAt(0);
      setStatus('');
    } else {
      setStatus('No images found in the folder.');
    }
  } catch (err) {
    console.error(err);
    setStatus('Failed to load labels/images.');
  }
}

function renderImageList() {
  dom.imageList.innerHTML = '';
  if (!state.images.length) {
    const empty = document.createElement('div');
    empty.textContent = 'No images found.';
    empty.className = 'empty';
    dom.imageList.appendChild(empty);
    return;
  }

  state.images.forEach((img, idx) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'scene-item';
    if (img.id === state.currentImage?.id) {
      button.classList.add('active');
    }
    if (img.completed) {
      button.classList.add('completed');
    }
    if (img.annotated) {
      button.classList.add('annotated');
    }
    button.dataset.index = String(idx);

    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = img.file;

    const dot = document.createElement('span');
    dot.className = 'status-dot';

    button.appendChild(label);
    button.appendChild(dot);

    button.addEventListener('click', () => jumpToIndex(idx));
    dom.imageList.appendChild(button);
  });
}

function renderLabelBar() {
  dom.labelBar.innerHTML = '';
  state.labels.forEach((label) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'label-btn';
    btn.textContent = label;
    btn.dataset.label = label;
    btn.addEventListener('click', () => handleLabelClick(label));
    dom.labelBar.appendChild(btn);
  });
  syncLabelButtonStates();
}

function handleLabelClick(label) {
  if (!state.currentImage) return;

  if (state.pendingPointDisplay) {
    const rawPoint = displayToRawPoint(state.pendingPointDisplay);
    state.annotations.push({ category: label, point: rawPoint });
    clearPending();
    state.activeLabel = label;
    syncLabelButtonStates();
    renderMarkers();
    renderChips();
    markDirty(`Added ${label}.`);
    return;
  }

  // Arm a label for faster annotation: select label, then click image to place point.
  state.activeLabel = state.activeLabel === label ? null : label;
  syncLabelButtonStates();
}

function handleImageClick(event) {
  if (!state.currentImage) return;
  if (!dom.imageMain.naturalWidth || !dom.imageMain.naturalHeight) return;

  const rect = dom.imageMain.getBoundingClientRect();
  const scaleX = dom.imageMain.naturalWidth / rect.width;
  const scaleY = dom.imageMain.naturalHeight / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;
  if (x < 0 || y < 0) return;

  if (state.activeLabel) {
    const rawPoint = displayToRawPoint({ x, y });
    state.annotations.push({ category: state.activeLabel, point: rawPoint });
    clearPending();
    syncLabelButtonStates();
    renderMarkers();
    renderChips();
    markDirty(`Added ${state.activeLabel}.`);
    return;
  }

  state.pendingPointDisplay = { x, y };
  applyPendingMarker();
  dom.saveStatus.textContent = 'Select a label to assign this point (or press Esc).';
}

function applyPendingMarker() {
  if (!state.pendingPointDisplay || !dom.imageMain.naturalWidth || !dom.imageMain.naturalHeight) {
    dom.pendingMarker.classList.add('hidden');
    return;
  }
  const leftPercent = (state.pendingPointDisplay.x / dom.imageMain.naturalWidth) * 100;
  const topPercent = (state.pendingPointDisplay.y / dom.imageMain.naturalHeight) * 100;
  dom.pendingMarker.style.left = `${leftPercent}%`;
  dom.pendingMarker.style.top = `${topPercent}%`;
  dom.pendingMarker.classList.remove('hidden');
}

function clearPending() {
  state.pendingPointDisplay = null;
  dom.pendingMarker.classList.add('hidden');
}

function renderMarkers() {
  dom.markersLayer.innerHTML = '';
  if (!dom.imageMain.naturalWidth || !dom.imageMain.naturalHeight) return;

  state.annotations.forEach((ann, idx) => {
    const el = document.createElement('div');
    el.className = 'point-marker';
    const color = colorForLabel(ann.category);
    el.style.background = color;
    const disp = rawToDisplayPoint(ann.point);
    const leftPercent = (disp.x / dom.imageMain.naturalWidth) * 100;
    const topPercent = (disp.y / dom.imageMain.naturalHeight) * 100;
    el.style.left = `${leftPercent}%`;
    el.style.top = `${topPercent}%`;
    el.title = `${ann.category} (${formatNumber(ann.point.x)}, ${formatNumber(ann.point.y)})`;
    el.dataset.index = String(idx);
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      removeAnnotationAt(idx);
    });
    dom.markersLayer.appendChild(el);
  });
}

function removeAnnotationAt(index) {
  if (index < 0 || index >= state.annotations.length) return;
  const removed = state.annotations[index];
  state.annotations.splice(index, 1);
  syncLabelButtonStates();
  renderMarkers();
  renderChips();
  markDirty(`Removed ${removed.category}.`);
}

function renderChips() {
  dom.annotationChips.innerHTML = '';
  if (!state.annotations.length) {
    const empty = document.createElement('div');
    empty.className = 'hint';
    empty.textContent = 'No labeled points yet (navigate with arrows to mark completion).';
    dom.annotationChips.appendChild(empty);
    return;
  }
  state.annotations.forEach((ann, idx) => {
    const chip = document.createElement('span');
    chip.className = 'chip';

    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = colorForLabel(ann.category);

    const text = document.createElement('span');
    text.textContent = `${ann.category} @ (${formatNumber(ann.point.x)}, ${formatNumber(ann.point.y)})`;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '×';
    btn.addEventListener('click', () => removeAnnotationAt(idx));

    chip.appendChild(swatch);
    chip.appendChild(text);
    chip.appendChild(btn);
    dom.annotationChips.appendChild(chip);
  });
}

function syncLabelButtonStates() {
  const counts = new Map();
  state.annotations.forEach((ann) => {
    counts.set(ann.category, (counts.get(ann.category) || 0) + 1);
  });
  dom.labelBar.querySelectorAll('.label-btn').forEach((btn) => {
    const label = btn.dataset.label;
    const has = counts.get(label) > 0;
    btn.classList.toggle('has', Boolean(has));
    btn.classList.toggle('active', state.activeLabel === label);
  });
}

function applyNewTraverseButton() {
  dom.newTraverseBtn.classList.toggle('on', Boolean(state.newTraversal));
}

function updateTraverseCount() {
  const idx = state.currentIndex;
  if (idx < 0) {
    dom.traverseCount.textContent = '';
    return;
  }
  // Traversal count starts at 1; each "new_traversal" image starts a new chapter.
  let count = 1;
  for (let i = 0; i <= idx; i += 1) {
    if (i === 0) continue;
    const img = state.images[i];
    if (img?.result?.new_traversal) {
      count += 1;
    }
  }
  const isStart = Boolean(state.images[idx]?.result?.new_traversal);
  dom.traverseCount.textContent = `Traversal: ${count}${isStart ? ' (start)' : ''}`;
}

async function jumpToIndex(index) {
  if (index === state.currentIndex) return;
  await saveCurrentIfNeeded({ reason: 'jump' });
  await loadImageAt(index);
}

async function navigate(delta) {
  if (!state.images.length) return;
  if (state.isSaving) return;
  const nextIndex = clamp(state.currentIndex + delta, 0, state.images.length - 1);
  if (nextIndex === state.currentIndex) return;
  await saveCurrentIfNeeded({ reason: 'nav' });
  await loadImageAt(nextIndex);
}

async function loadImageAt(index) {
  if (index < 0 || index >= state.images.length) return;
  state.currentIndex = index;
  const imgMeta = state.images[index];
  setStatus(`Loading ${imgMeta.file}…`);
  clearPending();

  try {
    const res = await fetch(`/api/images/${encodeURIComponent(imgMeta.id)}`);
    if (!res.ok) throw new Error('Image not found');
    const payload = await res.json();
    state.currentImage = payload;
    state.imageMeta = payload.meta || null;

    // Load existing result (if any).
    const result = payload.result || null;
    state.annotations = normalizeAnnotations(result?.annotations || []);
    state.newTraversal = Boolean(result?.new_traversal);
    state.activeLabel = null;

    // Keep list entry in sync with authoritative payload.
    const listItem = state.images[index];
    if (listItem) {
      listItem.result = result;
      listItem.completed = Boolean(result);
      listItem.annotated = Array.isArray(result?.annotations) && result.annotations.length > 0;
    }

    dom.imageMain.src = payload.url;
    dom.imageTitle.textContent = payload.file;
    dom.imageMeta.textContent = `${index + 1}/${state.images.length}`;

    applyNewTraverseButton();
    syncLabelButtonStates();
    renderChips();
    renderImageList();
    updateTraverseCount();
    dom.saveStatus.textContent = '';
    setStatus('');
  } catch (err) {
    console.error(err);
    setStatus('Unable to load image.');
  }
}

function normalizeAnnotations(list) {
  if (!Array.isArray(list)) return [];
  const out = [];
  list.forEach((item) => {
    if (!item || typeof item !== 'object') return;
    const category = typeof item.category === 'string' ? item.category : null;
    const point = item.point && typeof item.point === 'object' ? item.point : null;
    if (!category || !point) return;
    const x = Number(point.x);
    const y = Number(point.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    out.push({ category, point: { x, y } });
  });
  return out;
}

function displayToRawPoint(displayPoint) {
  const meta = state.imageMeta || {};
  const rawSize = meta.image_size || null;
  const o = Number(meta.exif_orientation || 1);
  if (!rawSize || !Number.isFinite(rawSize.width) || !Number.isFinite(rawSize.height)) {
    // Fallback: store display coords if we don't know raw size.
    return { x: displayPoint.x, y: displayPoint.y };
  }
  const W = rawSize.width;
  const H = rawSize.height;
  const x = displayPoint.x;
  const y = displayPoint.y;

  // Inverse of EXIF transform (display -> raw).
  switch (o) {
    case 1: // normal
      return { x, y };
    case 2: // mirror horizontal
      return { x: W - x, y };
    case 3: // rotate 180
      return { x: W - x, y: H - y };
    case 4: // mirror vertical
      return { x, y: H - y };
    case 5: // transpose
      return { x: y, y: x };
    case 6: // rotate 90 CW
      return { x: y, y: H - x };
    case 7: // transverse
      return { x: W - y, y: H - x };
    case 8: // rotate 270 CW
      return { x: W - y, y: x };
    default:
      return { x, y };
  }
}

function rawToDisplayPoint(rawPoint) {
  const meta = state.imageMeta || {};
  const rawSize = meta.image_size || null;
  const o = Number(meta.exif_orientation || 1);
  if (!rawSize || !Number.isFinite(rawSize.width) || !Number.isFinite(rawSize.height)) {
    return { x: rawPoint.x, y: rawPoint.y };
  }
  const W = rawSize.width;
  const H = rawSize.height;
  const x = rawPoint.x;
  const y = rawPoint.y;

  // Forward EXIF transform (raw -> display).
  switch (o) {
    case 1:
      return { x, y };
    case 2:
      return { x: W - x, y };
    case 3:
      return { x: W - x, y: H - y };
    case 4:
      return { x, y: H - y };
    case 5:
      return { x: y, y: x };
    case 6:
      return { x: H - y, y: x };
    case 7:
      return { x: H - y, y: W - x };
    case 8:
      return { x: y, y: W - x };
    default:
      return { x, y };
  }
}

function serializeAnnotations() {
  return state.annotations.map((ann) => ({
    category: ann.category,
    point: { x: ann.point.x, y: ann.point.y },
  }));
}

async function saveCurrentIfNeeded({ reason }) {
  if (!state.currentImage) return;
  // Save on any navigation: this marks the image as "completed" (even if annotations is empty).
  await saveCurrent({ reason });
}

async function saveCurrent({ reason }) {
  if (!state.currentImage) return;
  if (state.isSaving) return;
  state.isSaving = true;
  dom.saveStatus.textContent = 'Saving…';

  try {
    const res = await fetch(`/api/images/${encodeURIComponent(state.currentImage.id)}/annotation`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        new_traversal: state.newTraversal,
        annotations: serializeAnnotations(),
      }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Save failed');
    }
    const payload = await res.json();
    const result = payload.result;

    // Update local list item flags.
    const img = state.images[state.currentIndex];
    if (img) {
      img.completed = true;
      img.annotated = Array.isArray(result?.annotations) && result.annotations.length > 0;
      img.result = result || null;
    }
    dom.saveStatus.textContent = reason === 'nav' ? '' : 'Saved.';
    renderImageList();
    updateTraverseCount();
  } catch (err) {
    console.error(err);
    dom.saveStatus.textContent = 'Failed to save.';
  } finally {
    state.isSaving = false;
  }
}

function markDirty(message) {
  dom.saveStatus.textContent = message || '';
  // Sidebar coloring updates only after save (by design): completion = saved entry.
}

function setStatus(message) {
  dom.statusLine.textContent = message || '';
}

function formatNumber(value) {
  return Number.parseFloat(value).toFixed(1);
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

function colorForLabel(label) {
  // Deterministic nice-ish color from string.
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) {
    hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue} 75% 50%)`;
}

