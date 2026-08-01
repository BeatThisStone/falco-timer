"""
Screen capture.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from wei_timer.compositor import detect_environment, CaptureBackend, capture_backend, SessionType

from PIL import Image


class CaptureError(RuntimeError):
    pass

def _is_x11() -> bool:
    return detect_environment().session_type == SessionType.X11

def _current_backend() -> CaptureBackend:
    return capture_backend(detect_environment())

def _parse_geometry(geometry: str) -> tuple[int, int, int, int]:
    xy, wh = geometry.split(" ")
    x, y = (int(v) for v in xy.split(","))
    w, h = (int(v) for v in wh.split("x"))
    return x, y, w, h

def select_region_interactively() -> Optional[str]:
    """Returns a 'X,Y WxH' geometry string regardless of backend, so
    everything downstream (config storage, capture_region) stays
    identical between Wayland and X11."""
    if _is_x11():
        cmd = ["slop", "-f", "%x,%y %wx%h"]
        tool = "slop"
    else:
        cmd = ["slurp"]
        tool = "slurp"

    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise CaptureError(f"{tool} is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        return None

    if out.returncode != 0:
        return None
    geometry = out.stdout.strip()
    return geometry or None


def capture_region(geometry: str) -> Image.Image:
    backend = _current_backend()

    if backend == CaptureBackend.PORTAL:
        from wei_timer.portal_capture import take_full_screenshot
        x, y, w, h = _parse_geometry(geometry)
        full = take_full_screenshot()
        return full.crop((x, y, x + w, y + h))

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        if backend == CaptureBackend.X11:
            x, y, w, h = _parse_geometry(geometry)
            cmd = ["scrot", "-a", f"{x},{y},{w},{h}", str(tmp_path)]
            tool = "scrot"
        else:
            cmd = ["grim", "-g", geometry, str(tmp_path)]
            tool = "grim"
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise CaptureError(f"{tool} failed: {result.stderr.strip()}")
        return Image.open(tmp_path).convert("RGB")
    except FileNotFoundError:
        raise CaptureError(f"{tool} is not installed or not on PATH")
    finally:
        tmp_path.unlink(missing_ok=True)


def capture_region_interactive() -> Optional[Image.Image]:
    """Combined drag-select + capture. Returns None if the user cancelled."""
    geometry = select_region_interactively()
    if geometry is None:
        return None
    return capture_region(geometry)

