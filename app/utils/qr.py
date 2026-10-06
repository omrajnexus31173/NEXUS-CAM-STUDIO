"""Generate real QR rasters with Qt; no Pillow or network dependency."""
import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter


def qr_image(text, pixel_size=6):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix) * pixel_size
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor('#ffffff'))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#000000'))
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                painter.drawRect(x * pixel_size, y * pixel_size, pixel_size, pixel_size)
    painter.end()
    return image
