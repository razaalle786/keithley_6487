import re
from pathlib import Path

TARGET = Path("keithley_mini_app.py")  # change if needed

def main():
    if not TARGET.exists():
        raise FileNotFoundError(f"Can't find {TARGET.resolve()}")

    text = TARGET.read_text(encoding="utf-8", errors="ignore")
    backup = TARGET.with_suffix(".py.bak_hold2")
    backup.write_text(text, encoding="utf-8")

    # ---- Patch pattern: timed HOLD loop for current measurement ----
    # Matches blocks with i_meas = inst.measure_current()
    pat_i = r"""
(?P<indent>^[ \t]*)
t_end[ \t]*=[ \t]*time\.time\(\)[ \t]*\+[ \t]*self\.cfg\.duration_s[ \t]*\r?\n
(?P=indent)while[ \t]+time\.time\(\)[ \t]*<[ \t]*t_end[ \t]*:[ \t]*\r?\n
(?P=indent)[ \t]*if[ \t]+self\._stop[ \t]*:[ \t]*break[ \t]*\r?\n
(?P=indent)[ \t]*time\.sleep\(self\.cfg\.sample_period_s\)[ \t]*\r?\n
(?P=indent)[ \t]*i_meas[ \t]*=[ \t]*inst\.measure_current\(\)[ \t]*\r?\n
(?P=indent)[ \t]*emit_and_write\(self\.cfg\.start,[ \t]*i_meas\)[ \t]*\r?\n
"""

    rep_i = r"""\g<indent>if self.cfg.duration_s <= 0:
\g<indent>    while not self._stop:
\g<indent>        time.sleep(self.cfg.sample_period_s)
\g<indent>        i_meas = inst.measure_current()
\g<indent>        emit_and_write(self.cfg.start, i_meas)
\g<indent>else:
\g<indent>    t_end = time.time() + self.cfg.duration_s
\g<indent>    while time.time() < t_end and not self._stop:
\g<indent>        time.sleep(self.cfg.sample_period_s)
\g<indent>        i_meas = inst.measure_current()
\g<indent>        emit_and_write(self.cfg.start, i_meas)
"""

    text, n_i = re.subn(pat_i, rep_i, text, flags=re.M | re.X)

    # ---- Patch pattern: timed HOLD loop for voltage measurement ----
    # Matches blocks with v_meas = inst.measure_voltage()
    pat_v = r"""
(?P<indent>^[ \t]*)
t_end[ \t]*=[ \t]*time\.time\(\)[ \t]*\+[ \t]*self\.cfg\.duration_s[ \t]*\r?\n
(?P=indent)while[ \t]+time\.time\(\)[ \t]*<[ \t]*t_end[ \t]*:[ \t]*\r?\n
(?P=indent)[ \t]*if[ \t]+self\._stop[ \t]*:[ \t]*break[ \t]*\r?\n
(?P=indent)[ \t]*time\.sleep\(self\.cfg\.sample_period_s\)[ \t]*\r?\n
(?P=indent)[ \t]*v_meas[ \t]*=[ \t]*inst\.measure_voltage\(\)[ \t]*\r?\n
(?P=indent)[ \t]*emit_and_write\(self\.cfg\.start,[ \t]*v_meas\)[ \t]*\r?\n
"""

    rep_v = r"""\g<indent>if self.cfg.duration_s <= 0:
\g<indent>    while not self._stop:
\g<indent>        time.sleep(self.cfg.sample_period_s)
\g<indent>        v_meas = inst.measure_voltage()
\g<indent>        emit_and_write(self.cfg.start, v_meas)
\g<indent>else:
\g<indent>    t_end = time.time() + self.cfg.duration_s
\g<indent>    while time.time() < t_end and not self._stop:
\g<indent>        time.sleep(self.cfg.sample_period_s)
\g<indent>        v_meas = inst.measure_voltage()
\g<indent>        emit_and_write(self.cfg.start, v_meas)
"""

    text, n_v = re.subn(pat_v, rep_v, text, flags=re.M | re.X)

    if (n_i + n_v) == 0:
        raise RuntimeError(
            "Patch didn't find any timed HOLD loops to replace.\n"
            "Your HOLD loops may be written differently (e.g., different variable names).\n"
            "If so, paste your HOLD_V and HOLD_I sections from Runner.run()."
        )

    # Optional: set default hold duration to 0.0 (0 = until Stop)
    text = re.sub(
        r"(self\.duration_edit\.setValue\()([0-9.]+)(\))",
        r"\g<1>0.0\g<3>",
        text,
        count=1
    )

    # Optional: label hint
    text = text.replace(
        'QtWidgets.QLabel("Hold duration (s)")',
        'QtWidgets.QLabel("Hold duration (s) (0 = until Stop)")'
    )

    TARGET.write_text(text, encoding="utf-8")
    print(f"✅ Patched OK: {TARGET}")
    print(f"🧾 Backup saved: {backup}")
    print(f"Replaced loops: current={n_i}, voltage={n_v}")
    print("Now set Hold duration to 0 and it will run until you press Stop.")

if __name__ == "__main__":
    main()
