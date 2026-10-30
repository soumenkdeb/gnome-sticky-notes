"""Application object: one process, many notes, reminders in the background."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
from datetime import datetime
from pathlib import Path

from . import bootstrap  # noqa: F401

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import __version__, pinning
from .board import Board
from .model import Note, TodoItem, WELCOME_TEXT, next_color, parse_checklist, plain_to_spans, window_title
from .note_window import NoteWindow
from .reminders import due_entries, has_pending_reminder, reminder_copy, snooze_until
from .store import Store, data_dir

# Imported lazily so model stays free of the env-based id. The real id is below.
from . import APP_ID


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def launcher_exec() -> str:
    """Command written into the autostart desktop file."""
    bundled = project_root() / "bin" / "gnome-sticky-notes"
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("gnome-sticky-notes")
    if found:
        return found
    return "/usr/bin/gnome-sticky-notes"


def desktop_file_text(autostart: bool = False) -> str:
    command = launcher_exec()
    extra = "X-GNOME-Autostart-enabled=true\n" if autostart else ""
    return f"""[Desktop Entry]
Name=Sticky Notes
GenericName=Sticky Notes
Comment=Pin notes, write text, and keep checklists with reminders
Exec={command}
Icon={APP_ID}
Terminal=false
Type=Application
Categories=Utility;GTK;GNOME;
Keywords=sticky;notes;todo;checklist;reminder;
StartupWMClass=gnome-sticky-notes
Actions=new-note;new-todo;from-clipboard;
{extra}
[Desktop Action new-note]
Name=New Note
Exec={command} --new

[Desktop Action new-todo]
Name=New Checklist
Exec={command} --new-todo

