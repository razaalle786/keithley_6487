import time
import csv
import pyvisa
import numpy as np
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt

# ---------------- USER SETTINGS ----------------
GPIB_ADDR = "GPIB0::13::INSTR"   # Keithley 2450 @ GPIB 13

V_START =  20.0      # volts
V_STOP  = -20.0      # volts
V_STEP  = -0.5       # volts (negative because we sweep down)

HOLD_TIME = 1.0      # seconds

CURRENT_LIMIT = 2.5e-5   # 25 µA compliance (adjust as needed)
SOURCE_RANGE = 50        # volts source range (set to 20, 200 etc. as appropriate)

BASE_NAME = "IV_sweep_+20V_to_-20V_0.5Vstep_1.0s_hold_2450"
# ------------------------------------------------

def safe_float(x: str) -> float:
    """Convert instrument string to float robustly (handles extra whitespace, etc.)."""
    return float(x.strip().split(",")[0])

# -------- Choose safe output path --------
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_path = Path(__file__).resolve().parent / f"{BASE_NAME}_{ts}.csv"

rm = pyvisa.ResourceManager()
inst = rm.open_resource(GPIB_ADDR)
inst.timeout = 20000
inst.write_termination = "\n"
inst.read_termination = "\n"

print(inst.query("*IDN?").strip())
print("Saving to:", csv_path)

# ---------- Live plot setup ----------
plt.ion()

# Figure 1: I-V
fig_iv, ax_iv = plt.subplots()
ax_iv.set_xlabel("Set Voltage (V)")
ax_iv.set_ylabel("Current (A)")
ax_iv.set_title("Live I–V Sweep (Keithley 2450)")
(line_iv,) = ax_iv.plot([], [], marker="o", linestyle="-")
ax_iv.grid(True)
fig_iv.tight_layout()

# Figure 2: I-t
fig_it, ax_it = plt.subplots()
ax_it.set_xlabel("Time (s)")
ax_it.set_ylabel("Current (A)")
ax_it.set_title("Live I–t (Keithley 2450)")
(line_it,) = ax_it.plot([], [], marker="o", linestyle="-")
ax_it.grid(True)
fig_it.tight_layout()

Vs, Is = [], []
Ts, It = [], []

t0 = time.perf_counter()
PLOT_EVERY_N = 1

try:
    # ---------- Instrument setup (2450 SMU) ----------
    inst.write("*RST")
    inst.write("*CLS")

    # Use front terminals (change to REAR if you’re wired there)
    inst.write(":ROUT:TERM FRON")

    # Source voltage, measure current
    inst.write(":SOUR:FUNC VOLT")
    inst.write(':SENS:FUNC "CURR"')

    # Source range + compliance (current limit)
    inst.write(f":SOUR:VOLT:RANG {SOURCE_RANGE}")
    inst.write(f":SOUR:VOLT:ILIM {CURRENT_LIMIT}")
    print("ILIM actually set to:", inst.query(":SOUR:VOLT:ILIM?").strip())

    # Measurement settings (optional but helpful)
    inst.write(":SENS:CURR:RANG:AUTO ON")   # autorange current
    inst.write(":SENS:CURR:NPLC 1")         # integration time (1 PLC); increase for lower noise
    inst.write(":FORM:ELEM CURR")           # make READ? return current only (clean parsing)

    # Start at 0 V, output on
    inst.write(":SOUR:VOLT 0")
    inst.write(":OUTP ON")
    time.sleep(0.5)

    # Throwaway read
    try:
        inst.query(":READ?")
    except Exception:
        pass

    # ---------- Build sweep points robustly ----------
    npts = int(round((V_STOP - V_START) / V_STEP)) + 1
    voltages = np.linspace(V_START, V_STOP, npts)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Set Voltage (V)", "Current (A)", "t (s)", "Raw READ?"])

        for i, V in enumerate(voltages, start=1):
            inst.write(f":SOUR:VOLT {V:.6f}")
            time.sleep(HOLD_TIME)

            raw = inst.query(":READ?").strip()
            curr = safe_float(raw)
            t = time.perf_counter() - t0

            Vs.append(float(V))
            Is.append(curr)
            Ts.append(t)
            It.append(curr)

            writer.writerow([f"{V:.6f}", f"{curr:.12e}", f"{t:.6f}", raw])

            print(f"Vset={V:+.2f} V | I={curr:+.3e} A | t={t:7.2f} s")

            if (i % PLOT_EVERY_N) == 0:
                # I-V
                line_iv.set_data(Vs, Is)
                ax_iv.relim()
                ax_iv.autoscale_view()
                fig_iv.canvas.draw()
                fig_iv.canvas.flush_events()

                # I-t
                line_it.set_data(Ts, It)
                ax_it.relim()
                ax_it.autoscale_view()
                fig_it.canvas.draw()
                fig_it.canvas.flush_events()

finally:
    # ---------- Safe shutdown ----------
    try:
        inst.write(":SOUR:VOLT 0")
        time.sleep(0.5)
        inst.write(":OUTP OFF")
    except Exception:
        pass

    try:
        inst.close()
    except Exception:
        pass

    plt.ioff()
    plt.show()

print("Sweep complete.")
