import re
from pathlib import Path

TARGET = Path("keithley_mini_app.py")  # change if your filename differs

def must_find(pattern: str, text: str, desc: str):
    if not re.search(pattern, text, flags=re.S):
        raise RuntimeError(f"Couldn't find spot for: {desc}\nPattern:\n{pattern}")

def apply_patch(text: str) -> str:
    # 0) Ensure pyqtgraph import exists (you already have it, but make robust)
    if "import pyqtgraph as pg" not in text:
        text = text.replace("from pathlib import Path\n", "from pathlib import Path\n\nimport pyqtgraph as pg\n")

    # 1) Add rows buffer after x/y buffers in MainWindow.__init__
    # Look for the x/y buffers initialisation.
    pat_xy = r"(self\.x_data\s*=\s*\[\]\s*\n\s*self\.y_data\s*=\s*\[\]\s*)"
    must_find(pat_xy, text, "MainWindow x/y buffers")
    if "self.rows = []" not in text:
        text = re.sub(
            pat_xy,
            r"\1\n        self.rows = []  # store incoming rows for replot when axes change\n",
            text,
            flags=re.S
        )

    # 2) Add axis dropdown widgets after mode_combo is created in __init__
    pat_mode_combo = r"(self\.mode_combo\s*=\s*QtWidgets\.QComboBox\(\)\s*\n\s*self\.mode_combo\.addItems\(\[.*?\]\)\s*)"
    must_find(pat_mode_combo, text, "mode_combo creation")
    if "self.xaxis_combo" not in text:
        insert_axes_widgets = r"""\1

        # Live plot axis selection
        self.xaxis_combo = QtWidgets.QComboBox()
        self.yaxis_combo = QtWidgets.QComboBox()

        axis_options = [
            ("Auto", "AUTO"),
            ("Time (s)", "elapsed_s"),
            ("Set value", "set_value"),
            ("Measured value", "measured_value"),
        ]
        for label, key in axis_options:
            self.xaxis_combo.addItem(label, key)
            self.yaxis_combo.addItem(label, key)

        # default: Y = measured
        self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))

        self.xaxis_combo.currentIndexChanged.connect(self.replot_from_rows)
        self.yaxis_combo.currentIndexChanged.connect(self.replot_from_rows)
"""
        text = re.sub(pat_mode_combo, insert_axes_widgets, text, flags=re.S)

    # 3) Add layout row for axis dropdowns after the Mode row is added
    pat_mode_row = r"(layout\.addWidget\(QtWidgets\.QLabel\(\"Mode\"\),\s*row,\s*0\)\s*\n\s*layout\.addWidget\(self\.mode_combo,\s*row,\s*1\)\s*)"
    must_find(pat_mode_row, text, "Mode row in layout")
    if "Live plot X" not in text:
        insert_axes_row = r"""\1

        row += 1
        layout.addWidget(QtWidgets.QLabel("Live plot X"), row, 0)
        layout.addWidget(self.xaxis_combo, row, 1)
        layout.addWidget(QtWidgets.QLabel("Live plot Y"), row, 2)
        layout.addWidget(self.yaxis_combo, row, 3)
"""
        text = re.sub(pat_mode_row, insert_axes_row, text, flags=re.S)

    # 4) Insert helper functions into MainWindow class (before main())
    # We'll add them just before "def main():" which is outside the class.
    pat_before_main = r"\n(def main\(\):)"
    must_find(pat_before_main, text, "def main()")
    if "def set_plot_defaults_for_mode" not in text:
        helpers = r"""

    def set_plot_defaults_for_mode(self, mode: str):
        """ + '"""Set smart default axes + labels based on run mode."""' + r"""
        if mode == "IV_SWEEP":
            self.xaxis_combo.setCurrentIndex(self.xaxis_combo.findData("set_value"))
            self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))
            self.plot.setLabel("bottom", "Voltage (V)")
            self.plot.setLabel("left", "Current (A)")

        elif mode == "VI_SWEEP":
            self.xaxis_combo.setCurrentIndex(self.xaxis_combo.findData("set_value"))
            self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))
            self.plot.setLabel("bottom", "Current (A)")
            self.plot.setLabel("left", "Voltage (V)")

        elif mode == "HOLD_V":
            self.xaxis_combo.setCurrentIndex(self.xaxis_combo.findData("elapsed_s"))
            self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))
            self.plot.setLabel("bottom", "Time (s)")
            self.plot.setLabel("left", "Current (A)")

        elif mode == "HOLD_I":
            self.xaxis_combo.setCurrentIndex(self.xaxis_combo.findData("elapsed_s"))
            self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))
            self.plot.setLabel("bottom", "Time (s)")
            self.plot.setLabel("left", "Voltage (V)")

        else:
            self.xaxis_combo.setCurrentIndex(self.xaxis_combo.findData("set_value"))
            self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))

    def get_xy_from_row(self, row: dict):
        x_key = self.xaxis_combo.currentData()
        y_key = self.yaxis_combo.currentData()

        # AUTO behaviour
        if x_key == "AUTO" or y_key == "AUTO":
            mode = row.get("mode", "")
            if mode in ("HOLD_V", "HOLD_I"):
                x_key = "elapsed_s"
                y_key = "measured_value"
            else:
                x_key = "set_value"
                y_key = "measured_value"

        x = float(row[x_key])
        y = float(row[y_key])
        return x, y

    @QtCore.Slot()
    def replot_from_rows(self):
        """ + '"""Rebuild plot from stored rows (axes changed mid-run)."""' + r"""
        self.x_data = []
        self.y_data = []
        for row in self.rows:
            x, y = self.get_xy_from_row(row)
            self.x_data.append(x)
            self.y_data.append(y)
        self.curve.setData(self.x_data, self.y_data)
"""
        text = re.sub(pat_before_main, helpers + r"\n\1", text, flags=re.S)

    # 5) In start_run(): reset rows + set defaults for mode
    # Find where you reset table/x/y/curve; we’ll extend it.
    pat_reset_block = r"(self\.table\.setRowCount\(0\)\s*\n\s*self\.x_data\s*=\s*\[\]\s*\n\s*self\.y_data\s*=\s*\[\]\s*\n\s*self\.curve\.setData\(\[\],\s*\[\]\)\s*)"
    must_find(pat_reset_block, text, "start_run plot reset block")
    if "self.rows = []" not in re.search(pat_reset_block, text, flags=re.S).group(1):
        replacement = r"""self.table.setRowCount(0)
        self.rows = []
        self.x_data = []
        self.y_data = []
        self.curve.setData([], [])

        # Smart plot defaults based on mode
        self.set_plot_defaults_for_mode(mode)
        self.plot.enableAutoRange(True, True)
"""
        text = re.sub(pat_reset_block, replacement, text, flags=re.S)

    # 6) In on_point(): store row then plot chosen axes
    # We’ll replace the existing plot-update block if present; if not, we append.
    pat_on_point = r"(@QtCore\.Slot\(dict\)\s*\n\s*def on_point\(self,\s*row:\s*dict\):.*?self\.table\.scrollToBottom\(\)\s*)"
    must_find(pat_on_point, text, "on_point() body start")
    on_point_head = re.search(pat_on_point, text, flags=re.S).group(1)

    # Remove any existing "Update plot" lines inside on_point to prevent duplicates
    pat_existing_plot = r"\n\s*# Update plot.*?(?=\n\s*@QtCore\.Slot|\n\s*def on_done_ok|\n\s*def on_done_err|\n\s*def cleanup_runner|\n\s*def main\(|\Z)"
    text = re.sub(pat_existing_plot, "\n", text, flags=re.S)

    # Now ensure our plot update block exists
    if "self.rows.append(row)" not in text:
        insert_after_scroll = on_point_head + r"""
        # Store row for replotting
        self.rows.append(row)

        # Update plot based on selected axes
        x, y = self.get_xy_from_row(row)
        self.x_data.append(x)
        self.y_data.append(y)
        self.curve.setData(self.x_data, self.y_data)
"""
        text = re.sub(pat_on_point, insert_after_scroll, text, flags=re.S)

    return text

def main():
    if not TARGET.exists():
        raise FileNotFoundError(f"Can't find {TARGET.resolve()}")

    original = TARGET.read_text(encoding="utf-8", errors="ignore")
    patched = apply_patch(original)

    backup = TARGET.with_suffix(".py.bak")
    backup.write_text(original, encoding="utf-8")
    TARGET.write_text(patched, encoding="utf-8")

    print(f"Patched: {TARGET}")
    print(f"Backup : {backup}")
    print("Done. Run your app again.")

if __name__ == "__main__":
    main()
