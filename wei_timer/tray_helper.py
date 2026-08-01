import sys
import gi
import os
from pathlib import Path

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator3

timer_item = None

def emit(action: str) -> None:
    try:
        print(action, flush=True)
    except BrokenPipeError:
        Gtk.main_quit()

def build_menu() -> Gtk.Menu:
    global timer_item
    menu = Gtk.Menu()

    def add_item(label, action):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _i: emit(action))
        menu.append(item)

    timer_item = Gtk.MenuItem(label="Timer: not running")
    timer_item.set_sensitive(False)
    menu.append(timer_item)

    menu.append(Gtk.SeparatorMenuItem())

    add_item("Open", "open")
    add_item("Capture carats from screen", "capture_carats")
    add_item("Calibrate timer region", "calibrate")
    add_item("Force completion trigger", "force_complete")
    
    menu.append(Gtk.SeparatorMenuItem())
    add_item("Exit Wei Timer", "exit")

    menu.show_all()
    return menu


def _update_timer_label(text: str) -> bool:
    if timer_item is not None:
        timer_item.set_label(text)
    return False


def _read_stdin_commands() -> bool:
    line = sys.stdin.readline()
    if not line:
        Gtk.main_quit()
        return False
    line = line.strip()
    if line.startswith("settext:"):
        GLib.idle_add(_update_timer_label, line[len("settext:"):])
    return True

def _find_icon_path() -> str:
    candidates = []
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(Path(appdir) / "usr/share/icons/hicolor/256x256/apps/wei-timer.png")
    candidates.append(Path("/usr/share/icons/hicolor/256x256/apps/wei-timer.png"))
    candidates.append(Path(__file__).resolve().parent.parent / "packaging" / "wei-timer.png")
    for path in candidates:
        if path.exists():
            return str(path)
    return "appointment-soon"  # stock fallback if nothing resolves


def main() -> None:
    icon_path = _find_icon_path()
    indicator = AppIndicator3.Indicator.new(
        "wei-timer", icon_path, AppIndicator3.IndicatorCategory.APPLICATION_STATUS
    )
    indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
    indicator.set_title("lunaui's Wei Timer")
    indicator.set_menu(build_menu())
    GLib.io_add_watch(sys.stdin, GLib.IO_IN, lambda *_: _read_stdin_commands())
    Gtk.main()
    
if __name__ == "__main__":
    main()