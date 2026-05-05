# WafflePro

> *This utility is designed for your brand new MSI waffle maker! It will help turning it into a mostly functioning computer that can run perpetually.*

A very simple fan manager for MSI laptops. Turns max fan throttle ON at 90 °C and OFF at 80 °C, automatically. Designed on the **MSI Vector 16 HX A8WHG** — should work on most modern MSI laptops after some tuning.

Background tray utility for Windows. Watches your CPU temperature and writes the Cooler Boost bit directly to your laptop's embedded controller — same effect as pressing FN+UpArrow yourself, but automatic and silent. Plays nice with MSI Center.



---

## Why WafflePro exists

MSI laptops with AMD Ryzen processors can have CPU temperature spikes that the default MSI Center fan curve doesn't handle aggressively enough. MSI Center does have Cooler Boost (FN+UpArrow), but you have to press it yourself. WafflePro is the lazy person's solution: same button press, but the laptop pushes it for you.

The obvious approach — `SendInput`-style keystroke simulation — turned out to not work, because MSI Center filters out keyboard events that have the `LLKHF_INJECTED` flag (which Windows attaches to every software-injected event, and which is impossible to clear from user-mode). So WafflePro instead writes the Cooler Boost bit straight to the embedded controller — register `0x98`, bit 7 on this model — exactly the same bit MSI Center itself flips when it sees a real FN+UpArrow press.

---

## Compatibility

