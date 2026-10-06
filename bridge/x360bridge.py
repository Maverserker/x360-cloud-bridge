#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
x360-cloud-bridge helper.

Reads an Xbox 360 Wireless Receiver over libusb (no driver, no system changes)
and publishes the state of up to 4 controllers on a local WebSocket
(ws://127.0.0.1:8360). The companion Chrome extension turns that state into
standard Gamepad API controllers inside cloud-gaming pages.

Wire protocol knowledge comes from the Linux kernel's xpad driver.
"""

import argparse
import asyncio
import json
import logging
import math
import os
import re
import signal
import threading
import time

import usb.backend.libusb1
import usb.core
import usb.util
from websockets.asyncio.server import broadcast, serve

VERSION = "0.1.0"

VENDOR_ID = 0x045E
PRODUCT_IDS = (0x0291, 0x0719, 0x02A9)  # Microsoft receivers and common clones
SLOT_INTERFACE = (0xFF, 0x5D, 0x81)    # class / subclass / protocol of a controller slot
MAX_SLOTS = 4

DEFAULT_PORT = 8360
HEARTBEAT_SECONDS = 5      # keeps the extension's service worker alive
MAX_RUMBLE_MS = 5000
TRIGGER_THRESHOLD = 0.12   # analog trigger value that counts as "pressed"

# Browsers always send an Origin header; only the extension and local test
# pages are allowed. Non-browser local tools (no Origin) are allowed too.
ALLOWED_ORIGINS = [
    re.compile(r"chrome-extension://[a-p]{32}"),
    re.compile(r"http://(localhost|127\.0\.0\.1)(:\d+)?"),
    None,
]

# Standard Gamepad mapping (https://w3c.github.io/gamepad/#remapping):
#  0 A  1 B  2 X  3 Y  4 LB  5 RB  6 LT  7 RT  8 Back  9 Start
# 10 L3 11 R3 12 Up 13 Down 14 Left 15 Right 16 Guide
BYTE2_BUTTONS = {0x01: 12, 0x02: 13, 0x04: 14, 0x08: 15, 0x10: 9, 0x20: 8, 0x40: 10, 0x80: 11}
BYTE3_BUTTONS = {0x01: 4, 0x02: 5, 0x04: 16, 0x10: 0, 0x20: 1, 0x40: 2, 0x80: 3}

log = logging.getLogger("x360bridge")


def find_backend():
    for path in ("/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"):
        if os.path.exists(path):
            return usb.backend.libusb1.get_backend(find_library=lambda _name, p=path: p)
    return usb.backend.libusb1.get_backend()


def apply_deadzone(x, y, deadzone):
    """Radial deadzone, rescaled so the usable range still reaches 1.0."""
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone:
        return 0.0, 0.0
    scale = min(1.0, (magnitude - deadzone) / (1.0 - deadzone)) / magnitude
    return round(x * scale, 4), round(y * scale, 4)


def decode_input(report, deadzone):
    """Decode a wired-360-layout report (starts at byte 4 of a wireless packet)."""
    buttons = [0.0] * 17
    for bit, index in BYTE2_BUTTONS.items():
        if report[2] & bit:
            buttons[index] = 1.0
    for bit, index in BYTE3_BUTTONS.items():
        if report[3] & bit:
            buttons[index] = 1.0
    buttons[6] = round(report[4] / 255, 4)
    buttons[7] = round(report[5] / 255, 4)

    def axis(lo):
        raw = int.from_bytes(bytes(report[lo:lo + 2]), "little", signed=True)
        return max(-1.0, raw / 32767)

    # The Gamepad API wants "down" as positive Y; the 360 reports "up" as positive.
    lx, ly = apply_deadzone(axis(6), -axis(8), deadzone)
    rx, ry = apply_deadzone(axis(10), -axis(12), deadzone)
    return buttons, [lx, ly, rx, ry]


class ReceiverBusy(Exception):
    pass


class Receiver:
    """One Xbox 360 wireless receiver, with a reader thread per controller slot."""

    def __init__(self, on_packet, on_lost):
        self.on_packet = on_packet
        self.on_lost = on_lost
        self.dev = None
        self.slots = []  # (interface_number, ep_in, ep_out)
        self.threads = []
        self.stop = threading.Event()
        self.write_lock = threading.Lock()

    @staticmethod
    def find(backend):
        for pid in PRODUCT_IDS:
            dev = usb.core.find(idVendor=VENDOR_ID, idProduct=pid, backend=backend)
            if dev is not None:
                return dev
        return None

    def open(self, backend):
        dev = self.find(backend)
        if dev is None:
            return False
        try:
            dev.set_configuration()
        except usb.core.USBError as e:
            if e.errno == 13:
                raise ReceiverBusy() from e
            # Already configured by a previous run; carry on.
        slots = []
        for intf in dev.get_active_configuration():
            if (intf.bInterfaceClass, intf.bInterfaceSubClass, intf.bInterfaceProtocol) != SLOT_INTERFACE:
                continue
            ep_in = ep_out = None
            for ep in intf:
                if ep.bEndpointAddress & 0x80:
                    ep_in = ep.bEndpointAddress
                else:
                    ep_out = ep.bEndpointAddress
            if ep_in and ep_out:
                slots.append((intf.bInterfaceNumber, ep_in, ep_out))
            if len(slots) == MAX_SLOTS:
                break
        claimed = []
        try:
            for number, _, _ in slots:
                usb.util.claim_interface(dev, number)
                claimed.append(number)
        except usb.core.USBError as e:
            for number in claimed:
                usb.util.release_interface(dev, number)
            if e.errno == 13:
                raise ReceiverBusy() from e
            raise
        self.dev, self.slots = dev, slots
        log.info("Receiver %04x:%04x ready, %d controller slots", dev.idVendor, dev.idProduct, len(slots))
        self.stop.clear()
        for slot in range(len(slots)):
            self.send(slot, b"\x08\x00\x0f\xc0")  # ask which controllers are present
            t = threading.Thread(target=self._read_loop, args=(slot,), daemon=True)
            t.start()
            self.threads.append(t)
        return True

    def _read_loop(self, slot):
        ep_in = self.slots[slot][1]
        while not self.stop.is_set():
            try:
                data = bytes(self.dev.read(ep_in, 64, timeout=250))
            except usb.core.USBTimeoutError:
                continue
            except usb.core.USBError as e:
                if not self.stop.is_set():
                    log.warning("Lost the receiver (%s)", e)
                    self.stop.set()
                    self.on_lost()
                return
            self.on_packet(slot, data)

    def send(self, slot, payload):
        if self.dev is None or slot >= len(self.slots):
            return
        packet = payload.ljust(12, b"\x00")
        try:
            with self.write_lock:
                self.dev.write(self.slots[slot][2], packet, timeout=500)
        except usb.core.USBError as e:
            log.debug("Write to slot %d failed: %s", slot + 1, e)

    def set_led(self, slot, mode):
        # mode 6..9 = quadrant 1..4 solid, 0 = off
        self.send(slot, bytes([0x00, 0x00, 0x08, 0x40 + mode]))

    def rumble(self, slot, strong, weak):
        self.send(slot, bytes([0x00, 0x01, 0x0F, 0xC0, 0x00, strong, weak]))

    def close(self):
        self.stop.set()
        for t in self.threads:
            t.join(timeout=1)
        self.threads = []
        if self.dev is None:
            return
        for slot, (number, _, _) in enumerate(self.slots):
            self.rumble(slot, 0, 0)
            self.set_led(slot, 0)
            try:
                usb.util.release_interface(self.dev, number)
            except usb.core.USBError:
                pass
        usb.util.dispose_resources(self.dev)
        self.dev = None


class Bridge:
    """Owns controller state and the WebSocket clients."""

    def __init__(self, loop, deadzone):
        self.loop = loop
        self.deadzone = deadzone
        self.pads = [self._empty_pad() for _ in range(MAX_SLOTS)]
        self.receiver_present = False
        self.clients = set()
        self.receiver = None
        self.rumble_timers = {}
        self.flush_pending = False
        self.lock = threading.Lock()

    @staticmethod
    def _empty_pad():
        return {"connected": False, "buttons": [0.0] * 17, "axes": [0.0] * 4}

    # ---- called from USB reader threads ----

    def on_packet(self, slot, data):
        changed = False
        connected_now = None
        with self.lock:
            pad = self.pads[slot]
            if len(data) >= 2 and data[0] & 0x08:  # presence change
                present = bool(data[1] & 0x80)
                if present != pad["connected"]:
                    self.pads[slot] = pad = self._empty_pad()
                    pad["connected"] = present
                    connected_now = present
                    changed = True
            if len(data) >= 18 and data[1] == 0x01 and data[4] == 0x00 and data[5] == 0x13:
                buttons, axes = decode_input(data[4:], self.deadzone)
                if not pad["connected"]:  # input implies presence (missed status packet)
                    pad["connected"] = True
                    connected_now = True
                if buttons != pad["buttons"] or axes != pad["axes"]:
                    pad["buttons"], pad["axes"] = buttons, axes
                    changed = True
                changed = changed or connected_now is not None
        if connected_now is not None:
            log.info("Controller %d %s", slot + 1, "connected" if connected_now else "disconnected")
            if connected_now and self.receiver:
                self.receiver.set_led(slot, 6 + slot)
        if changed:
            self.schedule_flush()

    def on_receiver_lost(self):
        self.loop.call_soon_threadsafe(self._receiver_lost)

    def _receiver_lost(self):
        with self.lock:
            self.receiver_present = False
            self.pads = [self._empty_pad() for _ in range(MAX_SLOTS)]
        self.flush()

    def schedule_flush(self):
        # Coalesce bursts of USB packets into one WebSocket message per loop turn.
        with self.lock:
            if self.flush_pending:
                return
            self.flush_pending = True
        self.loop.call_soon_threadsafe(self.flush)

    # ---- asyncio side ----

    def snapshot(self):
        with self.lock:
            self.flush_pending = False
            pads = [dict(pad, slot=i) for i, pad in enumerate(self.pads)]
            return json.dumps({"t": "state", "receiver": self.receiver_present, "pads": pads},
                              separators=(",", ":"))

    def flush(self):
        broadcast(self.clients, self.snapshot())

    def handle_command(self, msg):
        if msg.get("t") != "rumble":
            return
        try:
            slot = int(msg.get("slot", 0))
            strong = round(max(0.0, min(1.0, float(msg.get("strong", 0)))) * 255)
            weak = round(max(0.0, min(1.0, float(msg.get("weak", 0)))) * 255)
            duration = max(0, min(MAX_RUMBLE_MS, int(msg.get("duration", 0))))
        except (TypeError, ValueError):
            return
        if not 0 <= slot < MAX_SLOTS:
            return
        if timer := self.rumble_timers.pop(slot, None):
            timer.cancel()
        self._rumble(slot, strong, weak)
        if (strong or weak) and duration:
            self.rumble_timers[slot] = self.loop.call_later(duration / 1000, self._rumble, slot, 0, 0)

    def _rumble(self, slot, strong, weak):
        if self.receiver:
            threading.Thread(target=self.receiver.rumble, args=(slot, strong, weak), daemon=True).start()
        else:
            log.info("[simulate] rumble slot %d strong=%d weak=%d", slot + 1, strong, weak)

    async def handler(self, ws):
        self.clients.add(ws)
        log.info("Browser connected (%d client%s)", len(self.clients), "" if len(self.clients) == 1 else "s")
        try:
            await ws.send(self.snapshot())
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self.handle_command(msg)
        finally:
            self.clients.discard(ws)
            log.info("Browser disconnected (%d left)", len(self.clients))

    async def heartbeat(self):
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            self.flush()

    async def supervise_receiver(self):
        """Open the receiver, and re-open it whenever it is unplugged or busy."""
        backend = find_backend()
        if backend is None:
            log.error("libusb not found. Install it with: brew install libusb")
            return
        warned_missing = warned_busy = False
        while True:
            if not self.receiver_present:
                if self.receiver:
                    await asyncio.to_thread(self.receiver.close)
                    self.receiver = None
                receiver = Receiver(self.on_packet, self.on_receiver_lost)
                try:
                    opened = await asyncio.to_thread(receiver.open, backend)
                except ReceiverBusy:
                    opened = False
                    if not warned_busy:
                        log.warning("Receiver is in use by another program (Steam?). Retrying every 2 s...")
                        warned_busy = True
                if opened:
                    self.receiver = receiver
                    self.receiver_present = True
                    warned_missing = warned_busy = False
                    self.flush()
                elif not warned_missing and not warned_busy:
                    log.warning("No Xbox 360 wireless receiver found. Plug it in; retrying every 2 s...")
                    warned_missing = True
            await asyncio.sleep(2)

    async def simulate(self):
        """Fake controller for testing the browser side without hardware."""
        self.receiver_present = True
        self.pads[0]["connected"] = True
        log.info("Simulating one controller (left stick circles, A toggles every second)")
        start = time.monotonic()
        while True:
            t = time.monotonic() - start
            with self.lock:
                pad = self.pads[0]
                pad["axes"] = [round(math.cos(t * 2), 4), round(math.sin(t * 2), 4), 0.0, 0.0]
                pad["buttons"][0] = 1.0 if int(t) % 2 else 0.0
                pad["buttons"][7] = round((t % 3) / 3, 4)
            self.schedule_flush()
            await asyncio.sleep(1 / 60)

    def shutdown(self):
        if self.receiver:
            self.receiver.close()


async def main(args):
    loop = asyncio.get_running_loop()
    bridge = Bridge(loop, args.deadzone)
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))

    async with serve(bridge.handler, "127.0.0.1", args.port, origins=ALLOWED_ORIGINS):
        log.info("x360-cloud-bridge %s listening on ws://127.0.0.1:%d (deadzone %.2f)",
                 VERSION, args.port, args.deadzone)
        tasks = [
            asyncio.create_task(bridge.heartbeat()),
            asyncio.create_task(bridge.simulate() if args.simulate else bridge.supervise_receiver()),
        ]
        await stop
        log.info("Shutting down...")
        for task in tasks:
            task.cancel()
    await asyncio.to_thread(bridge.shutdown)


def parse_args():
    p = argparse.ArgumentParser(description="Xbox 360 wireless receiver → browser Gamepad API bridge")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"WebSocket port (default {DEFAULT_PORT})")
    p.add_argument("--deadzone", type=float, default=0.15,
                   help="radial stick deadzone, 0-0.9 (default 0.15; raise it if sticks drift)")
    p.add_argument("--simulate", action="store_true", help="fake a controller, no receiver needed")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = p.parse_args()
    if not 0 <= args.deadzone <= 0.9:
        p.error("--deadzone must be between 0 and 0.9")
    return args


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    asyncio.run(main(args))
