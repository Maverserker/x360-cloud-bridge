// SPDX-License-Identifier: GPL-3.0-or-later
// Service worker: owns the WebSocket to the local helper and fans controller
// state out to every page (and the popup) that opened a "x360" port.

const HELPER_URL = 'ws://127.0.0.1:8360';
const RETRY_MS = 2000;

const ports = new Set();
let ws = null;
let lastState = null;
let retryTimer = null;

function offlineState() {
  return { t: 'state', helper: false, receiver: false, pads: [] };
}

function send(port, msg) {
  try {
    port.postMessage(msg);
  } catch {
    ports.delete(port);
  }
}

function fanOut(msg) {
  for (const port of ports) send(port, msg);
}

function connect() {
  if (ws || ports.size === 0) return;
  clearTimeout(retryTimer);
  retryTimer = null;

  const socket = new WebSocket(HELPER_URL);
  ws = socket;

  socket.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }
    if (msg.t !== 'state') return;
    msg.helper = true;
    lastState = msg;
    fanOut(msg);
  };

  socket.onclose = () => {
    if (ws !== socket) return;
    ws = null;
    const wasOnline = lastState !== null;
    lastState = null;
    if (wasOnline) fanOut(offlineState());
    if (ports.size > 0) retryTimer = setTimeout(connect, RETRY_MS);
  };
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'x360') return;
  ports.add(port);
  send(port, lastState || offlineState());
  connect();

  port.onMessage.addListener((msg) => {
    if (msg && msg.t === 'rumble' && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  });

  port.onDisconnect.addListener(() => {
    ports.delete(port);
    if (ports.size === 0 && ws) {
      const socket = ws;
      ws = null;
      lastState = null;
      socket.close();
    }
  });
});
