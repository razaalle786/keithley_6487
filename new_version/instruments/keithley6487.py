import re
import time
from .base import KeithleyBase

class Keithley6487(KeithleyBase):
    """
    Keep the exact working approach you validated:
      *RST, *CLS
      SYST:ZCH OFF
      SOUR:VOLT:RANG <50|500>
      SOUR:VOLT:ILIM <A>
      (optional) SENS:CURR:RANG:AUTO ON
      SOUR:VOLT 0
      SOUR:VOLT:STAT ON
      READ?
    """

    def reset(self):
        self.write("*RST")
        self.write("*CLS")

    def output_on(self):
        self.write("SOUR:VOLT:STAT ON")

    def output_off(self):
        self.write("SOUR:VOLT:STAT OFF")

    def set_nplc(self, nplc: float):
        self.write(f"SENS:CURR:NPLC {nplc}")

    def set_source_range(self, v_range: float):
        self.write(f"SOUR:VOLT:RANG {v_range}")

    def set_current_limit(self, i_limit: float):
        self.write(f"SOUR:VOLT:ILIM {i_limit}")

    def source_voltage(self, v: float):
        self.write(f"SOUR:VOLT {v}")

    def get_error(self) -> str:
        try:
            return self.query("SYST:ERR?").strip()
        except Exception:
            return ""

    def check_error(self, context: str):
        err = self.get_error()
        if err and not err.startswith("0"):
            raise RuntimeError(f"6487 SYST:ERR after {context}: {err}")

    @staticmethod
    def _parse_current_from_read(resp: str) -> float:
        first = resp.strip().split(",")[0].strip().replace("A", "")
        m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", first)
        if not m:
            raise ValueError(f"Could not parse current from READ?: {resp!r}")
        return float(m.group(0))

    def measure_current(self) -> float:
        resp = self.query("READ?").strip()
        return self._parse_current_from_read(resp)

    def configure_for_source(self, v_range: float, i_limit: float, autorange: bool, nplc: float):
        self.write("SYST:ZCH OFF")
        self.set_source_range(v_range)
        self.set_current_limit(i_limit)
        if autorange:
            try:
                self.write("SENS:CURR:RANG:AUTO ON")
            except Exception:
                pass
        self.set_nplc(nplc)

        self.source_voltage(0.0)
        self.output_on()
        time.sleep(0.3)

        try:
            self.query("READ?")
        except Exception:
            pass

        self.check_error("initial configure_for_source")
