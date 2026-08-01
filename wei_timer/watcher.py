"""
Watcher state machine.

Priority order, top short-circuits everything below it:
  1. manual override switch OFF -> fully idle, no polling at all
  2. timer already active -> sleep until deadline, no game/focus checks
  3. game process not running -> cheap process-only poll
  4. game running, not focused (when focus IPC is available) -> cheap poll
  5. game running + focused (or focus unknown) -> the only state that
     actually captures frames and hashes them, ~1s cadence

State 4 only exists on environments with focus IPC; where it's
unavailable (GNOME, etc.) state 3's "not running" check is the only
gate before falling through to full polling -- this is the documented
degraded mode the compatibility banner explains.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

from wei_timer.compositor import EnvironmentInfo
from wei_timer.config import Config
from wei_timer.detect import ReferenceHash, is_timer_present
from wei_timer.focus import is_game_focused, is_process_running

AUTORUN_DURATION_SECONDS = 50 * 60

IDLE_POLL_INTERVAL = 5.0       # when game isn't running, or watcher's off-tier checks
FOCUSED_POLL_INTERVAL = 1.0    # only while actually capturing frames


class WatcherState(Enum):
    DISABLED = auto()
    TIMER_ACTIVE = auto()
    GAME_NOT_RUNNING = auto()
    GAME_UNFOCUSED = auto()
    WATCHING = auto()


@dataclass
class WatcherStatus:
    state: WatcherState
    timer_remaining_seconds: Optional[float] = None


class Watcher:
    """Runs the poll loop on a background thread. Callbacks fire on that
    thread -- callers touching GTK from them must marshal back to the
    main loop (e.g. via GLib.idle_add)."""

    def __init__(
        self,
        config: Config,
        env: EnvironmentInfo,
        capture_region_fn: Callable[[str], "Image.Image"],
        on_timer_complete: Callable[[], None],
        on_status_change: Optional[Callable[[WatcherStatus], None]] = None,
    ):
        self._config = config
        self._env = env
        self._capture_region_fn = capture_region_fn
        self._on_timer_complete = on_timer_complete
        self._on_status_change = on_status_change

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._timer_deadline: Optional[float] = None  # monotonic time, or None

    # -- lifecycle ---------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def arm_timer(self, duration_seconds: float = AUTORUN_DURATION_SECONDS) -> None:
        """Manually arm the timer (also called internally when the box
        is detected). Exposed so a 'start manual timer' UI action can
        reuse the exact same countdown/notification path."""
        self._timer_deadline = time.monotonic() + duration_seconds

    def cancel_timer(self) -> None:
        self._timer_deadline = None

    # -- internals -----------------------------------------------------

    def _emit_status(self, state: WatcherState) -> None:
        if self._on_status_change is None:
            return
        remaining = None
        if self._timer_deadline is not None:
            remaining = max(0.0, self._timer_deadline - time.monotonic())
        self._on_status_change(WatcherStatus(state=state, timer_remaining_seconds=remaining))

    def _run_loop(self) -> None:
        reference: Optional[ReferenceHash] = None
        if self._config.timer_region_reference_hash and self._config.timer_region_max_distance is not None:
            reference = ReferenceHash(
                hash_str=self._config.timer_region_reference_hash,
                max_distance=self._config.timer_region_max_distance,
            )

        while not self._stop_event.is_set():
            # Tier 1: manual override.
            if not self._config.watcher_enabled:
                self._emit_status(WatcherState.DISABLED)
                self._sleep(IDLE_POLL_INTERVAL)
                continue

            # Tier 2: timer already running -- ignore everything else.
            if self._timer_deadline is not None:
                remaining = self._timer_deadline - time.monotonic()
                if remaining <= 0:
                    self._timer_deadline = None
                    self._on_timer_complete()
                    self._emit_status(WatcherState.GAME_NOT_RUNNING)  # re-evaluated next loop
                    continue
                self._emit_status(WatcherState.TIMER_ACTIVE)
                self._sleep(min(1.0, remaining))
                continue

            # Tier 3: is the game even running?
            if not is_process_running(self._config.game_process_name):
                self._emit_status(WatcherState.GAME_NOT_RUNNING)
                self._sleep(IDLE_POLL_INTERVAL)
                continue

            # Tier 4: is it focused? (None = can't tell -> fall through to watching)
            focused = is_game_focused(self._env, self._config.game_window_title_substring)
            if focused is False:
                self._emit_status(WatcherState.GAME_UNFOCUSED)
                self._sleep(IDLE_POLL_INTERVAL)
                continue

            # Tier 5: actually watching. Only reachable state that captures frames.
            self._emit_status(WatcherState.WATCHING)
            if reference is not None and self._config.timer_region_geometry:
                try:
                    frame = self._capture_region_fn(self._config.timer_region_geometry)
                    if is_timer_present(frame, reference):
                        self.arm_timer()
                except Exception as e:
                    # Capture can fail transiently (e.g. compositor busy);
                    # don't let one bad frame kill the whole watcher thread.
                    pass
            self._sleep(FOCUSED_POLL_INTERVAL)

    def _sleep(self, seconds: float) -> None:
        self._stop_event.wait(timeout=seconds)
