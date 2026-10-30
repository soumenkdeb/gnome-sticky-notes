# Sticky Notes

A GNOME desktop app in the spirit of Windows Sticky Notes. Each note is its own window. You can write text, turn a note into a checklist, set a reminder, and pin a note so it stays above other windows on every workspace.

## Install on Arch Linux

From this directory:

```sh
make package
sudo pacman -U gnome-sticky-notes-1.0.0-2-any.pkg.tar.zst
```

`make package` builds a normal pacman package. It installs the command to `/usr/bin/gnome-sticky-notes`, a desktop entry, the icon, an AppStream metainfo file, and the optional Wayland pin extension. Pacman updates the icon and desktop caches.

If `~/.local/bin/gnome-sticky-notes` still exists from an earlier user install, remove that symlink after `pacman -U`. It would otherwise hide the system command.

`make install` remains a user-local install under `~/.local`, without pacman.

## Run

```sh
gnome-sticky-notes
```

Notes are stored in `~/.local/share/app.sdeb.StickyNotes/notes.json`.

## Notes

- **Text.** The first line is the title. Ctrl+B, Ctrl+I, Ctrl+U, and Ctrl+Shift+X toggle bold, italic, underline, and strikethrough. The bullet button prefixes the current lines.
- **Checklist.** Switch a note from the menu, or create one with the list button. Enter adds a task. Backspace on an empty task removes it. Each task can have its own reminder.
- **Pin.** The pin keeps the note above other windows and on every workspace. Close hides a note; Delete in the menu removes it.
- **Appearance.** System, Light, or Dark is in the All notes menu and in each note menu. Note colors follow that choice, so a yellow note stays readable in both themes. System tracks the GNOME color scheme.
- **Reminders.** Use the bell for a time, or the shortcuts for an hour from now, tonight, or tomorrow morning. A notification can snooze for 10 minutes or an hour. The app keeps running after the last window closes when a reminder is still pending. Turn on **Launch at login** in the All notes menu if reminders should survive a reboot.
- **From text.** Drop text on the notes list, choose **New from clipboard**, or use the terminal:

```sh
gnome-sticky-notes --text "Buy milk"
printf 'Meeting notes\nBring the checklist' | gnome-sticky-notes --text -
gnome-sticky-notes --todo "Call Sam" --todo "Pay rent"
gnome-sticky-notes --new
gnome-sticky-notes --new-todo
gnome-sticky-notes --from-clipboard
```

Checkbox lines (`- [ ]`, `- [x]`, `☐`) become a checklist when they come from the clipboard or a drop. `--text` always makes a text note. Piping with `--text -` works even if the app is already open.

## Pinning on GNOME

This session is Wayland, and GTK 4 cannot ask the compositor to keep a normal window above others. GNOME still honors the X11 “always on top” hint for XWayland windows, and this display is at 100% scale, so the launcher uses the X11 backend by default.

To run as a native Wayland client instead:

```sh
STICKY_NOTES_BACKEND=wayland gnome-sticky-notes
```

Wayland pinning needs the bundled GNOME Shell extension in `extension/`. `make install` copies it to your extensions directory. Enable **Sticky Notes Pin** and log out once if it was not picked up immediately. The extension only changes windows that belong to this app.

## Tests

```sh
make test
```
