const state = {
  scenes: [],
  currentSceneId: null,
  currentScene: null,
  annotationPoint: null,
  refinementPoints: [],
  maskPreviewUrl: null,
  maskReady: false,
  maskModelReady: false,
  maskModelMessage: '',
};

const dom = {};

document.addEventListener('DOMContentLoaded', () => {
  dom.sceneSelect = document.getElementById('sceneSelect');
  dom.nextScene = document.getElementById('nextScene');
  dom.sceneStatus = document.getElementById('sceneStatus');
  dom.sceneList = document.getElementById('sceneList');
  dom.imageA = document.getElementById('imageA');
  dom.imageB = document.getElementById('imageB');
  dom.imageBWrapper = document.getElementById('imageBWrapper');
  dom.pointLayer = document.getElementById('pointLayer');
  dom.maskOverlay = document.getElementById('maskOverlay');
  dom.annotationSummary = document.getElementById('annotationSummary');
  dom.coordinateDisplay = document.getElementById('coordinateDisplay');
  dom.labelInput = document.getElementById('labelInput');
  dom.generateMaskBtn = document.getElementById('generateMaskBtn');
  dom.clearPointsBtn = document.getElementById('clearPointsBtn');
  dom.confirmBtn = document.getElementById('confirmBtn');
  dom.cancelBtn = document.getElementById('cancelBtn');
  dom.maskStatus = document.getElementById('maskStatus');
  dom.saveStatus = document.getElementById('saveStatus');
  dom.sceneStatus.dataset.locked = 'false';
  dom.uploadForm = document.getElementById('uploadForm');
  dom.uploadSceneId = document.getElementById('uploadSceneId');
  dom.uploadImageA = document.getElementById('uploadImageA');
  dom.uploadImageB = document.getElementById('uploadImageB');
  dom.uploadStatus = document.getElementById('uploadStatus');

  dom.sceneSelect.addEventListener('change', (event) => {
    loadScene(event.target.value);
  });

  dom.nextScene.addEventListener('click', () => {
    const next = getNextSceneId();
    if (next) {
      loadScene(next);
    }
  });

  document.addEventListener('keydown', handleSceneHotkeys);

  dom.imageB.addEventListener('click', (event) => handleImageClick(event, 'positive'));
  dom.imageB.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    handleImageClick(event, 'negative');
  });
  dom.imageB.addEventListener('load', () => {
    renderPointMarkers();
  });
  dom.imageB.addEventListener('error', () => {
    dom.pointLayer.innerHTML = '';
    dom.maskOverlay.classList.add('hidden');
    setStatus('Failed to load Image B.');
  });

  dom.generateMaskBtn.addEventListener('click', previewMask);
  dom.clearPointsBtn.addEventListener('click', clearMaskPoints);
  dom.confirmBtn.addEventListener('click', submitAnnotation);
  dom.cancelBtn.addEventListener('click', () => {
    hydrateEditingStateFromSaved();
    dom.saveStatus.textContent = '';
    dom.maskStatus.textContent = '';
    renderPointMarkers();
    updateAnnotationSummary();
    updateCoordinateDisplay();
  });

  if (dom.uploadForm) {
    dom.uploadForm.addEventListener('submit', handleUploadSubmit);
  }

  fetchMaskStatus().finally(fetchScenes);
});

async function fetchMaskStatus() {
  try {
    const response = await fetch('/api/mask/status');
    if (!response.ok) {
      throw new Error('Failed to load mask status');
    }
    const payload = await response.json();
    state.maskModelReady = Boolean(payload.ready);
    state.maskModelMessage = payload.message || '';
  } catch (error) {
    console.error(error);
    state.maskModelReady = false;
    state.maskModelMessage = 'Mask model status unavailable.';
  }
}

async function fetchScenes() {
  setStatus('Loading scenes…');
  try {
    const response = await fetch('/api/scenes');
    if (!response.ok) {
      throw new Error('Unable to load scenes');
    }
    const scenes = await response.json();
    state.scenes = scenes;
    renderSceneOptions();
    renderSceneList();
    if (scenes.length > 0) {
      loadScene(scenes[0].id);
    } else {
      setStatus('No scenes found in the dataset folder.');
    }
  } catch (error) {
    console.error(error);
    setStatus('Failed to load scenes. Make sure the path is correct.');
  }
}

