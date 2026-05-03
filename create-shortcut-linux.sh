#!/bin/bash
# Creates a desktop shortcut for W0BCQ Logger
# Run this once from the project folder

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="$HOME/Desktop/RadioLog.desktop"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=W0BCQ Logger
Comment=Log amateur radio contacts and export ADIF for N3FJP AC Log
Exec=bash -c 'cd "$APP_DIR" && ./RadioLog.sh'
Icon=$APP_DIR/icon_256.png
Terminal=false
Type=Application
Categories=Utility;HamRadio;
EOF

chmod +x "$DESKTOP_FILE"

# Some Linux desktops require this to trust the shortcut
if command -v gio &> /dev/null; then
    gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null
fi

echo "Desktop shortcut created: $DESKTOP_FILE"
echo
echo "Note: Your desktop environment may ask you to 'Trust' or"
echo "'Allow Launching' when you first double-click the shortcut."
