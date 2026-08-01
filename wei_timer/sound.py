"""
Sound playback.

No hard dependency on any specific audio stack. Tries backends in order
of preference at runtime and uses whichever is actually on PATH; if none
are present, playback just silently no-ops rather than crashing the app
or the notification flow around it.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional

# Ordered by preference: native pipewire CLI, then the pulse-compat
# layer (works under plain PulseAudio too), then plain ALSA as a last
# resort.
_BACKENDS = ["pw-play", "paplay", "aplay"]


def _first_available_backend() -> Optional[str]:
    for name in _BACKENDS:
        if shutil.which(name):
            return name
    return None


_current_process: Optional[subprocess.Popen] = None

def play_sound(path: Optional[str], volume: float = 1.0) -> bool:
    global _current_process
    if not path:
        return False
    backend = _first_available_backend()
    if backend is None:
        return False

    stop_sound()
    volume = max(0.0, min(1.0, volume))

    if backend == "paplay":
        cmd = [backend, f"--volume={int(volume * 65536)}", path]
    elif backend == "pw-play":
        cmd = [backend, f"--volume={volume:.3f}", path]
    else:  # aplay -- no volume flag support
        cmd = [backend, path]

    try:
        _current_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, OSError):
        return False

def is_playing() -> bool:
    return _current_process is not None and _current_process.poll() is None

def stop_sound() -> None:
    global _current_process
    if _current_process is not None and _current_process.poll() is None:
        try:
            _current_process.terminate()
        except OSError:
            pass
    _current_process = None