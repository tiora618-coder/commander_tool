#!/bin/bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

APP_NAME="CommanderTool"
DIST_DIR="$ROOT_DIR/dist"
RELEASE_DIR="$ROOT_DIR/Release"
STAGE_DIR="$RELEASE_DIR/_zip_stage"

APP_PATH="$DIST_DIR/$APP_NAME.app"
PLIST="$APP_PATH/Contents/Info.plist"

MAIN_PY="$ROOT_DIR/main.py"
README_SRC="$RELEASE_DIR/README.txt"
README_TMP="$STAGE_DIR/README.txt"

# ===============================
# Get version from main.py
# ===============================
APP_VERSION=$(grep -E '^APP_VERSION *= *"' "$MAIN_PY" | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$APP_VERSION" ]; then
  echo "ERROR: APP_VERSION not found"
  exit 1
fi

ZIP_NAME="CommanderTool_v${APP_VERSION}_Mac.zip"
ZIP_PATH="$RELEASE_DIR/$ZIP_NAME"

echo "=== Commander Tool Version: $APP_VERSION ==="
echo "ZIP output: $ZIP_PATH"

# ===============================
# PyInstaller build
# ===============================
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
  "$MAIN_PY"

# ===============================
# Update Info.plist
# ===============================
echo "=== Update Info.plist ==="
/usr/libexec/PlistBuddy -c "Add :NSCameraUsageDescription string 'This app uses the camera for card recognition.'" "$PLIST" || \
/usr/libexec/PlistBuddy -c "Set :NSCameraUsageDescription 'This app uses the camera for card recognition.'" "$PLIST"

/usr/libexec/PlistBuddy -c "Add :NSDocumentsFolderUsageDescription string 'Used to load deck files.'" "$PLIST" || \
/usr/libexec/PlistBuddy -c "Set :NSDocumentsFolderUsageDescription 'Used to load deck files.'" "$PLIST"

# ===============================
# Codesign
# ===============================
echo "=== Codesign ==="
codesign --force --deep --sign - "$APP_PATH"

# ===============================
# Remove quarantine
# ===============================
echo "=== Remove quarantine ==="
xattr -dr com.apple.quarantine "$APP_PATH"

# ===============================
# Prepare ZIP staging directory
# ===============================
echo "=== Prepare ZIP staging directory ==="
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# README with version header
{
  echo "Commander Tool v${APP_VERSION}"
  echo
  cat "$README_SRC"
} > "$README_TMP"

# Copy files into staging (flat)
cp -R "$APP_PATH" "$STAGE_DIR/"
cp "$RELEASE_DIR/LICENSE" "$STAGE_DIR/"
cp "$RELEASE_DIR/Sample_deck_file_Zurgo_Stormrender.txt" "$STAGE_DIR/"

# ===============================
# Create ZIP (absolute path)
# ===============================
echo "=== Create release ZIP ==="
rm -f "$ZIP_PATH"

cd "$STAGE_DIR"
zip -r "$ZIP_PATH" .
cd "$ROOT_DIR"

# ===============================
# Cleanup
# ===============================
rm -rf "$STAGE_DIR"

echo
echo "=== Release build completed ==="
echo "Output: $ZIP_PATH"
echo