| | Status |
|---|---|
| MSI Vector 16 HX A8WHG (AMD Ryzen 9 8940HX) | ✅ tested, works |
| Other MSI laptops with FN+UpArrow Cooler Boost | ⚠️ probably works — run `Run EC Discover.bat` to confirm your EC layout |
| MSI desktops / non-MSI laptops | ❌ not supported |
| Windows 10 / 11 | ✅ |
| Linux / macOS | ❌ (Linux users: use [`isw`](https://github.com/YoyPa/isw) or the `msi-ec` kernel module) |

---

## Quick start

> **Whatever model you're on, always start with `Run EC Verify.bat`.** Reason: WafflePro's default Cooler Boost register address (`0x98`, bit `0x80`) was discovered on the Vector 16 HX A8WHG. Other MSI models can use a different EC layout. The verify tool is the safe, non-destructive way to find out which case you're in before the auto-trigger ever runs.

1. **Get the code.** Clone this repo or download as ZIP into a folder of your choice (e.g. `C:\Users\You\Documents\WafflePro`).

2. **Run the safety pre-flight.** Right-click **`Run EC Verify.bat`** → **Run as administrator**. It writes `0x83` to register `0x98`, waits 5 seconds, writes `0x03`, waits 5 more seconds, then restores the original value. **Listen with your ears.**

   The first run also installs Python (via `winget`) if you don't have it, plus three pip packages and one DLL — total ~50 MB, ~2 minutes. Subsequent runs are instant.

3. **Did the fans go LOUD then QUIET?**

   ### ✅ YES — your model uses the same register layout. You're done with setup.
   - Right-click **`Run FanTrigger.bat`** → **Run as administrator**. A colored icon appears in the tray showing your live CPU temperature.
   - *(Optional)* Right-click **`Install Autostart.bat`** → **Run as administrator** to launch WafflePro automatically at every login.
   - Skip the rest of this section.

   ### ❌ NO (or anything weird) — your model uses a different EC register. Don't run `Run FanTrigger.bat` yet — port it first:

   1. Right-click **`Run EC Discover.bat`** → **Run as administrator**.
   2. Follow the prompts: it snapshots EC RAM 4 times while **you press FN+UpArrow by hand** between each snapshot to physically toggle Cooler Boost. Use your ears to confirm boost actually toggles each time.
   3. When the analysis prints, look for a single **clean whole-byte candidate** where OFF and ON differ by exactly `0x80` (or another single power-of-two bit like `0x40`, `0x20`). That's your model's Cooler Boost register.
   4. Open **`ec_control.py`** in Notepad. At the very top, update the two constants with your discovered values:
      ```python
      COOLER_BOOST_REG  = 0xXX   # your discovered register address
      COOLER_BOOST_MASK = 0xYY   # your discovered bit mask (often 0x80)
      ```
   5. **Re-run `Run EC Verify.bat`** to confirm. Now the fans should go loud → quiet on cue.
   6. Once verified, go back to the ✅ path and run `Run FanTrigger.bat`.
   7. **Please open an issue** in this repo with your laptop model and discovered values — we'll add it to a built-in model database so future users with your hardware don't have to repeat the dance.

   The discovery script only **reads** the EC during the four-snapshot dance. The verify script only writes values you literally just observed coming from your own button press, only to the address you discovered, and restores the original byte before exiting.

## Quick start (just want a one-click .exe?)

> ⚠️ **The pre-built .exe assumes the Vector 16 HX A8WHG register layout.** If you're on a different MSI model, the .exe path won't work for you out of the box — you need the source-code path above so you can update `ec_control.py` with your discovered register, then optionally rebuild the .exe yourself with `build_exe.bat`.

Grab the latest build from the [Releases](../../releases) page (a zip containing `WafflePro.exe` + `LibreHardwareMonitorLib.dll`), extract anywhere, then **right-click `WafflePro.exe` → Run as administrator**. No Python, no pip, no fuss.

To make it auto-start without Python, create a Windows scheduled task pointing at the `.exe` with **Run with highest privileges** checked.

---

## What's in the tray menu

Right-click the WafflePro icon in the system tray:

- **CPU 67C \| Boost OFF** — live status header (informational).
- **Pause / Resume monitoring** — stops the auto-trigger without quitting.
- **Toggle Cooler Boost now** — manual on/off, handy for testing.
- **Open log file** — exactly what the utility has been doing, in plain text.
- **Open WafflePro folder** — Explorer shortcut.
- **Exit** — quit cleanly.

The tray icon's number is the live CPU temp. A yellow border on the icon means Cooler Boost is currently ON.

---

## Configuration

Open `fan_trigger.py` in Notepad. The knobs are at the top:

```python
TEMP_TRIGGER_ON  = 90.0   # turn boost ON  when CPU temp >= this (°C)
TEMP_TRIGGER_OFF = 80.0   # turn boost OFF when CPU temp <= this (°C)
POLL_INTERVAL    = 2.0    # seconds between temperature readings
```

Restart the utility (right-click tray → Exit, then `Run FanTrigger.bat` again) for changes to take effect. The 10 °C gap between ON and OFF is hysteresis — it prevents the boost from flapping when the CPU hovers around the threshold.

The EC register address lives in `ec_control.py`. Don't touch it unless you've run the discovery tool and confirmed different values for your hardware.

---

## How it works (under the hood)

1. **Sensor reading.** [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) reads CPU temperature through its own kernel driver (WinRing0). We use only the CPU sensor group — other groups would pull in an extra HidSharp dependency we don't need.
2. **EC access.** WinRing0 exposes raw I/O port read/write to user-mode (with admin rights). We call into LibreHardwareMonitor's internal `Ring0` class via .NET reflection — guaranteed-correct IOCTL codes, no homebrew driver poking.
3. **EC RAM protocol.** Standard ACPI EC: write read-cmd `0x80` to port `0x66`, write address to port `0x62`, read data byte from `0x62`. Same for writes (cmd `0x81`).
4. **Cooler Boost bit.** On this model, bit 7 of EC register `0x98` is the boost flag. Setting it to 1 = boost on, 0 = off. The lower bits of `0x98` carry unrelated state and are preserved on every write (read-modify-write).
5. **State sync.** Every poll we read the actual EC bit, so if you press FN+UpArrow yourself or MSI Center toggles boost for any other reason, WafflePro notices within one polling interval (2 seconds by default).

---

## Build the .exe yourself

Run **`build_exe.bat`** (no admin needed). It installs PyInstaller, bundles everything, drops the result at `dist\WafflePro.exe`. To distribute, zip the `.exe` and `LibreHardwareMonitorLib.dll` together.

---

## Files in this repo

```
WafflePro/
├── README.md                  ← you are here
├── LICENSE                    ← MIT
├── requirements.txt           ← Python dependencies for source installs
├── .gitignore                 ← excludes logs, generated DLL, __pycache__
│
├── fan_trigger.py             ← the main background utility
├── ec_control.py              ← shared EC + temperature module
│
├── Run FanTrigger.bat         ← launcher (handles deps, elevation, etc.)
├── Install Autostart.bat      ← schedules WafflePro for every login
├── Uninstall Autostart.bat    ← removes the autostart task
│
├── ec_verify.py               ← quick safety check before first use
├── Run EC Verify.bat
│
├── ec_discover.py             ← finds your model's Cooler Boost register
├── Run EC Discover.bat
│
├── fan_diagnostic_v2.py       ← deep keyboard-event capture + replay test
├── Run Diagnostic V2.bat      (kept for porting investigations)
│
└── build_exe.bat              ← one-click PyInstaller build of WafflePro.exe
```

---

## Safety and disclaimer

WafflePro writes to a kernel-mode driver and to the embedded controller of your laptop. The important stuff is taken care of:

- We only ever write to **one specific register** (`0x98` by default), and only the bit we discovered (`0x80` by default). The other bits of the same register are preserved on every write (read-modify-write).
- The verify and discovery scripts isolate writes from the auto-trigger logic, so you can prove the address is right before the polling loop ever runs.
- Hysteresis (90 °C ON, 80 °C OFF) prevents oscillation around the threshold.
- The single-instance mutex prevents two copies fighting over the EC.

That said, **EC manipulation is inherently risky.** If you copy-paste the wrong register address, write to a register that controls fan PWM directly, or run this on a model with a substantially different EC layout, you could in theory leave fans stuck on or off and cook your CPU. Always run the verify tool on a new machine first. Always have an escape hatch ready (FN+UpArrow, MSI Center, hard power-off if needed).

**No warranty. Use at your own risk.** The author and contributors are not responsible for hardware damage, performance issues, voided warranties, or anything else that happens because you ran this on your waffle maker.

---

## Troubleshooting

- **"Could not initialize the embedded controller bridge" popup** → didn't run as Administrator. Right-click the `.bat` (or the `.exe`) and choose **Run as administrator**.
- **Tray icon never appears** → check `fan_trigger.log`; the FATAL line at the top tells you what failed.
- **Temperature shown is `??`** → LHM didn't initialize. Most likely admin issue, or another tool (HWiNFO, ThrottleStop) is holding the WinRing0 driver. Close the other tool and retry.
- **Fans stop reacting after a Windows / firmware update** → the EC layout may have changed. Re-run `Run EC Discover.bat` and update the constants in `ec_control.py`.
- **Two icons in the tray** → an old version is still running. Right-click both, pick Exit on each, then launch fresh.

---

## Contributing

Pull requests welcome:

- **New model support** — open an issue with `Run EC Discover.bat` output and the laptop's exact model string. We'll add it to the supported list.
- **Bug fixes** with reproduction steps.
- **Better tray UI / icons.**
- **Improved PyInstaller packaging** (cleaner release zips, optional bundled installer, etc.).

---

## Credits

- [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) — sensor reading + bundled WinRing0 driver. (MPL-2.0)
- [WinRing0](https://github.com/QCute/WinRing0) — the kernel driver behind LHM's I/O port access. (BSD-3-Clause)
- [pystray](https://github.com/moses-palmer/pystray), [Pillow](https://github.com/python-pillow/Pillow), [pythonnet](https://github.com/pythonnet/pythonnet) — Python tray + image + .NET interop.

---

## License

[MIT](LICENSE).
