"""
Session type + compositor detection.

Determines:
  - X11 vs Wayland (session_type)
  - which Wayland compositor, if any, via env vars that only exist when
    that compositor is actually running (doubles as "IPC socket exists")
  - a stable identity string for the banner-dismissal-per-compositor config
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional

_wlroots_capture_supported: Optional[bool] = None

class SessionType(str, Enum):
    X11 = "x11"
    WAYLAND = "wayland"
    UNKNOWN = "unknown"


class Compositor(str, Enum):
    NIRI = "niri"
    HYPRLAND = "hyprland"
    SWAY = "sway"
    GNOME = "gnome"
    PLASMA = "plasma"
    OTHER_WAYLAND = "other_wayland"
    X11_GENERIC = "x11"
    UNKNOWN = "unknown"


# Compositors with a documented IPC we actually use for focused-window info.
FOCUS_IPC_SUPPORTED = {Compositor.NIRI, Compositor.HYPRLAND, Compositor.SWAY, Compositor.X11_GENERIC}


@dataclass(frozen=True)
class EnvironmentInfo:
    session_type: SessionType
    compositor: Compositor

    @property
    def has_focus_ipc(self) -> bool:
        """Whether we can reliably query the focused window's title."""
        if self.compositor in FOCUS_IPC_SUPPORTED:
            return True
        return False

    @property
    def identity(self) -> str:
        """Stable key for per-compositor config (e.g. banner dismissal)."""
        return self.compositor.value


def _detect_session_type() -> SessionType:
    xdg = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if xdg == "wayland":
        return SessionType.WAYLAND
    if xdg == "x11":
        return SessionType.X11
    # Fallback if XDG_SESSION_TYPE isn't set for some reason.
    if os.environ.get("WAYLAND_DISPLAY"):
        return SessionType.WAYLAND
    if os.environ.get("DISPLAY"):
        return SessionType.X11
    return SessionType.UNKNOWN


def _detect_wayland_compositor() -> Compositor:
    # These env vars only exist when that specific compositor set them up,
    # which also implies its IPC socket is present.
    if os.environ.get("NIRI_SOCKET"):
        return Compositor.NIRI
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return Compositor.HYPRLAND
    if os.environ.get("SWAYSOCK"):
        return Compositor.SWAY

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in desktop:
        return Compositor.GNOME
    if "kde" in desktop or "plasma" in desktop:
        return Compositor.PLASMA

    return Compositor.OTHER_WAYLAND


def detect_environment() -> EnvironmentInfo:
    session = _detect_session_type()
    if session == SessionType.X11:
        return EnvironmentInfo(session_type=session, compositor=Compositor.X11_GENERIC)
    if session == SessionType.WAYLAND:
        return EnvironmentInfo(session_type=session, compositor=_detect_wayland_compositor())
    return EnvironmentInfo(session_type=SessionType.UNKNOWN, compositor=Compositor.UNKNOWN)

def has_binary(name: str) -> bool:
    return shutil.which(name) is not None

def _grim_actually_works() -> bool:
    """has_binary() only confirms grim/slurp are installed, not that the
    compositor implements wlr-screencopy. Plasma/GNOME can have grim
    installed with nothing for it to talk to. This runs a real 1x1 probe
    capture and caches the result for the process lifetime."""
    global _wlroots_capture_supported
    if _wlroots_capture_supported is not None:
        return _wlroots_capture_supported
    if not (has_binary("grim") and has_binary("slurp")):
        _wlroots_capture_supported = False
        return False
    try:
        result = subprocess.run(
            ["grim", "-g", "0,0 1x1", "/dev/null"],
            capture_output=True, text=True, timeout=5,
        )
        _wlroots_capture_supported = (result.returncode == 0)
    except (FileNotFoundError, subprocess.SubprocessError):
        _wlroots_capture_supported = False
    return _wlroots_capture_supported

class CaptureBackend(str, Enum):
    WLROOTS = "wlroots"
    X11 = "x11"
    PORTAL = "portal"


def capture_backend(env: EnvironmentInfo) -> CaptureBackend:
    forced = os.environ.get("WEI_TIMER_FORCE_BACKEND")
    if forced:
        return CaptureBackend(forced)
    if env.session_type == SessionType.X11:
        return CaptureBackend.X11
    if _grim_actually_works():
        return CaptureBackend.WLROOTS
    return CaptureBackend.PORTAL

def _has_gst_pipewire_plugin() -> bool:
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "pipewiresrc"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def required_capture_tools(env: EnvironmentInfo) -> tuple:
    backend = capture_backend(env)
    if backend == CaptureBackend.X11:
        return ("scrot", "slop")
    if backend == CaptureBackend.WLROOTS:
        return ("grim", "slurp")
    return ()  # PORTAL: Screenshot capture needs no binary,
               # but the watcher separately needs gst-plugin-pipewire


def missing_capture_tools(env: EnvironmentInfo) -> list:
    backend = capture_backend(env)
    if backend == CaptureBackend.X11:
        return [t for t in ("scrot", "slop") if not has_binary(t)]
    if backend == CaptureBackend.WLROOTS:
        return []  # capture_backend() already confirmed this works
    missing = []
    if not _has_gst_pipewire_plugin():
        missing.append("gst-plugin-pipewire")
    return missing