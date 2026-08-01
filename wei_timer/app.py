"""
Application entry point.
"""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

APP_ID = "cc.lunaui.WeiTimer"


class WeiTimerApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.window = None

    def do_activate(self) -> None:
        from wei_timer.window import MainWindow
        from gi.repository import Adw

        if self.window is None:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            self.window = MainWindow(self)
        self.window.present()


def main() -> int:
    app = WeiTimerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