function renderSceneOptions() {
  const select = dom.sceneSelect;
  select.innerHTML = '';
  state.scenes.forEach((scene) => {
    const option = document.createElement('option');
    option.value = scene.id;
    option.textContent = `${scene.annotated ? '🟢' : '⚪'} ${scene.name}`;
    option.dataset.annotated = scene.annotated ? 'true' : 'false';
    select.appendChild(option);
  });
  if (state.currentSceneId) {
    select.value = state.currentSceneId;
  }
}

function renderSceneList() {
  const list = dom.sceneList;
  list.innerHTML = '';
  if (state.scenes.length === 0) {
    const empty = document.createElement('div');
    empty.textContent = 'No scene folders found.';
    empty.className = 'empty';
    list.appendChild(empty);
    return;
  }

  state.scenes.forEach((scene) => {
    const button = document.createElement('button');
    button.className = 'scene-item';
    if (scene.annotated) {
      button.classList.add('annotated');
    }
    if (scene.id === state.currentSceneId) {
      button.classList.add('active');
    }
    button.type = 'button';
    button.dataset.sceneId = scene.id;

    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = scene.name;

    const dot = document.createElement('span');
    dot.className = 'status-dot';

    button.appendChild(label);
    button.appendChild(dot);

    button.addEventListener('click', () => loadScene(scene.id));
    list.appendChild(button);
  });
}

function getNextSceneId() {
  if (!state.currentSceneId || state.scenes.length === 0) {
    return null;
  }
  const idx = state.scenes.findIndex((scene) => scene.id === state.currentSceneId);
  if (idx === -1) {
    return null;
  }
  const nextIndex = (idx + 1) % state.scenes.length;
  return state.scenes[nextIndex].id;
}

function getPrevSceneId() {
  if (!state.currentSceneId || state.scenes.length === 0) {
    return null;
  }
  const idx = state.scenes.findIndex((scene) => scene.id === state.currentSceneId);
  if (idx === -1) {
    return null;
  }
  const prevIndex = (idx - 1 + state.scenes.length) % state.scenes.length;
  return state.scenes[prevIndex].id;
}

function handleSceneHotkeys(event) {
  if (isTypingTarget(event.target)) {
    return;
  }
  if (event.key === 'ArrowRight') {
    const next = getNextSceneId();
    if (next) {
      event.preventDefault();
      loadScene(next);
    }
  } else if (event.key === 'ArrowLeft') {
    const prev = getPrevSceneId();
    if (prev) {
      event.preventDefault();
      loadScene(prev);
    }
  }
}

async function loadScene(sceneId) {
  if (!sceneId) {
    return;
  }
  setStatus('Loading scene…');
  try {
    const response = await fetch(`/api/scenes/${encodeURIComponent(sceneId)}`);
    if (!response.ok) {
      throw new Error('Scene not found');
    }
    const data = await response.json();
    state.currentSceneId = sceneId;
    state.currentScene = data;

    dom.sceneSelect.value = sceneId;
    renderSceneList();

    setImage(dom.imageA, data.images?.a);
    setImage(dom.imageB, data.images?.b);

    dom.labelInput.value = data.annotation?.label || '';
    hydrateEditingStateFromSaved();
    renderPointMarkers();
    updateAnnotationSummary();
    updateCoordinateDisplay();
    updateControlState();
    dom.saveStatus.textContent = '';
    dom.maskStatus.textContent = state.maskModelReady ? '' : state.maskModelMessage;
    setStatus('');
  } catch (error) {
    console.error(error);
    setStatus('Unable to load scene.');
  }
}

function setImage(imgElement, src) {
  if (src) {
    imgElement.src = src;
    imgElement.classList.remove('empty');
  } else {
    imgElement.removeAttribute('src');
    imgElement.classList.add('empty');
  }
}

