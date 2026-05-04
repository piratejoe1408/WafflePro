"""
FanTrigger - EC register discovery (v2 - uses LHM's own Ring0)

v1 tried to talk to WinRing0 by hand-rolling DeviceIoControl with hardcoded
IOCTL codes. Those numbers depend on which WinRing0 fork is loaded, and the
ones I picked apparently don't match the LHM-bundled driver - every EC read
hit the 500ms timeout, which is why a snapshot took forever.

v2 cuts out the guesswork. We load LibreHardwareMonitor and reach into its
internal `Ring0` class via .NET reflection. Ring0.ReadIoPort / WriteIoPort
are the exact methods LHM itself uses for sensor reads - if the temperature
diagnostic worked, these work.

This script ONLY READS the EC during discovery. It only writes during the
optional verification step at the very end, and only with values you literally
just observed coming from your own FN+UpArrow press, only to the address we
identified.
"""

import os
import sys
import time
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "ec_discover_results.log"
DLL_PATH = SCRIPT_DIR / "LibreHardwareMonitorLib.dll"


# ============================================================
#  Logging
# ============================================================
def log(msg=""):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    print(msg, flush=True)


# ============================================================
#  Reflection-based bridge to LibreHardwareMonitor's Ring0
# ============================================================
class Ring0Bridge:
    """Calls into LHM's internal Ring0 static class via .NET reflection."""

    def __init__(self):
        if not DLL_PATH.exists():
            raise FileNotFoundError(
                f"Missing: {DLL_PATH}. Run 'Run FanTrigger.bat' once first."
            )
        import clr  # type: ignore
        sys.path.append(str(SCRIPT_DIR))
        clr.AddReference(str(DLL_PATH))

        from LibreHardwareMonitor.Hardware import Computer  # type: ignore
        self._computer = Computer()
        self._computer.IsCpuEnabled = True
        self._computer.Open()
        log("LibreHardwareMonitor opened (this loads WinRing0 if needed).")

        # Reach into LHM internals
        from System.Reflection import Assembly, BindingFlags  # type: ignore
        from System import UInt32, Byte  # type: ignore

        flags_static = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static

        asm = Assembly.LoadFrom(str(DLL_PATH))
        ring0 = asm.GetType("LibreHardwareMonitor.Hardware.Ring0")
        if ring0 is None:
            raise RuntimeError(
                "Couldn't find type LibreHardwareMonitor.Hardware.Ring0 — "
                "your LHM version may have moved it."
            )

        is_open_prop = ring0.GetProperty("IsOpen", flags_static)
        if is_open_prop is not None:
            try:
                if not bool(is_open_prop.GetValue(None)):
                    raise RuntimeError("Ring0.IsOpen == false after Computer.Open(). "
                                       "WinRing0 driver did not load.")
            except Exception:
                pass

        read_method = ring0.GetMethod("ReadIoPort", flags_static)
        write_method = ring0.GetMethod("WriteIoPort", flags_static)
        if read_method is None or write_method is None:
            # try all candidate signatures
            for m in ring0.GetMethods(flags_static):
                log(f"  candidate Ring0 method: {m.Name}({', '.join(p.ParameterType.Name for p in m.GetParameters())}) -> {m.ReturnType.Name}")
            raise RuntimeError("Couldn't find Ring0.ReadIoPort/WriteIoPort.")

        self._UInt32 = UInt32
        self._Byte = Byte
        self._read_method = read_method
        self._write_method = write_method

    def read_io_byte(self, port):
        # Ring0.ReadIoPort returns a byte
        result = self._read_method.Invoke(None, [self._UInt32(port)])
        return int(result) & 0xFF

    def write_io_byte(self, port, value):
        self._write_method.Invoke(None, [self._UInt32(port), self._Byte(value & 0xFF)])

    def close(self):
        try:
            self._computer.Close()
        except Exception:
            pass


