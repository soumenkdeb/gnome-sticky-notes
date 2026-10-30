"""Reminder shortcut file: parsing and the times it produces."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from gnome_sticky_notes.reminder_shortcuts import (
    FALLBACK,
    bundled_shortcuts_path,
    ensure_user_shortcuts,
    load_reminder_shortcuts,
    parse_shortcuts,
    resolve_shortcut,
    shortcut_stamp,
)

NOW = datetime(2026, 10, 30, 15, 30, 45)  # Friday


class ShortcutTests(unittest.TestCase):
    def test_parse_keeps_valid_lines(self):
        text = """
        # comment
        In 15 minutes = 15m

        Not a shortcut
        Bad clock = today 25:00
        Zero = 0m
        Tonight at 20:00 = today 20:00
        """
        parsed = parse_shortcuts(text)
        self.assertEqual(
            [(item.label, item.spec) for item in parsed],
            [("In 15 minutes", "15m"), ("Tonight at 20:00", "today 20:00")],
        )

    def test_builtin_list_matches_the_file(self):
        parsed = parse_shortcuts(bundled_shortcuts_path().read_text(encoding="utf-8"))
        self.assertEqual([(item.label, item.spec) for item in parsed], list(FALLBACK))

    def test_relative_and_clock_times(self):
        self.assertEqual(resolve_shortcut("15m", NOW), datetime(2026, 10, 30, 15, 45, 45))
        self.assertEqual(resolve_shortcut("1h", NOW), datetime(2026, 10, 30, 16, 30, 45))
        self.assertEqual(resolve_shortcut("2d", NOW), datetime(2026, 11, 1, 15, 30, 45))
        self.assertEqual(resolve_shortcut("today 20:00", NOW), datetime(2026, 10, 30, 20, 0))
        self.assertEqual(resolve_shortcut("today 09:00", NOW), datetime(2026, 10, 31, 9, 0))
        self.assertEqual(resolve_shortcut("tomorrow 09:00", NOW), datetime(2026, 10, 31, 9, 0))
        self.assertEqual(shortcut_stamp("15m", NOW), "2026-10-30T15:45:00")

    def test_weekday_rolls_forward_after_the_time_has_passed(self):
        self.assertEqual(NOW.weekday(), 4)
        self.assertEqual(resolve_shortcut("Friday 18:00", NOW), datetime(2026, 10, 30, 18, 0))
        self.assertEqual(resolve_shortcut("monday 09:00", NOW), datetime(2026, 11, 2, 9, 0))
        monday_morning = datetime(2026, 11, 2, 8, 0)
        self.assertEqual(monday_morning.weekday(), 0)
        self.assertEqual(resolve_shortcut("monday 09:00", monday_morning), datetime(2026, 11, 2, 9, 0))
        monday_afternoon = datetime(2026, 11, 2, 10, 0)
        self.assertEqual(resolve_shortcut("monday 09:00", monday_afternoon), datetime(2026, 11, 9, 9, 0))

    def test_unknown_spec_is_rejected(self):
        self.assertIsNone(resolve_shortcut("next week", NOW))
        self.assertIsNone(resolve_shortcut("soon", NOW))
        self.assertIsNone(shortcut_stamp("0h", NOW))

    def test_user_file_is_created_once_and_then_used(self):
        previous = os.environ.get("STICKY_NOTES_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STICKY_NOTES_DIR"] = tmp
            try:
                path = ensure_user_shortcuts()
                self.assertEqual(path, Path(tmp) / "reminder-shortcuts.conf")
                self.assertIn("In 1 hour = 1h", path.read_text(encoding="utf-8"))
                path.write_text("Later today = 3h\n# note\n", encoding="utf-8")
                self.assertEqual(ensure_user_shortcuts(), path)
                self.assertEqual(path.read_text(encoding="utf-8"), "Later today = 3h\n# note\n")
                loaded = load_reminder_shortcuts()
                self.assertEqual([(item.label, item.spec) for item in loaded], [("Later today", "3h")])
            finally:
                if previous is None:
                    os.environ.pop("STICKY_NOTES_DIR", None)
                else:
                    os.environ["STICKY_NOTES_DIR"] = previous

    def test_empty_user_file_falls_back_to_the_builtin_list(self):
        previous = os.environ.get("STICKY_NOTES_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STICKY_NOTES_DIR"] = tmp
            try:
                (Path(tmp) / "reminder-shortcuts.conf").write_text("# nothing usable\n", encoding="utf-8")
                loaded = load_reminder_shortcuts()
                self.assertEqual([(item.label, item.spec) for item in loaded], list(FALLBACK))
            finally:
                if previous is None:
                    os.environ.pop("STICKY_NOTES_DIR", None)
                else:
                    os.environ["STICKY_NOTES_DIR"] = previous
