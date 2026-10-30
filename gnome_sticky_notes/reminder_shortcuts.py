"""Reminder menu entries loaded from a text file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .reminders import stamp
from .store import data_dir

FILENAME = "reminder-shortcuts.conf"

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

FALLBACK: tuple[tuple[str, str], ...] = (
    ("In 15 minutes", "15m"),
    ("In 1 hour", "1h"),
    ("In 3 hours", "3h"),
    ("Tonight at 20:00", "today 20:00"),
    ("Tomorrow at 9:00", "tomorrow 09:00"),
    ("Tomorrow evening", "tomorrow 18:00"),
    ("Next Monday", "monday 09:00"),
)


@dataclass(frozen=True)
class ReminderShortcut:
    label: str
    spec: str


def bundled_shortcuts_path() -> Path:
    return Path(__file__).with_name(FILENAME)


def user_shortcuts_path() -> Path:
    return data_dir() / FILENAME


def ensure_user_shortcuts() -> Path:
    """Copy the built-in list beside the notes, once, so it can be edited."""
    path = user_shortcuts_path()
    if path.exists():
        return path
    try:
        text = bundled_shortcuts_path().read_text(encoding="utf-8")
    except OSError:
        text = "".join(f"{label} = {spec}\n" for label, spec in FALLBACK)
    path.write_text(text, encoding="utf-8")
    return path


def load_reminder_shortcuts(path: Path | None = None) -> list[ReminderShortcut]:
    """Read one file, or the user file when it has entries, or the built-in list."""
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    else:
        override = os.environ.get("STICKY_NOTES_DIR")
        user = Path(override) / FILENAME if override else user_shortcuts_path()
        if user.is_file():
            candidates.append(user)
        candidates.append(bundled_shortcuts_path())
    for candidate in candidates:
        parsed = _read(candidate)
        if parsed:
            return parsed
    return [ReminderShortcut(label, spec) for label, spec in FALLBACK]


def parse_shortcuts(text: str) -> list[ReminderShortcut]:
    found: list[ReminderShortcut] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        label, spec = line.split("=", 1)
        label = label.strip()
        spec = spec.strip()
        if not label or resolve_shortcut(spec, datetime(2026, 1, 5, 12, 0)) is None:
            continue
        found.append(ReminderShortcut(label, spec))
    return found


def resolve_shortcut(spec: str, now: datetime) -> datetime | None:
    """Turn a shortcut spec into a local time. None means the spec is not valid."""
    text = " ".join(spec.strip().lower().split())
    if not text:
        return None
    parts = text.split(" ")
    if len(parts) == 1:
        return _duration(parts[0], now)
    if len(parts) != 2:
        return None
    clock = _clock(parts[1])
    if clock is None:
        return None
    hour, minute = clock
    kind = parts[0]
    if kind == "today":
        moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= now:
            moment += timedelta(days=1)
        return moment
    if kind == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    weekday = _WEEKDAYS.get(kind)
    if weekday is None:
        return None
    days = (weekday - now.weekday()) % 7
    moment = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment <= now:
        moment += timedelta(days=7)
    return moment


def shortcut_stamp(spec: str, now: datetime | None = None) -> str | None:
    moment_now = now or datetime.now()
    moment = resolve_shortcut(spec, moment_now)
    if moment is None or moment <= moment_now:
        return None
    return stamp(moment)


def _read(path: Path) -> list[ReminderShortcut]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_shortcuts(text)


def _duration(text: str, now: datetime) -> datetime | None:
    if len(text) < 2 or not text[:-1].isdigit():
        return None
    amount = int(text[:-1])
    if amount <= 0:
        return None
    unit = text[-1]
    if unit == "m":
        return now + timedelta(minutes=amount)
    if unit == "h":
        return now + timedelta(hours=amount)
    if unit == "d":
        return now + timedelta(days=amount)
    return None


def _clock(text: str) -> tuple[int, int] | None:
    hour_text, sep, minute_text = text.partition(":")
    if sep != ":" or not hour_text.isdigit() or not minute_text.isdigit():
        return None
    if len(minute_text) != 2:
        return None
    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        return None
    return hour, minute