[Desktop Action from-clipboard]
Name=New Note from Clipboard
Exec={command} --from-clipboard
"""


class StickyApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.set_property("register-session", True)
        GLib.set_application_name("Sticky Notes")
        GLib.set_prgname("gnome-sticky-notes")
        self.store = Store()
        self.windows: dict[str, NoteWindow] = {}
        self.board: Board | None = None
        self.quitting = False
        self._started = False
        self._save_id = 0
        self._selftest_done = False
        self.set_option_context_summary("Notes that stay on the GNOME desktop.")
        self.add_main_option("new", ord("n"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Open a new text note", None)
        self.add_main_option("new-todo", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Open a new checklist", None)
        self.add_main_option(
            "text",
            ord("t"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Create a text note from TEXT. Use - to read standard input",
            "TEXT",
        )
        self.add_main_option(
            "todo",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING_ARRAY,
            "Create a checklist. Repeat for each task",
            "ITEM",
        )
        self.add_main_option(
            "from-clipboard",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Create a note from the clipboard",
            None,
        )
        self.add_main_option("version", ord("v"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Show the version", None)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()
        self.store.load()
        self._load_style()
        self._install_actions()
        Gtk.Window.set_default_icon_name(APP_ID)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._on_signal)
        GLib.timeout_add_seconds(15, self._check_reminders)
        GLib.idle_add(self._first_reminder_check)

    def do_activate(self):
        self._ensure_started()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        if options.contains("version"):
            self._cli_print(command_line, f"Sticky Notes {__version__}\n")
            if not self._started:
                GLib.idle_add(self.quit_app)
            return 0
        self._ensure_started()
        if os.environ.get("STICKY_NOTES_SELFTEST") == "1" and not self._selftest_done:
            self._selftest_done = True
            self._run_selftest()
            return 0
        created = self._apply_options(options)
        if not created and command_line.get_is_remote():
            self.show_board()
        return 0

    def do_shutdown(self):
        self.quitting = True
        try:
            if self._started and self.store is not None:
                for window in self.windows.values():
                    window.capture_geometry()
                self.store.save()
                self.write_pins()
        except Exception:
            pass
        Adw.Application.do_shutdown(self)

    def _on_signal(self):
        self.quit_app()
        return GLib.SOURCE_REMOVE

    def _cli_print(self, command_line, text: str) -> None:
        printer = getattr(command_line, "print_literal", None)
        if printer is not None:
            printer(text)
        else:
            print(text, end="")

    def _load_style(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("style.css")))
        display = Gdk.Display.get_default()
        if display is None:
            return
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        icon_root = project_root() / "data" / "icons"
        if icon_root.is_dir():
            Gtk.IconTheme.get_for_display(display).add_search_path(str(icon_root))

    def _install_actions(self) -> None:
        for name, handler in (
            ("new-note", lambda *_: self.create_note("text")),
            ("new-todo", lambda *_: self.create_note("todo")),
            ("from-clipboard", lambda *_: self.new_from_clipboard()),
            ("show-board", lambda *_: self.show_board()),
            ("quit", lambda *_: self.quit_app()),
            ("about", self._show_about),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        autostart = Gio.SimpleAction.new_stateful(
            "autostart", None, GLib.Variant.new_boolean(self.store.autostart)
        )
        autostart.connect("change-state", self._on_autostart)
        self.add_action(autostart)

        appearance = Gio.SimpleAction.new_stateful(
            "appearance",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(self.store.appearance),
        )
        appearance.connect("change-state", self._on_appearance)
        self.add_action(appearance)
        Adw.StyleManager.get_default().connect("notify::dark", self._on_system_scheme)
        self.apply_appearance()

        open_note = Gio.SimpleAction.new("open-note", GLib.VariantType.new("s"))
        open_note.connect("activate", self._on_open_note)
        self.add_action(open_note)

        snooze = Gio.SimpleAction.new("snooze", GLib.VariantType.new("(ssi)"))
        snooze.connect("activate", self._on_snooze)
        self.add_action(snooze)

        self.set_accels_for_action("app.new-note", ["<primary>n"])
        self.set_accels_for_action("app.new-todo", ["<primary><shift>n"])
        self.set_accels_for_action("app.show-board", ["<primary><shift>h"])
        self.set_accels_for_action("app.quit", ["<primary>q"])
        self.set_accels_for_action("win.pin", ["<primary>p"])

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        if os.environ.get("STICKY_NOTES_SELFTEST") == "1":
            return
        if self.store.fresh and not os.environ.get("STICKY_NOTES_NO_WELCOME"):
            self._create_welcome()
        else:
            opened = False
            for note in self.store.notes:
                if note.open:
                    self.present_note(note, focus=False)
                    opened = True
            if not opened:
                self.show_board()
        if not os.environ.get("STICKY_NOTES_DIR"):
            self.sync_autostart()
        self.write_pins()

    def _create_welcome(self) -> None:
        self.create_note("text", text=WELCOME_TEXT, color="yellow")

    def _apply_options(self, options) -> bool:
        created = False
        if options.contains("text"):
            value = options.lookup_value("text", None)
            text = value.get_string() if value is not None else ""
            self.create_from_text(text, force="text")
            created = True
        if options.contains("todo"):
            value = options.lookup_value("todo", None)
            items: list[TodoItem] = []
            if value is not None:
                for entry in value.unpack():
                    for line in str(entry).splitlines():
                        if line.strip():
                            items.append(TodoItem.new(text=line.strip()))
            self.create_note("todo", items=items or [TodoItem.new()])
            created = True
        if options.contains("new"):
            self.create_note("text")
            created = True
        if options.contains("new-todo"):
            self.create_note("todo")
            created = True
        if options.contains("from-clipboard"):
            self.new_from_clipboard()
            created = True
        return created

    def create_note(self, kind="text", *, text="", items=None, title="", color=None, present=True) -> Note:
        note = Note.new(kind="todo" if kind == "todo" else "text", color=color or next_color(self.store.notes))
        if note.kind == "text":
            note.body = plain_to_spans(text)
        else:
            note.title = title
            note.items = list(items) if items is not None else [TodoItem.new()]
        index = len(self.store.notes)
        note.x, note.y = pinning.cascade_position(index, note.width, note.height)
        self.store.notes.append(note)
        if present:
            self.present_note(note)
        elif self.board:
            self.board.refresh_one(note)
        self.schedule_save()
        self.write_pins()
        return note

    def create_from_text(self, text: str, force: str | None = None) -> Note:
        cleaned = (text or "").replace("\0", "")
        if force == "todo":
            lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
            return self.create_note("todo", items=[TodoItem.new(text=line) for line in lines] or [TodoItem.new()])
        if force != "text":
            parsed = parse_checklist(cleaned)
            if parsed is not None:
                return self.create_note("todo", items=parsed)
        return self.create_note("text", text=cleaned.strip())

    def present_note(self, note: Note, focus: bool = True) -> None:
        note.open = True
        window = self.windows.get(note.id)
        if window is None:
            window = NoteWindow(self, note)
            self.windows[note.id] = window
        window.present()
        if focus:
            GLib.idle_add(window.focus_editor)
        if self.board:
            self.board.refresh_one(note)
        self.write_pins()

    def hide_note(self, note: Note) -> None:
        note.open = False
        window = self.windows.pop(note.id, None)
        if window is not None:
            window.capture_geometry()
            window.allow_close = True
            window.destroy()
        if self.board:
            self.board.refresh_one(note)
        self.write_pins()
        self.schedule_save()

    def delete_note(self, note: Note) -> None:
        self.hide_note(note)
        self.store.notes = [item for item in self.store.notes if item.id != note.id]
        if self.board:
            self.board.remove_row(note.id)
        self.write_pins()
        self.schedule_save()
        self.refresh_titles()
        if not self.store.notes:
            self.show_board()

    def duplicate_note(self, note: Note) -> Note:
        copy = note.duplicate()
        if copy.x is None or copy.y is None:
            copy.x, copy.y = pinning.cascade_position(len(self.store.notes), copy.width, copy.height)
        self.store.notes.append(copy)
        self.present_note(copy)
        self.schedule_save()
        return copy

    def set_pinned(self, note: Note, pinned: bool) -> None:
        note.pinned = bool(pinned)
        note.touch()
        window = self.windows.get(note.id)
        if window is not None:
            window.sync_pin()
        if self.board:
            self.board.refresh_one(note)
        self.write_pins()
        self.schedule_save()

    def set_color(self, note: Note, color: str) -> None:
        note.color = color
        note.touch()
        window = self.windows.get(note.id)
        if window is not None:
            window.apply_color()
        if self.board:
            self.board.refresh_one(note)
        self.schedule_save()

    def note_edited(self, note: Note) -> None:
        self.refresh_titles()
        if self.board:
            self.board.refresh_one(note)
        self.schedule_save()

    def refresh_titles(self) -> None:
        changed = False
        for note in self.store.notes:
            window = self.windows.get(note.id)
            if window is None:
                continue
            title = window_title(note, self.store.notes)
            if window.get_title() != title:
                window.set_title(title)
                changed = True
        if changed and any(note.pinned and note.open for note in self.store.notes):
            self.write_pins()

    def show_board(self):
        if self.board is None:
            self.board = Board(self)
            self.board.connect("close-request", self._on_board_close)
        self.board.reload()
        self.board.present()
        return self.board

    def _on_board_close(self, board) -> bool:
        if self.quitting or board.allow_close:
            return False
        open_notes = any(note.open for note in self.store.notes)
        pending = has_pending_reminder(self.store.notes)
        if open_notes or pending:
            board.hide()
            if pending and not open_notes and not self.store.hinted_background:
                self._notify_background()
                self.store.hinted_background = True
                self.schedule_save()
            return True
        self.quit_app()
        return True

    def new_from_clipboard(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        clipboard = display.get_clipboard()
        clipboard.read_text_async(None, self._on_clipboard)

    def _on_clipboard(self, clipboard, result) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            text = None
        if not text or not str(text).strip():
            board = self.show_board()
            board.toast("The clipboard has no text.")
            return
        self.create_from_text(str(text))

    def write_pins(self) -> None:
        titles = [window_title(note, self.store.notes) for note in self.store.notes if note.pinned and note.open]
        path = data_dir() / "pinned.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"titles": titles}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def schedule_save(self) -> None:
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(400, self._flush_save)

    def _flush_save(self) -> bool:
        self._save_id = 0
        for window in self.windows.values():
            window.capture_geometry()
        self.store.save()
        return False

    def sync_autostart(self) -> None:
        if os.environ.get("STICKY_NOTES_DIR"):
            return
        path = Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"
        if self.store.autostart:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desktop_file_text(autostart=True), encoding="utf-8")
        elif path.exists():
            path.unlink()

    def _on_autostart(self, action, value) -> None:
        action.set_state(value)
        self.store.autostart = bool(value.get_boolean())
        self.sync_autostart()
        self.schedule_save()

    def effective_dark(self) -> bool:
        if self.store.appearance == "light":
            return False
        if self.store.appearance == "dark":
            return True
        return bool(Adw.StyleManager.get_default().get_dark())

    def apply_appearance(self) -> None:
        schemes = {
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }
        Adw.StyleManager.get_default().set_color_scheme(
            schemes.get(self.store.appearance, Adw.ColorScheme.DEFAULT)
        )
        self._apply_note_scheme()

    def _on_system_scheme(self, *_args) -> None:
        if self.quitting or self.store.appearance != "system":
            return
        self._apply_note_scheme()

    def _on_appearance(self, action, value) -> None:
        if value is None:
            return
        choice = value.get_string()
        if choice not in ("system", "light", "dark"):
            return
        action.set_state(GLib.Variant.new_string(choice))
        self.store.appearance = choice
        self.apply_appearance()
        self.schedule_save()

    def _apply_note_scheme(self) -> None:
        dark = self.effective_dark()
        if self.board is not None:
            self.board.set_scheme_dark(dark)
        for window in self.windows.values():
            window.set_scheme_dark(dark)

    def _check_reminders(self) -> bool:
        if not self._started or self.quitting:
            return True
        fired = False
        for kind, note, item in list(due_entries(self.store.notes)):
            if kind == "note":
                note.reminder_fired = True
                ident = f"note-{note.id}"
            else:
                item.reminder_fired = True
                ident = f"item-{item.id}"
            self._send_reminder(ident, kind, note, item)
            self.present_note(note)
            window = self.windows.get(note.id)
            if window is not None:
                window.refresh_reminder_labels()
            fired = True
        if fired:
            for window in self.windows.values():
                window.capture_geometry()
            self.store.save()
        return True

    def _first_reminder_check(self) -> bool:
        self._check_reminders()
        return GLib.SOURCE_REMOVE

    def _send_reminder(self, ident: str, kind: str, note: Note, item) -> None:
        title, body = reminder_copy(kind, note, item)
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_priority(Gio.NotificationPriority.NORMAL)
        notification.set_default_action_and_target("app.open-note", GLib.Variant.new_string(note.id))
        item_id = item.id if item is not None else ""
        for label, minutes in (("Snooze 10 min", 10), ("Snooze 1 hour", 60)):
            notification.add_button_with_target_value(
                label,
                "app.snooze",
                GLib.Variant.new_tuple(
                    GLib.Variant.new_string(note.id),
                    GLib.Variant.new_string(item_id),
                    GLib.Variant.new_int32(minutes),
                ),
            )
        self.send_notification(ident, notification)

    def _notify_background(self) -> None:
        notification = Gio.Notification.new("Sticky Notes is still running")
        notification.set_body("Reminders keep working while the app is open. Quit from the menu to exit.")
        notification.set_default_action("app.show-board")
        self.send_notification("background", notification)

    def _on_open_note(self, _action, param) -> None:
        note = self.store.get(param.get_string())
        if note is not None:
            self.present_note(note)

    def _on_snooze(self, _action, param) -> None:
        note_id, item_id, minutes = param.unpack()
        note = self.store.get(note_id)
        if note is None:
            return
        when = snooze_until(datetime.now(), int(minutes))
        if item_id:
            item = next((entry for entry in note.items if entry.id == item_id), None)
            if item is None:
                return
            item.reminder = when
            item.reminder_fired = False
            self.withdraw_notification(f"item-{item_id}")
        else:
            note.reminder = when
            note.reminder_fired = False
            self.withdraw_notification(f"note-{note.id}")
        note.touch()
        window = self.windows.get(note.id)
        if window is not None:
            window.refresh_reminder_labels()
        self.present_note(note)
        self.schedule_save()

    def _show_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name="Sticky Notes",
            application_icon=APP_ID,
            version=__version__,
            comments="Pin notes on the GNOME desktop, write text, and keep checklists with reminders.",
            license_type=Gtk.License.MIT_X11,
        )
        parent = self.get_active_window()
        if parent is None:
            parent = self.show_board()
        about.present(parent)

    def quit_app(self, *_args) -> None:
        if self.quitting:
            return
        self.quitting = True
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = 0
        if self._started and self.store is not None:
            for window in list(self.windows.values()):
                window.capture_geometry()
            self.store.save()
            self.write_pins()
        for window in list(self.windows.values()):
            window.allow_close = True
            window.destroy()
        self.windows.clear()
        if self.board is not None:
            self.board.allow_close = True
            self.board.destroy()
            self.board = None
        try:
            self.release()
        except Exception:
            pass
        Adw.Application.quit(self)

    def _run_selftest(self) -> None:
        note = self.create_note("text", text="Self test note")
        self.set_pinned(note, True)
        GLib.timeout_add(900, self._selftest_clear, note)

    def _selftest_clear(self, note: Note):
        window = self.windows.get(note.id)
        above = bool(window and pinning.is_kept_above(window))
        self.set_pinned(note, False)
        GLib.timeout_add(700, self._selftest_finish, note, above)
        return False

    def _selftest_finish(self, note: Note, was_above: bool):
        window = self.windows.get(note.id)
        cleared = bool(window and "_NET_WM_STATE_ABOVE" not in pinning.state_names(window))
        position = pinning.get_position(window) if window else None
        target = None
        delta = None
        if window is not None and window.note.x is not None and window.note.y is not None:
            target = list(
                pinning.position_on_screen(window.note.x, window.note.y, window.note.width, window.note.height)
            )
            if position is not None:
                delta = [position[0] - target[0], position[1] - target[1]]
        payload = {
            "above": was_above,
            "cleared": cleared,
            "position": list(position) if position else None,
            "target": target,
            "delta": delta,
            "x11": pinning.x11_backend(),
            "title": window.get_title() if window else "",
        }
        (data_dir() / "selftest.json").write_text(json.dumps(payload), encoding="utf-8")
        self.quit_app()
        return False


def _inline_stdin(argv: list[str]) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        output.append(token)
        if token in ("--text", "-t") and index + 1 < len(argv) and argv[index + 1] == "-":
            output.append(sys.stdin.read().replace("\0", ""))
            index += 2
            continue
        index += 1
    return output


def main(argv: list[str] | None = None) -> int:
    args = _inline_stdin(list(sys.argv if argv is None else argv))
    app = StickyApp()
    return app.run(args)
