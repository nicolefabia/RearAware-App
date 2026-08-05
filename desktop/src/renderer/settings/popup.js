// ============================================================
// RearAware settings window behaviors
// Adapted from RearAware-Chrome's popup.js: chrome.storage.local calls
// replaced with the window.rearaware bridge exposed by preload.js, and
// wired up two new fields the extension never had (loginToggle,
// contributeToggle). Interaction logic (toggle wiring, chip selection,
// disabled-state cascading, ticker) is otherwise unchanged.
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {

  const popup = document.getElementById('popup');

  // ---------- Version badge ----------
  const version = await window.rearaware.getAppVersion();
  document.getElementById('versionBadge').textContent = `Version ${version || '—'}`;

  // ---------- Element refs ----------
  const masterToggle = document.getElementById('masterToggle');
  const statusLabel = document.getElementById('statusLabel');
  const soundToggle = document.getElementById('soundToggle');
  const loginToggle = document.getElementById('loginToggle');
  const contributeToggle = document.getElementById('contributeToggle');
  const debugToggle = document.getElementById('debugToggle');
  const slider = document.getElementById('thresholdSlider');
  const thresholdValue = document.getElementById('thresholdValue');
  const chips = document.querySelectorAll('.chip');
  const chipGroup = document.getElementById('chipGroup');
  const obfuscationHelper = document.getElementById('obfuscationHelper');

  // ---------- Generic toggle wiring (buttons using aria-checked) ----------
  function wireToggle(el, { onChange } = {}) {
    el.addEventListener('click', () => {
      if (el.disabled) return;
      const checked = el.getAttribute('aria-checked') === 'true';
      el.setAttribute('aria-checked', String(!checked));
      if (onChange) onChange(!checked);
    });
  }

  function setToggleState(el, isChecked) {
    el.setAttribute('aria-checked', String(isChecked));
  }

  // Elements that go inert when Detection is off — everything that only makes
  // sense while the detector is actually running. (Chips are handled separately
  // below since they also depend on whether debug mode is on.)
  function setDependentControlsDisabled(isDisabled) {
    soundToggle.disabled = isDisabled;
    debugToggle.disabled = isDisabled;
    slider.disabled = isDisabled;
  }

  let isMasterOff = false;

  // The obfuscation picker is irrelevant while Bounding boxes (debug) is on —
  // the engine draws debug boxes instead of a sticker in that mode — so it's
  // disabled whenever either Detection is off OR debug mode is on. The slider
  // stays independently enabled in debug mode since threshold still affects
  // what gets boxed.
  function updateChipsDisabled() {
    const debugOn = debugToggle.getAttribute('aria-checked') === 'true';
    const isDisabled = isMasterOff || debugOn;
    chips.forEach((chip) => { chip.disabled = isDisabled; });
    const showDebugReason = debugOn && !isMasterOff;
    obfuscationHelper.hidden = !showDebugReason;
    if (showDebugReason) {
      chipGroup.title = 'Hidden while Bounding boxes (debug) is on';
    } else {
      chipGroup.removeAttribute('title');
    }
  }

  function setMasterState(isOn) {
    setToggleState(masterToggle, isOn);
    popup.classList.toggle('is-off', !isOn);
    statusLabel.textContent = isOn ? 'Detection: On' : 'Detection: Off';
    isMasterOff = !isOn;
    setDependentControlsDisabled(!isOn);
    updateChipsDisabled();
  }

  wireToggle(masterToggle, {
    onChange: (isOn) => {
      setMasterState(isOn);
      window.rearaware.setSetting('detectionEnabled', isOn);
    }
  });

  wireToggle(soundToggle, {
    onChange: (isOn) => window.rearaware.setSetting('soundEnabled', isOn)
  });

  wireToggle(loginToggle, {
    onChange: (isOn) => window.rearaware.setSetting('openAtLogin', isOn)
  });

  wireToggle(contributeToggle, {
    onChange: (isOn) => window.rearaware.setSetting('contributeEnabled', isOn)
  });

  wireToggle(debugToggle, {
    onChange: (isOn) => {
      window.rearaware.setSetting('debugEnabled', isOn);
      updateChipsDisabled();
    }
  });

  // ---------- Confidence threshold slider ----------
  function updateSlider() {
    const val = Number(slider.value);
    thresholdValue.textContent = `[${val}%]`;
    slider.style.setProperty('--fill', `${val}%`);
  }
  slider.addEventListener('input', updateSlider);
  slider.addEventListener('change', () => window.rearaware.setSetting('confidence', Number(slider.value)));

  // ---------- Obfuscation type chips ----------
  function selectChip(value) {
    chips.forEach((c) => {
      const isMatch = c.dataset.value === value;
      c.classList.toggle('is-selected', isMatch);
      c.setAttribute('aria-checked', String(isMatch));
    });
  }

  chips.forEach((chip) => {
    chip.addEventListener('click', () => {
      if (chip.disabled) return;
      selectChip(chip.dataset.value);
      window.rearaware.setSetting('obfuscation', chip.dataset.value);
    });
  });

  // ---------- Apply current settings to the UI ----------
  function applySettings(settings) {
    setToggleState(soundToggle, settings.soundEnabled);
    setToggleState(loginToggle, settings.openAtLogin);
    setToggleState(contributeToggle, settings.contributeEnabled);
    setToggleState(debugToggle, settings.debugEnabled);
    setMasterState(settings.detectionEnabled); // reads debugToggle's state, so must run after it's set above
    slider.value = settings.confidence;
    updateSlider();
    selectChip(settings.obfuscation);
  }

  applySettings(await window.rearaware.getSettings());

  // Another window/tray action (or a future second settings window) can
  // change settings too - keep this window's controls in sync.
  window.rearaware.onSettingsChanged(applySettings);

  // ---------- Live status from the engine ----------
  window.rearaware.onEngineEvent((event) => {
    if (event.type === 'status' && !isMasterOff) {
      // Detected state is reflected via the sticker itself in the actual
      // call, so this is mostly useful for confirming the engine is alive.
      statusBadge_setDetected(event.detected);
    }
  });

  function statusBadge_setDetected(detected) {
    document.getElementById('statusDot').style.background = detected ? 'var(--red)' : '';
  }

  // ---------- Footer buttons ----------
  document.getElementById('reportBtn').addEventListener('click', () => {
    window.rearaware.openExternal('https://github.com/nicolefabia/rearaware-chrome/issues/new');
  });
  document.getElementById('learnBtn').addEventListener('click', () => {
    window.rearaware.openExternal('https://github.com/nicolefabia/rearaware-chrome');
  });

  // ---------- Scrolling ticker ----------
  const tickerItems = [
    { text: 'Detecting feline posterior threats in real time', icon: 'icons/cat-blue.svg', name: 'cat' },
    { text: 'Because nobody asked to see that', icon: 'icons/eye.svg', name: 'eye' },
    { text: 'Your video calls, now compliant', icon: 'icons/surveillence.svg', name: 'surveillance' }
  ];

  const track = document.getElementById('tickerTrack');
  const html = tickerItems.concat(tickerItems).map(
    (item) => `<span class="ticker-item"><img src="${item.icon}" alt="" data-icon="${item.name}" width="12" height="12" /><span class="ticker-text">${item.text}</span></span>`
  ).join('');
  track.innerHTML = html;

});
