"""Decide which reminders are due and how to say them."""

from __future__ import annotations

from datetime import datetime, timedelta

from .model import Note, TodoItem, preview_line


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def stamp(moment: datetime) -> str:
    return moment.replace(second=0, microsecond=0).isoformat(timespec="seconds")


def format_when(value: str | None, now: datetime | None = None, fired: bool = False) -> str:
    moment = parse_when(value)
    if moment is None:
        return "Remind"
    now = now or datetime.now()
    if fired and moment <= now:
        return f"Reminded · {moment:%H:%M}"
    if moment.date() == now.date():
        prefix = "Today"
    elif moment.date() == (now.date() + timedelta(days=1)):
        prefix = "Tomorrow"
    else:
        prefix = moment.strftime("%a %d %b")
    label = f"{prefix} {moment:%H:%M}"
    if moment < now and not fired:
        return f"Due · {label}"
    return label


def is_past(value: str | None, now: datetime | None = None) -> bool:
    moment = parse_when(value)
    if moment is None:
        return False
    return moment <= (now or datetime.now())


def due_entries(notes: list[Note], now: datetime | None = None):
    """Yield (kind, note, item) for reminders whose time has arrived."""
    now = now or datetime.now()
    for note in notes:
        moment = parse_when(note.reminder)
        if moment is not None and not note.reminder_fired and moment <= now:
            yield "note", note, None
        if note.kind != "todo":
            continue
        for item in note.items:
            item_moment = parse_when(item.reminder)
            if item_moment is not None and not item.reminder_fired and item_moment <= now:
                yield "item", note, item


def snooze_until(now: datetime, minutes: int) -> str:
    return stamp(now + timedelta(minutes=minutes))


def reminder_copy(kind: str, note: Note, item: TodoItem | None) -> tuple[str, str]:
    if kind == "item" and item is not None:
        title = "Task reminder"
        body = item.text.strip() or "Checklist item"
        heading = note.title.strip()
        if heading:
            body = f"{body}\n{heading}"
        return title, body
    title = "Sticky note reminder"
    body = preview_line(note)
    if body in ("Sticky Note", "Checklist"):
        body = note.plain().strip() or "A note is due"
    return title, body


def has_pending_reminder(notes: list[Note], now: datetime | None = None) -> bool:
    now = now or datetime.now()
    for note in notes:
        moment = parse_when(note.reminder)
        if moment is not None and (not note.reminder_fired or moment > now):
            if not note.reminder_fired:
                return True
        for item in note.items:
            item_moment = parse_when(item.reminder)
            if item_moment is not None and not item.reminder_fired:
                return True
    return False
