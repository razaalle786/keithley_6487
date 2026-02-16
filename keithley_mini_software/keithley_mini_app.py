import sys
import time
import json
import csv
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
import pyvisa
from PySide6 import QtCore, QtWidgets


# ---------------------------- Config models ----------------------------

@dataclass
class RunConfig:
    instrument: str               # "2450" or "6487"
    resource: str                 # VISA resource string
    mode: str                     # "IV_SWEEP", "VI_SWEEP", "HOLD_V", "HOLD_I"
    start: float = 0.0
    stop: float = 0.0
    step: float = 0.0
    dwell_s: float = 0.2
    duration_s: float = 0.0       # 0 => run until Stop for HOLD modes
    sample_period_s: float = 0.2
    compliance: float = 0.001     # A for V-source modes, V for I-source modes
    nplc: float = 1.0
    autorange: bool = True


# ---------------------------- VISA helpers ----------------------------

def visa_list_resources() -> list[str]:
    rm = pyvisa.ResourceManager()
    return list(rm.list_resources())

def open_resource(resource: str, timeout_ms: int = 10000):
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(resource)
    inst.timeout = timeout_ms
    inst.write_termination = "\n"
    inst.read_termination = "\n"
    return inst


# ---------------------------- Instrument wrappers ----------------------------

class KeithleyBase:
    def __init__(self, resource: str):
        self.resource = resource
        self.inst = None

    def connect(self):
        self.inst = open_resource(self.resource)
        return self.idn()

    def close(self):
        if self.inst is not None:
            try:
                self.output_off()
            except Exception:
                pass
            try:
                self.inst.close()
            except Exception:
                pass
        self.inst = None

    def write(self, cmd: str):
        self.inst.write(cmd)

    def query(self, cmd: str) -> str:
        return self.inst.query(cmd)

    def idn(self) -> str:
        return self.query("*IDN?").strip()

    def output_on(self):
        raise NotImplementedError

    def output_off(self):
        raise NotImplementedError

    def shutdown_safe(self):
        self.output_off()


class Keithley2450(KeithleyBase):
    def reset(self):
        self.write("*RST")
        self.write("*CLS")

    def output_on(self):
        self.write("OUTP ON")

    def output_off(self):
        self.write("OUTP OFF")

    def set_nplc_current(self, nplc: float):
        self.write(f"SENS:CURR:NPLC {nplc}")

    def set_nplc_voltage(self, nplc: float):
        self.write(f"SENS:VOLT:NPLC {nplc}")

    def source_voltage_measure_current(self, v: float, i_limit: float, autorange=True):
        self.write("SOUR:FUNC VOLT")
        self.write(f"SOUR:VOLT {v}")
        self.write(f"SENS:CURR:PROT {i_limit}")
        self.write("SENS:FUNC 'CURR'")
        self.write("SENS:CURR:RANG:AUTO ON" if autorange else "SENS:CURR:RANG:AUTO OFF")

    def source_current_measure_voltage(self, i: float, v_limit: float, autorange=True):
        self.write("SOUR:FUNC CURR")
        self.write(f"SOUR:CURR {i}")
        self.write(f"SENS:VOLT:PROT {v_limit}")
        self.write("SENS:FUNC 'VOLT'")
        self.write("SENS:VOLT:RANG:AUTO ON" if autorange else "SENS:VOLT:RANG:AUTO OFF")

    def measure_current(self) -> float:
        return float(self.query("READ?").strip())

    def measure_voltage(self) -> float:
        return float(self.query("READ?").strip())


class Keithley6487(KeithleyBase):
    def reset(self):
        self.write("*RST")
        self.write("*CLS")

    def output_on(self):
        self.write(":SOUR:VOLT:STAT ON")

    def output_off(self):
        self.write(":SOUR:VOLT:STAT OFF")

    def set_nplc(self, nplc: float):
        self.write(f":SENS:CURR:NPLC {nplc}")

    def source_voltage(self, v: float):
        self.write(f":SOUR:VOLT {v}")

    def measure_current(self) -> float:
        return float(self.query(":MEAS:CURR?").strip())


