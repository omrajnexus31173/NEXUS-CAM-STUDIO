"""Real portrait segmentation using the bundled, CPU OpenCV Zoo PPHumanSeg model.
No downloads on launch and no cloud. Inference is capped at 15 Hz.
"""
import threading
import time
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from app.utils.frames import bgr_image, image_bgr
from app.utils.paths import resource

BACKGROUND_COLORS = {
    'Plain Blue': (182, 100, 48), 'Plain Green': (95, 154, 69),
    'Plain Gray': (122, 122, 128), 'Plain Cream': (218, 235, 245),
}
BACKGROUNDS = ['Original', 'Blur', 'Strong Blur', *BACKGROUND_COLORS]


class BackgroundProcessor:
    def __init__(self, model=None):
        self.model_path = model or resource('assets/models/portrait.onnx')
        self.net = None
        self.mask = None
        self.inferred = 0.

    def load(self):
        if not self.model_path.exists():
            raise RuntimeError('Portrait segmentation model is missing. Reinstall the application.')
        if self.net is None:
            self.net = cv2.dnn.readNet(str(self.model_path))
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    def segment(self, frame):
        self.load()
        rgb = cv2.cvtColor(cv2.resize(frame, (192, 192)), cv2.COLOR_BGR2RGB)
        blob = cv2.dnn.blobFromImage((rgb.astype(np.float32) / 255. - .5) / .5)
        self.net.setInput(blob)
        scores = self.net.forward()[0]
        if scores.shape[0] != 2 or not np.isfinite(scores).all():
            raise RuntimeError('Segmentation produced an invalid mask')
        # Model output is two-class softmax, not a generic background-color filter.
        mask = np.clip((scores[1] - .15) / .7, 0., 1.)
        mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR)
        self.mask = cv2.GaussianBlur(mask, (5, 5), 0)[:, :, None]
        self.inferred = time.monotonic()

    def apply(self, frame, mode):
        if mode == 'Original':
            return frame
        if mode not in BACKGROUNDS:
            raise ValueError('Unsupported camera background')
        if self.mask is None or self.mask.shape[:2] != frame.shape[:2] or time.monotonic() - self.inferred >= 1 / 15:
            self.segment(frame)
        if mode in ('Blur', 'Strong Blur'):
            # Blur only a small background image; avoid expensive full-resolution kernels.
            small = cv2.resize(frame, (max(32, frame.shape[1] // 4), max(32, frame.shape[0] // 4)))
            blur = cv2.GaussianBlur(small, (0, 0), 5 if mode == 'Blur' else 13)
            background = cv2.resize(blur, (frame.shape[1], frame.shape[0]))
        else:
            background = np.full_like(frame, BACKGROUND_COLORS[mode])
        return np.clip(frame * self.mask + background * (1 - self.mask), 0, 255).astype(np.uint8)


class EffectWorker(QThread):
    failed = Signal(str)

    def __init__(self, frames, state, parent=None):
        super().__init__(parent)
        self.frames, self.state = frames, state
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        processor = BackgroundProcessor()
        previous, last_mode = 0, ''
        while not self._stop.is_set():
            scene = self.state.get()
            image, sequence = self.frames.get('phone_raw' if scene.camera_source == 'phone' else 'camera_raw', 2)
            if image.isNull():
                self.frames.clear('camera')
            elif sequence != previous or scene.background != last_mode:
                try:
                    frame = image_bgr(image)
                    if scene.mirror:
                        frame = cv2.flip(frame, 1)
                    result = processor.apply(frame, scene.background)
                    self.frames.put('camera', bgr_image(result))
                except Exception as exc:
                    self.state.update(background='Original')
                    self.frames.put('camera', image.mirrored(scene.mirror, False))
                    self.failed.emit(f'Background effect unavailable: {exc}. Original camera restored; recording can continue.')
                previous, last_mode = sequence, scene.background
            self._stop.wait(1 / max(30, scene.fps))
