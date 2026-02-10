import time
import csv
import pyvisa
from pathlib import Path
from datetime import datetime

import matplotlib.pyplot as plt

# ---------------- USER SETTINGS ----------------
GPIB_ADDR = "GPIB0::22::INSTR"

BIAS_VOLTAGE = 5.0          # volts (constant bias)
MEAS_INTERVAL = 1.0         # seconds between readings
DURATION_S = 300            # total duration in seconds (e.g. 300 = 5 min)

# 6487 note: ILIM is quantised; always query back what it actually set.
CURRENT_LIMIT = 2.5e-5      # 25 µA (safe default; change to 2.5e-4 for 250 µA if needed)
SOURCE_RANGE = 50           # 50 V range is fine for up to ±50 V

BASE_NAME = "I_vs_t_constant_bias"
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
csv_path = Path(__file__).resolve().parent / f"{BASE_NAME}_{BIAS_VOLTAGE:+.1f}V_{ts}.csv"

rm = pyvisa.ResourceManager()
inst = rm.open_resource(GPIB_ADDR)
inst.timeout = 20000

print(inst.query("*IDN?").strip())
print("Saving to:", csv_path)

# ---------- Live plot setup (I vs t) ----------
plt.ion()
fig, ax = plt.subplots()
ax.set_xlabel("Time (s)")
ax.set_ylabel("Current (A)")
ax.set_title(f"Live I–t @ {BIAS_VOLTAGE:+.2f} V (Keithley 6487)")
(line,) = ax.plot([], [], marker="o", linestyle="-")
ax.grid(True)
fig.tight_layout()

Ts, Is = [], []
t0 = time.perf_counter()

# Optional: throttle plot refresh if you want
PLOT_EVERY_N = 1  # set to 5 to refresh every 5 points

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

    # Enable source and apply constant bias
    inst.write("SOUR:VOLT 0")
    inst.write("SOUR:VOLT:STAT ON")
    time.sleep(0.5)

    inst.write(f"SOUR:VOLT {BIAS_VOLTAGE:.6f}")
    time.sleep(1.0)

    # Throwaway read to avoid first-read overflow artefact
    try:
        inst.query("READ?")
    except Exception:
        pass

    # ---------- Logging ----------
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t (s)", "Bias Set (V)", "Current (A)", "Status", "Raw READ?"])

        npts = int(DURATION_S / MEAS_INTERVAL) + 1

        for i in range(1, npts + 1):
            # Keep a steady cadence
            t_now = time.perf_counter() - t0

            raw = inst.query("READ?").strip()
            curr, stat, _ = parse_read(raw)

            Ts.append(t_now)
            Is.append(curr)

            writer.writerow([f"{t_now:.6f}", f"{BIAS_VOLTAGE:.6f}", f"{curr:.12e}", f"{stat:.0f}", raw])

            print(f"t={t_now:8.2f} s | Vset={BIAS_VOLTAGE:+.2f} V | I={curr:+.3e} A | STAT={stat:.0f}")

            if (i % PLOT_EVERY_N) == 0:
                line.set_data(Ts, Is)
                ax.relim()
                ax.autoscale_view()
                fig.canvas.draw()
                fig.canvas.flush_events()

            # Sleep until next interval (simple, robust)
            time.sleep(MEAS_INTERVAL)

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

print("Done.")
