from .base import KeithleyBase

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