function updateSceneStatus(force = false) {
  if (!force && dom.sceneStatus.dataset.locked === 'true') {
    return;
  }
  const currentIndex = state.scenes.findIndex((scene) => scene.id === state.currentSceneId);
  if (currentIndex === -1) {
    dom.sceneStatus.textContent = '';
    return;
  }
  const scene = state.scenes[currentIndex];
  const annotated = state.currentScene?.annotation || scene.annotated;
  const label = annotated ? '🟢 Annotated' : '⚪ Pending';
  dom.sceneStatus.textContent = `Scene ${currentIndex + 1}/${state.scenes.length} • ${label}`;
}

function updateAnnotationSummary() {
  const container = dom.annotationSummary;
  const hasAnnotationPoint = Boolean(state.annotationPoint);
  const pending = hasAnnotationPoint || state.refinementPoints.length > 0;
  const saved = state.currentScene?.annotation;
  container.innerHTML = '';

  if (pending) {
    const pill = document.createElement('span');
    pill.className = 'status-pill pending';
    pill.textContent = 'Editing annotation';

    const text = document.createElement('div');
    const positives = state.refinementPoints.filter((point) => point.kind === 'positive').length;
    const negatives = state.refinementPoints.length - positives;
    const annotationText = hasAnnotationPoint
      ? `Annotation point set (${formatNumber(state.annotationPoint.x)}, ${formatNumber(state.annotationPoint.y)}).`
      : 'Annotation point not set.';
    text.textContent = `${annotationText} Refinement points: +${positives} / -${negatives}.`;

    container.appendChild(pill);
    container.appendChild(text);
    return;
  }

  if (saved) {
    const pill = document.createElement('span');
    pill.className = 'status-pill annotated';
    pill.innerHTML = 'Annotated <span aria-hidden="true">✓</span>';

    const detail = document.createElement('div');
    const maskText = saved.mask ? ' • Mask saved' : '';
    detail.textContent = `Label: ${saved.label} • Point: (${formatNumber(saved.x)}, ${formatNumber(saved.y)})${maskText}`;

    container.appendChild(pill);
    container.appendChild(detail);
    return;
  }

  container.textContent = 'No saved annotation yet.';
}

function handleImageClick(event, kind) {
  if (!state.currentScene) {
    return;
  }
  if (!state.maskModelReady && kind === 'negative') {
    dom.maskStatus.textContent = state.maskModelMessage || 'Mask model is not ready. Right-click refinement is unavailable.';
    return;
  }
  if (!dom.imageB.naturalWidth) {
    setStatus('Image B is not loaded yet.');
    return;
  }
  const renderRect = getRenderedImageRect(dom.imageB);
  if (!renderRect) {
    return;
  }
  const localX = event.clientX - renderRect.left;
  const localY = event.clientY - renderRect.top;
  if (localX < 0 || localY < 0 || localX > renderRect.width || localY > renderRect.height) {
    // Click landed in the letterbox (black bars), ignore it.
    return;
  }
  const x = (localX / renderRect.width) * dom.imageB.naturalWidth;
  const y = (localY / renderRect.height) * dom.imageB.naturalHeight;
  if (x < 0 || y < 0 || x > dom.imageB.naturalWidth || y > dom.imageB.naturalHeight) {
    return;
  }
  if (kind === 'positive' && !state.annotationPoint) {
    state.annotationPoint = { x, y };
  } else {
    state.refinementPoints.push({ x, y, kind });
  }
  if (!dom.labelInput.value.trim() && state.currentScene.annotation?.label) {
    dom.labelInput.value = state.currentScene.annotation.label;
  }
  updateControlState();
  const pointCount = (state.annotationPoint ? 1 : 0) + state.refinementPoints.length;
  if (pointCount === 1) {
    dom.labelInput.focus();
    dom.labelInput.select();
  }
  dom.saveStatus.textContent = '';
  dom.maskStatus.textContent = '';
  state.maskReady = false;
  hideMaskOverlay();

  renderPointMarkers();
  updateAnnotationSummary();
  updateCoordinateDisplay();
}

