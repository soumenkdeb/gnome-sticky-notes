"""Keep a note above other windows, and on every workspace.

Native Wayland clients cannot request this. On X11 and XWayland, GNOME still
honors the EWMH _NET_WM_STATE_ABOVE and _NET_WM_STATE_STICKY hints.
"""

from __future__ import annotations

from . import bootstrap  # noqa: F401

import ctypes
import ctypes.util

from gi.repository import Gdk

_x11 = None
_SubstructureRedirectMask = 1 << 20
_SubstructureNotifyMask = 1 << 19
_ClientMessage = 33


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data0", ctypes.c_long),
        ("data1", ctypes.c_long),
        ("data2", ctypes.c_long),
        ("data3", ctypes.c_long),
        ("data4", ctypes.c_long),
    ]


def x11_backend() -> bool:
    display = Gdk.Display.get_default()
    if display is None:
        return False
    return type(display).__name__ == "X11Display" or display.__class__.__name__.endswith("X11Display")


def _lib():
    global _x11
    if _x11 is None:
        _x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
        _x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        _x11.XOpenDisplay.restype = ctypes.c_void_p
        _x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        _x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        _x11.XInternAtom.restype = ctypes.c_ulong
        _x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        _x11.XDefaultRootWindow.restype = ctypes.c_ulong
        _x11.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        _x11.XSendEvent.restype = ctypes.c_int
        _x11.XFlush.argtypes = [ctypes.c_void_p]
        _x11.XGetAtomName.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        _x11.XGetAtomName.restype = ctypes.c_void_p
        _x11.XFree.argtypes = [ctypes.c_void_p]
        _x11.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        _x11.XGetWindowProperty.restype = ctypes.c_int
        _x11.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        _x11.XTranslateCoordinates.restype = ctypes.c_int
        _x11.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
        _x11.XMoveWindow.restype = ctypes.c_int
        _x11.XQueryPointer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
        ]
        _x11.XQueryPointer.restype = ctypes.c_int
    return _x11


def _xid(window) -> int | None:
    surface = window.get_surface()
    if surface is None or not hasattr(surface, "get_xid"):
        return None
    try:
        return int(surface.get_xid())
    except (TypeError, ValueError):
        return None


def _send(xid: int, message: bytes, data: tuple[int, int, int, int, int]) -> bool:
    lib = _lib()
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    try:
        atom = lib.XInternAtom(display, message, False)
        root = lib.XDefaultRootWindow(display)
        event = _XClientMessageEvent()
        event.type = _ClientMessage
        event.display = display
        event.window = xid
        event.message_type = atom
        event.format = 32
        event.data0, event.data1, event.data2, event.data3, event.data4 = data
        mask = _SubstructureRedirectMask | _SubstructureNotifyMask
        sent = lib.XSendEvent(display, root, False, mask, ctypes.byref(event))
        lib.XFlush(display)
        return bool(sent)
    finally:
        lib.XCloseDisplay(display)


def set_kept_above(window, enabled: bool) -> bool:
    """Pin or unpin. Returns False when this window has no X11 surface."""
    xid = _xid(window)
    if xid is None:
        return False
    lib = _lib()
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    try:
        above = lib.XInternAtom(display, b"_NET_WM_STATE_ABOVE", False)
        sticky = lib.XInternAtom(display, b"_NET_WM_STATE_STICKY", False)
    finally:
        lib.XCloseDisplay(display)
    action = 1 if enabled else 0
    return _send(xid, b"_NET_WM_STATE", (action, above, sticky, 1, 0))


def state_names(window) -> set[str]:
    xid = _xid(window)
    if xid is None:
        return set()
    lib = _lib()
    display = lib.XOpenDisplay(None)
    if not display:
        return set()
    try:
        prop = lib.XInternAtom(display, b"_NET_WM_STATE", False)
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        status = lib.XGetWindowProperty(
            display,
            xid,
            prop,
            0,
            1024,
            False,
            0,
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(nitems),
            ctypes.byref(bytes_after),
            ctypes.byref(data),
        )
        names: set[str] = set()
        if status == 0 and data and actual_format.value == 32:
            values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
            for index in range(int(nitems.value)):
                raw = lib.XGetAtomName(display, values[index])
                if raw:
                    names.add(ctypes.cast(raw, ctypes.c_char_p).value.decode())
                    lib.XFree(raw)
        if data:
            lib.XFree(ctypes.cast(data, ctypes.c_void_p))
        return names
    finally:
        lib.XCloseDisplay(display)