# ---------------------------- Worker thread ----------------------------

class Runner(QtCore.QThread):
    point_acquired = QtCore.Signal(dict)
    finished_ok = QtCore.Signal(str)
    finished_err = QtCore.Signal(str)

    def __init__(self, cfg: RunConfig, save_dir: Path):
        super().__init__()
        self.cfg = cfg
        self.save_dir = save_dir
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = self.save_dir / "run_config.json"
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.cfg), f, indent=2)

            csv_path = self.save_dir / "data.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as fcsv:
                writer = csv.DictWriter(fcsv, fieldnames=[
                    "timestamp", "elapsed_s", "instrument", "resource", "mode",
                    "set_value", "measured_value"
                ])
                writer.writeheader()

                # Connect instrument
                if self.cfg.instrument == "2450":
                    inst = Keithley2450(self.cfg.resource)
                    inst.connect()
                    inst.reset()
                else:
                    inst = Keithley6487(self.cfg.resource)
                    inst.connect()
                    inst.reset()

                t0 = time.time()

                def emit_and_write(set_val, meas_val):
                    row = {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "elapsed_s": round(time.time() - t0, 6),
                        "instrument": self.cfg.instrument,
                        "resource": self.cfg.resource,
                        "mode": self.cfg.mode,
                        "set_value": set_val,
                        "measured_value": meas_val,
                    }
                    writer.writerow(row)
                    fcsv.flush()
                    self.point_acquired.emit(row)

                try:
                    if self.cfg.mode == "IV_SWEEP":
                        # source V, measure I
                        if self.cfg.instrument == "2450":
                            inst.set_nplc_current(self.cfg.nplc)
                            inst.source_voltage_measure_current(0.0, self.cfg.compliance, self.cfg.autorange)
                            inst.output_on()
                            v = self.cfg.start
                            step = self.cfg.step if (self.cfg.stop >= self.cfg.start) else -abs(self.cfg.step)
                            while (v <= self.cfg.stop + 1e-12) if step > 0 else (v >= self.cfg.stop - 1e-12):
                                if self._stop:
                                    break
                                inst.source_voltage_measure_current(v, self.cfg.compliance, self.cfg.autorange)
                                time.sleep(self.cfg.dwell_s)
                                i_meas = inst.measure_current()
                                emit_and_write(v, i_meas)
                                v += step
                        else:
                            inst.set_nplc(self.cfg.nplc)
                            inst.source_voltage(0.0)
                            inst.output_on()
                            v = self.cfg.start
                            step = self.cfg.step if (self.cfg.stop >= self.cfg.start) else -abs(self.cfg.step)
                            while (v <= self.cfg.stop + 1e-12) if step > 0 else (v >= self.cfg.stop - 1e-12):
                                if self._stop:
                                    break
                                inst.source_voltage(v)
                                time.sleep(self.cfg.dwell_s)
                                i_meas = inst.measure_current()
                                emit_and_write(v, i_meas)
                                v += step

                    elif self.cfg.mode == "VI_SWEEP":
                        # source I, measure V (2450 only)
                        if self.cfg.instrument != "2450":
                            raise RuntimeError("VI sweep is only supported on the 2450.")
                        inst.set_nplc_voltage(self.cfg.nplc)
                        inst.source_current_measure_voltage(0.0, self.cfg.compliance, self.cfg.autorange)
                        inst.output_on()
                        i = self.cfg.start
                        step = self.cfg.step if (self.cfg.stop >= self.cfg.start) else -abs(self.cfg.step)
                        while (i <= self.cfg.stop + 1e-12) if step > 0 else (i >= self.cfg.stop - 1e-12):
                            if self._stop:
                                break
                            inst.source_current_measure_voltage(i, self.cfg.compliance, self.cfg.autorange)
                            time.sleep(self.cfg.dwell_s)
                            v_meas = inst.measure_voltage()
                            emit_and_write(i, v_meas)
                            i += step

                    elif self.cfg.mode == "HOLD_V":
                        # hold V, log I (duration_s <= 0 => until Stop)
                        if self.cfg.instrument == "2450":
                            inst.set_nplc_current(self.cfg.nplc)
                            inst.source_voltage_measure_current(self.cfg.start, self.cfg.compliance, self.cfg.autorange)
                            inst.output_on()
                            if self.cfg.duration_s <= 0:
                                while not self._stop:
                                    time.sleep(self.cfg.sample_period_s)
                                    i_meas = inst.measure_current()
                                    emit_and_write(self.cfg.start, i_meas)
                            else:
                                t_end = time.time() + self.cfg.duration_s
                                while time.time() < t_end and not self._stop:
                                    time.sleep(self.cfg.sample_period_s)
                                    i_meas = inst.measure_current()
                                    emit_and_write(self.cfg.start, i_meas)
                        else:
                            inst.set_nplc(self.cfg.nplc)
                            inst.source_voltage(self.cfg.start)
                            inst.output_on()
                            if self.cfg.duration_s <= 0:
                                while not self._stop:
                                    time.sleep(self.cfg.sample_period_s)
                                    i_meas = inst.measure_current()
                                    emit_and_write(self.cfg.start, i_meas)
                            else:
                                t_end = time.time() + self.cfg.duration_s
                                while time.time() < t_end and not self._stop:
                                    time.sleep(self.cfg.sample_period_s)
                                    i_meas = inst.measure_current()
                                    emit_and_write(self.cfg.start, i_meas)

                    elif self.cfg.mode == "HOLD_I":
                        # hold I, log V (2450 only) (duration_s <= 0 => until Stop)
                        if self.cfg.instrument != "2450":
                            raise RuntimeError("Hold current is only supported on the 2450.")
                        inst.set_nplc_voltage(self.cfg.nplc)
                        inst.source_current_measure_voltage(self.cfg.start, self.cfg.compliance, self.cfg.autorange)
                        inst.output_on()
                        if self.cfg.duration_s <= 0:
                            while not self._stop:
                                time.sleep(self.cfg.sample_period_s)
                                v_meas = inst.measure_voltage()
                                emit_and_write(self.cfg.start, v_meas)
                        else:
                            t_end = time.time() + self.cfg.duration_s
                            while time.time() < t_end and not self._stop:
                                time.sleep(self.cfg.sample_period_s)
                                v_meas = inst.measure_voltage()
                                emit_and_write(self.cfg.start, v_meas)

                    else:
                        raise RuntimeError(f"Unknown mode: {self.cfg.mode}")

                finally:
                    try:
                        inst.shutdown_safe()
                    finally:
                        inst.close()

            self.finished_ok.emit(f"Saved to: {self.save_dir}")
        except Exception as e:
            self.finished_err.emit(str(e))


