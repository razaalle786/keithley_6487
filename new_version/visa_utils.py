import pyvisa

def visa_list_resources() -> list[str]:
    rm = pyvisa.ResourceManager()
    return list(rm.list_resources())

def open_resource(resource: str, timeout_ms: int = 20000):
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(resource)
    inst.timeout = timeout_ms
    inst.write_termination = "\n"
    inst.read_termination = "\n"
    return inst
