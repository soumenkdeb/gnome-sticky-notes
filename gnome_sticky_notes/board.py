"""The list of every note, in the style of the Windows Sticky Notes home."""

from __future__ import annotations

from . import bootstrap  # noqa: F401

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from . import APP_NAME
from .model import COLORS, search_blob, subtitle, window_title
from .theme import appearance_menu as _appearance_menu


class NoteRow(Gtk.ListBoxRow):
    def __init__(self, board: Board, note):
        super().__init__()
        self.board = board
        self.note = note
        self.blob = ""
        box = Gtk.Box(spacing=8)
        self.swatch = Gtk.Box()
        self.swatch.set_size_request(8, -1)
        self.swatch.add_css_class("note-swatch")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, spacing=2)
        text.set_margin_top(8)
        text.set_margin_bottom(8)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("note-card-title")
        self.detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.detail.add_css_class("dim-label")
        text.append(self.title)
        text.append(self.detail)
        self.pin_icon = Gtk.Image(icon_name="view-pin-symbolic")
        self.bell = Gtk.Image(icon_name="alarm-symbolic")
        menu_button = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Note actions")
        menu_button.add_css_class("flat")
        menu_button.set_menu_model(self._menu())
        menu_button.connect("notify::active", self._on_menu)
        box.append(self.swatch)
        box.append(text)
        box.append(self.pin_icon)
        box.append(self.bell)
        box.append(menu_button)
        self.set_child(box)
        self.refresh()

    def _menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("Open", "win.open")
        menu.append("Pin or unpin", "win.pin")
        menu.append("Duplicate", "win.duplicate")
        menu.append("Delete", "win.delete")
        return menu

    def _on_menu(self, button, _pspec) -> None:
        if button.get_active():
            self.board.list.select_row(self)

    def refresh(self) -> None:
        note = self.note
        self.blob = search_blob(note)
        self.title.set_text(window_title(note, self.board.app.store.notes))
        detail = subtitle(note)
        if note.kind == "todo":
            detail = f"Checklist · {detail}"
        self.detail.set_text(detail)
        for name in COLORS:
            self.swatch.remove_css_class(f"swatch-{name}")
        self.swatch.add_css_class(f"swatch-{note.color}")
        self.pin_icon.set_visible(note.pinned)
        reminded = bool(note.reminder) or any(item.reminder for item in note.items)
        self.bell.set_visible(reminded)
        if note.open:
            self.add_css_class("note-card-open")
        else:
            self.remove_css_class("note-card-open")


