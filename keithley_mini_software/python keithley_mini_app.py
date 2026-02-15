import sys
import time
import json
import csv
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

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
    duration_s: float = 5.0
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
        # override if you want ramp-to-zero; default just output off
        self.output_off()

class Keithley2450(KeithleyBase):
    """
    Uses TSP / SCPI-ish commands for 2450.
    Many 2450s accept both SCPI-style :SOUR and TSP "smu." commands.
    We'll use SCPI-ish ones where possible.
    """
    def reset(self):
        self.write("*RST")
        self.write("*CLS")

    def output_on(self):
        # 2450: OUTP ON
        self.write("OUTP ON")

    def output_off(self):
        self.write("OUTP OFF")

    def set_nplc_current(self, nplc: float):
        # measure current NPLC
        self.write(f"SENS:CURR:NPLC {nplc}")

    def set_nplc_voltage(self, nplc: float):
        self.write(f"SENS:VOLT:NPLC {nplc}")

    def source_voltage_measure_current(self, v: float, i_limit: float, autorange=True):
        self.write("SOUR:FUNC VOLT")
        self.write(f"SOUR:VOLT {v}")
        self.write(f"SENS:CURR:PROT {i_limit}")  # current compliance
        self.write("SENS:FUNC 'CURR'")
        if autorange:
            self.write("SENS:CURR:RANG:AUTO ON")
        else:
            self.write("SENS:CURR:RANG:AUTO OFF")

    def source_current_measure_voltage(self, i: float, v_limit: float, autorange=True):
        self.write("SOUR:FUNC CURR")
        self.write(f"SOUR:CURR {i}")
        self.write(f"SENS:VOLT:PROT {v_limit}")  # voltage compliance
        self.write("SENS:FUNC 'VOLT'")
        if autorange:
            self.write("SENS:VOLT:RANG:AUTO ON")
        else:
            self.write("SENS:VOLT:RANG:AUTO OFF")

    def measure_current(self) -> float:
        # READ? returns reading in selected function
        return float(self.query("READ?").strip())

    def measure_voltage(self) -> float:
        return float(self.query("READ?").strip())

