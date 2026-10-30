"""Shared appearance menu for the board and each note."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib


def appearance_menu() -> Gio.Menu:
    menu = Gio.Menu()
    for label, value in (("System", "system"), ("Light", "light"), ("Dark", "dark")):
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value("app.appearance", GLib.Variant.new_string(value))
        menu.append_item(item)
    return menu
