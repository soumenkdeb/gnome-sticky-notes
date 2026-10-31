"""Selection bounds stay safe while GTK is moving the cursor marks."""

import unittest

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from gnome_sticky_notes.note_window import selection_bounds


class SelectionBoundsTests(unittest.TestCase):
    def test_empty_without_a_selection(self):
        buf = Gtk.TextBuffer()
        buf.set_text("hello world")
        self.assertIsNone(selection_bounds(buf))

    def test_returns_the_range(self):
        buf = Gtk.TextBuffer()
        buf.set_text("hello world")
        start = buf.get_iter_at_offset(0)
        end = buf.get_iter_at_offset(5)
        buf.select_range(start, end)
        bounds = selection_bounds(buf)
        self.assertIsNotNone(bounds)
        got_start, got_end = bounds
        self.assertEqual(got_start.get_offset(), 0)
        self.assertEqual(got_end.get_offset(), 5)

    def test_place_cursor_does_not_unpack_an_empty_tuple(self):
        """The reported crash: has-selection is stale, bounds are empty."""
        buf = Gtk.TextBuffer()
        buf.set_text("hello world")
        start = buf.get_iter_at_offset(0)
        end = buf.get_iter_at_offset(5)
        buf.select_range(start, end)

        seen = []

        def on_mark(buf, _location, mark):
            if mark.get_name() not in ("insert", "selection_bound"):
                return
            # The old code unpacked get_selection_bounds() whenever
            # get_has_selection() was true. That raises here.
            if buf.get_has_selection() and len(buf.get_selection_bounds()) != 2:
                seen.append("mismatch")
            bounds = selection_bounds(buf)
            if bounds is None:
                seen.append("cursor")
            else:
                seen.append("range")

        buf.connect("mark-set", on_mark)
        buf.place_cursor(buf.get_iter_at_offset(3))

        self.assertIn("mismatch", seen)
        self.assertIn("cursor", seen)
        self.assertIsNone(selection_bounds(buf))
        self.assertFalse(buf.get_has_selection())
