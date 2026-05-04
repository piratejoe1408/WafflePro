"""
FanTrigger - Diagnostic v2

What v1 missed:
  * v1 used the high-level `keyboard` Python package, which only exposes
    scan_code + name. We never saw the virtual key code (vkCode) or the
    event flags. That's why our first replay almost certainly sent the
    wrong "F3" key instead of the special MSI scancode.

What v2 does:
  PART A - 20-second capture using the Windows low-level keyboard hook
  directly via ctypes. Logs the FULL event struct (vkCode, scanCode,
  flags including EXTENDED and INJECTED) for every key press.

  PART B - Replays the captured FN+UpArrow event back at the system
  using SIX different strategies. Listen to the fans after each one and
  tell us which (if any) tripped Cooler Boost.

Run via "Run Diagnostic V2.bat" (which handles admin elevation + deps).
Output goes to diagnostic_v2_results.log next to this script.
"""

import os
import sys
import time
import datetime
import threading
import ctypes
from ctypes import wintypes
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "diagnostic_v2_results.log"

# ============================================================
#  Logging
# ============================================================
_lock = threading.Lock()

def log(msg=""):
    with _lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
        try:
            print(msg, flush=True)
        except Exception:
            pass


# ============================================================
#  Windows constants and structs
# ============================================================
WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_SYSKEYDOWN  = 0x0104
WM_SYSKEYUP    = 0x0105

LLKHF_EXTENDED          = 0x01
LLKHF_LOWER_IL_INJECTED = 0x02
LLKHF_INJECTED          = 0x10
LLKHF_ALTDOWN           = 0x20
LLKHF_UP                = 0x80

INPUT_KEYBOARD          = 1
KEYEVENTF_EXTENDEDKEY   = 0x0001
KEYEVENTF_KEYUP         = 0x0002
KEYEVENTF_SCANCODE      = 0x0008


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      wintypes.DWORD),
        ("scanCode",    wintypes.DWORD),
        ("flags",       wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         wintypes.WORD),
        ("wScan",       wintypes.WORD),
        ("dwFlags",     wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_ubyte * 32)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


LRESULT  = ctypes.c_long
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.SetWindowsHookExW.restype  = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype     = LRESULT
user32.CallNextHookEx.argtypes    = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.restype  = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]


# ============================================================
#  Capture state
# ============================================================
captured_events = []   # list of (timestamp, wParam, vkCode, scanCode, flags)
fn_up_candidates = []  # (vkCode, scanCode, flags) for scan_code 61 key-down only
_capture_active = True


def flags_label(f):
    parts = []
    if f & LLKHF_EXTENDED:          parts.append("EXT")
    if f & LLKHF_INJECTED:          parts.append("INJ")
    if f & LLKHF_LOWER_IL_INJECTED: parts.append("LOW_INJ")
    if f & LLKHF_ALTDOWN:           parts.append("ALT")
    if f & LLKHF_UP:                parts.append("UP")
    return "|".join(parts) if parts else "-"


def hook_proc(nCode, wParam, lParam):
    if nCode == 0 and _capture_active:
        kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT))[0]
        is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        evt_label = "DOWN" if is_down else "UP  "
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log(f"  {ts}  {evt_label}  "
            f"vk=0x{kbd.vkCode:02X} ({kbd.vkCode:>3d})  "
            f"scan=0x{kbd.scanCode:02X} ({kbd.scanCode:>3d})  "
            f"flags=0x{kbd.flags:02X} [{flags_label(kbd.flags)}]")
        captured_events.append((ts, wParam, kbd.vkCode, kbd.scanCode, kbd.flags))
        # Track candidate FN+UP events: scan_code 61, key down, NOT injected
        if is_down and kbd.scanCode == 61 and not (kbd.flags & LLKHF_INJECTED):
            fn_up_candidates.append((kbd.vkCode, kbd.scanCode, kbd.flags))
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


HOOK_PROC_REF = HOOKPROC(hook_proc)
_hook_id_holder = []


def hook_thread_main(stop_event):
    """Run the keyboard hook + message pump on a dedicated thread."""
    hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, HOOK_PROC_REF, None, 0)
    if not hook_id:
        log(f"!! SetWindowsHookExW failed; GetLastError={kernel32.GetLastError()}")
        return
    _hook_id_holder.append(hook_id)
    msg = wintypes.MSG()
    while not stop_event.is_set():
        # PM_REMOVE = 1
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)
    user32.UnhookWindowsHookEx(hook_id)
    _hook_id_holder.clear()


# ============================================================
#  Replay helpers
# ============================================================
def _make_kbd_input(vk, scan, flags):
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def _send_pair(vk, scan, base_flags):
    arr = (_INPUT * 2)()
    arr[0] = _make_kbd_input(vk, scan, base_flags)
    arr[1] = _make_kbd_input(vk, scan, base_flags | KEYEVENTF_KEYUP)
    return user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(_INPUT))


def attempt(label, vk, scan, base_flags, use_keybd_event=False):
    log("")
    log(f">>> Attempt: {label}")
    log(f"    vk=0x{vk:02X}, scan=0x{scan:02X}, base_flags=0x{base_flags:02X}, legacy={use_keybd_event}")
    log("    Sending in 3 seconds — focus is irrelevant for SendInput, just listen.")
    for i in (3, 2, 1):
        log(f"      {i}...")
        time.sleep(1)

    if use_keybd_event:
        # legacy keybd_event API
        flags_down = 0
        flags_up   = KEYEVENTF_KEYUP
        if base_flags & KEYEVENTF_EXTENDEDKEY:
            flags_down |= KEYEVENTF_EXTENDEDKEY
            flags_up   |= KEYEVENTF_EXTENDEDKEY
        user32.keybd_event(vk, scan, flags_down, 0)
        user32.keybd_event(vk, scan, flags_up,   0)
        log(f"    keybd_event sent.")
    else:
        n = _send_pair(vk, scan, base_flags)
        log(f"    SendInput returned {n} (expected 2).")

    log("    -- Listen now: did the fans react? Wait 4 seconds then next attempt.")
    time.sleep(4)


