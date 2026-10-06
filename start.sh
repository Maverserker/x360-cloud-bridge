#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Starts the x360-cloud-bridge helper, setting up its Python environment on
# first run. Any arguments are passed through, e.g. ./start.sh --deadzone 0.2
set -e
cd "$(dirname "$0")"

if [ ! -e /opt/homebrew/lib/libusb-1.0.dylib ] && [ ! -e /usr/local/lib/libusb-1.0.dylib ]; then
  echo "libusb is missing. Install it with:  brew install libusb"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating Python environment in .venv ..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --disable-pip-version-check -r bridge/requirements.txt
fi

exec .venv/bin/python bridge/x360bridge.py "$@"
