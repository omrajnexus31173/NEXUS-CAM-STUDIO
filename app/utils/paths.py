"""All mutable files belong to the user, never beside the executable."""
import ctypes
import os
import sys
from datetime import datetime
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get('NEXUS_DATA_DIR')
    base = Path(override) if override else (
        Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'NexusCamStudio'
        if sys.platform == 'win32' else Path.home() / '.config' / 'NexusCamStudio')
    base.mkdir(parents=True, exist_ok=True)
    return base


def videos_dir() -> Path:
    if os.environ.get('NEXUS_OUTPUT_DIR'):
        return Path(os.environ['NEXUS_OUTPUT_DIR'])
    if sys.platform == 'win32':
        try:
            from ctypes import wintypes
            class GUID(ctypes.Structure):
                _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                            ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]
            guid = GUID(0x18989B1D, 0x99B5, 0x455B,
                        (ctypes.c_ubyte * 8)(0x84, 0x1C, 0xAB, 0x7C, 0x74, 0xE4, 0xDF, 0xFC))
            path = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) == 0:
                result = Path(path.value) / 'NexusCamStudio'
                ctypes.windll.ole32.CoTaskMemFree(path)
                return result
        except Exception:
            pass
    return Path.home() / 'Videos' / 'NexusCamStudio'


def resource(relative: str) -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])) / relative


def writable_folder(path: str | Path) -> Path:
    if not str(path).strip():
        raise ValueError('Choose a non-empty output folder')
    folder = Path(path).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(prefix='.nexus-write-', dir=folder):
        pass
    return folder


def unique_path(folder: Path, prefix: str, extension: str) -> Path:
    stem = prefix + datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    path = folder / f'{stem}.{extension}'
    index = 1
    while path.exists():
        path = folder / f'{stem}_{index}.{extension}'
        index += 1
    return path