# ============================================================
#  Main
# ============================================================
def countdown(secs, msg):
    for i in range(secs, 0, -1):
        print(f"\r  {msg}: {i}s ", end="", flush=True)
        time.sleep(1)
    print()


def main():
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    log("=" * 72)
    log("  FanTrigger DIAGNOSTIC v2 - full hook capture + replay")
    log("=" * 72)
    log(f"Started: {datetime.datetime.now().isoformat()}")
    log(f"Python:  {sys.version.split()[0]}")
    log(f"Script:  {Path(__file__).resolve()}")
    log("")

    # Start hook thread early
    stop_event = threading.Event()
    hook_thread = threading.Thread(target=hook_thread_main, args=(stop_event,), daemon=True)
    hook_thread.start()
    time.sleep(0.5)
    if not _hook_id_holder:
        log("!! Hook failed to install. Are you running as Administrator?")
        input("Press Enter to close.")
        return

    # ---- PART A: capture ----
    log("=" * 72)
    log("  PART A - 20 second capture")
    log("=" * 72)
    log("")
    log("WHAT TO DO:")
    log("  1. Press FN + UpArrow about 4 times, slowly. The fans should")
    log("     toggle each time (loud/quiet). VERIFY this with your ears -")
    log("     this confirms the hand-press actually controls Cooler Boost.")
    log("  2. Then press UpArrow alone twice.")
    log("  3. Then press Spacebar once.")
    log("  4. Wait for the timer.")
    log("")
    log("Capture starts in 5 seconds...")
    time.sleep(5)
    log("")
    log("--- CAPTURING (20s) ---")

    countdown(20, "capturing")
    log("--- CAPTURE DONE ---")
    log("")
    log(f"Captured {len(captured_events)} events total.")
    log(f"Found {len(fn_up_candidates)} REAL (non-injected) FN+UP candidates.")
    log("")

    if not fn_up_candidates:
        log("!! No real FN+UP events were captured.")
        log("   Either FN+UpArrow doesn't reach Windows on this system,")
        log("   or you didn't press it during the capture window.")
        log("   Aborting replay phase.")
        input("Press Enter to close.")
        stop_event.set()
        return

    # Pick the most common (vk, scan, flags) tuple as our template
    from collections import Counter
    counter = Counter(fn_up_candidates)
    template, count = counter.most_common(1)[0]
    vk_real, scan_real, flags_real = template
    extended_real = bool(flags_real & LLKHF_EXTENDED)

    log(f"Most common FN+UP template ({count} of {len(fn_up_candidates)} matches):")
    log(f"    vkCode   = 0x{vk_real:02X} ({vk_real})")
    log(f"    scanCode = 0x{scan_real:02X} ({scan_real})")
    log(f"    flags    = 0x{flags_real:02X} [{flags_label(flags_real)}]")
    log(f"    extended = {extended_real}")
    log("")

    # ---- PART B: replay ----
    log("=" * 72)
    log("  PART B - Replay attempts")
    log("=" * 72)
    log("")
    log("We'll try SIX injection methods. After each, fans should react if")
    log("MSI Center accepted that injection. The hook will also record the")
    log("injected event (you'll see lines with [INJ] flag in the log).")
    log("")
    log("Starting in 5 seconds...")
    time.sleep(5)

    base_ext = KEYEVENTF_EXTENDEDKEY if extended_real else 0

    # 1. Match captured EXACTLY: scan-code only, with extended flag matching capture
    attempt("1. scan-code only, EXTENDED matching capture",
            vk=0, scan=scan_real,
            base_flags=KEYEVENTF_SCANCODE | base_ext)

    # 2. scan-code only, NO extended flag
    attempt("2. scan-code only, no EXTENDED flag",
            vk=0, scan=scan_real,
            base_flags=KEYEVENTF_SCANCODE)

    # 3. scan-code only, FORCE extended flag
    attempt("3. scan-code only, FORCE EXTENDED flag",
            vk=0, scan=scan_real,
            base_flags=KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY)

    # 4. vk + scan together, no EXTENDED
    attempt("4. vk + scan together, no EXTENDED",
            vk=vk_real, scan=scan_real,
            base_flags=0)

    # 5. vk + scan together, with EXTENDED matching capture
    attempt("5. vk + scan together, EXTENDED matching capture",
            vk=vk_real, scan=scan_real,
            base_flags=base_ext)

    # 6. legacy keybd_event with vk + scan
    attempt("6. legacy keybd_event with vk + scan",
            vk=vk_real, scan=scan_real,
            base_flags=base_ext, use_keybd_event=True)

    # ---- finish ----
    log("")
    log("=" * 72)
    log("  DONE")
    log("=" * 72)
    log("")
    log("Tell the assistant which attempt(s) (1..6) made the fans react.")
    log("If NONE worked, that means MSI Center is filtering out injected")
    log("events (LLKHF_INJECTED flag) and we'll need plan B (writing the")
    log("Cooler Boost bit directly to the embedded controller via the")
    log("WinRing0 driver that LibreHardwareMonitor already includes).")
    log("")
    log(f"Send back: {LOG_FILE.name}")
    log("")

    stop_event.set()
    hook_thread.join(timeout=2)

    print()
    print("Press Enter to close.")
    try:
        input()
    except EOFError:
        pass


if __name__ == "__main__":
    main()
