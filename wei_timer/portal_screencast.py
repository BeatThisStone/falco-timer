"""
Persistent screen capture for the autorun watcher on GNOME/Plasma Wayland.
"""
from __future__ import annotations

import uuid
from typing import Optional

import gi
gi.require_version("Gio", "2.0")
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gio, GLib, Gst, GstApp  # noqa: F401 -- GstApp import registers AppSink bindings (try_pull_sample etc.) even though the name itself is unused
from PIL import Image

from wei_timer.portal_common import portal_proxy, wait_for_response

Gst.init(None)


class ScreenCastError(RuntimeError):
    pass


class ScreenCastSession:
    def __init__(self):
        self._session_handle: Optional[str] = None
        self._pipeline = None
        self._appsink = None

    def start(self) -> None:
        proxy = portal_proxy("org.freedesktop.portal.ScreenCast")

        session_token = "wt_session_" + uuid.uuid4().hex[:12]
        create_token = "wt_create_" + uuid.uuid4().hex[:12]
        options = {
            "handle_token": GLib.Variant("s", create_token),
            "session_handle_token": GLib.Variant("s", session_token),
        }
        result = proxy.call_sync(
            "CreateSession", GLib.Variant("(a{sv})", (options,)),
            Gio.DBusCallFlags.NONE, -1, None,
        )
        response = wait_for_response(result.unpack()[0])
        if response.get("code") != 0:
            raise ScreenCastError("ScreenCast session creation was denied")
        self._session_handle = response["results"]["session_handle"]

        select_token = "wt_select_" + uuid.uuid4().hex[:12]
        select_options = {
            "handle_token": GLib.Variant("s", select_token),
            "types": GLib.Variant("u", 1),        # 1 = MONITOR
            "cursor_mode": GLib.Variant("u", 1),  # 1 = hidden
            "persist_mode": GLib.Variant("u", 0), # 2 = dont persist past this session
        }

        result = proxy.call_sync(
            "SelectSources",
            GLib.Variant("(oa{sv})", (self._session_handle, select_options)),
            Gio.DBusCallFlags.NONE, -1, None,
        )
        response = wait_for_response(result.unpack()[0])
        if response.get("code") != 0:
            raise ScreenCastError("Source selection was denied or cancelled")

        start_token = "wt_start_" + uuid.uuid4().hex[:12]
        start_options = {"handle_token": GLib.Variant("s", start_token)}
        result = proxy.call_sync(
            "Start",
            GLib.Variant("(osa{sv})", (self._session_handle, "", start_options)),
            Gio.DBusCallFlags.NONE, -1, None,
        )
        response = wait_for_response(result.unpack()[0])
        if response.get("code") != 0:
            raise ScreenCastError("ScreenCast start was denied or cancelled")

        streams = response["results"].get("streams", [])
        if not streams:
            raise ScreenCastError("No streams returned by portal")
        node_id = streams[0][0]

        fd_result, fd_list = proxy.call_with_unix_fd_list_sync(
            "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (self._session_handle, {})),
            Gio.DBusCallFlags.NONE, -1, None, None,
        )
        pw_fd = fd_list.get(0)
        self._start_pipeline(pw_fd, node_id)

    def _start_pipeline(self, pw_fd: int, node_id: int) -> None:
        pipeline_str = (
            f"pipewiresrc fd={pw_fd} path={node_id} ! "
            f"videoconvert ! video/x-raw,format=RGB ! "
            f"appsink name=sink emit-signals=false max-buffers=1 drop=true sync=false"
        )
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsink = self._pipeline.get_by_name("sink")
        self._pipeline.set_state(Gst.State.PLAYING)
        ret, state, pending = self._pipeline.get_state(5 * Gst.SECOND)

    def get_frame(self) -> Optional[Image.Image]:
        if self._appsink is None:
            return None
        sample = self._appsink.try_pull_sample(Gst.SECOND)
        if sample is None:
            return None
        buf = sample.get_buffer()
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")
        fmt = structure.get_value("format")

        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if not success:
            return None
        try:
            if fmt == "RGB":
                img = Image.frombytes("RGB", (width, height), mapinfo.data, "raw", "RGB", 0, 1)
            elif fmt == "BGRA":
                img = Image.frombytes("RGBA", (width, height), mapinfo.data, "raw", "BGRA", 0, 1).convert("RGB")
            elif fmt == "RGBA":
                img = Image.frombytes("RGBA", (width, height), mapinfo.data, "raw", "RGBA", 0, 1).convert("RGB")
            else:
                return None
            return img
        finally:
            buf.unmap(mapinfo)

    def get_cropped_frame(self, geometry: str):
        from wei_timer.capture import _parse_geometry, CaptureError
        frame = self.get_frame()
        if frame is None:
            raise CaptureError("No frame available from ScreenCast stream yet")
        x, y, w, h = _parse_geometry(geometry)

        return frame.crop((x, y, x + w, y + h))

    def stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._appsink = None
        self._session_handle = None


_shared_session: Optional[ScreenCastSession] = None


def get_shared_session() -> ScreenCastSession:
    global _shared_session
    if _shared_session is None:
        _shared_session = ScreenCastSession()
        _shared_session.start()
    return _shared_session


def get_watcher_capture_fn():
    def _capture(geometry: str):
        session = get_shared_session()
        return session.get_cropped_frame(geometry)
    return _capture


def stop_shared_session() -> None:
    global _shared_session
    if _shared_session is not None:
        _shared_session.stop()
        _shared_session = None

def reset_session() -> None:
    """Tears down any live session, forcing the next capture to
    renegotiate from scratch, which makes the portal show its monitor
    picker again instead of silently reusing the first-ever selection."""
    stop_shared_session()