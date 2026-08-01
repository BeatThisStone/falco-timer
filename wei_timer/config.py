"""
Central config/state persistence for wei-timer.

Single JSON file under $XDG_CONFIG_HOME (falls back to ~/.config).
Everything else in the app reads/writes through this module rather than
touching the file directly, so the on-disk shape only needs to be known
in one place.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Optional

APP_NAME = "wei-timer"

BUNDLED_SOUNDS = {
    "pop": "notif.mp3",
    "pipe": "metal_pipe.mp3",
    "harikitte ikou": "harikitte_ikou.mp3",
}
DEFAULT_SOUND_KEY = "pop"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"

def _find_bundled_sound(filename: str) -> Optional[str]:
    candidates = []
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(Path(appdir) / "usr/share/wei-timer/sounds" / filename)
    candidates.append(Path(f"/usr/share/{APP_NAME}/sounds") / filename)
    candidates.append(Path(__file__).resolve().parent.parent / "sounds" / filename)
    for path in candidates:
        if path.exists():
            return str(path)
    return None


@dataclass
class CaratLog:
    """Date-keyed daily carat totals. Keys are ISO date strings."""
    totals: dict = field(default_factory=dict)

    def today_key(self) -> str:
        return date.today().isoformat()

    def add(self, amount: int) -> int:
        key = self.today_key()
        self.totals[key] = self.totals.get(key, 0) + amount
        return self.totals[key]

    def today_total(self) -> int:
        return self.totals.get(self.today_key(), 0)


@dataclass
class Config:
    # Watcher on/off — hard gate above the whole detection state machine.
    watcher_enabled: bool = True

    # Region geometry for the autorun timer's static anchor (for perceptual
    # hashing) and the reference hash captured during calibration.
    # geometry is a "X,Y WxH" string in slurp/grim format.
    timer_region_geometry: Optional[str] = None
    timer_region_reference_hash: Optional[str] = None
    timer_region_max_distance: Optional[int] = None

    # Process/window matching for the game.
    game_process_name: str = "umamusume.exe"
    game_window_title_substring: str = "Umamusume"

    # Sound selection: one of BUNDLED_SOUNDS keys, or "custom".
    sound_choice: str = DEFAULT_SOUND_KEY
    custom_sound_path: Optional[str] = None

    # Independent opt-outs.
    sound_enabled: bool = True
    notifications_enabled: bool = True

    # Carat cap: False -> 100 (normal), True -> 200 (2x drop event).
    is_double_drop_event: bool = False

    # Compatibility banner dismissal, keyed by compositor identity so it
    # reappears correctly if you run this under a different WM later.
    banner_dismissed_for: dict = field(default_factory=dict)

    # Daily carat totals.
    carat_log: CaratLog = field(default_factory=CaratLog)

    # self explanatory
    sound_volume: float = 1.0  # 0.0-1.0
    seen_minimize_notice: bool = False
    window_width: int = 720
    window_height: int = 640

    @property
    def carat_cap(self) -> int:
        return 200 if self.is_double_drop_event else 100

    def resolved_sound_path(self) -> Optional[str]:
        if self.sound_choice == "custom":
            return self.custom_sound_path
        filename = BUNDLED_SOUNDS.get(self.sound_choice)
        if filename is None:
            return None
        return _find_bundled_sound(filename)

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        d = dict(d)  # shallow copy
        carat_log_data = d.pop("carat_log", {}) or {}
        cfg = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        cfg.carat_log = CaratLog(totals=carat_log_data.get("totals", {}))
        return cfg


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        return Config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError, KeyError):
        # Corrupt or unreadable config: don't crash the app, start fresh.
        return Config()


def save_config(cfg: Config) -> None:
    path = config_path()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2)
    tmp.replace(path)  # atomic on same filesystem
