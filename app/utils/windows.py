"""Per-thread COM initialization for Windows audio/device operations."""
import ctypes
import sys
from contextlib import contextmanager


@contextmanager
def com_thread():
    initialized = False
    if sys.platform == 'win32':
        ole = ctypes.windll.ole32
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole.CoInitializeEx.restype = ctypes.c_long
        status = ole.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        if status in (0, 1):
            initialized = True
        elif status != -2147417850:  # RPC_E_CHANGED_MODE: existing STA is usable.
            raise RuntimeError(f'Windows COM initialization failed: 0x{status & 0xffffffff:08x}')
    try:
        yield
    finally:
        if initialized:
            ctypes.windll.ole32.CoUninitialize()
