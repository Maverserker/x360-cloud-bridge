// SPDX-License-Identifier: GPL-3.0-or-later
// Main-world script: adds the bridged controllers to navigator.getGamepads()
// as standard-mapping Xbox 360 gamepads, fires gamepadconnected /
// gamepaddisconnected, and forwards vibrationActuator effects as rumble.

(() => {
  if (window.__x360CloudBridge) return;
  window.__x360CloudBridge = true;

  const TO_PAGE = 'x360cb:state';
  const FROM_PAGE = 'x360cb:cmd';
  const GAMEPAD_ID = 'Xbox 360 Controller (STANDARD GAMEPAD Vendor: 045e Product: 028e)';
  const PRESS_THRESHOLD = 0.12;
  const MAX_EFFECT_MS = 5000;

  const nativeGetGamepads = Navigator.prototype.getGamepads;
  const virtualPads = new Map(); // slot -> { index, gamepad, actuator, key }

  // Objects that inherit from the real prototypes pass `instanceof` checks;
  // own properties shadow the native getters, which would throw on fakes.
  function fake(proto, props) {
    const obj = Object.create(proto ? proto.prototype : Object.prototype);
    for (const [name, value] of Object.entries(props)) {
      Object.defineProperty(obj, name, { value, enumerable: true });
    }
    return obj;
  }

  function sendCommand(msg) {
    document.dispatchEvent(new CustomEvent(FROM_PAGE, { detail: JSON.stringify(msg) }));
  }

  function makeActuator(slot) {
    let pending = null; // resolver of the effect currently playing
    let stopTimer = null;

    function finish(result) {
      clearTimeout(stopTimer);
      if (pending) pending(result);
      pending = null;
    }

    return fake(window.GamepadHapticActuator, {
      type: 'dual-rumble',
      effects: Object.freeze(['dual-rumble', 'trigger-rumble']),
      playEffect(type, params = {}) {
        if (type !== 'dual-rumble' && type !== 'trigger-rumble') {
          return Promise.reject(new TypeError(`Unsupported effect type: ${type}`));
        }
        finish('preempted');
        const duration = Math.max(0, Math.min(MAX_EFFECT_MS, Number(params.duration) || 0));
        const delay = Math.max(0, Number(params.startDelay) || 0);
        const strong = Number(params.strongMagnitude) || 0;
        const weak = Number(params.weakMagnitude) || 0;
        return new Promise((resolve) => {
          pending = resolve;
          stopTimer = setTimeout(() => {
            sendCommand({ t: 'rumble', slot, strong, weak, duration });
            stopTimer = setTimeout(() => finish('complete'), duration);
          }, delay);
        });
      },
      reset() {
        finish('preempted');
        sendCommand({ t: 'rumble', slot, strong: 0, weak: 0, duration: 0 });
        return Promise.resolve('complete');
      },
    });
  }

  function makeGamepad(v, pad, connected) {
    return fake(window.Gamepad, {
      id: GAMEPAD_ID,
      index: v.index,
      connected,
      mapping: 'standard',
      timestamp: performance.now(),
      axes: Object.freeze(pad.axes.slice()),
      buttons: Object.freeze(
        pad.buttons.map((value) =>
          fake(window.GamepadButton, {
            pressed: value > PRESS_THRESHOLD,
            touched: value > 0,
            value,
          }),
        ),
      ),
      vibrationActuator: v.actuator,
    });
  }

  function realGamepads() {
    try {
      return Array.from(nativeGetGamepads.call(navigator));
    } catch {
      return [];
    }
  }

  function freeIndex() {
    const taken = new Set([...virtualPads.values()].map((v) => v.index));
    realGamepads().forEach((g, i) => g && taken.add(i));
    let i = 0;
    while (taken.has(i)) i++;
    return i;
  }

  function fire(type, gamepad) {
    const event = new Event(type);
    Object.defineProperty(event, 'gamepad', { value: gamepad, enumerable: true });
    window.dispatchEvent(event);
  }

  function disconnect(slot) {
    const v = virtualPads.get(slot);
    if (!v) return;
    virtualPads.delete(slot);
    v.actuator.reset();
    fire('gamepaddisconnected', makeGamepad(v, { buttons: [], axes: [] }, false));
  }

  function applyState(state) {
    const live = new Set();
    if (state.helper && state.receiver) {
      for (const pad of state.pads || []) {
        if (!pad.connected) continue;
        live.add(pad.slot);
        const key = JSON.stringify([pad.buttons, pad.axes]);
        let v = virtualPads.get(pad.slot);
        if (!v) {
          v = { index: freeIndex(), actuator: makeActuator(pad.slot), key };
          virtualPads.set(pad.slot, v);
          v.gamepad = makeGamepad(v, pad, true);
          fire('gamepadconnected', v.gamepad);
        } else if (v.key !== key) {
          v.key = key;
          v.gamepad = makeGamepad(v, pad, true);
        }
      }
    }
    for (const slot of [...virtualPads.keys()]) {
      if (!live.has(slot)) disconnect(slot);
    }
  }

  function getGamepads() {
    const list = realGamepads();
    while (list.length < 4) list.push(null);
    for (const v of virtualPads.values()) {
      while (list.length <= v.index) list.push(null);
      list[v.index] = v.gamepad;
    }
    return list;
  }

  const nativeToString = Function.prototype.toString.call(nativeGetGamepads);
  Object.defineProperty(getGamepads, 'toString', { value: () => nativeToString });
  Object.defineProperty(Navigator.prototype, 'getGamepads', {
    value: getGamepads,
    configurable: true,
    writable: true,
  });

  document.addEventListener(TO_PAGE, (event) => {
    try {
      applyState(JSON.parse(event.detail));
    } catch {
      // ignore malformed state
    }
  });
})();
