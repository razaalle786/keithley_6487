from __future__ import annotations
from ..visa_utils import open_resource

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

    def reset(self):
        raise NotImplementedError

    def output_on(self):
        raise NotImplementedError

    def output_off(self):
        raise NotImplementedError

    def shutdown_safe(self):
        self.output_off()
