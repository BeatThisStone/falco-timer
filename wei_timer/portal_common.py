"""
Shared XDG portal request/response plumbing.

Both the one-shot Screenshot portal (portal_capture.py) and the persistent
ScreenCast portal (portal_screencast.py) talk to the same
org.freedesktop.portal.Desktop object and follow the same Request/Response
signal handshake, so this is factored out to avoid two copies drifting.
"""
from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"


def portal_proxy(interface: str) -> Gio.DBusProxy:
    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
        PORTAL_BUS_NAME, PORTAL_OBJECT_PATH, interface, None,
    )


def wait_for_response(request_path: str, timeout_seconds: int = 60) -> dict:
    loop = GLib.MainLoop()
    result = {}

    def on_signal(_conn, _sender, path, _iface, _signal, params):
        if path != request_path:
            return
        code, results = params.unpack()
        result["code"] = code
        result["results"] = results
        loop.quit()

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    sub_id = bus.signal_subscribe(
        PORTAL_BUS_NAME, "org.freedesktop.portal.Request", "Response",
        request_path, None, Gio.DBusSignalFlags.NONE, on_signal,
    )
    GLib.timeout_add_seconds(timeout_seconds, loop.quit)
    loop.run()
    bus.signal_unsubscribe(sub_id)
    return result
