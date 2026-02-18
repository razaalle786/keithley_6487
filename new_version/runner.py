import time
import json
import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore

from .config import RunConfig
from .instruments import Keithley2450, Keithley6487


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

            # config
            cfg_path = self.save_dir / "run_config.json"
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.cfg), f, indent=2)

            csv_path = self.save_dir / "data.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as fcsv:
                writer = csv.DictWriter(
                    fcsv,
                    fieldnames=[
                        "timestamp", "elapsed_s", "instrument", "resource", "mode",
                        "set_value", "measured_value"
                    ]
                )
                writer.writeheader()

                inst = Keithley2450(self.cfg.resource) if self.cfg.instrument == "2450" else Keithley6487(self.cfg.resource)
                inst.connect()
                inst.reset()

                # 6487 configure
                if self.cfg.instrument == "6487":
                    if self.cfg.source_range_v and self.cfg.source_range_v > 0:
                        v_range = float(self.cfg.source_range_v)
                    else:
                        if self.cfg.mode in ("HOLD_V",):
                            max_v = abs(self.cfg.start)
                        else:
                            max_v = max(abs(self.cfg.start), abs(self.cfg.stop))
                        v_range = 50.0 if max_v <= 50.0 else 500.0

                    inst.configure_for_source(
                        v_range=v_range,
                        i_limit=self.cfg.compliance,
                        autorange=self.cfg.autorange,
                        nplc=self.cfg.nplc,
                    )

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
                                emit_and_write(v, inst.measure_current())
                                v += step
                        else:
                            v = self.cfg.start
                            step = self.cfg.step if (self.cfg.stop >= self.cfg.start) else -abs(self.cfg.step)
                            while (v <= self.cfg.stop + 1e-12) if step > 0 else (v >= self.cfg.stop - 1e-12):
                                if self._stop:
                                    break
                                inst.source_voltage(v)
                                inst.check_error(f"set V={v}")
                                time.sleep(self.cfg.dwell_s)
                                emit_and_write(v, inst.measure_current())
                                v += step

                    elif self.cfg.mode == "VI_SWEEP":
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
                            emit_and_write(i, inst.measure_voltage())
                            i += step

                    elif self.cfg.mode == "HOLD_V":
                        if self.cfg.instrument == "2450":
                            inst.set_nplc_current(self.cfg.nplc)
                            inst.source_voltage_measure_current(self.cfg.start, self.cfg.compliance, self.cfg.autorange)
                            inst.output_on()
                        else:
                            inst.source_voltage(self.cfg.start)
                            inst.check_error(f"set HOLD_V={self.cfg.start}")

                        if self.cfg.duration_s <= 0:
                            while not self._stop:
                                time.sleep(self.cfg.sample_period_s)
                                emit_and_write(self.cfg.start, inst.measure_current())
                        else:
                            t_end = time.time() + self.cfg.duration_s
                            while time.time() < t_end and not self._stop:
                                time.sleep(self.cfg.sample_period_s)
                                emit_and_write(self.cfg.start, inst.measure_current())

                    elif self.cfg.mode == "HOLD_I":
                        if self.cfg.instrument != "2450":
                            raise RuntimeError("Hold current is only supported on the 2450.")
                        inst.set_nplc_voltage(self.cfg.nplc)
                        inst.source_current_measure_voltage(self.cfg.start, self.cfg.compliance, self.cfg.autorange)
                        inst.output_on()

                        if self.cfg.duration_s <= 0:
                            while not self._stop:
                                time.sleep(self.cfg.sample_period_s)
                                emit_and_write(self.cfg.start, inst.measure_voltage())
                        else:
                            t_end = time.time() + self.cfg.duration_s
                            while time.time() < t_end and not self._stop:
                                time.sleep(self.cfg.sample_period_s)
                                emit_and_write(self.cfg.start, inst.measure_voltage())
                    else:
                        raise RuntimeError(f"Unknown mode: {self.cfg.mode}")

                finally:
                    try:
                        if self.cfg.instrument == "6487":
                            try:
                                inst.source_voltage(0.0)
                                time.sleep(0.3)
                            except Exception:
                                pass
                        inst.shutdown_safe()
                    finally:
                        inst.close()

            self.finished_ok.emit(f"Saved to: {self.save_dir}")
        except Exception as e:
            self.finished_err.emit(str(e))