class Keithley6487(KeithleyBase):
    """
    6487 picoammeter with voltage source.
    We'll use common SCPI commands used by 6487 family.
    """
    def reset(self):
        self.write("*RST")
        self.write("*CLS")

    def output_on(self):
        # 6487: :SOUR:VOLT:STAT ON (common)
        self.write(":SOUR:VOLT:STAT ON")

    def output_off(self):
        self.write(":SOUR:VOLT:STAT OFF")

    def set_nplc(self, nplc: float):
        # current measurement integration
        self.write(f":SENS:CURR:NPLC {nplc}")

    def source_voltage(self, v: float):
        self.write(f":SOUR:VOLT {v}")

    def measure_current(self) -> float:
        # MEAS:CURR? typically returns current
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
                    # -------------------- Modes --------------------
                    if self.cfg.mode == "IV_SWEEP":
                        # source V, measure I
                        if self.cfg.instrument == "2450":
                            inst.set_nplc_current(self.cfg.nplc)
                            inst.source_voltage_measure_current(0.0, self.cfg.compliance, self.cfg.autorange)
                            inst.output_on()
                            v = self.cfg.start
                            # inclusive sweep with step sign handling
                            step = self.cfg.step if (self.cfg.stop >= self.cfg.start) else -abs(self.cfg.step)
                            while (v <= self.cfg.stop + 1e-12) if step > 0 else (v >= self.cfg.stop - 1e-12):
                                if self._stop: break
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
                                if self._stop: break
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
                            if self._stop: break
                            inst.source_current_measure_voltage(i, self.cfg.compliance, self.cfg.autorange)
                            time.sleep(self.cfg.dwell_s)
                            v_meas = inst.measure_voltage()
                            emit_and_write(i, v_meas)
                            i += step

                    elif self.cfg.mode == "HOLD_V":
                        # hold V, log I
                        if self.cfg.instrument == "2450":
                            inst.set_nplc_current(self.cfg.nplc)
                            inst.source_voltage_measure_current(self.cfg.start, self.cfg.compliance, self.cfg.autorange)
                            inst.output_on()
                            t_end = time.time() + self.cfg.duration_s
                            while time.time() < t_end:
                                if self._stop: break
                                time.sleep(self.cfg.sample_period_s)
                                i_meas = inst.measure_current()
                                emit_and_write(self.cfg.start, i_meas)
                        else:
                            inst.set_nplc(self.cfg.nplc)
                            inst.source_voltage(self.cfg.start)
                            inst.output_on()
                            t_end = time.time() + self.cfg.duration_s
                            while time.time() < t_end:
                                if self._stop: break
                                time.sleep(self.cfg.sample_period_s)
                                i_meas = inst.measure_current()
                                emit_and_write(self.cfg.start, i_meas)

                    elif self.cfg.mode == "HOLD_I":
                        # hold I, log V (2450 only)
                        if self.cfg.instrument != "2450":
                            raise RuntimeError("Hold current is only supported on the 2450.")
                        inst.set_nplc_voltage(self.cfg.nplc)
                        inst.source_current_measure_voltage(self.cfg.start, self.cfg.compliance, self.cfg.autorange)
                        inst.output_on()
                        t_end = time.time() + self.cfg.duration_s
                        while time.time() < t_end:
                            if self._stop: break
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
        self.resize(980, 560)

        self.runner = None

        # Widgets
        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        layout = QtWidgets.QGridLayout(w)

        self.inst_combo = QtWidgets.QComboBox()
        self.inst_combo.addItems(["2450", "6487"])
        self.inst_combo.currentTextChanged.connect(self.on_instrument_changed)

        self.resource_combo = QtWidgets.QComboBox()
        self.scan_btn = QtWidgets.QPushButton("Scan VISA")
        self.scan_btn.clicked.connect(self.scan_resources)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["IV_SWEEP", "VI_SWEEP", "HOLD_V", "HOLD_I"])

        # Params
        self.start_edit = QtWidgets.QDoubleSpinBox(); self.start_edit.setRange(-1e6, 1e6); self.start_edit.setDecimals(6)
        self.stop_edit  = QtWidgets.QDoubleSpinBox(); self.stop_edit.setRange(-1e6, 1e6);  self.stop_edit.setDecimals(6)
        self.step_edit  = QtWidgets.QDoubleSpinBox(); self.step_edit.setRange(1e-12, 1e6);  self.step_edit.setDecimals(12); self.step_edit.setValue(0.5)
        self.dwell_edit = QtWidgets.QDoubleSpinBox(); self.dwell_edit.setRange(0, 3600); self.dwell_edit.setDecimals(3); self.dwell_edit.setValue(0.2)

        self.duration_edit = QtWidgets.QDoubleSpinBox(); self.duration_edit.setRange(0, 1e7); self.duration_edit.setDecimals(3); self.duration_edit.setValue(5.0)
        self.sample_edit   = QtWidgets.QDoubleSpinBox(); self.sample_edit.setRange(0.001, 3600); self.sample_edit.setDecimals(3); self.sample_edit.setValue(0.2)

        self.comp_edit = QtWidgets.QDoubleSpinBox(); self.comp_edit.setRange(0, 1e6); self.comp_edit.setDecimals(12); self.comp_edit.setValue(1e-6)
        self.nplc_edit = QtWidgets.QDoubleSpinBox(); self.nplc_edit.setRange(0.001, 50.0); self.nplc_edit.setDecimals(3); self.nplc_edit.setValue(1.0)

        self.autorange_chk = QtWidgets.QCheckBox("Auto-range")
        self.autorange_chk.setChecked(True)

        # Save path
        self.save_dir_edit = QtWidgets.QLineEdit(str(Path.cwd() / "runs"))
        self.browse_btn = QtWidgets.QPushButton("Browse…")
        self.browse_btn.clicked.connect(self.browse_dir)

        # Control buttons
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

        # Layout
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
        layout.addWidget(QtWidgets.QLabel("Start (V or A)"), row, 0)
        layout.addWidget(self.start_edit, row, 1)
        layout.addWidget(QtWidgets.QLabel("Stop (V or A)"), row, 2)
        layout.addWidget(self.stop_edit, row, 3)

        row += 1
        layout.addWidget(QtWidgets.QLabel("Step (V or A)"), row, 0)
        layout.addWidget(self.step_edit, row, 1)
        layout.addWidget(QtWidgets.QLabel("Dwell per point (s)"), row, 2)
        layout.addWidget(self.dwell_edit, row, 3)

        row += 1
        layout.addWidget(QtWidgets.QLabel("Hold duration (s)"), row, 0)
        layout.addWidget(self.duration_edit, row, 1)
        layout.addWidget(QtWidgets.QLabel("Sample period (s)"), row, 2)
        layout.addWidget(self.sample_edit, row, 3)

        row += 1
        layout.addWidget(QtWidgets.QLabel("Compliance (A for V-source / V for I-source)"), row, 0)
        layout.addWidget(self.comp_edit, row, 1)
        layout.addWidget(QtWidgets.QLabel("NPLC"), row, 2)
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
        layout.addWidget(self.table, row, 0, 1, 5)

        # Defaults
        self.scan_resources()
        self.set_default_resources()
        self.on_instrument_changed(self.inst_combo.currentText())

    def set_default_resources(self):
        # Preload your known addresses if present
        resources = [self.resource_combo.itemText(i) for i in range(self.resource_combo.count())]
        preferred_2450 = "GPIB0::13::INSTR"
        preferred_6487 = "GPIB0::22::INSTR"
        if preferred_2450 in resources or preferred_6487 in resources:
            pass  # keep scan results
        else:
            # If scan didn't return, still allow manual selection by inserting them
            self.resource_combo.addItem("GPIB0::13::INSTR")
            self.resource_combo.addItem("GPIB0::22::INSTR")

    def scan_resources(self):
        self.resource_combo.clear()
        try:
            res = visa_list_resources()
            # Keep only likely relevant ones first, but still list all
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
        # Enable/disable modes for 6487
        if inst == "6487":
            # disable VI_SWEEP and HOLD_I
            for i in range(self.mode_combo.count()):
                text = self.mode_combo.itemText(i)
                enabled = text not in ("VI_SWEEP", "HOLD_I")
                self.mode_combo.model().item(i).setEnabled(enabled)
            if self.mode_combo.currentText() in ("VI_SWEEP", "HOLD_I"):
                self.mode_combo.setCurrentText("IV_SWEEP")
        else:
            for i in range(self.mode_combo.count()):
                self.mode_combo.model().item(i).setEnabled(True)

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

        # Validate
        if mode in ("IV_SWEEP", "VI_SWEEP") and cfg.step <= 0:
            self.status.setText("Step must be > 0 for sweeps.")
            return

        save_root = Path(self.save_dir_edit.text())
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_folder = save_root / f"{inst}_{mode}_{stamp}"

        self.table.setRowCount(0)
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
