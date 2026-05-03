#!/bin/bash
echo "============================================"
echo " Amateur Radio Contact Log - First Time Setup"
echo "============================================"
echo

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo
    echo "Install it with:"
    echo "  macOS:        brew install python3"
    echo "  Ubuntu/Mint:  sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora:       sudo dnf install python3 python3-pip"
    echo
    exit 1
fi

echo "[1/3] Creating virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create venv. You may need: sudo apt install python3-venv"
    exit 1
fi

echo "[2/3] Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies."
    exit 1
fi

echo "[3/3] Setup complete!"
echo
echo "============================================"
echo " You can now launch the app by running:"
echo " ./RadioLog.sh"
echo "============================================"
echo
