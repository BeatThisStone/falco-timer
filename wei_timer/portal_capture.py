import uuid
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
from PIL import Image

from wei_timer.capture import CaptureError
from wei_timer.portal_common import portal_proxy, wait_for_response


def take_full_screenshot() -> Image.Image:
    """One-shot full-screen capture via the Screenshot portal. Shows the
    portal's own permission dialog every call -- fine here since this is
    always triggered by a deliberate user action (button click), never
    polled repeatedly."""
    proxy = portal_proxy("org.freedesktop.portal.Screenshot")
    token = "wt" + uuid.uuid4().hex[:16]
    options = {
        "handle_token": GLib.Variant("s", token),
        "interactive": GLib.Variant("b", False),
    }
    call_result = proxy.call_sync(
        "Screenshot", GLib.Variant("(sa{sv})", ("", options)),
        Gio.DBusCallFlags.NONE, -1, None,
    )
    request_path = call_result.unpack()[0]
    response = wait_for_response(request_path)

    if response.get("code") != 0:
        raise CaptureError("Screenshot request was cancelled or denied")
    uri = response.get("results", {}).get("uri")
    if not uri:
        raise CaptureError("Screenshot portal returned no image")
    path = Gio.File.new_for_uri(uri).get_path()
    return Image.open(path).convert("RGB")