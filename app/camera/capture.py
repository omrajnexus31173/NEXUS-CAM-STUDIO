import glob
import sys
import threading
import time
from dataclasses import dataclass
import cv2
from PySide6.QtCore import QThread, Signal
from app.utils.frames import bgr_image


@dataclass
class CameraDevice:
    index: int
    name: str
    backend: int
    key: str


def cameras():
    backend = cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_V4L2
    try:
        from cv2_enumerate_cameras import enumerate_cameras
        return [CameraDevice(d.index, d.name or f'Webcam {d.index}', backend,
                             f'{d.index}:{d.name}') for d in enumerate_cameras(backend)]
    except Exception:
        indices = range(5) if sys.platform == 'win32' else [int(p.split('video')[-1]) for p in glob.glob('/dev/video[0-9]*')]
        found = []
        for index in indices:
            cap = cv2.VideoCapture(index, backend)
            try:
                if cap.isOpened() and cap.read()[0]:
                    found.append(CameraDevice(index, f'Webcam {index}', backend, str(index)))
            finally:
                cap.release()
        return found


class CameraWorker(QThread):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, frames, device, fps=30, parent=None):
        super().__init__(parent)
        self.frames, self.device, self.fps = frames, device, fps
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        cap = None
        try:
            cap = cv2.VideoCapture(self.device.index, self.device.backend)
            if not cap.isOpened():
                raise RuntimeError('Camera permission denied, camera in use, or device disconnected')
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            first, failures = True, 0
            deadline = time.monotonic()
            while not self._stop.is_set():
                success, frame = cap.read()
                if not success or frame is None:
                    failures += 1
                    if failures > 30:
                        raise RuntimeError('Camera stopped sending frames; reconnect it and click Refresh Devices')
                    self._stop.wait(.03)
                    continue
                failures = 0
                self.frames.put('camera_raw', bgr_image(frame))
                if first:
                    self.ready.emit()
                    first = False
                deadline += 1 / self.fps
                if deadline < time.monotonic() - .25:
                    deadline = time.monotonic()
                self._stop.wait(max(0, deadline - time.monotonic()))
        except Exception as exc:
            self.frames.clear('camera_raw')
            self.frames.clear('camera')
            self.failed.emit(f'Camera unavailable: {exc}. Windows Settings → Privacy → Camera must allow desktop apps.')
        finally:
            if cap is not None:
                cap.release()
