#!/bin/sh
# Install Sticky Notes for the current user: launcher, desktop entry, icon, and the optional pin extension.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
APP_ID=app.sdeb.StickyNotes
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
EXT_DIR="${HOME}/.local/share/gnome-shell/extensions/sticky-notes-pin@sdeb.app"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$EXT_DIR"
chmod +x "$ROOT/bin/gnome-sticky-notes"
ln -sfn "$ROOT/bin/gnome-sticky-notes" "$BIN_DIR/gnome-sticky-notes"
cp -f "$ROOT/data/icons/hicolor/scalable/apps/${APP_ID}.svg" "$ICON_DIR/${APP_ID}.svg"
cp -f "$ROOT/extension/metadata.json" "$ROOT/extension/extension.js" "$EXT_DIR/"

cat > "$APP_DIR/${APP_ID}.desktop" << EOF
[Desktop Entry]
Name=Sticky Notes
GenericName=Sticky Notes
Comment=Pin notes, write text, and keep checklists with reminders
Exec=${ROOT}/bin/gnome-sticky-notes
Icon=${APP_ID}
Terminal=false
Type=Application
Categories=Utility;GTK;GNOME;
Keywords=sticky;notes;todo;checklist;reminder;
StartupWMClass=gnome-sticky-notes
Actions=new-note;new-todo;from-clipboard;

[Desktop Action new-note]
Name=New Note
Exec=${ROOT}/bin/gnome-sticky-notes --new

[Desktop Action new-todo]
Name=New Checklist
Exec=${ROOT}/bin/gnome-sticky-notes --new-todo

[Desktop Action from-clipboard]
Name=New Note from Clipboard
Exec=${ROOT}/bin/gnome-sticky-notes --from-clipboard
EOF

if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
    gtk4-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions enable sticky-notes-pin@sdeb.app >/dev/null 2>&1 || true
fi

echo "Installed Sticky Notes."
echo "  Launch: ${ROOT}/bin/gnome-sticky-notes"
echo "  Also on PATH: ${BIN_DIR}/gnome-sticky-notes"
