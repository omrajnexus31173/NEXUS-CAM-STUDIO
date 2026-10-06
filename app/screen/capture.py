import ctypes
import sys
import threading
import time
import mss
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


def monitors():
    with mss.MSS() as grabber:
        return [dict(m) for m in grabber.monitors[1:]]


def windows(exclude=0):
    if sys.platform != 'win32':
        return []
    user = ctypes.windll.user32
    # HWND must stay pointer-sized on 64-bit Windows.
    user.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user.IsIconic.argtypes = [ctypes.c_void_p]
    result = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    @callback_type
    def callback(hwnd, _):
        length = user.GetWindowTextLengthW(hwnd)
        if hwnd != exclude and length and user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd):
            title = ctypes.create_unicode_buffer(length + 1)
            user.GetWindowTextW(hwnd, title, length + 1)
            result.append((int(hwnd), title.value))
        return True
    user.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user.EnumWindows(callback, None)
    return result


def window_bounds(hwnd):
    from ctypes import wintypes
    rect = wintypes.RECT()
    user = ctypes.windll.user32
    user.IsWindow.argtypes = [ctypes.c_void_p]
    user.IsIconic.argtypes = [ctypes.c_void_p]
    if not user.IsWindow(hwnd) or user.IsIconic(hwnd):
        raise RuntimeError('The selected window was closed or minimized. Restore it and start capture again.')
    try:
        rc = ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 9,
                                                      ctypes.byref(rect), ctypes.sizeof(rect))
        if rc != 0:
            raise OSError(rc)
    except Exception:
        user.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError('Cannot read the selected window position.')
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise RuntimeError('The selected window has no visible area.')
    return dict(left=rect.left, top=rect.top, width=rect.right - rect.left, height=rect.bottom - rect.top)


class ScreenWorker(QThread):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, frames, target, fps=30, parent=None):
        super().__init__(parent)
        self.frames = frames
        self.target = dict(target)
        self.fps = fps
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            with mss.MSS(with_cursor=True) as grabber:
                first = True
                deadline = time.monotonic()
                while not self._stop.is_set():
                    target = window_bounds(self.target['hwnd']) if 'hwnd' in self.target else self.target
                    shot = grabber.grab(target)
                    image = QImage(shot.bgra, shot.width, shot.height, shot.width * 4,
                                   QImage.Format.Format_RGB32).copy()
                    self.frames.put('screen', image)
                    if first:
                        self.ready.emit()
                        first = False
                    deadline += 1 / self.fps
                    if deadline < time.monotonic() - .25:
                        deadline = time.monotonic()
                    self._stop.wait(max(0, deadline - time.monotonic()))
        except Exception as exc:
            self.frames.clear('screen')
            self.failed.emit(f'Screen capture unavailable: {exc}. Check Windows privacy permissions and try again.')
