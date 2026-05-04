"""
FanTrigger - automatic Cooler Boost based on CPU temperature.

Background tray utility for the MSI Vector A16 HX A8WHG.

  - Polls CPU temperature via LibreHardwareMonitor.
  - When temperature crosses thresholds, writes the Cooler Boost bit
    DIRECTLY to embedded controller (EC) register 0x98 via the WinRing0
    driver bundled with LHM. No keyboard simulation, no MSI Center
    cooperation - we flip the same bit MSI Center flips.
  - Tray icon shows current CPU temp; right-click for the menu.

CONFIGURATION - edit the constants at the top if you want to change
thresholds or polling rate.
"""

# ============================================================
#  CONFIGURATION
# ============================================================
TEMP_TRIGGER_ON  = 90.0   # turn boost ON  when CPU temp >= this (C)
TEMP_TRIGGER_OFF = 80.0   # turn boost OFF when CPU temp <= this (C)
POLL_INTERVAL    = 2.0    # seconds between temperature readings
# ============================================================

import os
import sys
import time
import datetime
import threading
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "fan_trigger.log"

_log_lock = threading.Lock()


def log(msg):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    try:
        print(line, flush=True)
    except Exception:
        pass  # console may not exist when launched via pythonw.exe


# ============================================================
#  Single-instance lock (prevents two copies running)
# ============================================================
def acquire_single_instance_lock():
    import ctypes
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183
    handle = kernel32.CreateMutexW(None, False, "Local\\FanTriggerMutex_v2")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        log("Another FanTrigger instance is already running. Exiting.")
        sys.exit(0)
    return handle  # keep reference alive


# ============================================================
#  Monitoring loop with hysteresis
# ============================================================
class Monitor:
    def __init__(self, bridge):
        from ec_control import get_cooler_boost
        self.bridge = bridge
        # Read REAL state at startup - no more "assumed" state guessing
        try:
            self.boost_on = get_cooler_boost(bridge)
        except Exception:
            log(f"Failed to read initial boost state: {traceback.format_exc()}")
            self.boost_on = False
        log(f"Initial Cooler Boost state (read from EC): "
            f"{'ON' if self.boost_on else 'OFF'}")
        self.paused = False
        self.current_temp = None
        self.running = True
        self._lock = threading.Lock()

    def loop(self):
        from ec_control import set_cooler_boost, get_cooler_boost
        log("Monitor loop started.")
        while self.running:
            try:
                if not self.paused:
                    t = self.bridge.read_max_cpu_temp()
                    with self._lock:
                        self.current_temp = t

                    # Re-sync our cached state with reality every poll. Cheap and
                    # eliminates drift if the user hits FN+UpArrow themselves.
                    try:
                        actual = get_cooler_boost(self.bridge)
                        if actual != self.boost_on:
                            log(f"External boost change detected (now {'ON' if actual else 'OFF'}).")
                            self.boost_on = actual
                    except Exception:
                        pass

                    if t is not None:
                        if (not self.boost_on) and t >= TEMP_TRIGGER_ON:
                            log(f"Temp {t:.1f}C >= {TEMP_TRIGGER_ON}C - turning boost ON.")
                            try:
                                wrote = set_cooler_boost(self.bridge, True)
                                log(f"  EC[0x98] <- 0x{wrote:02X}")
                                self.boost_on = True
                            except Exception:
                                log(f"  EC write failed: {traceback.format_exc()}")
                        elif self.boost_on and t <= TEMP_TRIGGER_OFF:
                            log(f"Temp {t:.1f}C <= {TEMP_TRIGGER_OFF}C - turning boost OFF.")
                            try:
                                wrote = set_cooler_boost(self.bridge, False)
                                log(f"  EC[0x98] <- 0x{wrote:02X}")
                                self.boost_on = False
                            except Exception:
                                log(f"  EC write failed: {traceback.format_exc()}")
            except Exception:
                log(f"Monitor error: {traceback.format_exc()}")
            # sleep in small chunks for fast shutdown
            for _ in range(int(POLL_INTERVAL * 10)):
                if not self.running:
                    break
                time.sleep(0.1)
        log("Monitor loop stopped.")

    def manual_toggle(self):
        from ec_control import set_cooler_boost, get_cooler_boost
        log("User pressed Manual Toggle.")
        try:
            current = get_cooler_boost(self.bridge)
            wrote = set_cooler_boost(self.bridge, not current)
            log(f"  toggled boost {'ON' if not current else 'OFF'} (wrote 0x{wrote:02X})")
            self.boost_on = not current
        except Exception:
            log(f"  EC manual toggle failed: {traceback.format_exc()}")


