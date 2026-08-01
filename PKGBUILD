pkgname=wei-timer
pkgver=0.1.1
pkgrel=1
pkgdesc="Independent training timer detector and carat tracker for Umamusume (wlroots Wayland compositors)"
arch=('any')
url="https://lunaui.cc/wei-timer"
license=('MIT')
depends=(
    'python'
    'python-gobject'
    'gtk4'
    'libadwaita'
    'tesseract'
    'tesseract-data-eng'
    'python-pillow'
    'python-pytesseract'
    'python-imagehash'
    'libayatana-appindicator'
)
optdepends=(
    'grim: screen capture on wlroots Wayland compositors'
    'slurp: region selection on wlroots Wayland compositors'
    'scrot: screen capture on X11'
    'slop: region selection on X11'
    'gstreamer: live screen capture for the autorun watcher on GNOME/Plasma Wayland'
    'gst-plugins-base: live screen capture for the autorun watcher on GNOME/Plasma Wayland'
    'gst-plugin-pipewire: live screen capture for the autorun watcher on GNOME/Plasma Wayland'
)
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=()

build() {
    cd "$startdir"
    python -m build --wheel --no-isolation --outdir "$srcdir/dist"
}

package() {
    cd "$startdir"
    python -m installer --destdir="$pkgdir" "$srcdir/dist"/*.whl
    install -Dm644 sounds/*.mp3 -t "$pkgdir/usr/share/$pkgname/sounds/" 2>/dev/null || true
    install -Dm644 packaging/wei-timer.desktop \
        "$pkgdir/usr/share/applications/wei-timer.desktop"
    install -Dm644 packaging/wei-timer.png \
        "$pkgdir/usr/share/icons/hicolor/256x256/apps/wei-timer.png"
}