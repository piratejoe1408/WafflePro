"""
FanTrigger - EC verification

Quick sanity check before we trust direct EC writes for the auto-toggle utility.

Reads the current value of EC register 0x98, sets bit 7 (Cooler Boost ON),
waits 5 seconds for you to listen, clears bit 7 (Cooler Boost OFF), waits 5
more seconds, restores the original value, and exits.

Run this once. If your fans go LOUD then QUIET as expected, the discovered
register is correct and we'll switch the main utility over to direct EC
writes.
"""

import time
import datetime
from pathlib import Path

from ec_control import (
    Ring0Bridge, ec_read, ec_write, get_cooler_boost, set_cooler_boost,
    COOLER_BOOST_REG, COOLER_BOOST_MASK,
)

LOG_FILE = Path(__file__).resolve().parent / "ec_verify_results.log"


def log(msg=""):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    print(msg, flush=True)


def main():
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    log("=" * 64)
    log("  FanTrigger - EC verification")
    log("=" * 64)
    log(f"Started: {datetime.datetime.now().isoformat()}")
    log(f"Target register: 0x{COOLER_BOOST_REG:02X}, mask: 0x{COOLER_BOOST_MASK:02X}")
    log("")

    log("Opening LibreHardwareMonitor + Ring0...")
    try:
        ring0 = Ring0Bridge()
    except Exception as e:
        log(f"FATAL: {e}")
        log("Run this as Administrator, with Run FanTrigger.bat already done once.")
        input("Press Enter to close.")
        return
    log("  Ring0 ready.")
    log("")

    original = ec_read(ring0, COOLER_BOOST_REG)
    log(f"Current EC[0x{COOLER_BOOST_REG:02X}] = 0x{original:02X}  "
        f"(Cooler Boost is currently {'ON' if original & COOLER_BOOST_MASK else 'OFF'})")
    log("")

    log("Will turn Cooler Boost ON in 3 seconds. Listen for the fans.")
    for i in (3, 2, 1):
        log(f"  {i}...")
        time.sleep(1)
    set_cooler_boost(ring0, True)
    val_on = ec_read(ring0, COOLER_BOOST_REG)
    log(f"  Wrote 0x{val_on:02X}. Listening for 5 seconds...")
    time.sleep(5)
    log("")

    log("Will turn Cooler Boost OFF in 3 seconds.")
    for i in (3, 2, 1):
        log(f"  {i}...")
        time.sleep(1)
    set_cooler_boost(ring0, False)
    val_off = ec_read(ring0, COOLER_BOOST_REG)
    log(f"  Wrote 0x{val_off:02X}. Listening for 5 seconds...")
    time.sleep(5)
    log("")

    # Restore original value
    log(f"Restoring original value (0x{original:02X}).")
    ec_write(ring0, COOLER_BOOST_REG, original)
    rb = ec_read(ring0, COOLER_BOOST_REG)
    log(f"  Readback after restore: 0x{rb:02X}")
    log("")

    log("=" * 64)
    log("  VERIFICATION DONE")
    log("=" * 64)
    log("")
    log("Did the fans go LOUD then QUIET?")
    log("  YES -> register is correct, we ship the new utility.")
    log("  NO  -> bit 7 of 0x98 is a status mirror, not the control bit.")
    log("         Send the log; we'll try the bit-level candidates next.")
    log("")

    ring0.close()
    print()
    input("Press Enter to close.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        log(f"Unhandled exception:\n{traceback.format_exc()}")
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