# ============================================================
#  Tray icon image
# ============================================================
def _make_icon_image(temp, boost_on):
    from PIL import Image, ImageDraw, ImageFont
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if temp is None:
        bg = (110, 110, 110, 255)
    elif temp >= TEMP_TRIGGER_ON:
        bg = (200, 50, 50, 255)
    elif temp >= TEMP_TRIGGER_OFF:
        bg = (210, 145, 40, 255)
    else:
        bg = (50, 140, 60, 255)
    draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=12, fill=bg)
    if boost_on:
        draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=12,
                               outline=(255, 230, 0, 255), width=4)
    txt = f"{int(round(temp))}" if temp is not None else "??"
    font = None
    for fname in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(fname, 36)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 2),
              txt, fill=(255, 255, 255, 255), font=font)
    return img


# ============================================================
#  Main
# ============================================================
def main():
    acquire_single_instance_lock()
    log("=" * 60)
    log("FanTrigger starting up.")
    log(f"Thresholds: ON >= {TEMP_TRIGGER_ON}C, OFF <= {TEMP_TRIGGER_OFF}C")
    log(f"Poll interval: {POLL_INTERVAL}s")
    log("Control method: direct EC write to register 0x98 (bit 7).")

    try:
        from ec_control import LhmBridge
        bridge = LhmBridge()
    except Exception:
        log(f"FATAL: failed to init LHM/Ring0 bridge:\n{traceback.format_exc()}")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "FanTrigger could not initialize the embedded controller bridge.\n\n"
                "Most likely it wasn't started as Administrator.\n"
                "Right-click 'Run FanTrigger.bat' and choose 'Run as administrator'.\n\n"
                "Full error is in fan_trigger.log",
                "FanTrigger - startup error",
                0x10
            )
        except Exception:
            pass
        return

    log(f"LHM ready. CPU: {bridge.cpu_name}")

    monitor = Monitor(bridge)
    threading.Thread(target=monitor.loop, daemon=True).start()

    from pystray import Icon, Menu, MenuItem

    def _title():
        with monitor._lock:
            t = monitor.current_temp
        ts = f"{t:.0f}C" if t is not None else "?"
        boost = "ON" if monitor.boost_on else "OFF"
        suffix = " (paused)" if monitor.paused else ""
        return f"FanTrigger | CPU {ts} | Boost {boost}{suffix}"

    def on_pause(icon, item):
        monitor.paused = not monitor.paused
        log(f"Monitoring paused: {monitor.paused}")

    def on_manual_toggle(icon, item):
        monitor.manual_toggle()

    def on_open_log(icon, item):
        try:
            os.startfile(str(LOG_FILE))
        except Exception:
            pass

    def on_open_folder(icon, item):
        try:
            os.startfile(str(SCRIPT_DIR))
        except Exception:
            pass

    def on_exit(icon, item):
        log("User clicked Exit.")
        monitor.running = False
        time.sleep(0.6)
        bridge.close()
        icon.stop()

    icon = Icon(
        "FanTrigger",
        _make_icon_image(None, False),
        title=_title(),
        menu=Menu(
            MenuItem(lambda item: _title(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(lambda item: ("Resume monitoring" if monitor.paused
                                   else "Pause monitoring"),
                     on_pause),
            MenuItem("Toggle Cooler Boost now", on_manual_toggle),
            Menu.SEPARATOR,
            MenuItem("Open log file", on_open_log),
            MenuItem("Open FanTrigger folder", on_open_folder),
            Menu.SEPARATOR,
            MenuItem("Exit", on_exit),
        ),
    )

    def _icon_updater():
        while monitor.running:
            time.sleep(2.0)
            try:
                with monitor._lock:
                    t = monitor.current_temp
                icon.icon = _make_icon_image(t, monitor.boost_on)
                icon.title = _title()
            except Exception:
                pass

    threading.Thread(target=_icon_updater, daemon=True).start()

    log("Tray icon ready - right-click it for the menu.")
    icon.run()
    log("Tray loop ended. Goodbye.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log(f"Unhandled exception in main:\n{traceback.format_exc()}")
        raise
