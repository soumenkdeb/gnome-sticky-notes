"""Palette chips stay painted inside a transparent header-bar button."""

import unittest
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gsk, Gtk

from gnome_sticky_notes.model import COLORS
from gnome_sticky_notes.note_window import color_chip, color_choice

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "gnome_sticky_notes" / "style.css"

# The center of a chip should land on the fill, not a transparent button.
LIGHT = {
    "yellow": (255, 243, 163),
    "green": (212, 245, 196),
    "pink": (255, 211, 228),
    "purple": (227, 212, 255),
    "blue": (210, 234, 255),
    "gray": (236, 239, 241),
    "charcoal": (58, 58, 58),
}
DARK = {
    "yellow": (74, 63, 22),
    "green": (30, 61, 36),
    "pink": (76, 36, 54),
    "purple": (52, 38, 76),
    "blue": (23, 52, 72),
    "gray": (44, 49, 52),
    "charcoal": (22, 22, 22),
}


def _pump(seconds: float) -> None:
    end = GLib.get_monotonic_time() + int(seconds * 1_000_000)
    context = GLib.MainContext.default()
    while GLib.get_monotonic_time() < end:
        context.iteration(False)


def _center(widget) -> tuple:
    width, height = widget.get_width(), widget.get_height()
    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None or width < 1 or height < 1:
        return (0, 0, 0, 0)
    renderer = Gsk.CairoRenderer.new()
    renderer.realize(None)
    texture = renderer.render_texture(node, None)
    renderer.unrealize()
    path = "/tmp/gnome-sticky-notes-chip.png"
    texture.save_to_png(path)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    row_stride = pixbuf.get_rowstride()
    channels = pixbuf.get_n_channels()
    pixels = pixbuf.get_pixels()
    x, y = pixbuf.get_width() // 2, pixbuf.get_height() // 2
    index = y * row_stride + x * channels
    return tuple(pixels[index:index + 4])


class ColorPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS))
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def _assert_palette(self, scheme: str, expected: dict) -> None:
        window = Gtk.Window()
        window.add_css_class("sticky-note")
        window.add_css_class(scheme)
        window.add_css_class("note-yellow")
        window.set_default_size(420, 280)
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        trigger = Gtk.Button(tooltip_text="Note color")
        trigger.add_css_class("color-dot")
        trigger.set_child(color_chip("yellow", 16))
        popover = Gtk.Popover()
        popover.add_css_class("color-palette")
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        chips = {}
        for index, name in enumerate(COLORS):
            button = Gtk.Button(tooltip_text=name)
            button.add_css_class("color-choice")
            chip = color_chip(name, 22)
            button.set_child(chip)
            chips[name] = chip
            grid.attach(button, index % 4, index // 4, 1, 1)
        popover.set_child(grid)
        popover.set_parent(trigger)
        header.pack_start(trigger)
        window.set_titlebar(header)
        window.set_child(Gtk.Box())
        window.present()
        _pump(0.4)
        popover.popup()
        _pump(0.4)
        try:
            self.assertGreater(popover.get_width(), 80, scheme)
            for name, want in expected.items():
                red, green, blue, alpha = _center(chips[name])
                self.assertGreater(alpha, 200, f"{scheme} {name}")
                for got, channel in zip((red, green, blue), want):
                    self.assertLess(abs(got - channel), 24, f"{scheme} {name} {(red, green, blue)} != {want}")
        finally:
            popover.unparent()
            window.close()
            _pump(0.1)

    def test_light_palette_chips_keep_their_color(self):
        self._assert_palette("scheme-light", LIGHT)

    def test_dark_palette_chips_keep_their_color(self):
        self._assert_palette("scheme-dark", DARK)

    def test_current_swatch_draws_a_check(self):
        window = Gtk.Window()
        window.add_css_class("sticky-note")
        window.add_css_class("scheme-light")
        window.set_default_size(160, 80)
        box = Gtk.Box(spacing=8)
        box.set_margin_top(8)
        box.set_margin_start(8)
        box.set_halign(Gtk.Align.START)
        box.set_valign(Gtk.Align.START)
        current = color_choice("pink")
        current.add_css_class("palette-current")
        other = color_choice("green")
        box.append(current)
        box.append(other)
        window.set_child(box)
        window.present()
        _pump(0.4)
        try:
            self.assertGreater(self._ink(current, LIGHT["pink"]), 8)
            self.assertEqual(self._ink(other, LIGHT["green"]), 0)
        finally:
            window.close()
            _pump(0.1)

    def _ink(self, widget, fill: tuple) -> int:
        width, height = widget.get_width(), widget.get_height()
        paintable = Gtk.WidgetPaintable.new(widget)
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        renderer = Gsk.CairoRenderer.new()
        renderer.realize(None)
        texture = renderer.render_texture(node, None)
        renderer.unrealize()
        path = "/tmp/gnome-sticky-notes-check.png"
        texture.save_to_png(path)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        row_stride = pixbuf.get_rowstride()
        channels = pixbuf.get_n_channels()
        pixels = pixbuf.get_pixels()
        # The check crosses the middle. The ring stays outside this box.
        width, height = pixbuf.get_width(), pixbuf.get_height()
        count = 0
        for y in range(int(height * 0.40), int(height * 0.72)):
            for x in range(int(width * 0.32), int(width * 0.70)):
                index = y * row_stride + x * channels
                red, green, blue = pixels[index], pixels[index + 1], pixels[index + 2]
                if any(abs(channel - want) > 50 for channel, want in zip((red, green, blue), fill)):
                    count += 1
        return count
