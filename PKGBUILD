# Maintainer: Sticky Notes contributors
pkgname=gnome-sticky-notes
pkgver=1.0.0
pkgrel=2
pkgdesc='Sticky notes and checklists with reminders for GNOME'
arch=(any)
url='https://github.com/sdeb/gnome-sticky-notes'
license=(MIT)
depends=(
  python
  python-gobject
  gtk4
  libadwaita
  libx11
  hicolor-icon-theme
)
makedepends=(desktop-file-utils)
optdepends=('gnome-shell: pin notes when running as a native Wayland client')
options=(!debug)
install=gnome-sticky-notes.install
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('1b25f4fe2c1eeac800ef006597b8d329073cab858030291541940b16ba2f1057')

check() {
  cd "$pkgname-$pkgver"
  python -m unittest tests.test_model -v
  desktop-file-validate data/applications/app.sdeb.StickyNotes.desktop
}

package() {
  cd "$pkgname-$pkgver"
  local site
  site=$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
  install -d "$pkgdir$site/gnome_sticky_notes"
  install -m644 gnome_sticky_notes/*.py gnome_sticky_notes/style.css \
    "$pkgdir$site/gnome_sticky_notes/"
  install -Dm755 bin/gnome-sticky-notes "$pkgdir/usr/bin/gnome-sticky-notes"
  install -Dm644 data/applications/app.sdeb.StickyNotes.desktop \
    "$pkgdir/usr/share/applications/app.sdeb.StickyNotes.desktop"
  install -Dm644 data/icons/hicolor/scalable/apps/app.sdeb.StickyNotes.svg \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/app.sdeb.StickyNotes.svg"
  install -Dm644 data/metainfo/app.sdeb.StickyNotes.metainfo.xml \
    "$pkgdir/usr/share/metainfo/app.sdeb.StickyNotes.metainfo.xml"
  install -Dm644 extension/metadata.json \
    "$pkgdir/usr/share/gnome-shell/extensions/sticky-notes-pin@sdeb.app/metadata.json"
  install -Dm644 extension/extension.js \
    "$pkgdir/usr/share/gnome-shell/extensions/sticky-notes-pin@sdeb.app/extension.js"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