# ---------------------------- UI ----------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Keithley Mini (2450 + 6487) — GPIB")
        self.resize(1150, 650)

        self.runner = None

        # Data buffers for plot
        self.rows: list[dict] = []
        self.x_data: list[float] = []
        self.y_data: list[float] = []

        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        layout = QtWidgets.QGridLayout(w)

        # ---------------- Widgets ----------------
        self.inst_combo = QtWidgets.QComboBox()
        self.inst_combo.addItems(["2450", "6487"])
        self.inst_combo.currentTextChanged.connect(self.on_instrument_changed)

        self.resource_combo = QtWidgets.QComboBox()
        self.scan_btn = QtWidgets.QPushButton("Scan VISA")
        self.scan_btn.clicked.connect(self.scan_resources)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["IV_SWEEP", "VI_SWEEP", "HOLD_V", "HOLD_I"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)

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
        self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))
        self.xaxis_combo.currentIndexChanged.connect(self.replot_from_rows)
        self.yaxis_combo.currentIndexChanged.connect(self.replot_from_rows)

        # Inputs
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

        self.comp_label = QtWidgets.QLabel("Compliance (A for V-source / V for I-source)")
        self.comp_edit = QtWidgets.QDoubleSpinBox(); self.comp_edit.setRange(0, 1e6); self.comp_edit.setDecimals(12); self.comp_edit.setValue(1e-6)

        self.nplc_label = QtWidgets.QLabel("NPLC")
        self.nplc_edit = QtWidgets.QDoubleSpinBox(); self.nplc_edit.setRange(0.001, 50.0); self.nplc_edit.setDecimals(3); self.nplc_edit.setValue(1.0)

        self.autorange_chk = QtWidgets.QCheckBox("Auto-range")
        self.autorange_chk.setChecked(True)

        # Save
        self.save_dir_edit = QtWidgets.QLineEdit(str(Path.cwd() / "runs"))
        self.browse_btn = QtWidgets.QPushButton("Browse…")
        self.browse_btn.clicked.connect(self.browse_dir)

        # Control
        self.run_btn = QtWidgets.QPushButton("Run")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.start_run)
        self.stop_btn.clicked.connect(self.stop_run)

        self.status = QtWidgets.QLabel("Ready.")

        # Table
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "timestamp", "elapsed_s", "mode", "set_value", "measured_value", "instrument", "resource"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)

        # Plot
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True)
        self.curve = self.plot.plot([], [], symbol='o')

        # ---------------- Layout ----------------
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
        layout.addWidget(self.status, row, 0, 1, 5)

        row += 1
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, row, 0, 1, 5)

        # Defaults
        self.scan_resources()
        self.set_default_resources()
        self.on_instrument_changed(self.inst_combo.currentText())
        self.on_mode_changed(self.mode_combo.currentText())

    # ---------------- UI behaviour ----------------

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
        # Disable unsupported modes on 6487
        if inst == "6487":
            for i in range(self.mode_combo.count()):
                text = self.mode_combo.itemText(i)
                enabled = text not in ("VI_SWEEP", "HOLD_I")
                self.mode_combo.model().item(i).setEnabled(enabled)
            if self.mode_combo.currentText() in ("VI_SWEEP", "HOLD_I"):
                self.mode_combo.setCurrentText("IV_SWEEP")
        else:
            for i in range(self.mode_combo.count()):
                self.mode_combo.model().item(i).setEnabled(True)

    def on_mode_changed(self, mode: str):
        # Adjust labels and which controls are relevant
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
        elif mode == "HOLD_I":
            self.stop_label.setText("(unused)")
            self.step_label.setText("(unused)")
        else:
            self.stop_label.setText("Stop voltage (V)")
            self.step_label.setText("Step voltage (V)")

        # Show/hide sweep-only controls
        self.stop_label.setVisible(not is_hold)
        self.stop_edit.setVisible(not is_hold)
        self.step_label.setVisible(not is_hold)
        self.step_edit.setVisible(not is_hold)
        self.dwell_label.setVisible(not is_hold)
        self.dwell_edit.setVisible(not is_hold)

        # Show/hide hold-only controls
        self.duration_label.setVisible(is_hold)
        self.duration_edit.setVisible(is_hold)
        self.sample_label.setVisible(is_hold)
        self.sample_edit.setVisible(is_hold)

        # In HOLD mode, stop/step values are irrelevant
        if is_hold:
            self.stop_edit.setValue(0.0)

        # Default plot axes and labels
        self.set_plot_defaults_for_mode(mode)

    # ---------------- Plot helpers ----------------

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

        else:
            self.xaxis_combo.setCurrentIndex(self.xaxis_combo.findData("set_value"))
            self.yaxis_combo.setCurrentIndex(self.yaxis_combo.findData("measured_value"))

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
        for r in self.rows:
            x, y = self.get_xy_from_row(r)
            self.x_data.append(x)
            self.y_data.append(y)
        self.curve.setData(self.x_data, self.y_data)

    # ---------------- Run control ----------------

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
        )

        if mode in ("IV_SWEEP", "VI_SWEEP") and cfg.step <= 0:
            self.status.setText("Step must be > 0 for sweeps.")
            return

        # Reset table + plot buffers
        self.table.setRowCount(0)
        self.rows = []
        self.x_data = []
        self.y_data = []
        self.curve.setData([], [])
        self.set_plot_defaults_for_mode(mode)
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
        self.x_data.append(x)
        self.y_data.append(y)
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


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
