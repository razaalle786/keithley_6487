import re
from pathlib import Path

TARGET = Path("keithley_mini_app.py")  # change if needed

def backup_file(path: Path):
    bak = path.with_suffix(path.suffix + ".bak")
    bak.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    return bak

def insert_after(text: str, pattern: str, insertion: str, desc: str) -> str:
    m = re.search(pattern, text, flags=re.S)
    if not m:
        raise RuntimeError(f"Couldn't find insertion point: {desc}\nPattern:\n{pattern}")
    idx = m.end()
    return text[:idx] + insertion + text[idx:]

def replace_block(text: str, pattern: str, replacement: str, desc: str, count=1) -> str:
    new_text, n = re.subn(pattern, replacement, text, flags=re.S, count=count)
    if n == 0:
        raise RuntimeError(f"Couldn't replace block: {desc}\nPattern:\n{pattern}")
    return new_text

def apply_patch(text: str) -> str:
    # Ensure pyqtgraph import exists
    if "import pyqtgraph as pg" not in text:
        text = text.replace(
            "from pathlib import Path\n",
            "from pathlib import Path\n\nimport pyqtgraph as pg\n"
        )

    # 1) Ensure MainWindow has buffers (x_data/y_data) and add rows buffer
    pat_main_init = r"class MainWindow\(QtWidgets\.QMainWindow\):\s*\n\s*def __init__\(self\):"
    if not re.search(pat_main_init, text):
        raise RuntimeError("Couldn't find MainWindow.__init__")

    # Add rows buffer right after first occurrence of x_data/y_data init (or create them if missing)
    if "self.x_data" in text and "self.y_data" in text:
        pat_xy = r"(self\.x_data\s*=\s*\[\]\s*\n\s*self\.y_data\s*=\s*\[\]\s*)"
        if re.search(pat_xy, text, flags=re.S) and "self.rows" not in text:
            text = re.sub(
                pat_xy,
                r"\1\n        self.rows = []  # store incoming rows for replot when axes change\n",
                text,
                flags=re.S,
                count=1
            )
    else:
        # Insert near top of __init__
        pat_after_title = r"(self\.setWindowTitle\([^\)]*\)\s*\n\s*self\.resize\([^\)]*\)\s*)"
        text = insert_after(
            text,
            pat_after_title,
            "\n        # Data buffers for plot\n        self.x_data = []\n        self.y_data = []\n        self.rows = []  # store incoming rows for replot when axes change\n",
            "after window title/resize"
        )

    # 2) Add axis dropdown widgets after mode_combo creation
    if "self.xaxis_combo" not in text:
        pat_mode_combo = r"(self\.mode_combo\s*=\s*QtWidgets\.QComboBox\(\)\s*\n\s*self\.mode_combo\.addItems\(\[.*?\]\)\s*)"
        text = insert_after(
            text,
            pat_mode_combo,
            """

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
""",
            "after mode_combo"
        )

    # 3) Add layout row for dropdowns after the Mode row
    if "Live plot X" not in text:
        pat_mode_row = r"(layout\.addWidget\(QtWidgets\.QLabel\(\"Mode\"\),\s*row,\s*0\)\s*\n\s*layout\.addWidget\(self\.mode_combo,\s*row,\s*1\)\s*)"
        text = insert_after(
            text,
            pat_mode_row,
            """

        row += 1
        layout.addWidget(QtWidgets.QLabel("Live plot X"), row, 0)
        layout.addWidget(self.xaxis_combo, row, 1)
        layout.addWidget(QtWidgets.QLabel("Live plot Y"), row, 2)
        layout.addWidget(self.yaxis_combo, row, 3)
""",
            "after Mode layout row"
        )

    # 4) Remove the WRONG block where plot is created inside on_point (if present)
    # This matches common accidental block content.
    pat_wrong_plot_in_on_point = r"""
\s*# ---- Live plot \(pyqtgraph\) ----\s*
\s*self\.x_data\s*=\s*\[\]\s*
\s*self\.y_data\s*=\s*\[\]\s*

\s*self\.plot\s*=\s*pg\.PlotWidget\(\)\s*
\s*self\.plot\.showGrid\(x=True,\s*y=True\)\s*
\s*self\.curve\s*=\s*self\.plot\.plot\(\[\],\s*\[\],\s*symbol='o'\)\s*
\s*self\.plot\.setLabel\('bottom',\s*'X'\)\s*
\s*self\.plot\.setLabel\('left',\s*'Y'\)\s*
"""
    text = re.sub(pat_wrong_plot_in_on_point, "\n", text, flags=re.S)

    # 5) Ensure live plot widget exists in __init__ (if missing)
    if "self.plot = pg.PlotWidget()" not in text:
        # Insert after table creation (first occurrence of "self.table = QtWidgets.QTableWidget")
        pat_table = r"(self\.table\s*=\s*QtWidgets\.QTableWidget\(0,\s*\d+\)\s*\n.*?self\.table\.horizontalHeader\(\)\.setStretchLastSection\(True\)\s*)"
        text = insert_after(
            text,
            pat_table,
            """

        # Live plot widget
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True)
        self.curve = self.plot.plot([], [], symbol='o')
        self.plot.setLabel('bottom', 'X')
        self.plot.setLabel('left', 'Y')
""",
            "after table setup"
        )

    # 6) Make sure splitter uses self.plot correctly (if splitter exists but plot not included)
    # If splitter already has plot, leave it.
    if "splitter.addWidget(self.plot)" not in text:
        pat_splitter = r"(splitter\s*=\s*QtWidgets\.QSplitter\(QtCore\.Qt\.Horizontal\)\s*\n\s*splitter\.addWidget\(self\.table\)\s*)"
        if re.search(pat_splitter, text, flags=re.S):
            text = re.sub(
                pat_splitter,
                r"\1\n        splitter.addWidget(self.plot)\n",
                text,
                flags=re.S,
                count=1
            )

    # 7) Add helper methods into MainWindow (before def main())
    if "def set_plot_defaults_for_mode" not in text:
        pat_before_main = r"\n(def main\(\):)"
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

        return float(row[x_key]), float(row[y_key])

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
        text = insert_after(text, pat_before_main, helpers, "before def main()")

    # 8) Patch start_run() to reset rows/plot and set defaults
    # Insert right after "self.table.setRowCount(0)" inside start_run.
    pat_start_run_reset = r"(def start_run\(self\):.*?self\.table\.setRowCount\(0\)\s*)"
    if re.search(pat_start_run_reset, text, flags=re.S):
        # Only insert if not already present
        if "self.rows = []" not in re.search(pat_start_run_reset, text, flags=re.S).group(1):
            text = insert_after(
                text,
                pat_start_run_reset,
                """
        self.rows = []
        self.x_data = []
        self.y_data = []
        self.curve.setData([], [])

        self.set_plot_defaults_for_mode(mode)
        self.plot.enableAutoRange(True, True)
""",
                "after self.table.setRowCount(0) in start_run"
            )
    else:
        raise RuntimeError("Couldn't find start_run() reset insertion point")

    # 9) Patch on_point() to store row and update plot
    # Insert right after self.table.scrollToBottom()
    pat_on_point_scroll = r"(def on_point\(self,\s*row:\s*dict\):.*?self\.table\.scrollToBottom\(\)\s*)"
    if re.search(pat_on_point_scroll, text, flags=re.S):
        # Avoid duplicate insertion
        if "self.rows.append(row)" not in text:
            text = insert_after(
                text,
                pat_on_point_scroll,
                """
        # Store row for replotting
        self.rows.append(row)

        # Update plot based on selected axes
        x, y = self.get_xy_from_row(row)
        self.x_data.append(x)
        self.y_data.append(y)
        self.curve.setData(self.x_data, self.y_data)
""",
                "after scrollToBottom() in on_point"
            )
    else:
        raise RuntimeError("Couldn't find on_point() insertion point")

    return text

def main():
    if not TARGET.exists():
        raise FileNotFoundError(f"Can't find {TARGET.resolve()}")

    original = TARGET.read_text(encoding="utf-8", errors="ignore")
    patched = apply_patch(original)

    bak = backup_file(TARGET)
    TARGET.write_text(patched, encoding="utf-8")

    print(f"Patched: {TARGET}")
    print(f"Backup : {bak}")
    print("Done. Now run: python keithley_mini_app.py")

if __name__ == "__main__":
    main()
