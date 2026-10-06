"""Bounded, latest-frame mailboxes: capture can never flood the UI queue."""
import threading
import time
from dataclasses import dataclass, replace
import numpy as np
from PySide6.QtGui import QImage


def bgr_image(frame: np.ndarray) -> QImage:
    frame = np.ascontiguousarray(frame)
    return QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0],
                  QImage.Format.Format_BGR888).copy()


def image_bgr(image: QImage) -> np.ndarray:
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    array = np.frombuffer(rgb.constBits(), np.uint8).reshape(rgb.height(), rgb.bytesPerLine())
    return np.ascontiguousarray(array[:, :rgb.width() * 3].reshape(rgb.height(), rgb.width(), 3)[:, :, ::-1])


class FrameStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._frames = {}
        self._sequence = 0

    def put(self, name, image):
        with self._lock:
            self._sequence += 1
            self._frames[name] = (QImage(image), time.monotonic(), self._sequence)

    def get(self, name, max_age=None):
        with self._lock:
            value = self._frames.get(name)
            if not value or (max_age and time.monotonic() - value[1] > max_age):
                return QImage(), 0
            return QImage(value[0]), value[2]

    def clear(self, name):
        with self._lock:
            self._frames.pop(name, None)

    def has_live_source(self, camera_only=False):
        if camera_only:
            return not self.get('camera', 2)[0].isNull()
        return not self.get('screen', 2)[0].isNull() or not self.get('camera', 2)[0].isNull()


@dataclass
class Scene:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    camera_enabled: bool = True
    camera_only: bool = False
    camera_source: str = 'webcam'
    x: float = .82
    y: float = .70
    w: float = .15
    h: float = .2666667
    shape: str = 'Circle'
    border: int = 4
    radius: int = 32
    color: str = '#8b8aff'
    shadow: bool = True
    opacity: float = 1.
    mirror: bool = True
    background: str = 'Original'


class SceneState:
    def __init__(self, scene=None):
        self._lock = threading.Lock()
        self._scene = scene or Scene()

    def get(self):
        with self._lock:
            return replace(self._scene)

    def update(self, **values):
        with self._lock:
            self._scene = replace(self._scene, **values)

    def overlay(self, x, y, w, h):
        w, h = max(.02, min(1., w)), max(.02, min(1., h))
        self.update(x=max(0., min(1. - w, x)), y=max(0., min(1. - h, y)), w=w, h=h)
