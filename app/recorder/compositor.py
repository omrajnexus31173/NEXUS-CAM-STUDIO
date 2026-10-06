import threading
import time
from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen


def overlay_rect(scene):
    return QRectF(scene.x * scene.width, scene.y * scene.height,
                  scene.w * scene.width, scene.h * scene.height)


def shape_path(rect, shape, radius=32):
    path = QPainterPath()
    if shape in ('Circle', 'Oval'):
        path.addEllipse(rect)
    elif shape == 'Rounded Rectangle':
        path.addRoundedRect(rect, min(radius, rect.width() / 2), min(radius, rect.height() / 2))
    else:
        path.addRect(rect)
    return path


def draw_fit(painter, rect, image, crop=False):
    if image.isNull():
        return
    iw, ih = image.width(), image.height()
    if crop:
        scale = max(rect.width() / iw, rect.height() / ih)
        sw, sh = rect.width() / scale, rect.height() / scale
        source = QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh)
        painter.drawImage(rect, image, source)
    else:
        scale = min(rect.width() / iw, rect.height() / ih)
        w, h = iw * scale, ih * scale
        painter.drawImage(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h), image)


def compose(scene, screen, camera):
    """The sole recording/screenshot/preview rasterizer. Selection handles are UI-only."""
    result = QImage(scene.width, scene.height, QImage.Format.Format_RGB32)
    result.fill(QColor('#0b101b'))
    painter = QPainter(result)
    try:
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        canvas = QRectF(0, 0, scene.width, scene.height)
        if scene.camera_only:
            if scene.camera_enabled:
                draw_fit(painter, canvas, camera)
        else:
            draw_fit(painter, canvas, screen)
            if scene.camera_enabled and not camera.isNull():
                rect = overlay_rect(scene)
                path = shape_path(rect, scene.shape, scene.radius)
                painter.save()
                painter.setOpacity(scene.opacity)
                if scene.shadow:
                    for offset, alpha in [(12, 20), (8, 30), (4, 45)]:
                        shadow = shape_path(rect.translated(offset, offset), scene.shape, scene.radius)
                        painter.fillPath(shadow, QColor(0, 0, 0, alpha))
                painter.setClipPath(path)
                draw_fit(painter, rect, camera, crop=True)
                painter.setClipping(False)
                if scene.border:
                    painter.setPen(QPen(QColor(scene.color), scene.border))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                painter.restore()
        if (scene.camera_only and (camera.isNull() or not scene.camera_enabled)) or (not scene.camera_only and screen.isNull() and (camera.isNull() or not scene.camera_enabled)):
            painter.setPen(QColor('#b5bfd1'))
            painter.setFont(QFont('Segoe UI', max(16, scene.width // 70)))
            painter.drawText(canvas, Qt.AlignmentFlag.AlignCenter,
                             'No live source\nStart screen capture or enable a connected camera')
    finally:
        painter.end()
    return result


class CompositionWorker(QThread):
    failed = Signal(str)

    def __init__(self, frames, state, parent=None):
        super().__init__(parent)
        self.frames, self.state = frames, state
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        deadline = time.monotonic()
        try:
            while not self._stop.is_set():
                scene = self.state.get()
                screen, _ = self.frames.get('screen', 2)
                camera, _ = self.frames.get('camera', 2)
                self.frames.put('composed', compose(scene, screen, camera))
                deadline += 1 / scene.fps
                if deadline < time.monotonic() - .2:
                    deadline = time.monotonic()
                self._stop.wait(max(0, deadline - time.monotonic()))
        except Exception as exc:
            self.failed.emit(f'Composition stopped: {exc}. Restart the application before recording.')
