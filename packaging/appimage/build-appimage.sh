#!/usr/bin/env bash
set -euo pipefail

# Requires: an x86_64 Linux system with GTK4/libadwaita/PyGObject already
# installed (the same deps PKGBUILD lists), since linuxdeploy bundles
# whatever's actually present on the build machine.

APP_NAME="wei-timer"
VERSION="${1:-0.1.0}"
BUILD_DIR="$(pwd)/build-appimage"
APPDIR="$BUILD_DIR/AppDir"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$BUILD_DIR/tools"

echo "==> Installing wei_timer + Python deps into AppDir"
python3 -m venv "$APPDIR/usr/python-env" --system-site-packages
"$APPDIR/usr/python-env/bin/pip" install --no-cache-dir .

echo "==> Copying desktop entry, icon, and sounds"
cp packaging/wei-timer.desktop "$APPDIR/usr/share/applications/"
cp packaging/wei-timer.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/" 2>/dev/null || \
    echo "warning: packaging/wei-timer.png not found, AppImage will use a generic icon"
mkdir -p "$APPDIR/usr/share/wei-timer/sounds"
cp sounds/*.mp3 "$APPDIR/usr/share/wei-timer/sounds/" 2>/dev/null || \
    echo "warning: no sound files in sounds/, bundled sound options won't work in this build"

echo "==> Writing AppRun"
cat > "$APPDIR/AppRun" << 'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"

if [ -d "$HERE/apprun-hooks" ]; then
    for hook in "$HERE"/apprun-hooks/*.sh; do
        [ -f "$hook" ] && . "$hook"
    done
fi

export PATH="$HERE/usr/python-env/bin:$PATH"
exec "$HERE/usr/python-env/bin/wei-timer" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cp packaging/wei-timer.desktop "$APPDIR/"
cp packaging/wei-timer.png "$APPDIR/" 2>/dev/null || true

echo "==> Fetching linuxdeploy and the GTK plugin (if not already present)"
mkdir -p "$BUILD_DIR/tools"
cd "$BUILD_DIR/tools"
[ -f linuxdeploy-x86_64.AppImage ] || \
    curl -L -o linuxdeploy-x86_64.AppImage \
    https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
[ -f linuxdeploy-plugin-gtk.sh ] || \
    curl -L -o linuxdeploy-plugin-gtk.sh \
    https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh
chmod +x linuxdeploy-x86_64.AppImage linuxdeploy-plugin-gtk.sh
cd - > /dev/null

echo "==> Patching copy_lib_tree to tolerate missing source directories (GTK4 systems often lack legacy module dirs)"
sed -i '/^copy_lib_tree() {/a\    [ -d "$1" ] || return 0' "$BUILD_DIR/tools/linuxdeploy-plugin-gtk.sh"

echo "==> Running linuxdeploy with the GTK plugin (bundles GTK4/libadwaita/PyGObject)"
DEPLOY_GTK_VERSION=4 \
"$BUILD_DIR/tools/linuxdeploy-x86_64.AppImage" \
    --appdir "$APPDIR" \
    --plugin gtk \
    --desktop-file "$APPDIR/wei-timer.desktop" \
    --icon-file "$APPDIR/wei-timer.png" \
    --output appimage

mv "$APP_NAME"*.AppImage "Wei_Timer-${VERSION}-x86_64.AppImage" 2>/dev/null || true
echo "==> Done: Wei_Timer-${VERSION}-x86_64.AppImage"