# ============================================================
#  EC RAM access via I/O ports 0x66 (cmd/status) and 0x62 (data)
# ============================================================
EC_SC      = 0x66
EC_DATA    = 0x62
EC_RD_CMD  = 0x80
EC_WR_CMD  = 0x81

EC_OBF_BIT = 0x01  # output buffer full -> data ready to read
EC_IBF_BIT = 0x02  # input buffer full  -> EC busy, can't write yet


def _ec_wait(ring0, mask, want_set, timeout=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = ring0.read_io_byte(EC_SC)
        if want_set:
            if st & mask:
                return True
        else:
            if not (st & mask):
                return True
    return False


def ec_read(ring0, addr):
    if not _ec_wait(ring0, EC_IBF_BIT, False): raise IOError("EC busy (pre-cmd IBF)")
    ring0.write_io_byte(EC_SC, EC_RD_CMD)
    if not _ec_wait(ring0, EC_IBF_BIT, False): raise IOError("EC busy (post-cmd IBF)")
    ring0.write_io_byte(EC_DATA, addr)
    if not _ec_wait(ring0, EC_OBF_BIT, True):  raise IOError("EC read timeout (OBF)")
    return ring0.read_io_byte(EC_DATA)


def ec_write(ring0, addr, value):
    if not _ec_wait(ring0, EC_IBF_BIT, False): raise IOError("EC busy (pre-cmd IBF)")
    ring0.write_io_byte(EC_SC, EC_WR_CMD)
    if not _ec_wait(ring0, EC_IBF_BIT, False): raise IOError("EC busy (post-cmd IBF)")
    ring0.write_io_byte(EC_DATA, addr)
    if not _ec_wait(ring0, EC_IBF_BIT, False): raise IOError("EC busy (post-addr IBF)")
    ring0.write_io_byte(EC_DATA, value)


def ec_snapshot(ring0, length=256, show_progress=True):
    out = bytearray(length)
    failed = 0
    t0 = time.time()
    for i in range(length):
        if show_progress and (i % 16 == 0):
            print(f"\r  reading EC RAM... 0x{i:02X}/0x{length:02X}", end="", flush=True)
        try:
            out[i] = ec_read(ring0, i)
        except IOError:
            out[i] = 0xFF
            failed += 1
    elapsed = time.time() - t0
    if show_progress:
        print(f"\r  reading EC RAM... done in {elapsed:.2f}s ({failed} byte(s) timed out)        ")
    return bytes(out), elapsed, failed


def fmt_hex(b):
    lines = []
    for off in range(0, len(b), 16):
        chunk = b[off:off+16]
        hexpart = " ".join(f"{x:02X}" for x in chunk)
        lines.append(f"  0x{off:02X}: {hexpart}")
    return "\n".join(lines)


# ============================================================
#  The discovery dance
# ============================================================
def prompt(msg):
    print()
    print("-" * 72)
    print(msg)
    print("-" * 72)
    input("  Press Enter when you've done the action above...")
    print()


def main():
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    log("=" * 72)
    log("  FanTrigger - EC register discovery (v2: via LHM Ring0)")
    log("=" * 72)
    log(f"Started: {datetime.datetime.now().isoformat()}")
    log("")

    log("Step 1: opening LibreHardwareMonitor and binding to its Ring0...")
    try:
        ring0 = Ring0Bridge()
    except Exception as e:
        log(f"FATAL: {e}")
        log("Make sure you ran 'Run FanTrigger.bat' once and that THIS script")
        log("is launched as Administrator.")
        input("Press Enter to close.")
        return

    log("")
    log("Step 2: 1-byte sanity read (port 0x66 status register)...")
    try:
        t0 = time.time()
        status = ring0.read_io_byte(EC_SC)
        dt = time.time() - t0
        log(f"  read 0x{status:02X} from port 0x66 in {dt*1000:.1f} ms")
        if dt > 0.5:
            log("  WARNING: that read was unusually slow. Continuing anyway.")
    except Exception as e:
        log(f"FATAL: I/O port read failed: {e}")
        log("This means Ring0 isn't actually delivering reads. We're stuck without")
        log("a more invasive driver. Send the log back.")
        ring0.close()
        input("Press Enter to close.")
        return

    log("")
    log("Step 3: timed full EC RAM snapshot (256 bytes)")
    log("  Should take well under 2 seconds. If it takes longer, abort with Ctrl+C.")
    try:
        baseline, elapsed, failed = ec_snapshot(ring0)
    except Exception as e:
        log(f"FATAL: EC snapshot failed: {e}")
        ring0.close()
        input("Press Enter to close.")
        return

    log(f"  Snapshot took {elapsed:.2f}s, {failed} bytes timed out.")
    if elapsed > 5:
        log("  STOP: snapshot took too long. EC port reads are likely failing.")
        log("  Send the log back.")
        ring0.close()
        input("Press Enter to close.")
        return
    log("")
    log("Baseline EC dump:")
    log(fmt_hex(baseline))
    log("")

    log("=" * 72)
    log("  Discovery dance")
    log("=" * 72)
    log("")
    log("We'll snapshot EC RAM 4 more times. Between each snapshot YOU press")
    log("FN+UP by hand to physically toggle Cooler Boost. Use your ears to")
    log("confirm fans actually go loud/quiet in the expected pattern -")
    log("if they don't, the data won't match and we're chasing noise.")
    log("")
    log("BEFORE WE START: please make sure Cooler Boost is currently OFF.")
    log("(Fans should be at normal idle level.)")
    log("")
    input("Press Enter to begin...")

    snapshots = []
    labels = []

    log("\nReading snapshot S1 (assumed boost OFF)...")
    s1, _, _ = ec_snapshot(ring0)
    snapshots.append(s1); labels.append("S1 (OFF)")

    prompt("PRESS  FN + UpArrow  ONCE  to turn boost ON.\nFans should ramp up loud. Confirm with your ears.")
    log("Reading snapshot S2 (boost ON)...")
    s2, _, _ = ec_snapshot(ring0)
    snapshots.append(s2); labels.append("S2 (ON)")

    prompt("PRESS  FN + UpArrow  ONCE  again to turn boost OFF.\nFans should drop back to normal.")
    log("Reading snapshot S3 (boost OFF)...")
    s3, _, _ = ec_snapshot(ring0)
    snapshots.append(s3); labels.append("S3 (OFF)")

    prompt("PRESS  FN + UpArrow  ONCE  again to turn boost ON.\nFans loud again.")
    log("Reading snapshot S4 (boost ON)...")
    s4, _, _ = ec_snapshot(ring0)
    snapshots.append(s4); labels.append("S4 (ON)")

    prompt("PRESS  FN + UpArrow  ONCE  more to turn boost OFF.\n(So we leave the laptop in OFF state.)")

    log("")
    log("=" * 72)
    log("  Analysis")
    log("=" * 72)
    log("")

    clean = []   # whole-byte clean toggle pattern: S1=S3 != S2=S4
    bit_candidates = []  # byte changes in any bit, even if not clean
    noisy = []
    for addr in range(256):
        v1, v2, v3, v4 = (snapshots[i][addr] for i in range(4))
        if v1 == v3 and v2 == v4 and v1 != v2:
            clean.append((addr, v1, v2))
        elif len({v1, v2, v3, v4}) > 1:
            # try bit-level: which bits flip with state?
            off_set = v1 & v3   # bits set in BOTH off snapshots
            off_clr = (~v1) & (~v3) & 0xFF
            on_set  = v2 & v4
            on_clr  = (~v2) & (~v4) & 0xFF
            # bit is clean if it's set in both ONs and clear in both OFFs (or vice versa)
            bit_off_then_on = off_clr & on_set       # bit clear off, set on
            bit_on_then_off = off_set & on_clr       # bit set off, clear on
            bit_diff = bit_off_then_on | bit_on_then_off
            if bit_diff:
                bit_candidates.append((addr, v1, v2, v3, v4, bit_diff))
            else:
                noisy.append((addr, v1, v2, v3, v4))

    log(f"Clean WHOLE-BYTE toggles (S1=S3 != S2=S4): {len(clean)} candidate(s)")
    for addr, off_v, on_v in clean:
        log(f"   register 0x{addr:02X} ({addr:>3d}):  OFF=0x{off_v:02X}  ON=0x{on_v:02X}")

    log("")
    log(f"Clean BIT-LEVEL toggles (specific bits flip with state): "
        f"{len(bit_candidates)} candidate(s)")
    for addr, v1, v2, v3, v4, bd in bit_candidates:
        log(f"   register 0x{addr:02X}: S1=0x{v1:02X} S2=0x{v2:02X} S3=0x{v3:02X} S4=0x{v4:02X}  "
            f"flipping_bits=0x{bd:02X}")

    log("")
    log(f"Pure noise (no clean pattern): {len(noisy)} byte(s)")
    for entry in noisy[:20]:
        log(f"   0x{entry[0]:02X}: S1=0x{entry[1]:02X} S2=0x{entry[2]:02X} "
            f"S3=0x{entry[3]:02X} S4=0x{entry[4]:02X}")
    if len(noisy) > 20:
        log(f"   ... and {len(noisy) - 20} more (truncated)")

    log("")
    log("Full snapshots saved into the log for the assistant:")
    for label, snap in zip(labels, snapshots):
        log(f"\n--- {label} ---")
        log(fmt_hex(snap))

    log("")
    if not clean and not bit_candidates:
        log("RESULT: No clean candidates. Likely fan toggle didn't actually happen,")
        log("or EC values drift between reads. Send the log; I'll look at the noise.")
    elif len(clean) == 1:
        addr, off_v, on_v = clean[0]
        log("RESULT: Single clean whole-byte candidate.")
        log(f"  Cooler Boost register: 0x{addr:02X}")
        log(f"  OFF value: 0x{off_v:02X}")
        log(f"  ON  value: 0x{on_v:02X}")
        log("")
        log("Optional verification: write OFF then ON to that register, listen.")
        ans = input("  Run the verification now? [y/N]: ").strip().lower()
        if ans == "y":
            try:
                log(f"\nWriting 0x{on_v:02X} to register 0x{addr:02X} (boost should go ON)...")
                ec_write(ring0, addr, on_v)
                log("  Listen... waiting 4 seconds.")
                time.sleep(4)
                rb = ec_read(ring0, addr)
                log(f"  Readback: 0x{rb:02X}  (expected 0x{on_v:02X})")

                log(f"\nWriting 0x{off_v:02X} to register 0x{addr:02X} (boost should go OFF)...")
                ec_write(ring0, addr, off_v)
                log("  Listen... waiting 4 seconds.")
                time.sleep(4)
                rb = ec_read(ring0, addr)
                log(f"  Readback: 0x{rb:02X}  (expected 0x{off_v:02X})")
                log("")
                log("If the fans responded to BOTH writes, we own the boost. Tell me.")
                log("If they didn't, the byte is read-only (status mirror); the real")
                log("control bit is elsewhere - send the log either way.")
            except Exception as e:
                log(f"  EC write failed: {e}")
    else:
        log(f"RESULT: {len(clean)} clean whole-byte candidates and "
            f"{len(bit_candidates)} bit-level ones. Send the log; I'll narrow it.")

    log("")
    log(f"Full log saved to: {LOG_FILE}")
    log("")

    ring0.close()

    print()
    input("Press Enter to close.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\nAborted by user (Ctrl+C).")
    except Exception:
        import traceback
        log(f"Unhandled exception:\n{traceback.format_exc()}")
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
