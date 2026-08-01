"""
Process presence + window focus checks.

Two independent, cheap questions:
  - is the game process running at all? (works everywhere, same code path)
  - is the game's window currently focused? (compositor-specific, may be
    unavailable -- callers should treat None as "unknown / assume not
    gated on this")
"""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from wei_timer.compositor import Compositor, EnvironmentInfo


def is_process_running(process_name: str) -> bool:
    """Check /proc directly rather than shelling out to pgrep, so this
    doesn't add a hard dependency on procps being installed."""
    try:
        import psutil  # optional, nicer if present
        for p in psutil.process_iter(attrs=["name", "cmdline"]):
            name = p.info.get("name") or ""
            cmdline = " ".join(p.info.get("cmdline") or [])
            haystack = f"{name} {cmdline}".lower()
            if process_name.lower() in haystack:
                return True
        return False
    except ImportError:
        pass

    # Fallback: scan /proc/*/comm and /proc/*/cmdline manually. comm is
    # truncated to 15 chars, so also check cmdline for exe names longer
    # than that (Proton exe names are usually short enough for comm, but
    # cmdline is the safer bet).
    import os
    target = process_name.lower()
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            cmdline_path = f"/proc/{pid}/cmdline"
            try:
                with open(cmdline_path, "rb") as f:
                    cmdline = f.read().decode(errors="ignore").lower()
                if target in cmdline:
                    return True
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    except FileNotFoundError:
        # /proc doesn't exist -- not Linux, or something's very wrong.
        return False
    return False


def focused_window_title(env: EnvironmentInfo) -> Optional[str]:
    """Returns the focused window's title, or None if unavailable/unknown.
    None should be treated by callers as 'can't tell', not 'nothing focused'.
    """
    if env.compositor == Compositor.NIRI:
        return _niri_focused_title()
    if env.compositor == Compositor.HYPRLAND:
        return _hyprland_focused_title()
    if env.compositor == Compositor.SWAY:
        return _sway_focused_title()
    if env.compositor == Compositor.X11_GENERIC:
        return _x11_focused_title()
    return None


def _run_json(cmd: list) -> Optional[dict]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError, OSError):
        return None


def _niri_focused_title() -> Optional[str]:
    data = _run_json(["niri", "msg", "-j", "focused-window"])
    if not data:
        return None
    return data.get("title")


def _hyprland_focused_title() -> Optional[str]:
    data = _run_json(["hyprctl", "activewindow", "-j"])
    if not data:
        return None
    return data.get("title")


def _sway_focused_title() -> Optional[str]:
    data = _run_json(["swaymsg", "-t", "get_tree"])
    if not data:
        return None

    def walk(node):
        if node.get("focused"):
            return node.get("name")
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(data)


def _x11_focused_title() -> Optional[str]:
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def is_game_focused(env: EnvironmentInfo, title_substring: str) -> Optional[bool]:
    """None means 'can't determine' (no focus IPC available) -- caller
    should fall back to process-only gating in that case."""
    if not env.has_focus_ipc:
        return None
    title = focused_window_title(env)
    if title is None:
        return None
    return title_substring.lower() in title.lower()
