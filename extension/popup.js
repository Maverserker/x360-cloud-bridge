// SPDX-License-Identifier: GPL-3.0-or-later
const NAMES = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'Back', 'Start', 'L3', 'R3', '↑', '↓', '←', '→', 'Guide'];

function setStatus(id, ok, yes, no) {
  const el = document.getElementById(id);
  el.textContent = ok ? yes : no;
  el.className = ok ? 'ok' : 'bad';
}

function render(state) {
  setStatus('helper', state.helper, 'running', 'not running');
  setStatus('receiver', state.receiver, 'found', state.helper ? 'not found' : '—');
  document.getElementById('hint').hidden = state.helper;

  const pads = document.getElementById('pads');
  pads.replaceChildren();
  for (const pad of state.pads || []) {
    if (!pad.connected) continue;
    const pressed = pad.buttons.map((v, i) => (v > 0.12 ? NAMES[i] : null)).filter(Boolean);
    const [lx, ly, rx, ry] = pad.axes.map((a) => a.toFixed(2));
    const box = document.createElement('div');
    box.className = 'pad';
    box.innerHTML = `<div class="row"><b>Controller ${pad.slot + 1}</b><span class="ok">connected</span></div>
      <div class="btns"></div>
      <div class="muted">L (${lx}, ${ly}) · R (${rx}, ${ry})</div>`;
    box.querySelector('.btns').textContent = pressed.join(' ') || '—';
    pads.append(box);
  }
  if (state.receiver && !pads.children.length) {
    pads.innerHTML = '<p class="muted">No controller connected. Press the Guide button to turn it on.</p>';
  }
}

chrome.runtime.connect({ name: 'x360' }).onMessage.addListener(render);
