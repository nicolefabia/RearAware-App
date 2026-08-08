document.addEventListener('DOMContentLoaded', async () => {

  // ---------------------------------------------------------------- tabs

  const tabs = document.querySelectorAll('.tab');
  const panels = {
    general: document.getElementById('panelGeneral'),
    training: document.getElementById('panelTraining'),
  };

  function showTab(name) {
    if (!panels[name]) return;
    tabs.forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.tab === name)));
    Object.entries(panels).forEach(([key, panel]) => { panel.hidden = key !== name; });
  }

  tabs.forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.tab)));

  const initialTab = new URLSearchParams(window.location.search).get('tab');
  showTab(initialTab && panels[initialTab] ? initialTab : 'general');
  window.rearaware.onShowTab((tab) => showTab(tab));

  // ---------------------------------------------------------------- general tab

  const detectionFieldset = document.getElementById('detectionFieldset');
  const thresholdSlider = document.getElementById('thresholdSlider');
  const thresholdValue = document.getElementById('thresholdValue');
  const obfuscationSelect = document.getElementById('obfuscationSelect');
  const soundCheckbox = document.getElementById('soundCheckbox');
  const debugCheckbox = document.getElementById('debugCheckbox');
  const loginCheckbox = document.getElementById('loginCheckbox');
  const contributeCheckbox = document.getElementById('contributeCheckbox');

  let currentSettings = null;

  function applyDisabledState() {
    const detectionOn = currentSettings.detectionEnabled;
    detectionFieldset.disabled = !detectionOn;
    // Obfuscation additionally goes inert under debug mode (which shows
    // bounding boxes instead of a censor sticker) - independent of, and on
    // top of, the fieldset-level disable above.
    obfuscationSelect.disabled = !detectionOn || currentSettings.debugEnabled;
  }

  function applySettingsToForm(settings) {
    currentSettings = settings;
    thresholdSlider.value = settings.confidence;
    thresholdValue.textContent = `${settings.confidence}%`;
    obfuscationSelect.value = settings.obfuscation;
    soundCheckbox.checked = settings.soundEnabled;
    debugCheckbox.checked = settings.debugEnabled;
    loginCheckbox.checked = settings.openAtLogin;
    contributeCheckbox.checked = settings.contributeEnabled;
    applyDisabledState();
  }

  thresholdSlider.addEventListener('input', () => {
    thresholdValue.textContent = `${thresholdSlider.value}%`;
  });
  thresholdSlider.addEventListener('change', () => {
    window.rearaware.setSetting('confidence', Number(thresholdSlider.value));
  });

  obfuscationSelect.addEventListener('change', () => {
    window.rearaware.setSetting('obfuscation', obfuscationSelect.value);
  });

  soundCheckbox.addEventListener('change', () => {
    window.rearaware.setSetting('soundEnabled', soundCheckbox.checked);
  });

  debugCheckbox.addEventListener('change', () => {
    window.rearaware.setSetting('debugEnabled', debugCheckbox.checked);
  });

  loginCheckbox.addEventListener('change', () => {
    window.rearaware.setSetting('openAtLogin', loginCheckbox.checked);
  });

  contributeCheckbox.addEventListener('change', () => {
    window.rearaware.setSetting('contributeEnabled', contributeCheckbox.checked);
  });

  applySettingsToForm(await window.rearaware.getSettings());
  window.rearaware.onSettingsChanged(applySettingsToForm);

  // ---------------------------------------------------------------- training tab review grid

  const reviewCountLabel = document.getElementById('reviewCountLabel');
  const trainingActions = document.getElementById('trainingActions');
  const reviewGrid = document.getElementById('reviewGrid');
  const cardTemplate = document.getElementById('cardTemplate');

  function buildCard(item) {
    const node = cardTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;

    node.querySelector('.thumb').src = item.dataUrl;

    const box = node.querySelector('.butt-box');
    const rel = item.metadata?.butt_box_relative;
    if (rel) {
      box.style.left = `${rel.x1 * 100}%`;
      box.style.top = `${rel.y1 * 100}%`;
      box.style.width = `${(rel.x2 - rel.x1) * 100}%`;
      box.style.height = `${(rel.y2 - rel.y1) * 100}%`;
    } else {
      box.hidden = true;
    }

    node.querySelector('[data-action="approve"]').addEventListener('click', () => act(item.id, node, 'approve'));
    node.querySelector('[data-action="reject"]').addEventListener('click', () => act(item.id, node, 'reject'));

    return node;
  }

  async function act(id, node, action) {
    node.classList.add('is-removing');
    try {
      if (action === 'approve') {
        await window.rearaware.approveContribution(id);
      } else {
        await window.rearaware.rejectContribution(id);
      }
      node.remove();
      updateReviewHeader();
    } catch (err) {
      node.classList.remove('is-removing');
      alert(`Couldn't ${action === 'approve' ? 'send' : 'delete'} this photo: ${err.message}`);
    }
  }

  function updateReviewHeader() {
    const count = reviewGrid.children.length;
    reviewCountLabel.textContent = count === 0
      ? 'No images awaiting review.'
      : `${count} image${count === 1 ? '' : 's'} awaiting review.`;
    trainingActions.hidden = count === 0;
  }

  async function loadAndRenderReviewGrid() {
    const items = await window.rearaware.listContributions();
    reviewGrid.innerHTML = '';
    items.forEach((item) => reviewGrid.appendChild(buildCard(item)));
    updateReviewHeader();
  }

  document.getElementById('sendAllBtn').addEventListener('click', async () => {
    const cards = Array.from(reviewGrid.children);
    if (cards.length === 0) return;
    if (!confirm(`Send all ${cards.length} image(s) to help train RearAware?`)) return;
    for (const node of cards) await act(node.dataset.id, node, 'approve');
  });

  document.getElementById('deleteAllBtn').addEventListener('click', async () => {
    const cards = Array.from(reviewGrid.children);
    if (cards.length === 0) return;
    if (!confirm(`Permanently delete all ${cards.length} image(s)? This can't be undone.`)) return;
    for (const node of cards) await act(node.dataset.id, node, 'reject');
  });

  document.getElementById('uploadPhotosBtn').addEventListener('click', () => {
    window.rearaware.openExternal('https://www.rearaware.com/#help-train');
  });

  await loadAndRenderReviewGrid();

  // A new capture (or the 30-day retention cleanup) can happen while this
  // window is open - keep the grid in sync rather than showing a stale list.
  window.rearaware.onContributionsChanged(() => loadAndRenderReviewGrid());

});
