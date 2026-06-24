#!/usr/bin/env bash
# Double-click this file (Mac: right-click > Open) to set up (first time) and
# launch AlphaMaxxin. If double-clicking just opens it in a text editor instead
# of running it, open Terminal, drag this file into the window, and press Enter.

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python was not found on this computer."
    echo "Download it from https://www.python.org/downloads/ and run this again."
    read -p "Press Enter to close..."
    exit 1
fi

python3 setup.py
read -p "Press Enter to close..."
