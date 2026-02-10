import time
import csv
import pyvisa
import numpy as np
from pathlib import Path
from datetime import datetime

import matplotlib.pyplot as plt

# ---------------- USER SETTINGS ----------------
GPIB_ADDR = "GPIB0::22::INSTR"

V_START =  5.0      # volts
V_STOP  = -5.0      # volts
V_STEP  = -0.1     # volts (negative because we sweep down)

HOLD_TIME = 1.0     # seconds

# 6487 note: ILIM is quantised; always query back what it actually set.
CURRENT_LIMIT = 2.5e-5   # 25 µA (safe for CZT; change to 2.5e-4 for 250 µA if needed)

# Use 50 V range for ±5 V sweeps (cleaner than 500 V range)
SOURCE_RANGE = 50

BASE_NAME = "IV_sweep_+5V_to_-5V_0.05Vstep_1.0s_hold"
# ------------------------------------------------

def parse_read(reading: str):
    """
    6487 READ? typically returns something like:
      '+1.234567E-09A,+..., +STAT'
    We trust:
      - current = first field (strip trailing 'A')
      - status  = last field (float)
    """
    parts = reading.strip().split(",")
    curr = float(parts[0].replace("A", ""))
    stat = float(parts[-1]) if len(parts) >= 2 else float("nan")
    return curr, stat, parts

# -------- Choose safe output path --------
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path = Path(__file__).resolve().parent / f"{BASE_NAME}_{ts}.csv"

rm = pyvisa.ResourceManager()
inst = rm.open_resource(GPIB_ADDR)
inst.timeout = 20000

print(inst.query("*IDN?").strip())
print("Saving to:", csv_path)

# ---------- Live plot setup ----------
plt.ion()
fig, ax = plt.subplots()
ax.set_xlabel("Set Voltage (V)")
ax.set_ylabel("Current (A)")
ax.set_title("Live I–V Sweep (Keithley 6487)")
(line,) = ax.plot([], [], marker="o", linestyle="-")
ax.grid(True)
fig.tight_layout()

Vs, Is = [], []

try:
    # ---------- Instrument setup ----------
    inst.write("*RST")
    inst.write("*CLS")

    inst.write("SYST:ZCH OFF")                 # Zero check OFF (mandatory)
    inst.write(f"SOUR:VOLT:RANG {SOURCE_RANGE}")
    inst.write(f"SOUR:VOLT:ILIM {CURRENT_LIMIT}")
    print("ILIM actually set to:", inst.query("SOUR:VOLT:ILIM?").strip())

    # Optional: enable current autorange for better sensitivity
    try:
        inst.write("SENS:CURR:RANG:AUTO ON")
    except Exception:
        pass

    # Enable source
    inst.write("SOUR:VOLT 0")
    inst.write("SOUR:VOLT:STAT ON")
    time.sleep(0.5)

    # Throwaway read to avoid first-read overflow artefact
    try:
        inst.query("READ?")
    except Exception:
        pass

    # ---------- Build sweep points robustly (avoid np.arange float weirdness) ----------
    npts = int(round((V_STOP - V_START) / V_STEP)) + 1
    voltages = np.linspace(V_START, V_STOP, npts)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Set Voltage (V)", "Current (A)", "Status", "Raw READ?"])

        for V in voltages:
            inst.write(f"SOUR:VOLT {V:.6f}")
            time.sleep(HOLD_TIME)

            raw = inst.query("READ?").strip()
            curr, stat, _ = parse_read(raw)

            Vs.append(float(V))
            Is.append(curr)

            writer.writerow([f"{V:.6f}", f"{curr:.12e}", f"{stat:.0f}", raw])

            # Console print (more decimals so you don't see duplicates)
            print(f"Vset={V:+.2f} V | I={curr:+.3e} A | STAT={stat:.0f}")

            # Live plot update
            line.set_data(Vs, Is)
            ax.relim()
            ax.autoscale_view()
            fig.canvas.draw()
            fig.canvas.flush_events()

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

    plt.ioff()
    plt.show()

print("Sweep complete.")