function clearMaskPoints() {
  if (!state.currentScene) {
    return;
  }
  state.annotationPoint = null;
  state.refinementPoints = [];
  state.maskReady = false;
  hideMaskOverlay();
  dom.maskStatus.textContent = '';
  dom.saveStatus.textContent = '';
  renderPointMarkers();
  updateControlState();
  updateAnnotationSummary();
  updateCoordinateDisplay();
}

function updateCoordinateDisplay() {
  if (state.annotationPoint || state.refinementPoints.length > 0) {
    const positives = state.refinementPoints.filter((point) => point.kind === 'positive').length;
    const negatives = state.refinementPoints.length - positives;
    if (state.annotationPoint) {
      dom.coordinateDisplay.textContent = `Annotation: (${formatNumber(state.annotationPoint.x)}, ${formatNumber(state.annotationPoint.y)}) • Refinement +${positives} / -${negatives}`;
    } else {
      dom.coordinateDisplay.textContent = `Set annotation point first (left click). Refinement +${positives} / -${negatives}`;
    }
    return;
  }
  const saved = state.currentScene?.annotation;
  if (saved) {
    dom.coordinateDisplay.textContent = `Saved: (${formatNumber(saved.x)}, ${formatNumber(saved.y)})`;
    return;
  }
  dom.coordinateDisplay.textContent = 'First left click sets annotation point. Then use left/right clicks to refine mask.';
}

function updateControlState() {
  const hasScene = Boolean(state.currentScene);
  const hasAnnotationPoint = Boolean(state.annotationPoint);
  const hasAnyPoints = hasAnnotationPoint || state.refinementPoints.length > 0;
  dom.labelInput.disabled = !hasScene;
  dom.generateMaskBtn.disabled = !hasScene || !hasAnnotationPoint || !state.maskModelReady;
  dom.clearPointsBtn.disabled = !hasScene || !hasAnyPoints;
  dom.cancelBtn.disabled = !hasScene;
  dom.confirmBtn.disabled = !hasScene || !hasAnnotationPoint || (state.maskModelReady && !state.maskReady);
}

function renderPointMarkers() {
  dom.pointLayer.innerHTML = '';
  if (!dom.imageB.naturalWidth || !dom.imageB.naturalHeight) {
    return;
  }
  if (!state.annotationPoint && !state.refinementPoints.length) {
    return;
  }
  const renderRect = getRenderedImageRect(dom.imageB);
  const wrapperRect = dom.imageBWrapper.getBoundingClientRect();
  if (!renderRect || !wrapperRect.width || !wrapperRect.height) {
    return;
  }
  const offsetX = renderRect.left - wrapperRect.left;
  const offsetY = renderRect.top - wrapperRect.top;
  const allPoints = [];
  if (state.annotationPoint) {
    allPoints.push({ ...state.annotationPoint, kind: 'annotation' });
  }
  state.refinementPoints.forEach((point) => allPoints.push(point));

  allPoints.forEach((point) => {
    const marker = document.createElement('div');
    marker.className = 'click-marker';
    if (point.kind === 'annotation') {
      marker.classList.add('annotation');
    } else if (point.kind === 'negative') {
      marker.classList.add('negative');
    }
    const x = offsetX + (point.x / dom.imageB.naturalWidth) * renderRect.width;
    const y = offsetY + (point.y / dom.imageB.naturalHeight) * renderRect.height;
    marker.style.left = `${x}px`;
    marker.style.top = `${y}px`;
    dom.pointLayer.appendChild(marker);
  });
}

function getRenderedImageRect(imageElement) {
  if (!imageElement.naturalWidth || !imageElement.naturalHeight) {
    return null;
  }
  const rect = imageElement.getBoundingClientRect();
  if (!rect.width || !rect.height) {
    return null;
  }
  const imageRatio = imageElement.naturalWidth / imageElement.naturalHeight;
  const boxRatio = rect.width / rect.height;
  let width = rect.width;
  let height = rect.height;
  if (boxRatio > imageRatio) {
    width = rect.height * imageRatio;
    height = rect.height;
  } else {
    width = rect.width;
    height = rect.width / imageRatio;
  }
  const left = rect.left + (rect.width - width) / 2;
  const top = rect.top + (rect.height - height) / 2;
  return { left, top, width, height };
}

