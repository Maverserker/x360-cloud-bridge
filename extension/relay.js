// SPDX-License-Identifier: GPL-3.0-or-later
// Isolated-world content script: relays between the extension service worker
// and inject.js (which runs in the page's own world and cannot use chrome.*).

(() => {
  const TO_PAGE = 'x360cb:state';
  const FROM_PAGE = 'x360cb:cmd';
  let port = null;

  function toPage(msg) {
    document.dispatchEvent(new CustomEvent(TO_PAGE, { detail: JSON.stringify(msg) }));
  }

  function open() {
    try {
      port = chrome.runtime.connect({ name: 'x360' });
    } catch {
      return; // extension was reloaded or removed; this page needs a refresh
    }
    port.onMessage.addListener(toPage);
    port.onDisconnect.addListener(() => {
      port = null;
      toPage({ t: 'state', helper: false, receiver: false, pads: [] });
      // The service worker may have been stopped by Chrome; reconnecting wakes it.
      setTimeout(open, 1000);
    });
  }

  document.addEventListener(FROM_PAGE, (event) => {
    if (!port || typeof event.detail !== 'string') return;
    try {
      port.postMessage(JSON.parse(event.detail));
    } catch {
      // ignore malformed commands
    }
  });

  open();
})();
