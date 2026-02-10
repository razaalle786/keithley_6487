"""
Keithley 6487 wiring/proof-resistor diagnostic script (robust, verbose)

What it does:
- Resets + configures the 6487 safely
- Prints key settings (source range, ILIM, current range, etc.)
- Performs a throwaway READ? to avoid the 9.9e37 overflow artefact
- Runs a small 0/1/5 V test (ratio check)
- Optionally runs a 0/5/20/50 V test (only if you enable it)
- Prints RAW lines + parsed current + status field

IMPORTANT:
- This script assumes your 6487 returns READ? like: "<I>A,<something>,<STAT>"
  We only trust the first field as current and the last field as status.
"""

import time
import pyvisa

GPIB_ADDR = "GPIB0::22::INSTR"

# ---------- user knobs ----------
SOURCE_RANGE_V = 50          # 10 / 50 / 500 (use 50 for up to ±50 V)
ILIM_A = 2.5e-3              # try 2.5e-3 for resistor tests (2.5 mA)
USE_FIXED_I_RANGE = True
FIXED_I_RANGE_A = 1e-3       # 1 mA range (adjust if needed)
SETTLE_S = 1.0               # seconds per point

RUN_WIDE_TEST = True         # set False to only do 0/1/5V test
WIDE_POINTS_V = [0, 5, 20, 50]
# ------------------------------

def q(inst, cmd: str) -> str:
    return inst.query(cmd).strip()

def w(inst, cmd: str) -> None:
    inst.write(cmd)

def parse_reading(raw: str):
    """
    raw example: '+1.234567E-09A,+1.234000E+02,+0.000000E+00'
    We trust:
      - current = first field (strip trailing 'A')
      - status  = last field (float)
    """
    parts = raw.strip().split(",")
    if len(parts) < 2:
        raise ValueError(f"Unexpected READ? format: {raw!r}")

    curr_str = parts[0].replace("A", "").strip()
    curr = float(curr_str)

    stat = None
    try:
        stat = float(parts[-1])
    except Exception:
        stat = None

    return curr, stat, parts

def drain_err(inst, n=5):
    out = []
    for _ in range(n):
        e = q(inst, "SYST:ERR?")
        out.append(e)
        if e.startswith('0,"No error"') or e.startswith("+0"):
            break
    return out

def print_settings(inst):
    def safe_query(cmd):
        try:
            return q(inst, cmd)
        except Exception as e:
            return f"<query failed: {e}>"

    print("---- SETTINGS ----")
    print("IDN:", safe_query("*IDN?"))
    print("SOUR:VOLT?      :", safe_query("SOUR:VOLT?"))
    print("SOUR:VOLT:RANG? :", safe_query("SOUR:VOLT:RANG?"))
    print("SOUR:VOLT:ILIM? :", safe_query("SOUR:VOLT:ILIM?"))
    print("SOUR:VOLT:STAT? :", safe_query("SOUR:VOLT:STAT?"))
    print("SENS:FUNC?      :", safe_query("SENS:FUNC?"))
    print("SENS:CURR:RANG? :", safe_query("SENS:CURR:RANG?"))
    print("SENS:CURR:RANG:AUTO? :", safe_query("SENS:CURR:RANG:AUTO?"))
    print("FORM:ELEM?      :", safe_query("FORM:ELEM?"))
    print("Errors (tail):", drain_err(inst))
    print("------------------")

def measure_point(inst, V):
    w(inst, f"SOUR:VOLT {V}")
    time.sleep(SETTLE_S)
    raw = q(inst, "READ?")
    curr, stat, _parts = parse_reading(raw)
    print(f"Vset={V:+} V  I={curr:+.6e} A  STAT={stat if stat is not None else 'NA'}  raw={raw}")
    return curr, stat, raw

def main():
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(GPIB_ADDR)
    inst.timeout = 20000

    try:
        # Reset/clear
        w(inst, "*RST")
        w(inst, "*CLS")

        # Mandatory for real measurements
        w(inst, "SYST:ZCH OFF")

        # Configure source
        w(inst, f"SOUR:VOLT:RANG {SOURCE_RANGE_V}")
        w(inst, f"SOUR:VOLT:ILIM {ILIM_A}")

        # Configure sense (current)
        w(inst, "SENS:FUNC 'CURR'")

        if USE_FIXED_I_RANGE:
            w(inst, "SENS:CURR:RANG:AUTO OFF")
            w(inst, f"SENS:CURR:RANG {FIXED_I_RANGE_A}")
        else:
            w(inst, "SENS:CURR:RANG:AUTO ON")

        # Set output on at 0 V
        w(inst, "SOUR:VOLT 0")
        w(inst, "SOUR:VOLT:STAT ON")
        time.sleep(0.5)

        # Print settings after config
        print_settings(inst)

        # Throwaway read to avoid first-reading overflow artefact
        _ = q(inst, "READ?")

        print("\n=== Ratio test (0, +1, +5 V) ===")
        i0, _, _ = measure_point(inst, 0)
        i1, _, _ = measure_point(inst, 1)
        i5, _, _ = measure_point(inst, 5)

        # Simple sanity: I(5V)/I(1V) should be ~5 for a resistor-dominated path
        if abs(i1) > 0:
            ratio = i5 / i1
            print(f"Ratio I(5V)/I(1V) = {ratio:.3f}  (expected ~5.0 for a clean resistor)")
        else:
            print("I(1V) is ~0; cannot compute ratio (suggests open circuit or measurement floor).")

        if RUN_WIDE_TEST:
            print("\n=== Wide test (0, +5, +20, +50 V) ===")
            for V in WIDE_POINTS_V:
                measure_point(inst, V)

        print("\nDone. Returning to 0 V and disabling output...")

    finally:
        # Safe shutdown
        try:
            w(inst, "SOUR:VOLT 0")
            time.sleep(0.5)
            w(inst, "SOUR:VOLT:STAT OFF")
        except Exception:
            pass
        try:
            inst.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