function hideMaskOverlay() {
  state.maskPreviewUrl = null;
  dom.maskOverlay.removeAttribute('src');
  dom.maskOverlay.classList.add('hidden');
}

function showMaskOverlay(url) {
  state.maskPreviewUrl = url;
  dom.maskOverlay.src = url;
  dom.maskOverlay.classList.remove('hidden');
}

function hydrateEditingStateFromSaved() {
  const saved = state.currentScene?.annotation;
  if (!saved) {
    state.annotationPoint = null;
    state.refinementPoints = [];
    state.maskReady = false;
    hideMaskOverlay();
    updateControlState();
    return;
  }

  if (saved.annotation_point && Number.isFinite(Number(saved.annotation_point.x)) && Number.isFinite(Number(saved.annotation_point.y))) {
    state.annotationPoint = {
      x: Number(saved.annotation_point.x),
      y: Number(saved.annotation_point.y),
    };
  } else {
    state.annotationPoint = { x: Number(saved.x), y: Number(saved.y) };
  }

  state.refinementPoints = [];
  if (Array.isArray(saved.mask_points) && saved.mask_points.length > 0) {
    let annotationMatched = false;
    saved.mask_points.forEach((point) => {
      const px = Number(point.x);
      const py = Number(point.y);
      const kind = point.kind === 'negative' ? 'negative' : 'positive';
      if (!Number.isFinite(px) || !Number.isFinite(py)) {
        return;
      }
      if (!annotationMatched && kind === 'positive' && state.annotationPoint && nearlyEqual(px, state.annotationPoint.x) && nearlyEqual(py, state.annotationPoint.y)) {
        annotationMatched = true;
        return;
      }
      state.refinementPoints.push({ x: px, y: py, kind });
    });
  }
  if (saved.mask_url) {
    showMaskOverlay(saved.mask_url);
    state.maskReady = true;
  } else {
    hideMaskOverlay();
    state.maskReady = false;
  }
  updateControlState();
}

