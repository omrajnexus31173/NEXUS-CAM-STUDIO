import mss
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class RegionSelector(QWidget):
    selected = Signal(object)

    def __init__(self, monitor, index=0, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.monitor = dict(monitor)
        screens = QApplication.screens()
        self.setGeometry(screens[min(index, len(screens) - 1)].geometry())
        with mss.MSS() as cap:
            shot = cap.grab(monitor)
            self.backdrop = QImage(shot.bgra, shot.width, shot.height, shot.width * 4, QImage.Format.Format_RGB32).copy()
        self.selection = QRectF(self.width() * .12, self.height() * .15, self.width() * .76, self.height() * .70)
        self.drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def points(self):
        r = self.selection
        return {'tl': r.topLeft(), 'tr': r.topRight(), 'bl': r.bottomLeft(), 'br': r.bottomRight()}

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(self.rect(), self.backdrop)
        p.fillRect(self.rect(), QColor(5, 10, 20, 165))
        r = self.selection
        source = QRectF(r.x() / self.width() * self.backdrop.width(), r.y() / self.height() * self.backdrop.height(),
                        r.width() / self.width() * self.backdrop.width(), r.height() / self.height() * self.backdrop.height())
        p.drawImage(r, self.backdrop, source)
        p.setPen(QPen(QColor('#b6a5ff'), 2))
        p.drawRect(r)
        p.setBrush(QColor('#aa97ff'))
        for point in self.points().values():
            p.drawRect(QRectF(point.x() - 6, point.y() - 6, 12, 12))
        p.fillRect(0, 0, self.width(), 54, QColor('#171e32'))
        p.setPen(QColor('#eeeeff'))
        width = round(r.width() / self.width() * self.monitor['width'])
        height = round(r.height() / self.height() * self.monitor['height'])
        p.drawText(self.rect().adjusted(22, 0, -22, -(self.height() - 54)), Qt.AlignmentFlag.AlignVCenter,
                   f'SELECT REGION   {width} × {height}    •    Drag to select / move • Corners resize • ENTER confirms • ESC cancels')
        p.end()

    def mousePressEvent(self, event):
        point = event.position()
        for name, corner in self.points().items():
            if (corner - point).manhattanLength() < 20:
                self.drag = (name, point, QRectF(self.selection))
                return
        if self.selection.contains(point):
            self.drag = ('move', point, QRectF(self.selection))
        else:
            self.drag = ('new', point, QRectF(point, point))

    def mouseMoveEvent(self, event):
        if not self.drag:
            return
        mode, start, rect = self.drag
        delta = event.position() - start
        if mode == 'new':
            result = QRectF(start, event.position()).normalized()
        elif mode == 'move':
            result = rect.translated(delta)
            result.moveLeft(max(0, min(self.width() - result.width(), result.left())))
            result.moveTop(max(54, min(self.height() - result.height(), result.top())))
        else:
            result = QRectF(rect)
            if 'l' in mode:
                result.setLeft(rect.left() + delta.x())
            else:
                result.setRight(rect.right() + delta.x())
            if 't' in mode:
                result.setTop(rect.top() + delta.y())
            else:
                result.setBottom(rect.bottom() + delta.y())
            result = result.normalized()
        self.selection = result.intersected(QRectF(0, 54, self.width(), self.height() - 54))
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            r = self.selection
            sx, sy = self.monitor['width'] / self.width(), self.monitor['height'] / self.height()
            if r.width() * sx < 32 or r.height() * sy < 32:
                return
            left = self.monitor['left'] + round(r.x() * sx)
            top = self.monitor['top'] + round(r.y() * sy)
            right = min(self.monitor['left'] + self.monitor['width'], self.monitor['left'] + round(r.right() * sx))
            bottom = min(self.monitor['top'] + self.monitor['height'], self.monitor['top'] + round(r.bottom() * sy))
            self.selected.emit(dict(left=left, top=top, width=right - left, height=bottom - top))
            self.close()
