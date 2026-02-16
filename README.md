# Keithley 6487 Python Control

Python scripts for:
- Live I–V sweeps
- Constant-bias I–t measurements
- CZT and high-resistance detector characterisation

## Requirements
- Python 3.9+
- pyvisa
- numpy
- matplotlib

## Tested with
- Keithley 6487 Picoammeter / Voltage Source
- NI-VISA on Windows

## Notes
All scripts include:
- Safe shutdown
- Compliance limiting
- Live plotting


---

## Keithley Mini GUI (2450 + 6487)

This repository now includes a modular PySide6-based GUI located in:

`keithley_mini_software/`

The Mini GUI provides a structured interface for controlling both the Keithley 6487 and Keithley 2450 via GPIB.

### Features

- IV Sweep (Source Voltage → Measure Current)
- VI Sweep (2450 only)
- Hold Voltage (Current vs Time)
- Hold Current (2450 only, Voltage vs Time)
- Live plot with selectable X/Y axes
- Continuous hold mode (set duration = 0 to run until Stop)
- Compliance limiting
- Safe output shutdown on stop
- Automatic CSV logging

### Installation (GUI only)

```bash
pip install -r keithley_mini_software/requirements.txt
