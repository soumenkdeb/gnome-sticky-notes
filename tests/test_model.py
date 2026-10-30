"""Model, store, and reminder tests. These do not open a window."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from gnome_sticky_notes.model import (
    Note,
    Span,
    TodoItem,
    merge_spans,
    parse_checklist,
    plain_to_spans,
    window_title,
)
from gnome_sticky_notes.reminders import due_entries, format_when, has_pending_reminder, snooze_until
from gnome_sticky_notes.store import Store


class ModelTests(unittest.TestCase):
    def test_roundtrip(self):
        note = Note.new("todo", "pink")
        note.title = "Shop"
        note.items = [TodoItem.new("Milk", done=True), TodoItem.new("Eggs")]
        note.reminder = "2026-10-30T18:00:00"
        note.pinned = True
        copy = Note.from_dict(note.to_dict())
        self.assertEqual(copy.title, "Shop")
        self.assertEqual(copy.color, "pink")
        self.assertTrue(copy.items[0].done)
        self.assertEqual(copy.items[1].text, "Eggs")
        self.assertTrue(copy.pinned)
        self.assertEqual(copy.reminder, "2026-10-30T18:00:00")

    def test_merge_spans(self):
        spans = merge_spans([Span("Hello ", bold=True), Span("there", bold=True), Span("!", italic=True)])
        self.assertEqual([(span.text, span.bold, span.italic) for span in spans], [("Hello there", True, False), ("!", False, True)])

    def test_plain_spans(self):
        spans = plain_to_spans("Line\nTwo")
        self.assertEqual(spans[0].text, "Line\nTwo")

    def test_checklist_detection(self):
        self.assertIsNone(parse_checklist("Just a sentence"))
        items = parse_checklist("- [ ] Milk\n- [x] Eggs")
        self.assertEqual([item.text for item in items], ["Milk", "Eggs"])
        self.assertFalse(items[0].done)
        self.assertTrue(items[1].done)
        boxes = parse_checklist("☐ Call Sam")
        self.assertEqual(boxes[0].text, "Call Sam")
        self.assertIsNone(parse_checklist("one line\n- [ ] only sometimes"))

    def test_unique_titles(self):
        first = Note.new()
        second = Note.new()
        first.body = plain_to_spans("Same")
        second.body = plain_to_spans("Same")
        self.assertNotEqual(window_title(first, [first, second]), window_title(second, [first, second]))
        self.assertEqual(window_title(first, [first]), "Same")

    def test_duplicate_gets_new_ids(self):
        note = Note.new("todo")
        note.items = [TodoItem.new("A")]
        copy = note.duplicate()
        self.assertNotEqual(copy.id, note.id)
        self.assertNotEqual(copy.items[0].id, note.items[0].id)

    def test_corrupt_store_is_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            path.write_text("{", encoding="utf-8")
            store = Store(path)
            store.load()
            self.assertTrue(store.fresh)
            self.assertTrue(path.with_suffix(".json.bak").exists())

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            store = Store(path)
            store.load()
            store.notes.append(Note.new())
            store.notes[0].body = [Span("Saved", italic=True)]
            self.assertEqual(store.appearance, "system")
            store.autostart = True
            store.appearance = "dark"
            store.save()
            again = Store(path)
            again.load()
            self.assertTrue(again.autostart)
            self.assertEqual(again.appearance, "dark")
            path.write_text(path.read_text(encoding="utf-8").replace('"dark"', '"nope"'), encoding="utf-8")
            broken = Store(path)
            broken.load()
            self.assertEqual(broken.appearance, "system")
            self.assertEqual(again.notes[0].body[0].text, "Saved")
            self.assertTrue(again.notes[0].body[0].italic)


class ReminderTests(unittest.TestCase):
    def test_due_and_fired(self):
        note = Note.new()
        note.reminder = "2020-01-01T00:00:00"
        found = list(due_entries([note], datetime(2020, 1, 1, 0, 1)))
        self.assertEqual(len(found), 1)
        note.reminder_fired = True
        self.assertEqual(list(due_entries([note], datetime(2020, 1, 1, 0, 1))), [])

    def test_item_due(self):
        note = Note.new("todo")
        item = TodoItem.new("Pay rent")
        item.reminder = "2026-01-01T09:00:00"
        note.items = [item]
        found = list(due_entries([note], datetime(2026, 1, 1, 9, 0)))
        self.assertEqual(found[0][0], "item")
        self.assertEqual(found[0][2].text, "Pay rent")

    def test_format_and_snooze(self):
        now = datetime(2026, 10, 30, 12, 0)
        self.assertEqual(format_when("2026-10-30T15:30:00", now), "Today 15:30")
        self.assertEqual(format_when("2026-10-31T09:00:00", now), "Tomorrow 09:00")
        self.assertTrue(has_pending_reminder([Note.from_dict({"id": "a", "reminder": "2099-01-01T00:00:00"})], now))
        self.assertEqual(snooze_until(now, 10), "2026-10-30T12:10:00")


if __name__ == "__main__":
    unittest.main()
