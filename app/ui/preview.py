from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from app.recorder.compositor import overlay_rect


class PreviewWidget(QWidget):
    overlay_changed = Signal()

    def __init__(self, frames, state, parent=None):
        super().__init__(parent)
        self.frames, self.state = frames, state
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.selected = False
        self.drag = None
        self.setToolTip('Click a live camera overlay to select. Drag to move; drag a corner to resize. Arrow keys nudge; Escape deselects.')

    def canvas(self):
        scene = self.state.get()
        scale = min((self.width() - 16) / scene.width, (self.height() - 16) / scene.height)
        w, h = scene.width * scale, scene.height * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def camera_rect(self):
        scene, canvas = self.state.get(), self.canvas()
        return QRectF(canvas.x() + scene.x * canvas.width(), canvas.y() + scene.y * canvas.height(),
                      scene.w * canvas.width(), scene.h * canvas.height())

    def handles(self):
        rect = self.camera_rect()
        return {'tl': rect.topLeft(), 'tr': rect.topRight(), 'bl': rect.bottomLeft(), 'br': rect.bottomRight()}

    def live_overlay(self):
        scene = self.state.get()
        return scene.camera_enabled and not scene.camera_only and not self.frames.get('camera', 2)[0].isNull()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#090e18'))
        canvas = self.canvas()
        image, _ = self.frames.get('composed')
        if not image.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(canvas, image)
        else:
            painter.setPen(QColor('#8c99b1'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Initializing live composition…')
        painter.setPen(QPen(QColor('#2a3549'), 1))
        painter.drawRoundedRect(canvas, 3, 3)
        if self.selected and self.live_overlay():
            painter.setPen(QPen(QColor('#d0c5ff'), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.camera_rect())
            painter.setPen(QPen(QColor('#ffffff'), 1))
            painter.setBrush(QColor('#8e7afb'))
            for point in self.handles().values():
                painter.drawRoundedRect(QRectF(point.x() - 4, point.y() - 4, 8, 8), 2, 2)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        if self.live_overlay():
            for handle, corner in self.handles().items():
                if self.selected and (corner - point).manhattanLength() < 13:
                    self.drag = (handle, point, self.state.get())
                    self.setFocus()
                    return
            if self.camera_rect().contains(point):
                self.selected = True
                self.drag = ('move', point, self.state.get())
                self.setFocus()
                self.update()
                return
        self.selected = False
        self.drag = None
        self.update()

    def mouseMoveEvent(self, event):
        if not self.drag:
            if self.live_overlay() and self.camera_rect().contains(event.position()):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            return
        mode, start, initial = self.drag
        canvas = self.canvas()
        dx = (event.position().x() - start.x()) / canvas.width()
        dy = (event.position().y() - start.y()) / canvas.height()
        if mode == 'move':
            self.state.overlay(initial.x + dx, initial.y + dy, initial.w, initial.h)
        else:
            left, top, right, bottom = initial.x, initial.y, initial.x + initial.w, initial.y + initial.h
            if 'l' in mode:
                left = min(right - .025, max(0., left + dx))
            else:
                right = max(left + .025, min(1., right + dx))
            if 't' in mode:
                top = min(bottom - .04, max(0., top + dy))
            else:
                bottom = max(top + .04, min(1., bottom + dy))
            w, h = right - left, bottom - top
            if initial.shape in ('Circle', 'Square'):
                # A circle/square stays square in output pixels, not normalized coordinates.
                side = max(40., min(w * initial.width, h * initial.height))
                w, h = side / initial.width, side / initial.height
                if 'l' in mode:
                    left = right - w
                if 't' in mode:
                    top = bottom - h
            self.state.overlay(left, top, w, h)
        self.overlay_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.unsetCursor()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.selected = False
            self.update()
            return
        if self.selected:
            scene = self.state.get()
            amount = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            directions = {Qt.Key.Key_Left: (-amount, 0), Qt.Key.Key_Right: (amount, 0),
                          Qt.Key.Key_Up: (0, -amount), Qt.Key.Key_Down: (0, amount)}
            if event.key() in directions:
                dx, dy = directions[event.key()]
                self.state.overlay(scene.x + dx / scene.width, scene.y + dy / scene.height, scene.w, scene.h)
                self.overlay_changed.emit()
                self.update()
