#!/usr/bin/env bash
# Double-click this file (Mac: right-click > Open) to set up (first time) and
# launch AlphaMaxxin. If double-clicking just opens it in a text editor instead
# of running it, open Terminal, drag this file into the window, and press Enter.

cd "$(dirname "$0")" || exit 1

if [ -x .venv/bin/python ]; then
    .venv/bin/python setup.py
    setup_status=$?
elif command -v python3 >/dev/null 2>&1; then
    python3 setup.py
    setup_status=$?
else
    echo "Python was not found on this computer."
    echo "Download it from https://www.python.org/downloads/ and run this again."
    read -p "Press Enter to close..."
    exit 1
fi
read -p "Press Enter to close..."
exit "$setup_status"
