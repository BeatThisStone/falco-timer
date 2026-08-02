# Falco Timer

![Wei Timer logo](packaging/wei-timer.png)

A GTK4 based independent training timer detector and daily carat tracker for Umamusume for Wayland and X11.

The name Falco Timer (weitimer) comes from a portmaneau of "way" as in wayland and "wei", something a certain gen Z uma loves saying.

## What it does

- Watches for the in-game autorun timer box to appear on screen (using perceptual image hashing) and starts a 50-minute countdown when it does, notifying you and playing a sound when it ends.
- Watching is gated behind whether Umamusume is even running, and, where your compositor supports it, whether it's focused, so there's near-zero overhead the rest of the time.
- Lets you drag-select the carat-count region on the results screen after a run, OCRs the number, and tracks a running daily total against a configurable cap (100 normally, 200 during a 2x drop event).

## Installation

### Arch

Clone this repo and then cd into it:
```bash
git clone https://github.com/lunauii/wei-timer.git
cd wei-timer
```

Then build the package from the included `PKGBUILD`:

```bash
makepkg -si
```

To update, you just have to pull the repo and rebuild the package:

```bash
git pull
rm -rf src pkg && makepkg -sif
```

### Linux (universal)

**AppImage**

Download `Wei_Timer-x.y.z-x86_64.AppImage` from the [latest release](https://github.com/lunauii/wei-timer/releases/latest) and run it.

**pip (recommended)**

Install `gtk4`, `libadwaita`, `python-gobject` (or your distro's equivalent, e.g. `libgtk-4-dev`/`gir1.2-adw-1` on Debian/Ubuntu, `gtk4-devel` on Fedora), `tesseract` with English language data, and `grim`+`slurp` via your distro's package manager.

Then clone this repo and hook into a virtual environment and install the remaining packages:

```bash
git clone https://github.com/lunauii/wei-timer.git
cd wei-timer
python -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e .
```

Finally, run it by calling it:
```bash
wei-timer
```

### Windows
See the [.NET port](https://github.com/lunauii/wei-timer-dotnet).

## First-run setup

1. **Timer region calibration**: click "Calibrate timer region..." in the app while the autorun timer's container is visible, then select something static like the Time Left area.

![Calibration Region](calibration.png)

After this, just make sure you wait until you see what you calibrated it to before unfocusing from the game.

2. **Process and window matching**: the default process name is `UmamusumePrettyDerby.exe`, matching the actual exe under GE-Proton. If your setup differs, find the real process name with:
   ```bash
   ps aux | grep -i uma
   ```
   and update `game_process_name` in the config file to match. Config lives at `$XDG_CONFIG_HOME/wei-timer/config.json` (`~/.config/wei-timer/config.json` by default).

## Tray icon

Closing the window doesn't quit Wei Timer, it minimizes to the system tray, and the watcher keeps running in the background. The first time you do this, a notification explains it; after that it's silent.

To bring the window back, click **Open** in the tray menu, or just relaunch `wei-timer` (it re-presents the existing window rather than starting a second instance).

A live countdown also shows at the top of the menu whenever a timer's running.

Requires a tray host that implements the StatusNotifierItem protocol. Most modern bars/shells support this (including Noctalia, KDE Plasma, and most others with a tray widget enabled); if yours doesn't, the tray icon just won't appear, everything else in the app still works normally, minimize-to-tray included, you'd just use the in-app buttons instead of the tray menu.


## Scope and known edge cases

- **No game-input automation anywhere**. This is *not* an auto-runner script. Wei Timer only serves to automate setting a timer and counting your daily carats.
- **Not tested for GNOME**. While theoretically possible on paper with Screenshot Portal implementation tested on KDE Plasma, actual GNOME testing hasn't been carried out.

## Project layout

```
wei_timer/
  __init__.py           - package init
  __main__.py           - entry point for `python -m wei_timer`
  config.py             - persisted app state (JSON)
  compositor.py         - X11/Wayland and compositor detection
  focus.py              - process presence and window focus checks
  capture.py            - grim/slurp/scrot/slop screen capture (wlroots + X11 backends)
  portal_capture.py     - one-shot Screenshot portal capture (GNOME/Plasma Wayland)
  portal_picker.py      - in-app drag-select overlay for the portal backend
  portal_screencast.py  - ScreenCast + PipeWire live capture for the watcher (GNOME/Plasma Wayland)
  detect.py             - perceptual-hash autorun-box presence detection
  tray_helper.py        - GTK3/AppIndicator subprocess for the system tray icon
  ocr.py                - tesseract-based carat count parsing
  sound.py              - pw-play/paplay/aplay fallback playback with volume and stop control
  notify.py             - Gio.Notification desktop notifications
  watcher.py            - the core state machine
  window.py             - GTK4/libadwaita UI
  app.py                - application entry point
```

## Attribution and AI Notice

Default notification SFX by [Universfield](https://pixabay.com/users/universfield-28281460/?utm_source=link-attribution&utm_medium=referral&utm_campaign=music&utm_content=493469) from [Pixabay](https://pixabay.com/sound-effects//?utm_source=link-attribution&utm_medium=referral&utm_campaign=music&utm_content=493469) \
Metal pipe SFX: origin unconfirmed \
Harikitte Ikou SFX: sourced from Umamusume

This project's development was heavily assisted by a local LLM (Qwen3.5-9B) and Claude Sonnet 5 through OpenClaw and Claude Code.
