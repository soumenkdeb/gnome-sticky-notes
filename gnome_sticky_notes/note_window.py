"""One sticky-note window: text or a checklist, with pin and reminder."""

from __future__ import annotations

from datetime import datetime, timedelta

from . import bootstrap  # noqa: F401

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import pinning
from .model import COLORS, Span, TodoItem, merge_spans, parse_checklist, spans_plain, window_title
from .theme import appearance_menu as _appearance_menu
from .reminders import format_when, is_past, stamp

_TYPING = ("bold", "italic", "underline", "strike")


def buffer_to_spans(buf: Gtk.TextBuffer, tags: dict) -> list[Span]:
    spans: list[Span] = []
    cursor = buf.get_start_iter()
    end = buf.get_end_iter()
    while not cursor.equal(end):
        nxt = cursor.copy()
        if not nxt.forward_to_tag_toggle(None):
            nxt = end.copy()
        text = buf.get_text(cursor, nxt, True)
        active = set(cursor.get_tags())
        spans.append(
            Span(
                text=text,
                bold=tags["bold"] in active,
                italic=tags["italic"] in active,
                underline=tags["underline"] in active,
                strike=tags["strike"] in active,
            )
        )
        cursor = nxt
    return merge_spans(spans)


class ReminderPopover(Gtk.Popover):
    def __init__(self):
        super().__init__()
        self._on_save = None
        self._on_clear = None
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(10)
        root.set_margin_bottom(10)
        root.set_margin_start(10)
        root.set_margin_end(10)
        quick = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for label, handler in (
            ("In 1 hour", self._in_one_hour),
            ("Tonight at 20:00", self._tonight),
            ("Tomorrow at 9:00", self._tomorrow),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            quick.append(button)
        root.append(quick)

        self.calendar = Gtk.Calendar()
        self.calendar.connect("day-selected", lambda *_: self._refresh_hint())
        root.append(self.calendar)

        times = Gtk.Box(spacing=8)
        times.append(Gtk.Label(label="Time"))
        self.hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.minute = Gtk.SpinButton.new_with_range(0, 59, 5)
        self.hour.set_wrap(True)
        self.minute.set_wrap(True)
        self.hour.connect("value-changed", lambda *_: self._refresh_hint())
        self.minute.connect("value-changed", lambda *_: self._refresh_hint())
        times.append(self.hour)
        times.append(Gtk.Label(label=":"))
        times.append(self.minute)
        root.append(times)

        self.hint = Gtk.Label(xalign=0)
        self.hint.set_wrap(True)
        root.append(self.hint)

        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        clear = Gtk.Button(label="Remove")
        clear.connect("clicked", lambda *_: self._clear())
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save_custom())
        self.save_btn = save
        buttons.append(clear)
        buttons.append(save)
        root.append(buttons)
        self.set_child(root)

    def popup_for(self, widget, current: str | None, on_save, on_clear) -> None:
        if self.get_parent() is not None:
            self.unparent()
        self.set_parent(widget)
        self._on_save = on_save
        self._on_clear = on_clear
        moment = None
        if current:
            try:
                moment = datetime.fromisoformat(current)
            except ValueError:
                moment = None
        if moment is None:
            moment = datetime.now() + timedelta(hours=1)
        self.calendar.set_year(moment.year)
        self.calendar.set_month(moment.month - 1)
        self.calendar.set_day(moment.day)
        self.hour.set_value(moment.hour)
        self.minute.set_value(moment.minute)
        self._refresh_hint()
        self.popup()

    def _chosen(self) -> datetime:
        return datetime(
            self.calendar.get_year(),
            self.calendar.get_month() + 1,
            self.calendar.get_day(),
            int(self.hour.get_value()),
            int(self.minute.get_value()),
        )

    def _refresh_hint(self) -> None:
        chosen = self._chosen()
        past = chosen <= datetime.now()
        self.hint.set_text("That time has already passed." if past else chosen.strftime("%a %d %b %H:%M"))
        self.save_btn.set_sensitive(not past)

    def _emit(self, moment: datetime) -> None:
        if moment <= datetime.now():
            self.hint.set_text("That time has already passed.")
            return
        if self._on_save:
            self._on_save(stamp(moment))
        self.popdown()

    def _save_custom(self, *_args) -> None:
        self._emit(self._chosen())

    def _in_one_hour(self, *_args) -> None:
        self._emit(datetime.now() + timedelta(hours=1))

    def _tomorrow(self, *_args) -> None:
        moment = datetime.now() + timedelta(days=1)
        self._emit(moment.replace(hour=9, minute=0, second=0, microsecond=0))

    def _tonight(self, *_args) -> None:
        moment = datetime.now().replace(hour=20, minute=0, second=0, microsecond=0)
        if moment <= datetime.now():
            moment += timedelta(days=1)
        self._emit(moment)

    def _clear(self) -> None:
        if self._on_clear:
            self._on_clear()
        self.popdown()


