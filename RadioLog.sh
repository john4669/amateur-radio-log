#!/bin/bash
# Amateur Radio Contact Log - Launcher
# Run this to start the app

cd "$(dirname "$0")"

if [ ! -f "venv/bin/python" ]; then
    echo
    echo "The app has not been set up yet."
    echo "Please run: ./setup.sh"
    echo
    exit 1
fi

venv/bin/python main.py &
