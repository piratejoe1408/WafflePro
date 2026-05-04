"""
FanTrigger - EC control + CPU temperature module

Reads/writes the Cooler Boost bit on MSI laptops by talking to the embedded
controller (EC) directly via LibreHardwareMonitor's Ring0. No keyboard
simulation, no MSI Center cooperation - we flip the same bit MSI Center
would flip when you press FN+UpArrow.

Discovered via ec_discover.py for the MSI Vector A16 HX A8WHG, then verified
with ec_verify.py:

    EC register 0x98, bit 7 (mask 0x80)
        bit set   -> Cooler Boost ON
        bit clear -> Cooler Boost OFF
    Other bits of 0x98 (currently 0x03) carry unrelated state and must be
    preserved on writes.

If we ever port to a different MSI model, only the constants below should
need updating.

Also exposes CPU temperature reading on the same LHM Computer instance, so
the main utility doesn't have to spin up two of them.
"""

import sys
import time
from pathlib import Path

# === MODEL-SPECIFIC CONSTANTS =================================
COOLER_BOOST_REG  = 0x98
COOLER_BOOST_MASK = 0x80
# ==============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DLL_PATH = SCRIPT_DIR / "LibreHardwareMonitorLib.dll"

# EC protocol ports / commands
_EC_SC      = 0x66
_EC_DATA    = 0x62
_EC_RD_CMD  = 0x80
_EC_WR_CMD  = 0x81
_EC_OBF_BIT = 0x01
_EC_IBF_BIT = 0x02


class LhmBridge:
    """One shared LibreHardwareMonitor Computer instance, exposing both:
       - I/O port reads/writes via internal Ring0 (for EC manipulation)
       - CPU sensor reads (Tdie/Tctl etc.) via the standard public API
    """

    def __init__(self):
        if not DLL_PATH.exists():
            raise FileNotFoundError(f"Missing: {DLL_PATH}")

        import clr  # type: ignore
        sys.path.append(str(SCRIPT_DIR))
        clr.AddReference(str(DLL_PATH))

        from LibreHardwareMonitor.Hardware import Computer  # type: ignore
        self._computer = Computer()
        self._computer.IsCpuEnabled = True
        # Other groups deliberately disabled (some pull in HidSharp etc.)
        self._computer.IsMotherboardEnabled = False
        self._computer.IsControllerEnabled  = False
        self._computer.IsGpuEnabled         = False
        self._computer.IsMemoryEnabled      = False
        self._computer.IsStorageEnabled     = False
        self._computer.IsNetworkEnabled     = False
        self._computer.IsBatteryEnabled     = False
        self._computer.IsPsuEnabled         = False
        self._computer.Open()

        from System.Reflection import Assembly, BindingFlags  # type: ignore
        from System import UInt32, Byte  # type: ignore

        flags_static = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static
        asm = Assembly.LoadFrom(str(DLL_PATH))
        ring0 = asm.GetType("LibreHardwareMonitor.Hardware.Ring0")
        if ring0 is None:
            raise RuntimeError("LibreHardwareMonitor.Hardware.Ring0 not found.")

        self._UInt32 = UInt32
        self._Byte = Byte
        self._read_method  = ring0.GetMethod("ReadIoPort", flags_static)
        self._write_method = ring0.GetMethod("WriteIoPort", flags_static)
        if self._read_method is None or self._write_method is None:
            raise RuntimeError("Ring0.ReadIoPort/WriteIoPort missing.")

        # Find the CPU hardware once so temperature reads are cheap
        self._cpu_hw = None
        for hw in self._computer.Hardware:
            if "Cpu" in str(hw.HardwareType):
                self._cpu_hw = hw
                break
        if self._cpu_hw is None:
            raise RuntimeError("LHM didn't detect any CPU hardware.")

        # Prime sensors
        for _ in range(2):
            self._cpu_hw.Update()
            time.sleep(0.2)

    # ---- I/O port primitives (used internally) ----
    def read_io_byte(self, port):
        return int(self._read_method.Invoke(None, [self._UInt32(port)])) & 0xFF

    def write_io_byte(self, port, value):
        self._write_method.Invoke(None, [self._UInt32(port), self._Byte(value & 0xFF)])

    # ---- CPU temperature ----
    @property
    def cpu_name(self):
        return str(self._cpu_hw.Name) if self._cpu_hw is not None else "?"

    def read_max_cpu_temp(self):
        """Return the highest reported CPU temperature in C, or None."""
        try:
            self._cpu_hw.Update()
        except Exception:
            return None
        max_t = None
        for sensor in self._cpu_hw.Sensors:
            if str(sensor.SensorType) == "Temperature":
                v = sensor.Value
                if v is not None and (max_t is None or v > max_t):
                    max_t = float(v)
        return max_t

    def close(self):
        try:
            self._computer.Close()
        except Exception:
            pass


# Backwards-compat alias for ec_discover.py / ec_verify.py
Ring0Bridge = LhmBridge


# ============================================================
#  EC RAM access via I/O ports 0x66 (cmd/status) and 0x62 (data)
# ============================================================
def _ec_wait(bridge, mask, want_set, timeout=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = bridge.read_io_byte(_EC_SC)
        if want_set and (st & mask):
            return True
        if (not want_set) and (not (st & mask)):
            return True
    return False


def ec_read(bridge, addr):
    if not _ec_wait(bridge, _EC_IBF_BIT, False): raise IOError("EC pre-cmd busy")
    bridge.write_io_byte(_EC_SC, _EC_RD_CMD)
    if not _ec_wait(bridge, _EC_IBF_BIT, False): raise IOError("EC post-cmd busy")
    bridge.write_io_byte(_EC_DATA, addr)
    if not _ec_wait(bridge, _EC_OBF_BIT, True):  raise IOError("EC read timeout")
    return bridge.read_io_byte(_EC_DATA)


def ec_write(bridge, addr, value):
    if not _ec_wait(bridge, _EC_IBF_BIT, False): raise IOError("EC pre-cmd busy")
    bridge.write_io_byte(_EC_SC, _EC_WR_CMD)
    if not _ec_wait(bridge, _EC_IBF_BIT, False): raise IOError("EC post-cmd busy")
    bridge.write_io_byte(_EC_DATA, addr)
    if not _ec_wait(bridge, _EC_IBF_BIT, False): raise IOError("EC post-addr busy")
    bridge.write_io_byte(_EC_DATA, value)


# ============================================================
#  Cooler Boost helpers
# ============================================================
def get_cooler_boost(bridge):
    """Return True if Cooler Boost bit is set."""
    return bool(ec_read(bridge, COOLER_BOOST_REG) & COOLER_BOOST_MASK)


def set_cooler_boost(bridge, on):
    """Set the Cooler Boost bit while preserving every other bit of the
    register. Returns the byte we wrote."""
    current = ec_read(bridge, COOLER_BOOST_REG)
    if on:
        new_val = current | COOLER_BOOST_MASK
    else:
        new_val = current & (~COOLER_BOOST_MASK & 0xFF)
    if new_val != current:
        ec_write(bridge, COOLER_BOOST_REG, new_val)
    return new_val
