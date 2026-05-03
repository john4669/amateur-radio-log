#!/bin/bash
# Creates a macOS .app bundle for W0BCQ Logger.
# Run this once from the project folder after running setup.sh.

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="W0BCQ Logger"
APP_BUNDLE="$APP_DIR/$APP_NAME.app"

echo "Creating $APP_NAME.app..."

# ── Bundle structure ───────────────────────────────────────────────
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# ── Launcher executable ────────────────────────────────────────────
cat > "$APP_BUNDLE/Contents/MacOS/W0BCQ Logger" << LAUNCHER
#!/bin/bash
cd "$APP_DIR"
if [ ! -f "venv/bin/python" ]; then
    osascript -e 'display alert "W0BCQ Logger" message "App not set up yet. Please run setup.sh first."'
    exit 1
fi
exec venv/bin/python main.py
LAUNCHER
chmod +x "$APP_BUNDLE/Contents/MacOS/W0BCQ Logger"

# ── Icon (convert PNG → ICNS using built-in Mac tools) ────────────
ICON_SRC="$APP_DIR/icon_256.png"
if [ -f "$ICON_SRC" ] && command -v sips &>/dev/null && command -v iconutil &>/dev/null; then
    ICONSET=$(mktemp -d)
    sips -z 16   16   "$ICON_SRC" --out "$ICONSET/icon_16x16.png"      &>/dev/null
    sips -z 32   32   "$ICON_SRC" --out "$ICONSET/icon_16x16@2x.png"   &>/dev/null
    sips -z 32   32   "$ICON_SRC" --out "$ICONSET/icon_32x32.png"      &>/dev/null
    sips -z 64   64   "$ICON_SRC" --out "$ICONSET/icon_32x32@2x.png"   &>/dev/null
    sips -z 128  128  "$ICON_SRC" --out "$ICONSET/icon_128x128.png"    &>/dev/null
    sips -z 256  256  "$ICON_SRC" --out "$ICONSET/icon_128x128@2x.png" &>/dev/null
    sips -z 256  256  "$ICON_SRC" --out "$ICONSET/icon_256x256.png"    &>/dev/null
    # iconutil expects a directory named *.iconset
    ICONSET_DIR="$APP_DIR/AppIcon.iconset"
    mv "$ICONSET" "$ICONSET_DIR"
    iconutil -c icns "$ICONSET_DIR" -o "$APP_BUNDLE/Contents/Resources/AppIcon.icns" 2>/dev/null
    rm -rf "$ICONSET_DIR"
fi

# ── Info.plist ─────────────────────────────────────────────────────
cat > "$APP_BUNDLE/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>W0BCQ Logger</string>
    <key>CFBundleDisplayName</key>
    <string>W0BCQ Logger</string>
    <key>CFBundleIdentifier</key>
    <string>com.w0bcq.radioLogger</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleExecutable</key>
    <string>W0BCQ Logger</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.14</string>
</dict>
</plist>
PLIST

# ── Clear quarantine so macOS doesn't block launch ─────────────────
xattr -cr "$APP_BUNDLE" 2>/dev/null

echo "Done: $APP_BUNDLE"
echo
echo "Drag '$APP_NAME.app' to your Desktop or Applications folder."
echo "On first launch, right-click > Open if macOS shows a security warning."
