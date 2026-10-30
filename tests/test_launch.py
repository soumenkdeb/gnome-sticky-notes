"""Launch the real windows against the current GNOME session."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(tmp: str, app_id: str, **extra) -> dict:
    env = os.environ.copy()
    env["STICKY_NOTES_DIR"] = tmp
    env["STICKY_NOTES_APP_ID"] = app_id
    env["STICKY_NOTES_NO_WELCOME"] = "1"
    env["GDK_BACKEND"] = "x11"
    env.pop("STICKY_NOTES_SELFTEST", None)
    env.update(extra)
    return env


class LaunchTests(unittest.TestCase):
    def test_pin_sets_and_clears_above(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env(tmp, "app.sdeb.StickyNotesSelfTest", STICKY_NOTES_SELFTEST="1")
            env.pop("STICKY_NOTES_NO_WELCOME", None)
            completed = subprocess.run(
                [sys.executable, "-m", "gnome_sticky_notes"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads((Path(tmp) / "selftest.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["x11"], payload)
            self.assertTrue(payload["above"], payload)
            self.assertTrue(payload["cleared"], payload)
            self.assertIsNotNone(payload["position"], payload)
            delta = payload.get("delta")
            self.assertIsNotNone(delta, payload)
            self.assertLessEqual(abs(delta[0]), 24, payload)
            self.assertLessEqual(abs(delta[1]), 24, payload)

    def test_remote_command_creates_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_id = "app.sdeb.StickyNotesCliTest"
            env = _env(tmp, app_id)
            log_path = Path(tmp) / "log.txt"
            log = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "gnome_sticky_notes"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                self.assertTrue(_wait_ready(app_id), log_path.read_text(encoding="utf-8") if log_path.exists() else "")
                subprocess.run(
                    [sys.executable, "-m", "gnome_sticky_notes", "--text", "Milk and bread"],
                    cwd=ROOT,
                    env=env,
                    check=True,
                    timeout=20,
                )
                subprocess.run(
                    [sys.executable, "-m", "gnome_sticky_notes", "--todo", "Eggs", "--todo", "Bread"],
                    cwd=ROOT,
                    env=env,
                    check=True,
                    timeout=20,
                )
                subprocess.run(
                    [sys.executable, "-m", "gnome_sticky_notes", "--text", "-"],
                    cwd=ROOT,
                    env=env,
                    input="Piped note\n",
                    text=True,
                    check=True,
                    timeout=20,
                )
                notes = _wait_notes(Path(tmp) / "notes.json", 3)
            finally:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGINT)
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                log.close()
            self.assertIsNotNone(notes, log_path.read_text(encoding="utf-8"))
            blob = json.dumps(notes)
            self.assertIn("Milk and bread", blob)
            self.assertIn("Eggs", blob)
            self.assertIn("Bread", blob)
            self.assertIn("Piped note", blob)


def _wait_ready(app_id: str) -> bool:
    path = "/" + app_id.replace(".", "/")
    for _ in range(50):
        result = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                app_id,
                "--object-path",
                path,
                "--method",
                "org.freedesktop.DBus.Peer.Ping",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
        time.sleep(0.2)
    return False


def _wait_notes(path: Path, count: int):
    for _ in range(40):
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = {}
            notes = raw.get("notes") or []
            if len(notes) >= count:
                return notes
        time.sleep(0.25)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("notes")
    return None


if __name__ == "__main__":
    unittest.main()
