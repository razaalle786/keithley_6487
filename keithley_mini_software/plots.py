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
    "xtick.labelsize": 30,
    "ytick.labelsize": 30,
    "legend.fontsize": 30,
    "lines.linewidth": 3.0,
    "figure.autolayout": True
})

# -------- USER: Add your CSV files here --------
csv_files = [
    r"mf_setup0T_underRoomLight/6487_IV_SWEEP_20260218_132139/CZT_planar_0to400V_1Vstep_1sdelay_0T.csv",
    r"mf_setup60mT_underRoomLight/6487_IV_SWEEP_20260218_133447/CZT_planar_0to400V_1Vstep_1sdelay_60mT.csv",
    # r"more_data.csv",
]

# Optional custom legend labels (same order as csv_files).
# If None or empty, filenames will be used automatically.
labels = [
    "At 0 T - room light ",
    "at 60 mT - room light",
    # "Condition 3",
]
# -----------------------------------------------

def find_column(df, candidates):
    """Return the first matching column name from candidates (case/space insensitive)."""
    norm = {c.lower().replace(" ", "").replace("-", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace(" ", "").replace("-", "").replace("_", "")
        if key in norm:
            return norm[key]
    return None

fig, ax = plt.subplots()

ax.set_xlabel("Applied bias (V)", fontsize =30)
ax.set_ylabel("Current (A)" , fontsize =30)
ax.grid(False)

# If labels not provided (or wrong length), fall back to file stem names
use_auto_labels = (not labels) or (len(labels) != len(csv_files))

for i, file in enumerate(csv_files):
    path = Path(file)

    df = pd.read_csv(path)

    # Flexible column matching
    v_col = find_column(df, ["set_value", "set value", "setvoltage", "set voltage", "voltage", "bias"])
    i_col = find_column(df, ["measured_value", "measured value", "current", "i", "measuredcurrent", "measured current"])

    if v_col is None or i_col is None:
        raise KeyError(
            f"\nIn file: {path}\n"
            f"Could not find required columns.\n"
            f"Found columns: {list(df.columns)}\n"
            f"Expected something like: set_value and measured_value."
        )

    V = pd.to_numeric(df[v_col], errors="coerce")
    I = pd.to_numeric(df[i_col], errors="coerce")

    # Drop non-numeric rows safely
    mask = V.notna() & I.notna()
    V, I = V[mask], I[mask]

    label = path.stem if use_auto_labels else labels[i]

    ax.plot(V, I, marker="o", linestyle="-", label=label)

ax.legend()
plt.yscale('log')
plt.tight_layout()
plt.show()
