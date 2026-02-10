import time
import csv
import pyvisa
import numpy as np
from pathlib import Path
from datetime import datetime

# ---------------- USER SETTINGS ----------------
GPIB_ADDR = "GPIB0::22::INSTR"

V_START =  5.0    # volts
V_STOP  = -5.0     # volts
V_STEP  = -0.05     # volts (negative because we sweep down)

HOLD_TIME = 1.0     # seconds
CURRENT_LIMIT = 1e-3  # 1 mA compliance

BASE_NAME = "IV_sweep_+5V_to_-5V_0.5_1.5s_delayV"
# ------------------------------------------------

def parse_current(reading: str) -> float:
    """Extract current (A) from READ? response"""
    return float(reading.strip().split(",")[0].replace("A", ""))

# -------- Choose safe output path --------
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path = Path(__file__).resolve().parent / f"{BASE_NAME}_{ts}.csv"

rm = pyvisa.ResourceManager()
inst = rm.open_resource(GPIB_ADDR)
inst.timeout = 10000

print(inst.query("*IDN?").strip())
print("Saving to:", csv_path)

try:
    # ---------- Instrument setup ----------
    inst.write("*RST")
    inst.write("*CLS")

    inst.write("SYST:ZCH OFF")          # Zero check OFF (mandatory)
    inst.write("SOUR:VOLT:RANG 500")    # 500 V range (needed for ±50 V)
    inst.write(f"SOUR:VOLT:ILIM {CURRENT_LIMIT}")

    # Enable source
    inst.write("SOUR:VOLT 0")
    inst.write("SOUR:VOLT:STAT ON")
    time.sleep(0.5)

    # ---------- Sweep ----------
    voltages = np.arange(V_START, V_STOP + (V_STEP / 2), V_STEP)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Set Voltage (V)", "Current (A)"])

        for V in voltages:
            inst.write(f"SOUR:VOLT {V}")
            time.sleep(HOLD_TIME)

            reading = inst.query("READ?").strip()
            curr = parse_current(reading)

            writer.writerow([V, curr])
            print(f"Vset={V:+.1f} V | I={curr:.3e} A")

finally:
    # ---------- Safe shutdown ----------
    try:
        inst.write("SOUR:VOLT 0")
        time.sleep(0.5)
        inst.write("SOUR:VOLT:STAT OFF")
    except Exception:
        pass

    try:
        inst.close()
    except Exception:
        pass

print("Sweep complete.")
