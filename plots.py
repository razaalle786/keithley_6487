import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# =======================
# Publication Plot Style
# =======================
plt.rcParams.update({
    "figure.figsize": (11.7, 8.3),   # A4 landscape
    "axes.linewidth": 3,
    "axes.labelsize": 30,
    #"axes.labelweight": "bold",
    "xtick.labelsize": 30,
    "ytick.labelsize": 30,
    "legend.fontsize": 30,
    "lines.linewidth": 3.0,
    #"font.weight": "",
    "figure.autolayout": True
})

# -------- USER: Add your CSV files here --------
csv_files = [
    r"IV_sweep_+20V_to_-20V_0.5Vstep_1.0s_hold_2450_20260213_145419_light.csv",
    r"IV_sweep_+20V_to_-20V_0.5Vstep_1.0s_hold_2450_20260213_144930.csv",
]

# Custom legend labels (same order as files above)
labels = [
    "2450 Ligh",
    "2450 Dark"
]
# -----------------------------------------------

fig, ax = plt.subplots()

ax.set_xlabel("Set Voltage (V)", fontsize = 30)
ax.set_ylabel("Current (A)", fontsize = 30)
#ax.set_title("I–V Comparison",)
ax.grid(False)

for file, label in zip(csv_files, labels):
    path = Path(file)
    
    df = pd.read_csv(path)
    
    V = df["Set Voltage (V)"]
    I = df["Current (A)"]
    
    ax.plot(V, I, marker="o", linestyle="-", label=label)

ax.legend()
plt.tight_layout()
plt.show()