async function previewMask() {
  if (!state.currentScene || !state.annotationPoint) {
    return;
  }
  const label = dom.labelInput.value.trim();
  if (!label) {
    dom.maskStatus.textContent = 'Please provide a label before generating mask.';
    dom.labelInput.focus();
    return;
  }
  dom.maskStatus.textContent = 'Generating mask…';
  hideMaskOverlay();
  state.maskReady = false;
  updateControlState();
  try {
    const response = await fetch(`/api/scenes/${encodeURIComponent(state.currentScene.id)}/mask-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        points: buildMaskPointsPayload(),
        label,
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Mask generation failed');
    }
    const payload = await response.json();
    const dataUrl = `data:image/png;base64,${payload.mask_png_base64}`;
    showMaskOverlay(dataUrl);
    state.maskReady = true;
    dom.maskStatus.textContent = `Mask ready (score ${Number(payload.score).toFixed(3)}). Add more points and regenerate if needed.`;
    updateControlState();
  } catch (error) {
    console.error(error);
    state.maskReady = false;
    updateControlState();
    dom.maskStatus.textContent = `Failed to generate mask: ${error?.message || 'unknown error'}`;
  }
}

async function submitAnnotation() {
  if (!state.currentScene) {
    return;
  }
  if (!state.annotationPoint) {
    dom.saveStatus.textContent = 'Set annotation point (left click) before confirming.';
    return;
  }
  const label = dom.labelInput.value.trim();
  if (!label) {
    dom.saveStatus.textContent = 'Please provide a label before confirming.';
    dom.labelInput.focus();
    return;
  }
  if (!state.maskReady) {
    if (!state.maskModelReady) {
      return;
    }
    dom.saveStatus.textContent = 'Generate or update mask before confirming.';
    return;
  }
  const annotationPoint = state.annotationPoint;

  dom.saveStatus.textContent = 'Saving…';
  try {
    const response = await fetch(`/api/scenes/${encodeURIComponent(state.currentScene.id)}/annotation`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        x: annotationPoint.x,
        y: annotationPoint.y,
        label,
        annotation_point: annotationPoint,
        mask_points: buildMaskPointsPayload(),
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Failed to save annotation');
    }
    const result = await response.json();
    const annotation = result.annotation;
    state.currentScene.annotation = {
      label: annotation.label,
      x: annotation.point?.x ?? annotationPoint.x,
      y: annotation.point?.y ?? annotationPoint.y,
      annotation_point: annotation.annotation_point || { ...annotationPoint },
      updated_at: annotation.updated_at,
      image_size: annotation.image_size || null,
      mask: annotation.mask || null,
      mask_url: annotation.mask_url || null,
      mask_points: Array.isArray(annotation.mask_points) ? annotation.mask_points : buildMaskPointsPayload(),
    };
    hydrateEditingStateFromSaved();
    dom.labelInput.value = annotation.label;
    dom.saveStatus.textContent = 'Annotation saved.';
    dom.maskStatus.textContent = annotation.mask ? 'Saved with mask.' : 'Saved.';
    updateAnnotationSummary();
    updateCoordinateDisplay();
    updateSceneAnnotatedFlag(state.currentScene.id, true);
  } catch (error) {
    console.error(error);
    dom.saveStatus.textContent = 'Failed to save annotation.';
  }
}

async function handleUploadSubmit(event) {
  event.preventDefault();
  if (!dom.uploadImageA?.files?.length || !dom.uploadImageB?.files?.length) {
    dom.uploadStatus.textContent = 'Please choose both Image A and Image B.';
    return;
  }
  const sceneName = dom.uploadSceneId.value.trim();
  const formData = new FormData();
  if (sceneName) {
    formData.append('scene_id', sceneName);
  }
  formData.append('image_a', dom.uploadImageA.files[0]);
  formData.append('image_b', dom.uploadImageB.files[0]);

  dom.uploadStatus.textContent = 'Uploading…';
  try {
    const response = await fetch('/api/scenes/upload', {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Upload failed');
    }
    const payload = await response.json();
    const newScene = payload.scene;
    upsertScene(newScene);
    dom.uploadForm.reset();
    dom.uploadStatus.textContent = `Scene '${newScene.name}' uploaded.`;
    loadScene(newScene.id);
  } catch (error) {
    console.error(error);
    dom.uploadStatus.textContent = 'Upload failed. Please try again.';
  }
}

function upsertScene(scene) {
  const index = state.scenes.findIndex((item) => item.id === scene.id);
  if (index >= 0) {
    state.scenes[index] = scene;
  } else {
    state.scenes.push(scene);
  }
  state.scenes.sort((a, b) => a.name.localeCompare(b.name));
  renderSceneOptions();
  renderSceneList();
  updateSceneStatus(true);
}

function updateSceneAnnotatedFlag(sceneId, annotated) {
  const scene = state.scenes.find((item) => item.id === sceneId);
  if (scene) {
    scene.annotated = annotated;
  }
  renderSceneOptions();
  renderSceneList();
  updateSceneStatus();
}

function formatNumber(value) {
  return Number.parseFloat(value).toFixed(1);
}

function nearlyEqual(a, b, epsilon = 1e-3) {
  return Math.abs(a - b) <= epsilon;
}

function buildMaskPointsPayload() {
  const points = [];
  if (state.annotationPoint) {
    points.push({ x: state.annotationPoint.x, y: state.annotationPoint.y, kind: 'positive' });
  }
  state.refinementPoints.forEach((point) => {
    points.push({ x: point.x, y: point.y, kind: point.kind === 'negative' ? 'negative' : 'positive' });
  });
  return points;
}

function setStatus(message) {
  if (message) {
    dom.sceneStatus.dataset.locked = 'true';
    dom.sceneStatus.textContent = message;
  } else {
    dom.sceneStatus.dataset.locked = 'false';
    updateSceneStatus(true);
  }
}

function isTypingTarget(target) {
  if (!target) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  const tag = target.tagName ? target.tagName.toUpperCase() : '';
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}