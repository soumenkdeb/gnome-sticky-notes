"""JSON persistence for notes. A failed read is kept beside the live file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import Note, normalize_appearance


def data_dir() -> Path:
    override = os.environ.get("STICKY_NOTES_DIR")
    if override:
        path = Path(override)
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        path = path / "app.sdeb.StickyNotes"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "notes.json")
        self.notes: list[Note] = []
        self.autostart = False
        self.hinted_background = False
        self.appearance = "system"
        self.fresh = False

    def load(self) -> None:
        if not self.path.exists():
            self.fresh = True
            self.autostart = False
            self.appearance = "system"
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            backup = self.path.with_suffix(".json.bak")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self.fresh = True
            return
        if not isinstance(raw, dict):
            self.fresh = True
            return
        self.autostart = bool(raw.get("autostart", False))
        self.hinted_background = bool(raw.get("hinted_background", False))
        self.appearance = normalize_appearance(raw.get("appearance", "system"))
        notes = []
        for item in raw.get("notes") or []:
            if isinstance(item, dict):
                notes.append(Note.from_dict(item))
        self.notes = notes
        self.fresh = False

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "autostart": self.autostart,
            "hinted_background": self.hinted_background,
            "appearance": normalize_appearance(self.appearance),
            "notes": [note.to_dict() for note in self.notes],
        }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def get(self, note_id: str) -> Note | None:
        for note in self.notes:
            if note.id == note_id:
                return note
        return None