def is_kept_above(window) -> bool:
    names = state_names(window)
    return "_NET_WM_STATE_ABOVE" in names and "_NET_WM_STATE_STICKY" in names


def get_position(window) -> tuple[int, int] | None:
    xid = _xid(window)
    if xid is None:
        return None
    lib = _lib()
    display = lib.XOpenDisplay(None)
    if not display:
        return None
    try:
        root = lib.XDefaultRootWindow(display)
        dest_x = ctypes.c_int()
        dest_y = ctypes.c_int()
        child = ctypes.c_ulong()
        ok = lib.XTranslateCoordinates(
            display, xid, root, 0, 0, ctypes.byref(dest_x), ctypes.byref(dest_y), ctypes.byref(child)
        )
        if not ok:
            return None
        return dest_x.value, dest_y.value
    finally:
        lib.XCloseDisplay(display)


def move_window(window, x: int, y: int) -> bool:
    """Move a top-level XWayland window.

    This session ignores _NET_MOVERESIZE_WINDOW. XMoveWindow on the client
    window does land at the requested root coordinates.
    """
    xid = _xid(window)
    if xid is None:
        return False
    lib = _lib()
    display = lib.XOpenDisplay(None)
    if not display:
        return False
    try:
        lib.XMoveWindow(display, xid, int(x), int(y))
        lib.XFlush(display)
        return True
    finally:
        lib.XCloseDisplay(display)


def pointer_position() -> tuple[int, int] | None:
    lib = _lib()
    display = lib.XOpenDisplay(None)
    if not display:
        return None
    try:
        root = lib.XDefaultRootWindow(display)
        root_return = ctypes.c_ulong()
        child = ctypes.c_ulong()
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        win_x = ctypes.c_int()
        win_y = ctypes.c_int()
        mask = ctypes.c_uint()
        ok = lib.XQueryPointer(
            display,
            root,
            ctypes.byref(root_return),
            ctypes.byref(child),
            ctypes.byref(root_x),
            ctypes.byref(root_y),
            ctypes.byref(win_x),
            ctypes.byref(win_y),
            ctypes.byref(mask),
        )
        if not ok:
            return None
        return int(root_x.value), int(root_y.value)
    finally:
        lib.XCloseDisplay(display)


def _monitor_containing(px: int, py: int):
    display = Gdk.Display.get_default()
    if display is None:
        return None
    monitors = display.get_monitors()
    count = monitors.get_n_items()
    if count == 0:
        return None
    fallback = monitors.get_item(0)
    for index in range(count):
        monitor = monitors.get_item(index)
        geo = monitor.get_geometry()
        if geo.x <= px < geo.x + geo.width and geo.y <= py < geo.y + geo.height:
            return monitor
    return fallback


def position_on_screen(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    monitor = _monitor_containing(x, y)
    if monitor is None:
        return x, y
    geo = monitor.get_geometry()
    margin = 16
    max_x = geo.x + geo.width - min(width, geo.width - margin)
    max_y = geo.y + geo.height - min(max(height, 80), geo.height - margin)
    x = min(max(x, geo.x + margin), max(max_x, geo.x + margin))
    y = min(max(y, geo.y + margin), max(max_y, geo.y + margin))
    return x, y


def cascade_position(index: int, width: int, height: int) -> tuple[int, int]:
    """Stack a new note on the monitor under the pointer."""
    point = pointer_position()
    monitor = _monitor_containing(*(point if point else (0, 0)))
    if monitor is None:
        origin_x, origin_y = 72, 56
    else:
        geo = monitor.get_geometry()
        origin_x = geo.x + 56
        origin_y = geo.y + 48
    step = index % 8
    return position_on_screen(origin_x + step * 32, origin_y + step * 28, width, height)
