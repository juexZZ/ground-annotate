const state = {
  scenes: [],
  currentSceneId: null,
  currentScene: null,
  pendingPoint: null,
  markerTarget: null,
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
  dom.marker = document.getElementById('clickMarker');
  dom.annotationSummary = document.getElementById('annotationSummary');
  dom.coordinateDisplay = document.getElementById('coordinateDisplay');
  dom.labelInput = document.getElementById('labelInput');
  dom.confirmBtn = document.getElementById('confirmBtn');
  dom.cancelBtn = document.getElementById('cancelBtn');
  dom.saveStatus = document.getElementById('saveStatus');
  dom.sceneStatus.dataset.locked = 'false';

  dom.sceneSelect.addEventListener('change', (event) => {
    loadScene(event.target.value);
  });

  dom.nextScene.addEventListener('click', () => {
    const next = getNextSceneId();
    if (next) {
      loadScene(next);
    }
  });

  dom.imageB.addEventListener('click', handleImageClick);
  dom.imageB.addEventListener('load', applyMarker);
  dom.imageB.addEventListener('error', () => {
    dom.marker.classList.add('hidden');
    setStatus('Failed to load Image B.');
  });

  dom.confirmBtn.addEventListener('click', submitAnnotation);
  dom.cancelBtn.addEventListener('click', () => {
    state.pendingPoint = null;
    dom.labelInput.value = state.currentScene?.annotation?.label || '';
    toggleAnnotationControls(false);
    setMarkerFromScene();
    updateAnnotationSummary();
    updateCoordinateDisplay();
  });

  fetchScenes();
});

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

async function loadScene(sceneId) {
  if (!sceneId) {
    return;
  }
  state.pendingPoint = null;
  toggleAnnotationControls(false);
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
    state.markerTarget = null;
    setMarkerFromScene();
    updateAnnotationSummary();
    updateCoordinateDisplay();
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
  const pending = state.pendingPoint;
  const saved = state.currentScene?.annotation;
  container.innerHTML = '';

  if (pending) {
    const pill = document.createElement('span');
    pill.className = 'status-pill pending';
    pill.textContent = 'Pending annotation';

    const text = document.createElement('div');
    text.textContent = 'Confirm to save this new annotation.';

    container.appendChild(pill);
    container.appendChild(text);
    return;
  }

  if (saved) {
    const pill = document.createElement('span');
    pill.className = 'status-pill annotated';
    pill.innerHTML = 'Annotated <span aria-hidden="true">✓</span>';

    const detail = document.createElement('div');
    detail.textContent = `Label: ${saved.label} • Point: (${formatNumber(saved.x)}, ${formatNumber(saved.y)})`;

    container.appendChild(pill);
    container.appendChild(detail);
    return;
  }

  container.textContent = 'No saved annotation yet.';
}

function handleImageClick(event) {
  if (!state.currentScene) {
    return;
  }
  if (!dom.imageB.naturalWidth) {
    setStatus('Image B is not loaded yet.');
    return;
  }
  const rect = dom.imageB.getBoundingClientRect();
  const scaleX = dom.imageB.naturalWidth / rect.width;
  const scaleY = dom.imageB.naturalHeight / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;
  if (x < 0 || y < 0) {
    return;
  }

  state.pendingPoint = { x, y };
  dom.labelInput.value = state.currentScene.annotation?.label || '';
  toggleAnnotationControls(true);
  dom.labelInput.focus();
  dom.labelInput.select();
  dom.saveStatus.textContent = '';

  setMarker(state.pendingPoint, true);
  updateAnnotationSummary();
  updateCoordinateDisplay();
}

function toggleAnnotationControls(active) {
  const disabled = !active || !state.currentScene;
  dom.confirmBtn.disabled = !active;
  dom.cancelBtn.disabled = !active;
  dom.labelInput.disabled = disabled;
}

function updateCoordinateDisplay() {
  if (state.pendingPoint) {
    dom.coordinateDisplay.textContent = `Pending: (${formatNumber(state.pendingPoint.x)}, ${formatNumber(state.pendingPoint.y)})`;
    return;
  }
  const saved = state.currentScene?.annotation;
  if (saved) {
    dom.coordinateDisplay.textContent = `Saved: (${formatNumber(saved.x)}, ${formatNumber(saved.y)})`;
    return;
  }
  dom.coordinateDisplay.textContent = 'Click Image B to select a point.';
}

function setMarkerFromScene() {
  const saved = state.currentScene?.annotation;
  if (saved && !state.pendingPoint) {
    setMarker({ x: saved.x, y: saved.y }, false);
  } else if (!state.pendingPoint) {
    hideMarker();
  }
}

function setMarker(point, isPending) {
  if (!point) {
    hideMarker();
    return;
  }
  state.markerTarget = { point, isPending };
  applyMarker();
}

function hideMarker() {
  state.markerTarget = null;
  dom.marker.classList.add('hidden');
}

function applyMarker() {
  const markerData = state.markerTarget;
  if (!markerData || !dom.imageB.naturalWidth || !dom.imageB.naturalHeight) {
    dom.marker.classList.add('hidden');
    return;
  }
  const { point, isPending } = markerData;
  const leftPercent = (point.x / dom.imageB.naturalWidth) * 100;
  const topPercent = (point.y / dom.imageB.naturalHeight) * 100;

  dom.marker.style.left = `${leftPercent}%`;
  dom.marker.style.top = `${topPercent}%`;
  dom.marker.classList.toggle('pending', Boolean(isPending));
  dom.marker.classList.remove('hidden');
}

async function submitAnnotation() {
  if (!state.pendingPoint || !state.currentScene) {
    return;
  }
  const label = dom.labelInput.value.trim();
  if (!label) {
    dom.saveStatus.textContent = 'Please provide a label before confirming.';
    dom.labelInput.focus();
    return;
  }

  dom.saveStatus.textContent = 'Saving…';
  try {
    const response = await fetch(`/api/scenes/${encodeURIComponent(state.currentScene.id)}/annotation`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        x: state.pendingPoint.x,
        y: state.pendingPoint.y,
        label,
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
      x: annotation.point?.x ?? state.pendingPoint.x,
      y: annotation.point?.y ?? state.pendingPoint.y,
      updated_at: annotation.updated_at,
      image_size: annotation.image_size || null,
    };
    state.pendingPoint = null;
    toggleAnnotationControls(false);
    dom.labelInput.value = annotation.label;
    dom.saveStatus.textContent = 'Annotation saved.';
    setMarkerFromScene();
    updateAnnotationSummary();
    updateCoordinateDisplay();
    updateSceneAnnotatedFlag(state.currentScene.id, true);
  } catch (error) {
    console.error(error);
    dom.saveStatus.textContent = 'Failed to save annotation.';
  }
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

function setStatus(message) {
  if (message) {
    dom.sceneStatus.dataset.locked = 'true';
    dom.sceneStatus.textContent = message;
  } else {
    dom.sceneStatus.dataset.locked = 'false';
    updateSceneStatus(true);
  }
}
