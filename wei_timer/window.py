"""
Main application window.

Written against GTK4 + libadwaita.
"""
from __future__ import annotations

import gi
import sys
from pathlib import Path
from typing import Optional

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib, Gio, Gdk  # noqa: E402

from wei_timer.capture import capture_region, capture_region_interactive, CaptureError
from wei_timer.compositor import detect_environment,  missing_capture_tools, CaptureBackend, capture_backend, SessionType
from wei_timer.config import Config, load_config, save_config, BUNDLED_SOUNDS
from wei_timer.detect import ReferenceHash
from wei_timer.notify import send_notification
from wei_timer.ocr import extract_carat_count
from wei_timer.sound import play_sound, stop_sound, is_playing
from wei_timer.watcher import Watcher, WatcherState, WatcherStatus


SOUND_LABELS = {
    "pop": "generic pop effect",
    "pipe": "metal pipe",
    "harikitte ikou": "harikitte ikou!",
    "matko": "matko special",
}
# Order matters for the radio group: "No sound" listed above the default,
# per the spec.
SOUND_ORDER = list(BUNDLED_SOUNDS.keys())

def _find_matching_monitor(frame_size) -> Optional[Gdk.Monitor]:
    display = Gdk.Display.get_default()
    monitors = display.get_monitors()
    for i in range(monitors.get_n_items()):
        monitor = monitors.get_item(i)
        geo = monitor.get_geometry()
        if (geo.width, geo.height) == frame_size:
            return monitor
    return None

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app)
        self.app = app
        self.config: Config = load_config()
        self.env = detect_environment()

        self.set_title("lunaui's Falco Timer")
        self.set_default_size(self.config.window_width, self.config.window_height)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root_box.set_margin_top(12)
        root_box.set_margin_bottom(12)
        root_box.set_margin_start(16)
        root_box.set_margin_end(16)
        toolbar_view.set_content(self._wrap_scrollable(root_box))

        # -- compatibility banner (only shown in degraded focus-detection mode) --
        missing_tools = missing_capture_tools(self.env)
        backend = capture_backend(self.env)

        self.banner = Adw.Banner()
        self.banner.set_button_label("Dismiss")
        self.banner.connect("button-clicked", self._on_banner_dismiss)

        if missing_tools:
            tool_list = " and ".join(missing_tools)
            self.banner.set_title(
                f"Missing {tool_list}: screen capture won't work until these are installed. "
                f"Install via your distro's package manager."
            )
            self.banner.set_revealed(True)
        elif backend == CaptureBackend.PORTAL and self.env.session_type == SessionType.WAYLAND:
            self.banner.set_title(
                "Wayland detected: grim and slurp weren't found, so we assume you're on GNOME or "
                "KDE Plasma and will use the screenshot portal instead. If that's wrong and you're on a "
                "wlroots compositor, install grim and slurp for better capture support."
            )
            self.banner.set_revealed(True)
        elif not self.env.has_focus_ipc and not self.config.banner_dismissed_for.get(self.env.identity, False):
            self.banner.set_title(self._banner_text())
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        root_box.append(self.banner)

        # -- watcher status + manual override switch --
        watcher_group = Adw.PreferencesGroup(title="Autorun Watcher")
        root_box.append(watcher_group)

        switch_row = Adw.SwitchRow(title="Watching enabled", subtitle="Turn off during manual runs")
        switch_row.set_active(self.config.watcher_enabled)
        switch_row.connect("notify::active", self._on_watcher_switch_toggled)
        watcher_group.add(switch_row)

        self.status_label = Gtk.Label(label="Status: —", xalign=0)
        self.status_label.add_css_class("dim-label")
        status_box = Adw.ActionRow(title="Status")
        status_box.add_suffix(self.status_label)
        watcher_group.add(status_box)

        self.countdown_label = Gtk.Label(label="—")
        self.countdown_label.add_css_class("title-1")
        countdown_row = Adw.ActionRow(title="Time remaining")
        countdown_row.add_suffix(self.countdown_label)
        watcher_group.add(countdown_row)

        calibrate_button = Gtk.Button(label="Calibrate timer region…")
        calibrate_button.connect("clicked", self._on_calibrate_clicked)
        calibrate_row = Adw.ActionRow(title="Timer region", subtitle="You should recalibrate every time you change the window position or monitor of Umamusume")
        calibrate_row.add_suffix(calibrate_button)
        watcher_group.add(calibrate_row)

        if capture_backend(self.env) == CaptureBackend.PORTAL:
            change_monitor_button = Gtk.Button(label="Change capture monitor…")
            change_monitor_button.connect("clicked", self._on_change_monitor_clicked)
            change_monitor_row = Adw.ActionRow(title="Capture monitor")
            change_monitor_row.add_suffix(change_monitor_button)
            watcher_group.add(change_monitor_row)

        # -- carat tracking --
        carat_group = Adw.PreferencesGroup(title="Carat Tracking")
        root_box.append(carat_group)

        self.carat_total_label = Gtk.Label(label=self._carat_label_text())
        self.carat_total_label.add_css_class("title-1")
        total_row = Adw.ActionRow(title="Today's total")
        total_row.add_suffix(self.carat_total_label)
        carat_group.add(total_row)

        capture_button = Gtk.Button(label="Capture carats from screen…")
        capture_button.connect("clicked", self._on_capture_carats_clicked)
        capture_row = Adw.ActionRow(title="Add a run")
        capture_row.add_suffix(capture_button)
        carat_group.add(capture_row)

        self.event_switch_row = Adw.SwitchRow(
            title="2x drop event", subtitle="Cap becomes 200 instead of 100"
        )
        self.event_switch_row.set_active(self.config.is_double_drop_event)
        self.event_switch_row.connect("notify::active", self._on_event_toggle)
        carat_group.add(self.event_switch_row)

        # -- notification/sound settings --
        settings_group = Adw.PreferencesGroup(title="Notification &amp; Sound")
        root_box.append(settings_group)

        self.notif_switch_row = Adw.SwitchRow(title="Desktop notifications")
        self.notif_switch_row.set_active(self.config.notifications_enabled)
        self.notif_switch_row.connect("notify::active", self._on_notif_toggle)
        settings_group.add(self.notif_switch_row)

        self.sound_switch_row = Adw.SwitchRow(title="Play sound")
        self.sound_switch_row.set_active(self.config.sound_enabled)
        self.sound_switch_row.connect("notify::active", self._on_sound_toggle)
        settings_group.add(self.sound_switch_row)

        self.sound_preview_button = Gtk.Button(icon_name="media-playback-start-symbolic")
        self.sound_preview_button.set_tooltip_text("Preview selected sound")
        self.sound_preview_button.connect("clicked", self._on_sound_preview_toggled)
        self.sound_switch_row.add_suffix(self.sound_preview_button)

        volume_row = Adw.ActionRow(title="Volume")
        self.volume_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
        self.volume_scale.set_range(0, 100)
        self.volume_scale.set_value(self.config.sound_volume * 100)
        self.volume_scale.set_size_request(150, -1)
        self.volume_scale.set_draw_value(True)
        self.volume_scale.connect("value-changed", self._on_volume_changed)
        volume_row.add_suffix(self.volume_scale)
        settings_group.add(volume_row)

        self._build_sound_radio_group(settings_group)

        # -- debug --
        debug_group = Adw.PreferencesGroup(title="Debug")
        root_box.append(debug_group)

        debug_button = Gtk.Button(label="Trigger completion now (DEBUG)")
        debug_button.add_css_class("destructive-action")
        debug_button.connect("clicked", self._on_debug_trigger_completion)
        debug_row = Adw.ActionRow(title="Debug")
        debug_row.add_suffix(debug_button)
        debug_group.add(debug_row)

        if capture_backend(self.env) == CaptureBackend.PORTAL:
            from wei_timer.portal_screencast import get_watcher_capture_fn
            watcher_capture_fn = get_watcher_capture_fn()
        else:
            watcher_capture_fn = capture_region

        # -- background watcher --
        self.watcher = Watcher(
            config=self.config,
            env=self.env,
            capture_region_fn=watcher_capture_fn,
            on_timer_complete=self._on_timer_complete_background_thread,
            on_status_change=self._on_status_change_background_thread,
        )
        self.watcher.start()

        import subprocess, threading

        tray_script = str(Path(__file__).resolve().parent / "tray_helper.py")
        self._tray_process = subprocess.Popen(
            [sys.executable, tray_script],
            stdout=subprocess.PIPE, stdin=subprocess.PIPE, text=True,
        )
        threading.Thread(target=self._read_tray_commands, daemon=True).start()

        # update the countdown label every second on the UI thread,
        # independent of the watcher's own status callbacks
        GLib.timeout_add_seconds(1, self._tick_countdown_display)

        self._local_deadline_mirror = None  # set from status callback

        self.connect("close-request", self._on_close_request)

    # -- helpers ---------------------------------------------------------

    def _on_change_monitor_clicked(self, _button) -> None:
        from wei_timer.portal_screencast import reset_session, get_shared_session
        reset_session()
        try:
            get_shared_session()  # forces the portal's monitor picker right now
            self.toast_overlay.add_toast(Adw.Toast(title="Capture monitor updated"))
        except Exception as e:
            self.toast_overlay.add_toast(Adw.Toast(title=f"Monitor switch failed: {e}"))

    def _read_tray_commands(self) -> None:
        for line in self._tray_process.stdout:
            action = line.strip()
            GLib.idle_add(self._handle_tray_action, action)

    def _write_tray_timer(self, text: str) -> None:
        if self._tray_process.poll() is not None:
            return  # helper already exited, nothing to write to
        try:
            self._tray_process.stdin.write(f"settext:{text}\n")
            self._tray_process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _handle_tray_action(self, action: str) -> bool:
        if action == "capture_carats":
            self.present()
            self._on_capture_carats_clicked(None)
        elif action == "calibrate":
            self.present()
            self._on_calibrate_clicked(None)
        elif action == "force_complete":
            self.watcher.cancel_timer()
            self._apply_timer_complete()
        elif action == "open":
            self.present()
        elif action == "exit":
            self._tray_process.terminate()
            self.watcher.stop()
            try:
                from wei_timer.portal_screencast import stop_shared_session
                stop_shared_session()
            except ImportError:
                pass
            self.app.quit()
        return False

    def _on_volume_changed(self, scale: Gtk.Scale) -> None:
        self.config.sound_volume = scale.get_value() / 100.0
        save_config(self.config)

    def _on_sound_preview_toggled(self, _button) -> None:
        if is_playing():
            stop_sound()
            self.sound_preview_button.set_icon_name("media-playback-start-symbolic")
        else:
            played = play_sound(self.config.resolved_sound_path(), self.config.sound_volume)
            if played:
                self.sound_preview_button.set_icon_name("media-playback-stop-symbolic")
                GLib.timeout_add(500, self._check_preview_finished)
            else:
                self.toast_overlay.add_toast(Adw.Toast(title="Nothing played — check the file exists / a sound backend is installed"))

    def _check_preview_finished(self) -> bool:
        if is_playing():
            return True  # keep polling
        self.sound_preview_button.set_icon_name("media-playback-start-symbolic")
        return False  # stop polling

    def _on_debug_trigger_completion(self, _button) -> None:
        self.watcher.cancel_timer()
        self._apply_timer_complete()

    def _carat_label_text(self) -> str:
        return f"{self.config.carat_log.today_total()}/{self.config.carat_cap}"

    def _wrap_scrollable(self, box: Gtk.Box) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(box)
        return scroller

    def _banner_text(self) -> str:
        return (
            f"Focus detection unavailable on this window manager "
            f"({self.env.identity}) — autorun detection will run on "
            f"process presence only, which may poll more than necessary."
        )

    def _build_sound_radio_group(self, settings_group: Adw.PreferencesGroup) -> None:
        self._sound_radio_buttons = {}
        first_button = None
        for key in SOUND_ORDER:
            row = Adw.ActionRow(title=SOUND_LABELS[key])
            check = Gtk.CheckButton()
            if first_button is None:
                first_button = check
            else:
                check.set_group(first_button)
            check.set_active(self.config.sound_choice == key)
            check.connect("toggled", self._on_sound_choice_toggled, key)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self._sound_radio_buttons[key] = check
            settings_group.add(row)

        # custom sound option
        custom_row = Adw.ActionRow(title="Custom…")
        self._custom_check = Gtk.CheckButton()
        self._custom_check.set_group(first_button)
        self._custom_check.set_active(self.config.sound_choice == "custom")
        self._custom_check.connect("toggled", self._on_sound_choice_toggled, "custom")
        custom_row.add_prefix(self._custom_check)

        self._custom_path_entry = Gtk.Entry()
        self._custom_path_entry.set_placeholder_text("/path/to/sound.ogg")
        if self.config.custom_sound_path:
            self._custom_path_entry.set_text(self.config.custom_sound_path)
        self._custom_path_entry.connect("changed", self._on_custom_path_changed)
        custom_row.add_suffix(self._custom_path_entry)
        browse_button = Gtk.Button(label="Browse…")
        browse_button.connect("clicked", self._on_browse_custom_sound)
        custom_row.add_suffix(browse_button)
        settings_group.add(custom_row)

    # -- watcher callbacks (fire on background thread) -------------------

    def _on_status_change_background_thread(self, status: WatcherStatus) -> None:
        GLib.idle_add(self._apply_status, status)

    def _on_timer_complete_background_thread(self) -> None:
        GLib.idle_add(self._apply_timer_complete)

    # -- UI-thread handlers ------------------------------------------------

    def _on_browse_custom_sound(self, _button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose a sound file")

        audio_filter = Gtk.FileFilter()
        audio_filter.set_name("Audio files")
        for mime in ("audio/ogg", "audio/wav", "audio/mpeg"):
            audio_filter.add_mime_type(mime)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(audio_filter)
        dialog.set_filters(filters)

        def on_finish(dlg, result):
            try:
                file = dlg.open_finish(result)
            except GLib.Error:
                return  # cancelled, or no portal backend -- text entry still works manually
            path = file.get_path() if file else None
            if path:
                self._custom_check.set_active(True)
                self._custom_path_entry.set_text(path)

        dialog.open(self, None, on_finish)

    def _apply_status(self, status: WatcherStatus) -> bool:
        labels = {
            WatcherState.DISABLED: "Watcher disabled",
            WatcherState.TIMER_ACTIVE: "Autorun timer active",
            WatcherState.GAME_NOT_RUNNING: "Game not running",
            WatcherState.GAME_UNFOCUSED: "Game running (not focused)",
            WatcherState.WATCHING: "Watching for autorun…",
        }
        self.status_label.set_label(labels.get(status.state, "—"))
        self._local_deadline_mirror = status.timer_remaining_seconds
        return False  # GLib.idle_add: don't repeat

    def _apply_timer_complete(self) -> bool:
        if self.config.notifications_enabled:
            try:
                send_notification(
                    self.app,
                    title="Autorun finished",
                    body="Your 50-minute autorun timer has ended.",
                )
            except Exception:
                pass
        if self.config.sound_enabled:
            play_sound(self.config.resolved_sound_path(), self.config.sound_volume)
        self.toast_overlay.add_toast(Adw.Toast(title="Autorun timer finished"))
        return False

    def _tick_countdown_display(self) -> bool:
        remaining = self._local_deadline_mirror
        if remaining is None:
            self.countdown_label.set_label("—")
            self._write_tray_timer("00:00")
        else:
            remaining = max(0, remaining)
            mins, secs = divmod(int(remaining), 60)
            text = f"{mins:02d}:{secs:02d}"
            self.countdown_label.set_label(text)
            self._write_tray_timer(text)
            self._local_deadline_mirror = max(0.0, remaining - 1)
        return True

    def _on_watcher_switch_toggled(self, row: Adw.SwitchRow, _pspec) -> None:
        self.config.watcher_enabled = row.get_active()
        save_config(self.config)

    def _on_event_toggle(self, row: Adw.SwitchRow, _pspec) -> None:
        self.config.is_double_drop_event = row.get_active()
        save_config(self.config)
        self.carat_total_label.set_label(self._carat_label_text())

    def _on_notif_toggle(self, row: Adw.SwitchRow, _pspec) -> None:
        self.config.notifications_enabled = row.get_active()
        save_config(self.config)

    def _on_sound_toggle(self, row: Adw.SwitchRow, _pspec) -> None:
        self.config.sound_enabled = row.get_active()
        save_config(self.config)

    def _on_sound_choice_toggled(self, button: Gtk.CheckButton, key: str) -> None:
        if not button.get_active():
            return
        self.config.sound_choice = key
        save_config(self.config)

    def _on_custom_path_changed(self, entry: Gtk.Entry) -> None:
        self.config.custom_sound_path = entry.get_text() or None
        if self.config.sound_choice == "custom":
            save_config(self.config)

    def _on_banner_dismiss(self, _banner: Adw.Banner) -> None:
        self.banner.set_revealed(False)
        self.config.banner_dismissed_for[self.env.identity] = True
        save_config(self.config)

    def _on_calibrate_clicked(self, _button: Gtk.Button) -> None:
        if capture_backend(self.env) == CaptureBackend.PORTAL:
            from wei_timer.portal_screencast import get_shared_session
            from wei_timer.portal_picker import select_region_from_image
            session = get_shared_session()
            frame = session.get_frame()
            if frame is None:
                self.toast_overlay.add_toast(Adw.Toast(title="No frame available yet, try again"))
                return
            matched_monitor = _find_matching_monitor(frame.size)
            geometry = select_region_from_image(frame, monitor=matched_monitor)
        else:
            try:
                from wei_timer.capture import select_region_interactively
                geometry = select_region_interactively()
            except CaptureError as e:
                self.toast_overlay.add_toast(Adw.Toast(title=f"Capture error: {e}"))
                return

        if geometry is None:
            return  # cancelled

        self.config.timer_region_geometry = geometry
        samples = []

        def collect_sample():
            try:
                if capture_backend(self.env) == CaptureBackend.PORTAL:
                    from wei_timer.portal_screencast import get_shared_session
                    frame = get_shared_session().get_cropped_frame(geometry)
                    samples.append(frame)
                else:
                    samples.append(capture_region(geometry))
            except Exception:
                pass
            if len(samples) < 4:
                GLib.timeout_add_seconds(1, collect_sample)
            else:
                self._finish_calibration(samples)
            return False

        self.toast_overlay.add_toast(
            Adw.Toast(title="Calibrating — keep the autorun timer visible for a few seconds…")
        )
        GLib.timeout_add_seconds(1, collect_sample)

    def _finish_calibration(self, samples) -> None:
        if not samples:
            self.toast_overlay.add_toast(Adw.Toast(title="Calibration failed — no frames captured"))
            return
        ref = ReferenceHash.calibrate(samples)
        self.config.timer_region_reference_hash = ref.hash_str
        self.config.timer_region_max_distance = ref.max_distance
        save_config(self.config)
        self.toast_overlay.add_toast(Adw.Toast(title="Timer region calibrated"))

    def _on_capture_carats_clicked(self, _button: Gtk.Button) -> None:
        try:
            img = capture_region_interactive()
        except CaptureError as e:
            self.toast_overlay.add_toast(Adw.Toast(title=f"Capture error: {e}"))
            return
        if img is None:
            return  # cancelled

        parsed = extract_carat_count(img)
        self._show_carat_confirm_dialog(parsed)

    def _show_carat_confirm_dialog(self, parsed_value) -> None:
        dialog = Adw.AlertDialog(
            heading="Confirm carat count",
            body="Edit if the OCR read it wrong, then confirm.",
        )
        entry = Gtk.Entry()
        entry.set_text(str(parsed_value) if parsed_value is not None else "")
        entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", "Add")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("confirm")

        def on_response(_dialog, response):
            if response != "confirm":
                return
            try:
                amount = int(entry.get_text().strip())
            except ValueError:
                self.toast_overlay.add_toast(Adw.Toast(title="Not a valid number"))
                return
            new_total = self.config.carat_log.add(amount)
            save_config(self.config)
            self.carat_total_label.set_label(self._carat_label_text())
            if new_total >= self.config.carat_cap:
                self.toast_overlay.add_toast(
                    Adw.Toast(title=f"Cap reached: {new_total}/{self.config.carat_cap} carats today")
                )

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_close_request(self, _window) -> bool:
        save_config(self.config)
        self.config.window_width, self.config.window_height = self.get_default_size()
        if not self.config.seen_minimize_notice:
            send_notification(
                self.app,
                title="Wei Timer is still running!",
                body="It's just hiding in the tray... Right-click the tray icon and choose Exit Wei Timer to fully close it.",
            )
            self.config.seen_minimize_notice = True
            save_config(self.config)
        self.hide()
        return True
