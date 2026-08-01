"""
In-app drag-select overlay for the portal capture backend.

The Screenshot portal doesn't guarantee interactive region selection
(that's compositor-implementation-dependent, not part of the spec), so
we take one full-screen shot and let the user drag-select within it
here, inside the app. This keeps timer_region_geometry meaning the same
thing (an absolute pixel rect) across every backend.

"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
from PIL import Image


def select_region_from_image(image: Image.Image, monitor: Optional[Gdk.Monitor] = None) -> Optional[str]:
    """Blocks via a nested GLib main loop until the user finishes a
    drag-select or presses Escape. Returns 'X,Y WxH' or None if cancelled."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    image.save(tmp_path)
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    img_w, img_h = pixbuf.get_width(), pixbuf.get_height()
    state = {"start": None, "current": None, "result": None, "cancelled": False}
    loop = GLib.MainLoop()

    window = Gtk.Window()
    window.set_decorated(False)
    if monitor is not None:
        window.fullscreen_on_monitor(monitor)
    else:
        window.fullscreen()

    area = Gtk.DrawingArea()
    area.set_content_width(img_w)
    area.set_content_height(img_h)

    def on_draw(_area, cr, _width, _height, _data=None):
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()

        # dark scrim over the whole screenshot, so it's visually obvious
        # you're in selection mode rather than looking at a frozen screen
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.rectangle(0, 0, img_w, img_h)
        cr.fill()

        if state["start"] and state["current"]:
            x0, y0 = state["start"]
            x1, y1 = state["current"]
            x, y = min(x0, x1), min(y0, y1)
            w, h = abs(x1 - x0), abs(y1 - y0)

            # punch a clear "hole" back through the scrim for the selected area,
            # so the region you're actually picking looks bright/normal again
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint()
            cr.restore()

            cr.set_source_rgba(0.3, 0.6, 1.0, 0.95)
            cr.set_line_width(2)
            cr.rectangle(x, y, w, h)
            cr.stroke()

    area.set_draw_func(on_draw)

    drag = Gtk.GestureDrag()

    def on_drag_begin(_gesture, x, y):
        state["start"] = (x, y)
        state["current"] = (x, y)
        area.queue_draw()

    def on_drag_update(gesture, offset_x, offset_y):
        ok, start_x, start_y = gesture.get_start_point()
        if ok:
            state["current"] = (start_x + offset_x, start_y + offset_y)
            area.queue_draw()

    def on_drag_end(gesture, offset_x, offset_y):
        ok, start_x, start_y = gesture.get_start_point()
        if not ok or state["start"] is None:
            loop.quit()
            return
        x0, y0 = state["start"]
        x1, y1 = start_x + offset_x, start_y + offset_y
        x, y = int(min(x0, x1)), int(min(y0, y1))
        w, h = int(abs(x1 - x0)), int(abs(y1 - y0))
        if w > 2 and h > 2:
            state["result"] = f"{x},{y} {w}x{h}"
        loop.quit()

    drag.connect("drag-begin", on_drag_begin)
    drag.connect("drag-update", on_drag_update)
    drag.connect("drag-end", on_drag_end)
    area.add_controller(drag)

    key_controller = Gtk.EventControllerKey()

    def on_key_pressed(_controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            state["cancelled"] = True
            loop.quit()
            return True
        return False

    key_controller.connect("key-pressed", on_key_pressed)
    window.add_controller(key_controller)

    overlay = Gtk.Overlay()
    overlay.set_child(area)

    hint_label = Gtk.Label(label="Drag to select the timer region  •  Esc to cancel")
    hint_label.add_css_class("title-2")
    hint_label.set_valign(Gtk.Align.START)
    hint_label.set_margin_top(24)
    hint_label.add_css_class("osd")  # libadwaita's on-screen-display style, readable over imagery
    overlay.add_overlay(hint_label)

    window.set_child(overlay)

    window.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
    window.present()
    loop.run()
    window.destroy()

    return None if state["cancelled"] else state["result"]