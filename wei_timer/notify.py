"""
Desktop notifications via Gio.Notification.

Deliberately not shelling out to `notify-send` -- Gio.Notification hits
the same org.freedesktop.Notifications D-Bus interface directly, and
Gio is already pulled in by python-gobject/GTK4, so this adds no extra
dependency. If there's no notification daemon listening (e.g. a bare
compositor with nothing providing the popup UI), the call just no-ops
rather than raising.
"""
from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402


def send_notification(app: Gio.Application, title: str, body: str, notification_id: str = "wei-timer") -> None:
    """`app` is the running Adw.Application/Gtk.Application instance --
    notifications are sent through it rather than a standalone Gio call
    so they're correctly associated with the app for the desktop shell."""
    notification = Gio.Notification.new(title)
    notification.set_body(body)
    try:
        app.send_notification(notification_id, notification)
    except Exception:
        # No daemon listening, or the portal call failed for some other
        # environment-specific reason -- degrade silently, don't crash
        # the timer-completion flow over a missing popup.
        pass
