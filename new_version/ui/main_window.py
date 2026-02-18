import sys
from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from ..config import RunConfig
from ..runner import Runner
from ..visa_utils import visa_list_resources


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Keithley Mini (2450 + 6487) — GPIB")
        self.resize(1180, 680)

        self.runner = None
        self.rows: list[dict] = []
        self.x_data: list[float] = []
        self.y_data: list[float] = []

        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        layout = QtWidgets.QGridLayout(w)

        # ---- Widgets ----
        self.inst_combo = QtWidgets.QComboBox()
        self.inst_combo.addItems(["2450", "6487"])
        self.inst_combo.currentTextChanged.connect(self.on_instrument_changed)

        self.resource_combo = QtWidgets.QComboBox()
        self.scan_btn = QtWidgets.QPushButton("Scan VISA")
        self.scan_btn.clicked.connect(self.scan_resources)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["IV_SWEEP", "VI_SWEEP", "HOLD_V", "HOLD_I"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)

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
        self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))
        self.xaxis_combo.currentIndexChanged.connect(self.replot_from_rows)
        self.yaxis_combo.currentIndexChanged.connect(self.replot_from_rows)

        self.scale_combo = QtWidgets.QComboBox()
        self.scale_combo.addItem("Linear", "LIN")
        self.scale_combo.addItem("Log X", "LOGX")
        self.scale_combo.addItem("Log Y", "LOGY")
        self.scale_combo.addItem("Log X & Y", "LOGXY")
        self.scale_combo.currentIndexChanged.connect(self.apply_plot_scale)

        self.abslog_chk = QtWidgets.QCheckBox("Log uses abs()")
        self.abslog_chk.setChecked(True)
        self.abslog_chk.stateChanged.connect(self.replot_from_rows)

        self.range_label = QtWidgets.QLabel("6487 source range")
        self.range_combo = QtWidgets.QComboBox()
        self.range_combo.addItem("Auto", 0.0)
        self.range_combo.addItem("50 V", 50.0)
        self.range_combo.addItem("500 V", 500.0)

        self.start_label = QtWidgets.QLabel("Start (V or A)")
        self.stop_label = QtWidgets.QLabel("Stop (V or A)")
        self.step_label = QtWidgets.QLabel("Step (V or A)")
        self.dwell_label = QtWidgets.QLabel("Dwell per point (s)")

        self.start_edit = QtWidgets.QDoubleSpinBox(); self.start_edit.setRange(-1e6, 1e6); self.start_edit.setDecimals(6)
        self.stop_edit  = QtWidgets.QDoubleSpinBox(); self.stop_edit.setRange(-1e6, 1e6);  self.stop_edit.setDecimals(6)
        self.step_edit  = QtWidgets.QDoubleSpinBox(); self.step_edit.setRange(1e-12, 1e6);  self.step_edit.setDecimals(12); self.step_edit.setValue(0.5)
        self.dwell_edit = QtWidgets.QDoubleSpinBox(); self.dwell_edit.setRange(0, 3600); self.dwell_edit.setDecimals(3); self.dwell_edit.setValue(0.2)

        self.duration_label = QtWidgets.QLabel("Hold duration (s) (0 = until Stop)")
        self.sample_label = QtWidgets.QLabel("Sample period (s)")

        self.duration_edit = QtWidgets.QDoubleSpinBox(); self.duration_edit.setRange(0, 1e7); self.duration_edit.setDecimals(3); self.duration_edit.setValue(0.0)
        self.sample_edit   = QtWidgets.QDoubleSpinBox(); self.sample_edit.setRange(0.001, 3600); self.sample_edit.setDecimals(3); self.sample_edit.setValue(0.2)

        self.comp_label = QtWidgets.QLabel("Compliance (2450: A/V) / 6487: ILIM (A)")
        self.comp_edit = QtWidgets.QDoubleSpinBox(); self.comp_edit.setRange(0, 1e6); self.comp_edit.setDecimals(12)
        self.comp_edit.setValue(2.5e-5)

        self.nplc_label = QtWidgets.QLabel("NPLC")
        self.nplc_edit = QtWidgets.QDoubleSpinBox(); self.nplc_edit.setRange(0.001, 50.0); self.nplc_edit.setDecimals(3); self.nplc_edit.setValue(1.0)

        self.autorange_chk = QtWidgets.QCheckBox("Auto-range")
        self.autorange_chk.setChecked(True)

        self.save_dir_edit = QtWidgets.QLineEdit(str(Path.cwd() / "runs"))
        self.browse_btn = QtWidgets.QPushButton("Browse…")
        self.browse_btn.clicked.connect(self.browse_dir)

        self.run_btn = QtWidgets.QPushButton("Run")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.start_run)
        self.stop_btn.clicked.connect(self.stop_run)

        self.status = QtWidgets.QLabel("Ready.")

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "timestamp", "elapsed_s", "mode", "set_value", "measured_value", "instrument", "resource"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True)
        self.curve = self.plot.plot([], [], symbol='o')

        # ---- Layout ----
        row = 0
        layout.addWidget(QtWidgets.QLabel("Instrument"), row, 0)
        layout.addWidget(self.inst_combo, row, 1)
        layout.addWidget(QtWidgets.QLabel("VISA Resource"), row, 2)
        layout.addWidget(self.resource_combo, row, 3)
        layout.addWidget(self.scan_btn, row, 4)

        row += 1
        layout.addWidget(QtWidgets.QLabel("Mode"), row, 0)
        layout.addWidget(self.mode_combo, row, 1)

        row += 1
        layout.addWidget(QtWidgets.QLabel("Live plot X"), row, 0)
        layout.addWidget(self.xaxis_combo, row, 1)
        layout.addWidget(QtWidgets.QLabel("Live plot Y"), row, 2)
        layout.addWidget(self.yaxis_combo, row, 3)
        layout.addWidget(QtWidgets.QLabel("Scale"), row, 4)
        scale_row = QtWidgets.QHBoxLayout()
        scale_row.addWidget(self.scale_combo)
        scale_row.addWidget(self.abslog_chk)
        scale_widget = QtWidgets.QWidget()
        scale_widget.setLayout(scale_row)
        layout.addWidget(scale_widget, row, 5)

        row += 1
        layout.addWidget(self.range_label, row, 0)
        layout.addWidget(self.range_combo, row, 1)

        row += 1
        layout.addWidget(self.start_label, row, 0)
        layout.addWidget(self.start_edit, row, 1)
        layout.addWidget(self.stop_label, row, 2)
        layout.addWidget(self.stop_edit, row, 3)

        row += 1
        layout.addWidget(self.step_label, row, 0)
        layout.addWidget(self.step_edit, row, 1)
        layout.addWidget(self.dwell_label, row, 2)
        layout.addWidget(self.dwell_edit, row, 3)

        row += 1
        layout.addWidget(self.duration_label, row, 0)
        layout.addWidget(self.duration_edit, row, 1)
        layout.addWidget(self.sample_label, row, 2)
        layout.addWidget(self.sample_edit, row, 3)

        row += 1
        layout.addWidget(self.comp_label, row, 0)
        layout.addWidget(self.comp_edit, row, 1)
        layout.addWidget(self.nplc_label, row, 2)
        layout.addWidget(self.nplc_edit, row, 3)
        layout.addWidget(self.autorange_chk, row, 4)

        row += 1
        layout.addWidget(QtWidgets.QLabel("Save root folder"), row, 0)
        layout.addWidget(self.save_dir_edit, row, 1, 1, 3)
        layout.addWidget(self.browse_btn, row, 4)

        row += 1
        layout.addWidget(self.run_btn, row, 3)
        layout.addWidget(self.stop_btn, row, 4)

        row += 1
        layout.addWidget(self.status, row, 0, 1, 6)

        row += 1
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, row, 0, 1, 6)

        # Defaults
        self.scan_resources()
        self.set_default_resources()
        self.on_instrument_changed(self.inst_combo.currentText())
        self.on_mode_changed(self.mode_combo.currentText())
        self.apply_plot_scale()

    # ---- UI behaviour ----
    def set_default_resources(self):
        preferred_2450 = "GPIB0::13::INSTR"
        preferred_6487 = "GPIB0::22::INSTR"
        resources = [self.resource_combo.itemText(i) for i in range(self.resource_combo.count())]
        if preferred_2450 not in resources:
            self.resource_combo.addItem(preferred_2450)
        if preferred_6487 not in resources:
            self.resource_combo.addItem(preferred_6487)

    def scan_resources(self):
        self.resource_combo.clear()
        try:
            res = visa_list_resources()
            gpib = [r for r in res if "GPIB" in r]
            other = [r for r in res if "GPIB" not in r]
            for r in gpib + other:
                self.resource_combo.addItem(r)
            self.status.setText(f"Found {len(res)} VISA resources.")
        except Exception as e:
            self.status.setText(f"VISA scan error: {e}")

    def browse_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select save folder", self.save_dir_edit.text())
        if d:
            self.save_dir_edit.setText(d)

    def on_instrument_changed(self, inst: str):
        if inst == "6487":
            for i in range(self.mode_combo.count()):
                text = self.mode_combo.itemText(i)
                enabled = text not in ("VI_SWEEP", "HOLD_I")
                self.mode_combo.model().item(i).setEnabled(enabled)
            if self.mode_combo.currentText() in ("VI_SWEEP", "HOLD_I"):
                self.mode_combo.setCurrentText("IV_SWEEP")

            self.range_label.setVisible(True)
            self.range_combo.setVisible(True)

            if self.comp_edit.value() < 1e-6:
                self.comp_edit.setValue(2.5e-5)
        else:
            for i in range(self.mode_combo.count()):
                self.mode_combo.model().item(i).setEnabled(True)
            self.range_label.setVisible(False)
            self.range_combo.setVisible(False)

        preferred = "GPIB0::13::INSTR" if inst == "2450" else "GPIB0::22::INSTR"
        idx = self.resource_combo.findText(preferred)
        if idx >= 0:
            self.resource_combo.setCurrentIndex(idx)

    def on_mode_changed(self, mode: str):
        is_hold = mode in ("HOLD_V", "HOLD_I")
        is_vi = mode == "VI_SWEEP"

        if mode == "HOLD_V":
            self.start_label.setText("Set voltage (V)")
        elif mode == "HOLD_I":
            self.start_label.setText("Set current (A)")
        elif mode == "VI_SWEEP":
            self.start_label.setText("Start current (A)")
        else:
            self.start_label.setText("Start voltage (V)")

        if is_vi:
            self.stop_label.setText("Stop current (A)")
            self.step_label.setText("Step current (A)")
        else:
            self.stop_label.setText("Stop voltage (V)")
            self.step_label.setText("Step voltage (V)")

        self.stop_label.setVisible(not is_hold)
        self.stop_edit.setVisible(not is_hold)
        self.step_label.setVisible(not is_hold)
        self.step_edit.setVisible(not is_hold)
        self.dwell_label.setVisible(not is_hold)
        self.dwell_edit.setVisible(not is_hold)

        self.duration_label.setVisible(is_hold)
        self.duration_edit.setVisible(is_hold)
        self.sample_label.setVisible(is_hold)
        self.sample_edit.setVisible(is_hold)

        if is_hold:
            self.stop_edit.setValue(0.0)

        self.set_plot_defaults_for_mode(mode)
        self.apply_plot_scale()

    # ---- Plot helpers ----
    def apply_plot_scale(self):
        mode = self.scale_combo.currentData()
        logx = mode in ("LOGX", "LOGXY")
        logy = mode in ("LOGY", "LOGXY")
        self.plot.setLogMode(x=logx, y=logy)
        self.replot_from_rows()

    def set_plot_defaults_for_mode(self, mode: str):
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
        self.replot_from_rows()

    def get_xy_from_row(self, row: dict):
        x_key = self.xaxis_combo.currentData()
        y_key = self.yaxis_combo.currentData()
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
        self.x_data = []
        self.y_data = []

        log_mode = self.scale_combo.currentData()
        logx = log_mode in ("LOGX", "LOGXY")
        logy = log_mode in ("LOGY", "LOGXY")
        use_abs = self.abslog_chk.isChecked()

        for r in self.rows:
            x, y = self.get_xy_from_row(r)
            x_plot = abs(x) if (logx and use_abs) else x
            y_plot = abs(y) if (logy and use_abs) else y
            if logx and x_plot <= 0:
                continue
            if logy and y_plot <= 0:
                continue
            self.x_data.append(x_plot)
            self.y_data.append(y_plot)

        self.curve.setData(self.x_data, self.y_data)

    # ---- Run control ----
    def start_run(self):
        if self.runner is not None:
            return

        inst = self.inst_combo.currentText()
        resource = self.resource_combo.currentText().strip()
        mode = self.mode_combo.currentText()

        cfg = RunConfig(
            instrument=inst,
            resource=resource,
            mode=mode,
            start=float(self.start_edit.value()),
            stop=float(self.stop_edit.value()),
            step=float(self.step_edit.value()),
            dwell_s=float(self.dwell_edit.value()),
            duration_s=float(self.duration_edit.value()),
            sample_period_s=float(self.sample_edit.value()),
            compliance=float(self.comp_edit.value()),
            nplc=float(self.nplc_edit.value()),
            autorange=bool(self.autorange_chk.isChecked()),
            source_range_v=float(self.range_combo.currentData()) if inst == "6487" else 0.0,
        )

        if mode in ("IV_SWEEP", "VI_SWEEP") and cfg.step <= 0:
            self.status.setText("Step must be > 0 for sweeps.")
            return

        self.table.setRowCount(0)
        self.rows = []
        self.x_data = []
        self.y_data = []
        self.curve.setData([], [])

        self.set_plot_defaults_for_mode(mode)
        self.apply_plot_scale()
        self.plot.enableAutoRange(True, True)

        save_root = Path(self.save_dir_edit.text())
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_folder = save_root / f"{inst}_{mode}_{stamp}"
        self.status.setText(f"Running… saving to {run_folder}")

        self.runner = Runner(cfg, run_folder)
        self.runner.point_acquired.connect(self.on_point)
        self.runner.finished_ok.connect(self.on_done_ok)
        self.runner.finished_err.connect(self.on_done_err)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.runner.start()

    def stop_run(self):
        if self.runner is not None:
            self.status.setText("Stopping… (will switch output off safely)")
            self.runner.stop()

    @QtCore.Slot(dict)
    def on_point(self, row: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)
        cols = ["timestamp", "elapsed_s", "mode", "set_value", "measured_value", "instrument", "resource"]
        for c, k in enumerate(cols):
            self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(row.get(k, ""))))
        self.table.scrollToBottom()

        self.rows.append(row)

        x, y = self.get_xy_from_row(row)
        log_mode = self.scale_combo.currentData()
        logx = log_mode in ("LOGX", "LOGXY")
        logy = log_mode in ("LOGY", "LOGXY")
        use_abs = self.abslog_chk.isChecked()

        x_plot = abs(x) if (logx and use_abs) else x
        y_plot = abs(y) if (logy and use_abs) else y
        if logx and x_plot <= 0:
            return
        if logy and y_plot <= 0:
            return

        self.x_data.append(x_plot)
        self.y_data.append(y_plot)
        self.curve.setData(self.x_data, self.y_data)

    @QtCore.Slot(str)
    def on_done_ok(self, msg: str):
        self.status.setText(msg)
        self.cleanup_runner()

    @QtCore.Slot(str)
    def on_done_err(self, msg: str):
        self.status.setText(f"ERROR: {msg}")
        self.cleanup_runner()

    def cleanup_runner(self):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.runner = None
