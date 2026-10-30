"""Notes, checklists, and the small bits of text parsing around them."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

COLORS = ("yellow", "green", "pink", "purple", "blue", "gray", "charcoal")
APPEARANCES = ("system", "light", "dark")
COLOR_VALUES = {
    "yellow": {"bg": "#fff3a3", "fg": "#3a3010", "muted": "#6d5b22", "line": "#e6d36a"},
    "green": {"bg": "#d4f5c4", "fg": "#163016", "muted": "#3c6840", "line": "#b0e09a"},
    "pink": {"bg": "#ffd3e4", "fg": "#3d1828", "muted": "#8a4564", "line": "#f3b3cc"},
    "purple": {"bg": "#e3d4ff", "fg": "#281544", "muted": "#64508a", "line": "#cdb6f5"},
    "blue": {"bg": "#d2eaff", "fg": "#10283c", "muted": "#3d6484", "line": "#b4d7f5"},
    "gray": {"bg": "#eceff1", "fg": "#1c1c1c", "muted": "#5c656b", "line": "#d5dbdf"},
    "charcoal": {"bg": "#3a3a3a", "fg": "#f5f5f5", "muted": "#c8c8c8", "line": "#555555"},
}


def normalize_appearance(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in APPEARANCES else "system"

_CHECK = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])?\s*(?:\[([ xX])\]|([☐☑✓✔]))\s*(.*?)\s*$"
)


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def next_color(existing: list[Note]) -> str:
    return COLORS[len(existing) % len(COLORS)]


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False

    def style_key(self) -> tuple[bool, bool, bool, bool]:
        return (self.bold, self.italic, self.underline, self.strike)

    def to_dict(self) -> dict:
        data = {"text": self.text}
        if self.bold:
            data["bold"] = True
        if self.italic:
            data["italic"] = True
        if self.underline:
            data["underline"] = True
        if self.strike:
            data["strike"] = True
        return data

    @classmethod
    def from_dict(cls, raw) -> Span:
        if isinstance(raw, str):
            return cls(text=raw)
        if not isinstance(raw, dict):
            return cls(text="")
        return cls(
            text=str(raw.get("text", "")),
            bold=bool(raw.get("bold", False)),
            italic=bool(raw.get("italic", False)),
            underline=bool(raw.get("underline", False)),
            strike=bool(raw.get("strike", False)),
        )


def merge_spans(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for span in spans:
        if not span.text:
            continue
        if merged and merged[-1].style_key() == span.style_key():
            merged[-1].text += span.text
        else:
            merged.append(
                Span(
                    span.text,
                    span.bold,
                    span.italic,
                    span.underline,
                    span.strike,
                )
            )
    return merged


def plain_to_spans(text: str) -> list[Span]:
    if not text:
        return []
    return [Span(text=text)]


def spans_plain(spans: list[Span]) -> str:
    return "".join(span.text for span in spans)


@dataclass
class TodoItem:
    id: str
    text: str = ""
    done: bool = False
    reminder: str | None = None
    reminder_fired: bool = False

    @classmethod
    def new(cls, text: str = "", done: bool = False) -> TodoItem:
        return cls(id=new_id(), text=text, done=done)

    def to_dict(self) -> dict:
        data = {"id": self.id, "text": self.text, "done": self.done}
        if self.reminder:
            data["reminder"] = self.reminder
        if self.reminder_fired:
            data["reminder_fired"] = True
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> TodoItem:
        return cls(
            id=str(raw.get("id") or new_id()),
            text=str(raw.get("text", "")),
            done=bool(raw.get("done", False)),
            reminder=raw.get("reminder") or None,
            reminder_fired=bool(raw.get("reminder_fired", False)),
        )


@dataclass
class Note:
    id: str
    kind: str = "text"
    color: str = "yellow"
    pinned: bool = False
    title: str = ""
    body: list[Span] = field(default_factory=list)
    items: list[TodoItem] = field(default_factory=list)
    reminder: str | None = None
    reminder_fired: bool = False
    width: int = 320
    height: int = 380
    x: int | None = None
    y: int | None = None
    open: bool = True
    created: str = ""
    updated: str = ""

    @classmethod
    def new(cls, kind: str = "text", color: str = "yellow") -> Note:
        stamp = now_stamp()
        return cls(id=new_id(), kind=kind, color=color, created=stamp, updated=stamp)

    def touch(self) -> None:
        self.updated = now_stamp()

    def plain(self) -> str:
        if self.kind == "todo":
            lines = []
            if self.title.strip():
                lines.append(self.title.strip())
            for item in self.items:
                mark = "x" if item.done else " "
                lines.append(f"- [{mark}] {item.text}")
            return "\n".join(lines)
        return spans_plain(self.body)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "color": self.color,
            "pinned": self.pinned,
            "title": self.title,
            "body": [span.to_dict() for span in self.body],
            "items": [item.to_dict() for item in self.items],
            "reminder": self.reminder,
            "reminder_fired": self.reminder_fired,
            "width": self.width,
            "height": self.height,
            "x": self.x,
            "y": self.y,
            "open": self.open,
            "created": self.created,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Note:
        kind = raw.get("kind") if raw.get("kind") in ("text", "todo") else "text"
        color = raw.get("color") if raw.get("color") in COLORS else "yellow"
        body = [Span.from_dict(item) for item in raw.get("body") or []]
        items = [TodoItem.from_dict(item) for item in raw.get("items") or [] if isinstance(item, dict)]
        width = _clamp_int(raw.get("width"), 320, 240, 1600)
        height = _clamp_int(raw.get("height"), 380, 200, 1200)
        return cls(
            id=str(raw.get("id") or new_id()),
            kind=kind,
            color=color,
            pinned=bool(raw.get("pinned", False)),
            title=str(raw.get("title") or ""),
            body=merge_spans(body),
            items=items,
            reminder=raw.get("reminder") or None,
            reminder_fired=bool(raw.get("reminder_fired", False)),
            width=width,
            height=height,
            x=_optional_int(raw.get("x")),
            y=_optional_int(raw.get("y")),
            open=bool(raw.get("open", True)),
            created=str(raw.get("created") or now_stamp()),
            updated=str(raw.get("updated") or now_stamp()),
        )

    def duplicate(self) -> Note:
        copy = Note.from_dict(self.to_dict())
        copy.id = new_id()
        copy.open = True
        copy.reminder_fired = False
        copy.created = now_stamp()
        copy.updated = copy.created
        if copy.x is not None and copy.y is not None:
            copy.x += 28
            copy.y += 28
        for item in copy.items:
            item.id = new_id()
            item.reminder_fired = False
        return copy


def _clamp_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_checklist(text: str) -> list[TodoItem] | None:
    """Return checklist items when the text is mostly checkbox lines."""
    nonempty = [line for line in text.splitlines() if line.strip()]
    if not nonempty:
        return None
    hits = sum(1 for line in nonempty if _CHECK.match(line))
    if hits == 0:
        return None
    threshold = max(2, int(len(nonempty) * 0.6))
    if hits != len(nonempty) and hits < threshold:
        return None
    items: list[TodoItem] = []
    for line in nonempty:
        match = _CHECK.match(line)
        if match:
            mark, box, body = match.group(1), match.group(2), match.group(3)
            done = (mark or "").lower() == "x" or (box or "") in {"☑", "✓", "✔"}
            items.append(TodoItem.new(text=body, done=done))
        else:
            items.append(TodoItem.new(text=line.strip()))
    return items


def preview_line(note: Note) -> str:
    if note.kind == "todo":
        if note.title.strip():
            return note.title.strip()
        for item in note.items:
            if item.text.strip() and not item.done:
                return item.text.strip()
        for item in note.items:
            if item.text.strip():
                return item.text.strip()
        return "Checklist"
    text = spans_plain(note.body).strip()
    if not text:
        return "Sticky Note"
    first = text.splitlines()[0].strip()
    return first or "Sticky Note"


def base_title(note: Note) -> str:
    base = " ".join(preview_line(note).split())
    if base == "Sticky Notes":
        base = "Sticky Notes note"
    if len(base) > 70:
        base = base[:69].rstrip() + "…"
    return base


def window_title(note: Note, notes: list[Note]) -> str:
    base = base_title(note)
    clash = any(other.id != note.id and base_title(other) == base for other in notes)
    if clash:
        return f"{base} · {note.id[:4]}"
    return base


def subtitle(note: Note) -> str:
    if note.kind == "todo":
        total = len([item for item in note.items if item.text.strip()])
        done = len([item for item in note.items if item.text.strip() and item.done])
        pending = next((item.text.strip() for item in note.items if item.text.strip() and not item.done), "")
        count = f"{done}/{total}" if total else "Empty checklist"
        if pending and note.title.strip():
            return f"{count} · {pending}"
        if pending and not note.title.strip():
            extra = [item.text.strip() for item in note.items if item.text.strip() and not item.done]
            if len(extra) > 1:
                return f"{count} · {extra[1]}"
            return count
        return count
    lines = [line.strip() for line in spans_plain(note.body).splitlines() if line.strip()]
    if len(lines) > 1:
        return lines[1]
    return "Text note" if lines else "Empty note"


def search_blob(note: Note) -> str:
    parts = [note.title, spans_plain(note.body)]
    parts.extend(item.text for item in note.items)
    return "\n".join(parts).lower()


WELCOME_TEXT = (
    "Sticky Notes\n"
    "\n"
    "Pin a note to keep it above other windows.\n"
    "Open the menu to make a checklist, or set a reminder with the bell.\n"
    "\n"
    "Copy text anywhere, then choose New from clipboard. "
    "Or from a terminal:\n"
    "gnome-sticky-notes --text \"Buy milk\""
)
