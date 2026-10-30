"""Choose a GDK backend before GTK is imported.

GNOME Wayland does not let a normal client ask to stay above other windows.
XWayland still honors the EWMH always-on-top hint, and this session uses
integer scaling, so the default backend is X11. Set STICKY_NOTES_BACKEND=wayland
to stay on the native Wayland backend and use the bundled shell extension.
"""

import os

_choice = os.environ.get("STICKY_NOTES_BACKEND", "x11").strip().lower()
if _choice != "wayland" and not os.environ.get("GDK_BACKEND"):
    os.environ["GDK_BACKEND"] = "x11"
