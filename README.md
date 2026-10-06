# X360 Cloud Bridge

Use your **Xbox 360 wireless controller** (with the USB wireless receiver) to play
**Xbox Cloud Gaming** and **GeForce NOW** in Chrome on a modern Mac, including Apple Silicon.

No kernel extension, no driver, and no changes to SIP, AMFI or NVRAM.

[Leer en español](README.es.md)

## Why

macOS has never supported the Xbox 360 wireless receiver. The old 360Controller
kext stopped working years ago. Newer userspace drivers can read the receiver, but
to show up as a system-wide gamepad they need an Apple-restricted entitlement, which
means weakening macOS security (`amfi_get_out_of_my_way`), and that doesn't even work
on current macOS 26 releases.

Cloud gaming runs in the browser, so the controller only needs to exist **inside the
page**. This project skips the operating system entirely:

```
Xbox 360 receiver ──USB──▶ helper (Python + libusb) ──WebSocket 127.0.0.1:8360──▶ Chrome extension
                                                                                      │
                               navigator.getGamepads() in xbox.com / GeForce NOW ◀────┘
```

- **Helper** (`bridge/x360bridge.py`): talks to the receiver directly through libusb.
  It decodes up to 4 controllers, lights each one's player LED and drives rumble.
- **Extension** (`extension/`): adds the controllers to the page's Gamepad API as
  standard Xbox 360 gamepads, fires `gamepadconnected` / `gamepaddisconnected`, and
  forwards `vibrationActuator` effects back to the controller.

## Requirements

- macOS 13 or newer (tested on macOS 26.6.2, Apple Silicon)
- An Xbox 360 wireless receiver (`045e:0291`, `045e:0719` or the `045e:02a9` clones)
- [Homebrew](https://brew.sh), Python 3.10+
- Google Chrome. Other Chromium browsers (Edge, Brave) should work but are untested.

## Setup

```bash
brew install libusb
git clone https://github.com/Maverserker/x360-cloud-bridge.git
cd x360-cloud-bridge
./start.sh
```

The first run creates a Python virtual environment in `.venv`. Leave the helper
running while you play. Press `Ctrl+C` to stop it.

**Install the extension** (once):

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked** and pick the `extension` folder

The extension's toolbar popup shows whether the helper is running, whether the
receiver was found, and the live state of each controller.

**Play:** turn on the controller (Guide button) and open
[xbox.com/play](https://www.xbox.com/play) or [play.geforcenow.com](https://play.geforcenow.com).
The controller appears as a regular Xbox controller. If a page was already open
before you installed the extension, reload it.

## Options

```bash
./start.sh --deadzone 0.2   # raise if the sticks drift (default 0.15)
./start.sh --simulate       # fake controller, no receiver needed (for development)
./start.sh -v               # debug logging
```

Older controllers often don't fully re-center their sticks. If your character or camera
moves by itself, increase `--deadzone`. Values between 0.15 and 0.25 usually work.

## Testing

- **Without hardware:** run `./start.sh --simulate`, then serve the test page with
  `cd test && python3 -m http.server 8000` and open
  `http://localhost:8000/gamepad-test.html`. You should see a controller whose left
  stick moves in circles, and a "Test rumble" button.
- **With your controller:** the same test page, or
  [gamepad-tester.com](https://gamepad-tester.com) (the extension is enabled there too).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Popup says *Helper: not running* | Start `./start.sh` and keep the terminal open |
| Helper says *Receiver is in use by another program* | **Steam** grabs the receiver while it runs. Quit Steam; the helper retries every 2 s |
| Helper says *No Xbox 360 wireless receiver found* | Check that `system_profiler SPUSBDataType` lists vendor `045e`. Try another port or hub |
| Controller connected in the popup but not in the game | Reload the game tab. Make sure the site is in the list below |
| Controller won't pair | Press the receiver's button (green light blinks), then the small connect button on the top of the controller |

**Supported sites:** `www.xbox.com`, `play.geforcenow.com`, `gamepad-tester.com`,
`hardwaretester.com` and `localhost`. To add another site, add it to both
`content_scripts` entries in `extension/manifest.json`.

## Limitations

- Only works in the browser. It does **not** work with the native GeForce NOW app,
  native Mac games or Steam. For those, macOS needs a real system-level gamepad (see *Why*).
- The helper must be running while you play.
- The headset port and chatpad are not supported.
- Tested with one original controller and one `045e:0291` receiver. Reports from other
  receivers and multi-controller setups are very welcome.

## Security

- The helper only listens on `127.0.0.1` and only accepts WebSocket connections from
  Chrome extensions and `localhost` pages. Other websites are rejected (HTTP 403).
- The extension requests no special permissions. It runs only on the sites listed above.
- Nothing is installed system-wide, and no network access is used beyond localhost.

## Contributing

Issues and pull requests are welcome. Some ideas:

- A **WebUSB-only version** that reads the receiver directly from the extension, with no helper
- Start the helper automatically on login (launchd agent)
- Battery level reporting
- Firefox support
- Testing other receivers and clones, and more cloud-gaming sites

To work on it, `./start.sh --simulate` plus the test page give you a full loop without
hardware. After changing the extension, click the reload icon in `chrome://extensions`
and refresh the page.

## Credits

The Xbox 360 wireless protocol is documented by the Linux kernel's
[`xpad`](https://github.com/torvalds/linux/blob/master/drivers/input/joystick/xpad.c) driver.

## License

[GPL-3.0-or-later](LICENSE). You can use, study, share and modify this project; if you distribute a modified version, it must also be released under the GPL with its source code.
