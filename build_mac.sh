#!/bin/bash
set -e

APP_NAME="CommanderTool"
DIST_DIR="dist"
APP_PATH="$DIST_DIR/$APP_NAME.app"
PLIST="$APP_PATH/Contents/Info.plist"

echo "=== PyInstaller build ==="
pyinstaller \
  --onedir \
  --windowed \
  --noconsole \
  --name "$APP_NAME" \
  --collect-all cv2 \
  --collect-all torch \
  --add-data "weights:weights" \
  --add-data "venv/lib/python3.11/site-packages/open_clip:open_clip" \
  --clean \
  --noconfirm \
  main.py

echo "=== Update Info.plist ==="
/usr/libexec/PlistBuddy -c "Add :NSCameraUsageDescription string 'This app uses the camera for card recognition.'" "$PLIST" || \
/usr/libexec/PlistBuddy -c "Set :NSCameraUsageDescription 'This app uses the camera for card recognition.'" "$PLIST"

/usr/libexec/PlistBuddy -c "Add :NSDocumentsFolderUsageDescription string 'Used to load deck files.'" "$PLIST" || \
/usr/libexec/PlistBuddy -c "Set :NSDocumentsFolderUsageDescription 'Used to load deck files.'" "$PLIST"

echo "=== Codesign ==="
codesign --force --deep --sign - "$APP_PATH"

echo "=== Remove quarantine ==="
xattr -dr com.apple.quarantine "$APP_PATH"

echo "=== Zip for release ==="
cd "$DIST_DIR"
zip -r "$APP_NAME-mac.zip" "$APP_NAME.app"

echo "=== Done ==="