class Board(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.allow_close = False
        self.rows: dict[str, NoteRow] = {}
        self.set_default_size(440, 620)
        self.add_css_class("sticky-board")
        self.set_scheme_dark(app.effective_dark())

        header = Adw.HeaderBar()
        new_note = Gtk.Button(icon_name="list-add-symbolic", label="Note", tooltip_text="New text note")
        new_note.connect("clicked", lambda *_: app.create_note("text"))
        new_todo = Gtk.Button(icon_name="view-list-symbolic", tooltip_text="New checklist")
        new_todo.connect("clicked", lambda *_: app.create_note("todo"))
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        menu_button.set_menu_model(self._app_menu())
        header.pack_start(new_note)
        header.pack_start(new_todo)
        header.pack_end(menu_button)

        self.search = Gtk.SearchEntry(placeholder_text="Search notes")
        self.search.set_margin_start(12)
        self.search.set_margin_end(12)
        self.search.set_margin_top(6)
        self.search.set_margin_bottom(6)
        self.search.connect("search-changed", lambda *_: self._on_search())

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("boxed-list")
        self.list.set_margin_start(12)
        self.list.set_margin_end(12)
        self.list.set_margin_bottom(12)
        self.list.set_filter_func(self._filter)
        self.list.set_sort_func(self._sort)
        self.list.connect("row-activated", self._on_activated)
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.set_child(self.list)

        self.status = Adw.StatusPage(
            title="No notes yet",
            description="Create a text note or a checklist. You can also drop text here, or use New from clipboard.",
            icon_name="document-edit-symbolic",
        )
        paste = Gtk.Button(label="New from clipboard")
        paste.add_css_class("pill")
        paste.connect("clicked", lambda *_: app.new_from_clipboard())
        self.status.set_child(paste)

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(self.status, "empty")
        self.stack.add_named(scrolled, "list")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.search)
        body.append(self.stack)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(body)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        for name, handler in (
            ("open", self._action_open),
            ("pin", self._action_pin),
            ("duplicate", self._action_duplicate),
            ("delete", self._action_delete),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        self._selected_id = None

    def _app_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append("New note", "app.new-note")
        menu.append("New checklist", "app.new-todo")
        menu.append("New from clipboard", "app.from-clipboard")
        menu.append("Launch at login", "app.autostart")
        menu.append_section("Appearance", _appearance_menu())
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        return menu

    def set_scheme_dark(self, dark: bool) -> None:
        if dark:
            self.add_css_class("scheme-dark")
            self.remove_css_class("scheme-light")
        else:
            self.add_css_class("scheme-light")
            self.remove_css_class("scheme-dark")

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(message))

    def reload(self) -> None:
        child = self.list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.list.remove(child)
            child = nxt
        self.rows.clear()
        for note in self.app.store.notes:
            self._add_row(note)
        self.list.invalidate_sort()
        self.list.invalidate_filter()
        self._sync_empty()

    def refresh_one(self, note) -> None:
        row = self.rows.get(note.id)
        if row is None:
            self._add_row(note)
        else:
            row.note = note
            row.refresh()
        self.list.invalidate_sort()
        self.list.invalidate_filter()
        self._sync_empty()

    def remove_row(self, note_id: str) -> None:
        row = self.rows.pop(note_id, None)
        if row is not None:
            self.list.remove(row)
        self._sync_empty()

    def _add_row(self, note) -> None:
        row = NoteRow(self, note)
        self.rows[note.id] = row
        self.list.append(row)

    def _filter(self, row: NoteRow) -> bool:
        query = self.search.get_text().strip().lower()
        if not query:
            return True
        return query in row.blob

    def _sort(self, left: NoteRow, right: NoteRow) -> int:
        if left.note.pinned != right.note.pinned:
            return -1 if left.note.pinned else 1
        if left.note.updated != right.note.updated:
            return -1 if left.note.updated > right.note.updated else 1
        return 0

    def _on_search(self) -> None:
        self.list.invalidate_filter()
        self._sync_empty()

    def _sync_empty(self) -> None:
        query = self.search.get_text().strip().lower()
        notes = self.app.store.notes
        if not notes:
            self.status.set_title("No notes yet")
            self.status.set_description(
                "Create a text note or a checklist. Drop text here, or use New from clipboard."
            )
            self.stack.set_visible_child_name("empty")
            return
        matches = [note for note in notes if not query or query in search_blob(note)]
        if not matches:
            self.status.set_title("No matching notes")
            self.status.set_description("Try a different search.")
            self.stack.set_visible_child_name("empty")
            return
        self.stack.set_visible_child_name("list")

    def _on_activated(self, _list, row: NoteRow) -> None:
        self.app.present_note(row.note)

    def _target(self) -> str | None:
        row = self.list.get_selected_row()
        if row is None:
            return None
        return row.note.id

    def _action_open(self, *_args) -> None:
        note_id = self._target()
        note = self.app.store.get(note_id) if note_id else None
        if note:
            self.app.present_note(note)

    def _action_pin(self, *_args) -> None:
        note_id = self._target()
        note = self.app.store.get(note_id) if note_id else None
        if note:
            self.app.set_pinned(note, not note.pinned)

    def _action_duplicate(self, *_args) -> None:
        note_id = self._target()
        note = self.app.store.get(note_id) if note_id else None
        if note:
            self.app.duplicate_note(note)

    def _action_delete(self, *_args) -> None:
        note_id = self._target()
        note = self.app.store.get(note_id) if note_id else None
        if note is None:
            return
        dialog = Adw.AlertDialog(
            heading="Delete this note?",
            body="The note and its reminders will be removed.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _dialog, response, note=note: self.app.delete_note(note) if response == "delete" else None)
        dialog.present(self)

    def _on_drop(self, _target, value, _x, _y) -> bool:
        if isinstance(value, str) and value.strip():
            self.app.create_from_text(value)
            return True
        return False