class TodoRow(Gtk.ListBoxRow):
    def __init__(self, window: NoteWindow, item: TodoItem):
        super().__init__()
        self.window = window
        self.item = item
        box = Gtk.Box(spacing=2)
        self.check = Gtk.CheckButton(active=item.done)
        self.check.connect("toggled", self._on_toggle)
        self.entry = Gtk.Entry(text=item.text, hexpand=True, placeholder_text="Task")
        self.entry.set_has_frame(False)
        self.entry.connect("changed", self._on_changed)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.entry.add_controller(keys)
        self.bell = Gtk.Button.new_from_icon_name("alarm-symbolic")
        self.bell.add_css_class("flat")
        self.bell.add_css_class("row-tool")
        self.bell.connect("clicked", self._on_bell)
        self.delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.delete.add_css_class("flat")
        self.delete.add_css_class("row-delete")
        self.delete.add_css_class("row-tool")
        self.delete.set_tooltip_text("Remove task")
        self.delete.connect("clicked", lambda *_: window.remove_item(item.id, focus=True))
        box.append(self.check)
        box.append(self.entry)
        box.append(self.bell)
        box.append(self.delete)
        self.set_child(box)
        self.sync_look()

    def sync_look(self) -> None:
        if self.item.done:
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_strikethrough_new(True))
            self.entry.set_attributes(attrs)
            self.entry.add_css_class("done")
        else:
            self.entry.set_attributes(Pango.AttrList())
            self.entry.remove_css_class("done")
        if self.item.reminder:
            self.bell.set_tooltip_text(format_when(self.item.reminder, fired=self.item.reminder_fired))
            self.bell.add_css_class("pin-on")
        else:
            self.bell.set_tooltip_text("Remind me about this task")
            self.bell.remove_css_class("pin-on")

    def _on_toggle(self, check) -> None:
        self.item.done = check.get_active()
        self.sync_look()
        self.window.mark_edited()

    def _on_changed(self, entry) -> None:
        self.item.text = entry.get_text()
        self.window.mark_edited()

    def _on_bell(self, _button) -> None:
        self.window.popup_reminder(
            self.bell,
            self.item.reminder,
            lambda when: self.window.set_item_reminder(self.item, when),
            lambda: self.window.set_item_reminder(self.item, None),
        )

    def _on_key(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.window.focus_after(self.item.id)
            return True
        if keyval == Gdk.KEY_BackSpace and self.entry.get_text() == "":
            self.window.remove_item(self.item.id, focus=True)
            return True
        return False


class NoteWindow(Gtk.ApplicationWindow):
    def __init__(self, app, note):
        super().__init__(application=app, title=window_title(note, app.store.notes))
        self.app = app
        self.note = note
        self.allow_close = False
        self._loading = False
        self._pin_block = False
        self._placed = False
        self.typing = {name: False for name in _TYPING}
        self.rows: dict[str, TodoRow] = {}

        self.add_css_class("sticky-note")
        self.add_css_class(f"note-{note.color}")
        self.set_scheme_dark(app.effective_dark())
        self.set_default_size(note.width, note.height)
        self.set_size_request(240, 220)
        self.connect("close-request", self._on_close)
        self.connect("map", self._on_map)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        header.set_title_widget(Gtk.Box())
        self.color_btn = Gtk.Button(tooltip_text="Note color")
        self.color_btn.add_css_class("color-dot")
        self.color_popover = self._build_color_popover()
        self.color_popover.set_parent(self.color_btn)
        self.color_btn.connect("clicked", lambda *_: self.color_popover.popup())
        self.pin_btn = Gtk.ToggleButton(icon_name="view-pin-symbolic", tooltip_text="Pin above other windows")
        self.pin_btn.connect("toggled", self._on_pin_button)
        header.pack_start(self.color_btn)
        header.pack_start(self.pin_btn)

        self._install_actions()
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Note menu")
        menu_btn.set_menu_model(self._menu_model)
        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text("New note")
        add_btn.connect("clicked", lambda *_: app.create_note(self.note.kind))
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Hide note")
        close_btn.connect("clicked", lambda *_: self.close())
        header.pack_end(close_btn)
        header.pack_end(add_btn)
        header.pack_end(menu_btn)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pin_hint = Gtk.Label(
            label="This window could not stay above others. Sticky Notes uses the X11 backend for that.",
            wrap=True,
            xalign=0,
        )
        self.pin_hint.add_css_class("pin-hint")
        self.pin_hint.set_visible(False)
        root.append(self.pin_hint)

        self.text_view = Gtk.TextView(
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            accepts_tab=False,
            left_margin=12,
            right_margin=12,
            top_margin=6,
            bottom_margin=8,
            vexpand=True,
        )
        self.buffer = self.text_view.get_buffer()
        self.tags = {
            "bold": self.buffer.create_tag("bold", weight=Pango.Weight.BOLD),
            "italic": self.buffer.create_tag("italic", style=Pango.Style.ITALIC),
            "underline": self.buffer.create_tag("underline", underline=Pango.Underline.SINGLE),
            "strike": self.buffer.create_tag("strike", strikethrough=True),
            "title": self.buffer.create_tag("title", weight=Pango.Weight.BOLD, scale=1.25),
        }
        self.buffer.connect("changed", self._on_buffer_changed)
        self.buffer.connect_after("insert-text", self._after_insert)
        self.buffer.connect("mark-set", self._on_mark)
        self.placeholder = Gtk.Label(label="Write a note…", xalign=0, yalign=0)
        self.placeholder.add_css_class("placeholder")
        self.placeholder.set_can_target(False)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.text_view)
        self.text_overlay = Gtk.Overlay()
        self.text_overlay.set_child(scroller)
        self.text_overlay.add_overlay(self.placeholder)

        self.title_entry = Gtk.Entry(placeholder_text="Title")
        self.title_entry.add_css_class("todo-title")
        self.title_entry.set_has_frame(False)
        self.title_entry.connect("changed", self._on_title_changed)
        self.item_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.add_entry = Gtk.Entry(placeholder_text="Add a task")
        self.add_entry.add_css_class("todo-add")
        self.add_entry.set_has_frame(False)
        self.add_entry.set_margin_start(34)
        self.add_entry.set_margin_end(8)
        self.add_entry.set_margin_bottom(4)
        self.add_entry.connect("activate", self._on_add_task)
        tasks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tasks.append(self.item_list)
        tasks.append(self.add_entry)
        item_scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        item_scroll.set_child(tasks)
        todo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        todo.append(self.title_entry)
        todo.append(item_scroll)

        self.body = Gtk.Stack(vexpand=True)
        self.body.add_named(self.text_overlay, "text")
        self.body.add_named(todo, "todo")
        root.append(self.body)

        footer = Gtk.Box(spacing=4)
        footer.add_css_class("note-footer")
        self.reminder_btn = Gtk.Button(icon_name="alarm-symbolic", label="Remind")
        self.reminder_btn.connect("clicked", self._on_note_reminder)
        footer.append(self.reminder_btn)
        spacer = Gtk.Box(hexpand=True)
        footer.append(spacer)
        self.format_box = Gtk.Box(spacing=0)
        self.format_buttons = {}
        for name, icon, tip in (
            ("bold", "format-text-bold-symbolic", "Bold"),
            ("italic", "format-text-italic-symbolic", "Italic"),
            ("underline", "format-text-underline-symbolic", "Underline"),
            ("strike", "format-text-strikethrough-symbolic", "Strikethrough"),
        ):
            button = Gtk.ToggleButton(icon_name=icon, tooltip_text=tip)
            button.connect("toggled", self._on_format_toggled, name)
            self.format_buttons[name] = button
            self.format_box.append(button)
        bullets = Gtk.Button(icon_name="view-list-bullet-symbolic", tooltip_text="Bullet list")
        bullets.connect("clicked", self._toggle_bullets)
        self.format_box.append(bullets)
        footer.append(self.format_box)
        root.append(footer)
        self.set_child(root)

        self.reminder_popover = ReminderPopover()
        self._load_content()
        self._apply_color()
        self.sync_pin()
        self._bind_shortcuts()
        self.connect("destroy", self._on_destroy)

    def _build_color_popover(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        for index, name in enumerate(COLORS):
            button = Gtk.Button(tooltip_text=name.capitalize())
            button.add_css_class("color-choice")
            button.add_css_class(f"dot-{name}")
            button.connect("clicked", self._choose_color, name)
            grid.attach(button, index % 4, index // 4, 1, 1)
        popover.set_child(grid)
        return popover

    def _install_actions(self) -> None:
        kind = Gio.SimpleAction.new_stateful(
            "kind",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(self.note.kind),
        )
        kind.connect("change-state", self._on_kind_action)
        self.kind_action = kind
        self.add_action(kind)

        pin = Gio.SimpleAction.new_stateful("pin", None, GLib.Variant.new_boolean(self.note.pinned))
        pin.connect("change-state", self._on_pin_action)
        self.pin_action = pin
        self.add_action(pin)

        for name, handler in (
            ("duplicate", self._action_duplicate),
            ("delete", self._action_delete),
            ("clear-done", self._action_clear_done),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            if name == "clear-done":
                self.clear_action = action

        menu = Gio.Menu()
        section = Gio.Menu()
        text_item = Gio.MenuItem.new("Text", None)
        text_item.set_action_and_target_value("win.kind", GLib.Variant.new_string("text"))
        todo_item = Gio.MenuItem.new("Checklist", None)
        todo_item.set_action_and_target_value("win.kind", GLib.Variant.new_string("todo"))
        section.append_item(text_item)
        section.append_item(todo_item)
        menu.append_section(None, section)
        menu.append("Pin to top", "win.pin")
        menu.append_section("Appearance", _appearance_menu())
        menu.append("All notes", "app.show-board")
        menu.append("Duplicate", "win.duplicate")
        menu.append("New from clipboard", "app.from-clipboard")
        menu.append("Clear completed tasks", "win.clear-done")
        menu.append("Delete", "win.delete")
        self._menu_model = menu

    def _bind_shortcuts(self) -> None:
        shortcuts = Gtk.ShortcutController()
        shortcuts.set_scope(Gtk.ShortcutScope.GLOBAL)
        for accel, name in (
            ("<primary>b", "bold"),
            ("<primary>i", "italic"),
            ("<primary>u", "underline"),
            ("<primary><shift>x", "strike"),
        ):
            shortcuts.add_shortcut(
                Gtk.Shortcut.new(
                    Gtk.ShortcutTrigger.parse_string(accel),
                    Gtk.CallbackAction.new(self._style_shortcut, name),
                )
            )
        self.add_controller(shortcuts)

    def _style_shortcut(self, _widget, _args, name: str) -> bool:
        button = self.format_buttons[name]
        button.set_active(not button.get_active())
        return True

    def _load_content(self) -> None:
        self._loading = True
        self.title_entry.set_text(self.note.title)
        self.buffer.set_text("")
        cursor = self.buffer.get_start_iter()
        for span in self.note.body:
            start = cursor.get_offset()
            self.buffer.insert(cursor, span.text)
            begin = self.buffer.get_iter_at_offset(start)
            end = self.buffer.get_iter_at_offset(start + len(span.text))
            for flag, tag_name in (
                (span.bold, "bold"),
                (span.italic, "italic"),
                (span.underline, "underline"),
                (span.strike, "strike"),
            ):
                if flag:
                    self.buffer.apply_tag(self.tags[tag_name], begin, end)
            cursor = self.buffer.get_end_iter()
        self._loading = False
        self._rebuild_items()
        self._show_kind()
        self._refresh_title_style()
        self._update_placeholder()
        self.refresh_reminder_labels()

    def _show_kind(self) -> None:
        todo = self.note.kind == "todo"
        self.body.set_visible_child_name("todo" if todo else "text")
        self.format_box.set_visible(not todo)
        if hasattr(self, "clear_action"):
            self.clear_action.set_enabled(todo)

    def _rebuild_items(self) -> None:
        child = self.item_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.item_list.remove(child)
            child = nxt
        self.rows.clear()
        for item in self.note.items:
            self._append_row(item)

    def _append_row(self, item: TodoItem) -> TodoRow:
        row = TodoRow(self, item)
        self.item_list.append(row)
        self.rows[item.id] = row
        return row

    def focus_editor(self) -> None:
        if self.note.kind == "todo":
            if not self.note.title.strip():
                self.title_entry.grab_focus()
            else:
                self.add_entry.grab_focus()
        else:
            self.text_view.grab_focus()

    def focus_after(self, item_id: str) -> None:
        ids = [item.id for item in self.note.items]
        if item_id not in ids:
            self.add_entry.grab_focus()
            return
        index = ids.index(item_id)
        if index + 1 < len(ids):
            self.rows[ids[index + 1]].entry.grab_focus()
        else:
            self.add_entry.grab_focus()

    def mark_edited(self) -> None:
        if self._loading:
            return
        self.note.touch()
        self.set_title(window_title(self.note, self.app.store.notes))
        self.app.note_edited(self.note)

    def _on_title_changed(self, entry) -> None:
        if self._loading:
            return
        self.note.title = entry.get_text()
        self.mark_edited()

    def _on_add_task(self, entry) -> None:
        text = entry.get_text().strip()
        if not text:
            return
        item = TodoItem.new(text=text)
        self.note.items.append(item)
        entry.set_text("")
        row = self._append_row(item)
        self.mark_edited()
        row.entry.grab_focus()
        row.entry.set_position(-1)

    def remove_item(self, item_id: str, focus: bool = False) -> None:
        ids = [item.id for item in self.note.items]
        if item_id not in ids:
            return
        index = ids.index(item_id)
        self.note.items = [item for item in self.note.items if item.id != item_id]
        row = self.rows.pop(item_id, None)
        if row is not None:
            self.item_list.remove(row)
        self.mark_edited()
        if not focus:
            return
        if index > 0 and self.note.items:
            previous = self.note.items[min(index, len(self.note.items)) - 1]
            self.rows[previous.id].entry.grab_focus()
        else:
            self.add_entry.grab_focus()

    def _on_buffer_changed(self, buf) -> None:
        if self._loading:
            return
        self.note.body = buffer_to_spans(buf, self.tags)
        self._refresh_title_style()
        self._update_placeholder()
        self.mark_edited()

    def _after_insert(self, buf, location, text, _length) -> None:
        if self._loading or not text or not any(self.typing.values()):
            return
        end = location.copy()
        start = end.copy()
        start.backward_chars(len(text))
        self._loading = True
        for name in _TYPING:
            if self.typing[name]:
                buf.apply_tag(self.tags[name], start, end)
        self._loading = False
        # `changed` runs before this handler, so write the tagged text again.
        self.note.body = buffer_to_spans(buf, self.tags)

    def _refresh_title_style(self) -> None:
        if self.note.kind != "text":
            return
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        self._loading = True
        self.buffer.remove_tag(self.tags["title"], start, end)
        line_end = start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        if start.compare(line_end) < 0:
            self.buffer.apply_tag(self.tags["title"], start, line_end)
        self._loading = False

    def _update_placeholder(self) -> None:
        empty = self.buffer.get_char_count() == 0
        self.placeholder.set_visible(empty and self.note.kind == "text")

    def _on_mark(self, _buf, _location, mark) -> None:
        if mark != self.buffer.get_insert():
            return
        self._sync_format_buttons()

    def _sync_format_buttons(self) -> None:
        if self.buffer.get_has_selection():
            start, _end = self.buffer.get_selection_bounds()
            tags = set(start.get_tags())
        else:
            tags = set(self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_tags())
        self._pin_block = True
        for name, button in self.format_buttons.items():
            active = self.tags[name] in tags
            button.set_active(active)
            self.typing[name] = active
        self._pin_block = False

    def _on_format_toggled(self, button, name: str) -> None:
        if self._pin_block:
            return
        active = button.get_active()
        self.typing[name] = active
        if self.buffer.get_has_selection():
            start, end = self.buffer.get_selection_bounds()
            if active:
                self.buffer.apply_tag(self.tags[name], start, end)
            else:
                self.buffer.remove_tag(self.tags[name], start, end)

    def _toggle_bullets(self, *_args) -> None:
        buf = self.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
        else:
            start = buf.get_iter_at_mark(buf.get_insert())
            start.set_line_offset(0)
            end = start.copy()
            if not end.ends_line():
                end.forward_to_line_end()
        start.set_line_offset(0)
        if not end.ends_line() and not end.is_end():
            end.forward_to_line_end()
        text = buf.get_text(start, end, False)
        lines = text.split("\n")
        if lines and all(not line.strip() or line.startswith("• ") for line in lines):
            lines = [line[2:] if line.startswith("• ") else line for line in lines]
        else:
            lines = [("• " + line) if line.strip() else line for line in lines]
        buf.delete(start, end)
        buf.insert(start, "\n".join(lines))

    def _choose_color(self, _button, name: str) -> None:
        self.color_popover.popdown()
        self.app.set_color(self.note, name)

    def set_scheme_dark(self, dark: bool) -> None:
        if dark:
            self.add_css_class("scheme-dark")
            self.remove_css_class("scheme-light")
        else:
            self.add_css_class("scheme-light")
            self.remove_css_class("scheme-dark")

    def apply_color(self) -> None:
        for name in COLORS:
            self.remove_css_class(f"note-{name}")
        self.add_css_class(f"note-{self.note.color}")
        self._apply_color()

    def _apply_color(self) -> None:
        for name in COLORS:
            self.color_btn.remove_css_class(f"dot-{name}")
        self.color_btn.add_css_class(f"dot-{self.note.color}")
        # Keep the readable foreground explicit for themes that ignore the window color.
        self.color_btn.set_tooltip_text(f"Color: {self.note.color}")

    def sync_pin(self) -> None:
        pinned = self.note.pinned
        self._pin_block = True
        self.pin_action.set_state(GLib.Variant.new_boolean(pinned))
        self.pin_btn.set_active(pinned)
        self._pin_block = False
        if pinned:
            self.pin_btn.add_css_class("pin-on")
            self.pin_btn.set_tooltip_text("Unpin")
        else:
            self.pin_btn.remove_css_class("pin-on")
            self.pin_btn.set_tooltip_text("Pin above other windows")
        self.apply_pin()
        GLib.timeout_add(700, self._refresh_pin_hint)

    def _on_pin_button(self, button) -> None:
        if self._pin_block:
            return
        self.app.set_pinned(self.note, button.get_active())

    def _on_pin_action(self, action, value) -> None:
        if self._pin_block:
            action.set_state(value)
            return
        self.app.set_pinned(self.note, value.get_boolean())

    def apply_pin(self) -> None:
        if self.get_surface() is not None:
            pinning.set_kept_above(self, self.note.pinned)

    def _refresh_pin_hint(self) -> bool:
        show = bool(self.note.pinned and self.get_mapped() and not pinning.is_kept_above(self))
        self.pin_hint.set_visible(show)
        return False

    def _on_map(self, *_args) -> None:
        self.apply_pin()
        self._place_attempts = 0
        self._place()
        GLib.timeout_add(250, self._place_later)
        GLib.timeout_add(600, self._reapply_pin)

    def _place(self) -> None:
        if self.note.x is None or self.note.y is None or self._placed:
            return
        self._place_attempts += 1
        x, y = pinning.position_on_screen(self.note.x, self.note.y, self.note.width, self.note.height)
        if not pinning.move_window(self, x, y):
            return
        pos = pinning.get_position(self)
        close = pos is not None and abs(pos[0] - x) <= 20 and abs(pos[1] - y) <= 20
        if close or self._place_attempts >= 2:
            self._placed = True

    def _place_later(self) -> bool:
        if not self._placed:
            self._place()
        return False

    def _reapply_pin(self) -> bool:
        self.apply_pin()
        self._refresh_pin_hint()
        return False

    def capture_geometry(self) -> None:
        width, height = self.get_width(), self.get_height()
        if width > 1 and height > 1:
            self.note.width = max(240, width)
            self.note.height = max(200, height)
        if self.get_mapped():
            pos = pinning.get_position(self)
            if pos:
                self.note.x, self.note.y = pos

    def popup_reminder(self, widget, current, on_save, on_clear) -> None:
        self.reminder_popover.popup_for(widget, current, on_save, on_clear)

    def _on_note_reminder(self, _button) -> None:
        self.popup_reminder(
            self.reminder_btn,
            self.note.reminder,
            self.set_note_reminder,
            lambda: self.set_note_reminder(None),
        )

    def set_note_reminder(self, when: str | None) -> None:
        self.note.reminder = when
        self.note.reminder_fired = False
        self.refresh_reminder_labels()
        self.mark_edited()

    def set_item_reminder(self, item: TodoItem, when: str | None) -> None:
        item.reminder = when
        item.reminder_fired = False
        row = self.rows.get(item.id)
        if row:
            row.sync_look()
        self.mark_edited()

    def refresh_reminder_labels(self) -> None:
        label = format_when(self.note.reminder, fired=self.note.reminder_fired)
        self.reminder_btn.set_label(label if self.note.reminder else "Remind")
        overdue = bool(self.note.reminder and is_past(self.note.reminder) and not self.note.reminder_fired)
        if overdue:
            self.reminder_btn.add_css_class("reminder-overdue")
        else:
            self.reminder_btn.remove_css_class("reminder-overdue")
        for row in self.rows.values():
            row.sync_look()

    def set_kind(self, kind: str) -> None:
        if kind not in ("text", "todo") or kind == self.note.kind:
            self._pin_block = True
            self.kind_action.set_state(GLib.Variant.new_string(self.note.kind))
            self._pin_block = False
            return
        if kind == "todo":
            source = self.note.plain()
            parsed = parse_checklist(source)
            if parsed is None:
                lines = [line.strip() for line in spans_plain(self.note.body).splitlines() if line.strip()]
                self.note.title = lines[0] if lines else ""
                self.note.items = [TodoItem.new(text=line) for line in lines[1:]]
            else:
                self.note.title = ""
                self.note.items = parsed
            self.note.body = []
        else:
            self.note.body = [Span(text=self.note.plain())] if self.note.plain() else []
            self.note.items = []
            self.note.title = ""
        self.note.kind = kind
        self._pin_block = True
        self.kind_action.set_state(GLib.Variant.new_string(kind))
        self._pin_block = False
        self._load_content()
        self.mark_edited()
        GLib.idle_add(self.focus_editor)

    def _on_kind_action(self, action, value) -> None:
        if self._pin_block:
            action.set_state(value)
            return
        self.set_kind(value.get_string())

    def _action_duplicate(self, *_args) -> None:
        self.app.duplicate_note(self.note)

    def _action_delete(self, *_args) -> None:
        dialog = Adw.AlertDialog(
            heading="Delete this note?",
            body="The note and its reminders will be removed.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._confirm_delete)
        dialog.present(self)

    def _confirm_delete(self, _dialog, response) -> None:
        if response == "delete":
            self.app.delete_note(self.note)

    def _action_clear_done(self, *_args) -> None:
        if self.note.kind != "todo":
            return
        self.note.items = [item for item in self.note.items if not item.done]
        self._rebuild_items()
        self.mark_edited()

    def _on_close(self, *_args) -> bool:
        if self.allow_close or self.app.quitting:
            return False
        self.app.hide_note(self.note)
        return True

    def _on_destroy(self, *_args) -> None:
        if self.color_popover.get_parent() is not None:
            self.color_popover.unparent()
        if self.reminder_popover.get_parent() is not None:
            self.reminder_popover.unparent()


