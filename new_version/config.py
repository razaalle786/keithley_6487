from dataclasses import dataclass

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
    compliance: float = 0.001     # 2450: A (V-source) or V (I-source). 6487: ILIM (A).
    nplc: float = 1.0
    autorange: bool = True
    source_range_v: float = 0.0   # 6487 only. 0 => Auto, else e.g. 50 or 500
