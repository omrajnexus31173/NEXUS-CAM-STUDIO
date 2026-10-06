from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from app.utils.diagnostics import DiagnosticWorker
from app.utils.paths import writable_folder
from app.utils.qr import qr_image


def note(text):
    label = QLabel(text)
    label.setObjectName('Muted')
    label.setWordWrap(True)
    return label


def combo(items, selected=None):
    widget = QComboBox()
    widget.addItems(items)
    if selected in items:
        widget.setCurrentText(selected)
    return widget


def folder_field(initial, parent):
    line = QLineEdit(initial)
    button = QPushButton('Browse…')
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(line, 1)
    layout.addWidget(button)
    def choose():
        path = QFileDialog.getExistingDirectory(parent, 'Choose recording output folder', line.text())
        if path:
            line.setText(path)
    button.clicked.connect(choose)
    return row, line


class WelcomeDialog(QDialog):
    def __init__(self, settings, devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Welcome to Nexus Cam Studio')
        self.setMinimumWidth(590)
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(17)
        tag = QLabel('NEXUS CAM STUDIO  /  FIRST-RUN SETUP')
        tag.setObjectName('Section')
        layout.addWidget(tag)
        heading = QLabel('A simpler way to hit record.')
        heading.setObjectName('Heading')
        layout.addWidget(heading)
        layout.addWidget(note('Welcome to NEXUS CAM STUDIO. Choose your devices and a local output folder. Nothing is uploaded. You can record your screen without a webcam or microphone.'))
        form = QFormLayout()
        form.setSpacing(15)
        self.camera = QComboBox()
        self.camera.addItem('No camera · screen-only', '')
        for device in devices.get('cameras', []):
            self.camera.addItem(device.name, device.key)
        if self.camera.count() > 1:
            self.camera.setCurrentIndex(1)
        self.mic = QComboBox()
        self.mic.addItem('Off · no microphone', '')
        for device in devices.get('microphones', []):
            self.mic.addItem(device.name, device.key)
        if self.mic.count() > 1:
            self.mic.setCurrentIndex(1)
        field, self.output = folder_field(settings.output_folder, self)
        form.addRow('1. Select Camera', self.camera)
        form.addRow('2. Select Microphone', self.mic)
        form.addRow('3. Output Folder', field)
        layout.addLayout(form)
        layout.addWidget(note('Android phone camera can be paired later with Connect Phone. Windows privacy settings must allow desktop camera/microphone access.'))
        self.error = QLabel('')
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#f39ba8')
        layout.addWidget(self.error)
        start = QPushButton('START USING NEXUS CAM STUDIO')
        start.setObjectName('Primary')
        start.setMinimumHeight(44)
        start.clicked.connect(self.accept)
        layout.addWidget(start)

    def accept(self):
        try:
            self.settings.output_folder = str(writable_folder(self.output.text()))
            self.settings.camera_key = self.camera.currentData() or ''
            self.settings.camera_enabled = bool(self.settings.camera_key)
            self.settings.microphone_key = self.mic.currentData() or ''
            self.settings.mic_enabled = bool(self.settings.microphone_key)
            self.settings.welcomed = True
            super().accept()
        except Exception as exc:
            self.error.setText(f'Invalid recording folder: {exc}. Choose a folder you can write to.')


class PhoneDialog(QDialog):
    disconnect_requested = Signal()
    retry_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Connect Android camera + microphone')
        self.resize(640, 740)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        heading = QLabel('Phone camera + your USB microphone.')
        heading.setObjectName('Heading')
        layout.addWidget(heading)
        layout.addWidget(note('Connect phone to the same Wi-Fi network. Scan the secure camera QR, allow camera access, then tap START CAMERA and allow microphone access. Select the USB microphone in the microphone picker on the phone page.'))
        self.qr = QLabel('Starting the local secure receiver…')
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumHeight(265)
        layout.addWidget(self.qr)
        self.status = QLabel('Waiting for receiver startup')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color:#a798ff;font-weight:700')
        layout.addWidget(self.status)
        self.secure = QLineEdit()
        self.guide = QLineEdit()
        for line, title in [(self.secure, 'HTTPS CAMERA + MICROPHONE · QR URL'), (self.guide, 'HTTP SETUP GUIDE · CERTIFICATE DOWNLOAD')]:
            layout.addWidget(note(title))
            row = QHBoxLayout()
            line.setReadOnly(True)
            row.addWidget(line, 1)
            copy = QPushButton('Copy')
            copy.clicked.connect(lambda checked=False, item=line: QApplication.clipboard().setText(item.text()))
            row.addWidget(copy)
            layout.addLayout(row)
        layout.addWidget(note('Mobile browsers block camera access on plain HTTP. If the HTTPS page is not trusted, first open the HTTP setup guide, install this PC’s local CA certificate in Android Settings, restart Chrome, and reopen the QR link. No globally unsafe browser flags are needed.'))
        self.certificate = QPushButton('Open Certificate Folder')
        self.certificate.setEnabled(False)
        self.certificate.clicked.connect(self.open_certificate)
        layout.addWidget(self.certificate)
        layout.addWidget(note('Allow Nexus on Private networks if Windows Firewall prompts. Guest Wi-Fi, VPNs, or managed certificate policies can prevent a connection. The helper is embedded locally, not a cloud/backend service.'))
        row = QHBoxLayout()
        retry = QPushButton('Retry Receiver')
        retry.clicked.connect(self.retry_requested.emit)
        disconnect = QPushButton('Disconnect Phone')
        disconnect.clicked.connect(self.disconnect_requested.emit)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(retry)
        row.addWidget(disconnect)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.info = None

    def set_info(self, info):
        self.info = info
        image = qr_image(info['https_url'])
        self.qr.setPixmap(QPixmap.fromImage(image).scaled(265, 265, Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.FastTransformation))
        self.secure.setText(info['https_url'])
        self.guide.setText(info['http_url'])
        self.certificate.setEnabled(True)
        self.status.setText(f"Receiver ready on {info['ip']} · waiting for real phone audio/video")

    def set_connection(self, connected, text):
        self.status.setText(text)
        self.status.setStyleSheet('color:#79dfba;font-weight:700' if connected else 'color:#afa0ef;font-weight:700')

    def set_error(self, text):
        self.status.setText(text)
        self.status.setStyleSheet('color:#f298a7')

    def open_certificate(self):
        if self.info and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.info['certificate']).parent))):
            self.set_error('The OS could not open the certificate folder. Path: ' + self.info['certificate'])


class SettingsDialog(QDialog):
    def __init__(self, settings, devices, diagnostic_callback, recording=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Nexus Cam Studio · Settings')
        self.resize(730, 560)
        self.original, self.value = settings, None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        general, video, audio, phone, diagnostics = [QWidget() for _ in range(5)]
        for title, page in zip(['General', 'Video', 'Audio', 'Phone', 'Diagnostics'], [general, video, audio, phone, diagnostics]):
            self.tabs.addTab(page, title)
        form = QFormLayout(general)
        form.setSpacing(17)
        field, self.output = folder_field(settings.output_folder, self)
        field.setEnabled(not recording)
        self.minimized = QCheckBox('Start minimized (after setup)')
        self.minimized.setChecked(settings.start_minimized)
        self.remember = QCheckBox('Remember the last camera')
        self.remember.setChecked(settings.remember_camera)
        form.addRow('Output Folder', field)
        form.addRow(self.minimized)
        form.addRow(self.remember)
        form.addRow(note('Settings and history are stored per user. Administrator privileges and a database are not required.'))
        v = QFormLayout(video)
        v.setSpacing(17)
        self.resolution = combo(['1920x1080', '1280x720', '854x480'], settings.resolution)
        self.fps = combo(['30', '60'], str(settings.fps))
        self.quality = combo(['Low', 'Medium', 'High'], settings.quality)
        self.format = combo(['mp4', 'mkv', 'webm'], settings.format)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(0, 50000)
        self.bitrate.setSpecialValueText('Automatic')
        self.bitrate.setSuffix(' kbps')
        self.bitrate.setValue(settings.bitrate_kbps)
        self.bitrate_note = note('')
        for title, widget in [('Resolution', self.resolution), ('FPS', self.fps), ('Quality', self.quality), ('Bitrate', self.bitrate), ('Format', self.format)]:
            v.addRow(title, widget)
        v.addRow(self.bitrate_note)
        v.addRow(note('MP4 uses H.264 when available. Fallback codecs/containers are reported, never disguised. FPS is encoded output cadence; actual camera FPS depends on the device.'))
        if recording:
            video.setEnabled(False)
        for widget in (self.resolution, self.fps, self.quality):
            widget.currentTextChanged.connect(self.update_bitrate)
        self.bitrate.valueChanged.connect(self.update_bitrate)
        self.update_bitrate()
        a = QFormLayout(audio)
        a.setSpacing(17)
        self.mic_on = QCheckBox('Record microphone')
        self.mic_on.setChecked(settings.mic_enabled)
        self.system_on = QCheckBox('Record system audio · Windows WASAPI loopback')
        self.system_on.setChecked(settings.system_enabled)
        self.mic = QComboBox()
        for d in devices.get('microphones', []):
            self.mic.addItem(d.name, d.key)
        if not self.mic.count():
            self.mic.addItem('No microphone available', '')
            self.mic_on.setChecked(False)
            self.mic_on.setEnabled(False)
        index = self.mic.findData(settings.microphone_key)
        if index >= 0:
            self.mic.setCurrentIndex(index)
        self.system = QComboBox()
        for d in devices.get('outputs', []):
            self.system.addItem(d.name, d.key)
        if not self.system.count():
            self.system.addItem('WASAPI loopback unavailable', '')
            self.system_on.setChecked(False)
            self.system_on.setEnabled(False)
        index = self.system.findData(settings.system_device_key)
        if index >= 0:
            self.system.setCurrentIndex(index)
        self.phone_mic_on = QCheckBox('Record phone microphone · choose USB input on phone page')
        self.phone_mic_on.setChecked(settings.phone_mic_enabled)
        self.phone_mic_volume = QSpinBox()
        self.phone_mic_volume.setRange(0, 100)
        self.phone_mic_volume.setSuffix(' %')
        self.phone_mic_volume.setValue(settings.phone_mic_gain)
        a.addRow(self.phone_mic_on)
        a.addRow('Phone Mic Volume', self.phone_mic_volume)
        a.addRow(self.mic_on)
        a.addRow('Microphone', self.mic)
        a.addRow(self.system_on)
        a.addRow('Playback Output', self.system)
        a.addRow(note('Microphone and system audio are mixed locally, aligned to the recording clock. Pausing excludes both audio and video. Protected/DRM audio may not be capturable.'))
        if recording:
            audio.setEnabled(False)
        p = QFormLayout(phone)
        p.setSpacing(17)
        self.port = QSpinBox()
        self.port.setRange(1024, 65534)
        self.port.setValue(settings.phone_port)
        self.auto_ip = QCheckBox('Auto-detect PC LAN IPv4 address')
        self.auto_ip.setChecked(settings.phone_auto_ip)
        self.ip = QLineEdit(settings.phone_ip)
        self.ip.setPlaceholderText('e.g. 192.168.1.25 · your PC Wi-Fi address')
        self.ip.setEnabled(not settings.phone_auto_ip)
        self.auto_ip.toggled.connect(lambda enabled: self.ip.setEnabled(not enabled))
        p.addRow('Setup HTTP Port', self.port)
        p.addRow(self.auto_ip)
        p.addRow('Manual PC IP', self.ip)
        p.addRow(note('The secure camera page uses the next port (HTTP + 1). A token-protected local receiver is started only when you click Connect Phone. Existing phone connections restart if these settings change.'))
        if recording:
            phone.setEnabled(False)
        d = QVBoxLayout(diagnostics)
        d.addWidget(note('Run real component tests: application, camera, microphone, screen capture, FFmpeg, the local HTTPS phone helper, and a short encoding/decoding probe. Missing hardware is reported as unavailable, not passed.'))
        run = QPushButton('Run Diagnostics')
        run.setObjectName('Primary')
        run.clicked.connect(lambda: diagnostic_callback(self))
        d.addWidget(run)
        d.addStretch()
        self.error = QLabel('')
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#f399a6')
        layout.addWidget(self.error)
        if recording:
            layout.addWidget(note('Video, output, audio-device and phone changes are locked while recording. You can still edit the camera overlay in the main window.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_bitrate(self, *args):
        value = replace(self.original, resolution=self.resolution.currentText(), fps=int(self.fps.currentText()),
                        quality=self.quality.currentText(), bitrate_kbps=self.bitrate.value())
        self.bitrate_note.setText(f'Effective video bitrate: {value.bitrate:,} kbps')

    def accept(self):
        try:
            folder = writable_folder(self.output.text())
            if not self.auto_ip.isChecked():
                from app.phone.network import choose_ip
                choose_ip(False, self.ip.text())
            self.value = replace(self.original, output_folder=str(folder), start_minimized=self.minimized.isChecked(),
                remember_camera=self.remember.isChecked(), resolution=self.resolution.currentText(),
                fps=int(self.fps.currentText()), quality=self.quality.currentText(), format=self.format.currentText(),
                bitrate_kbps=self.bitrate.value(), microphone_key=self.mic.currentData() or '',
                system_device_key=self.system.currentData() or '', mic_enabled=self.mic_on.isChecked(),
                system_enabled=self.system_on.isChecked(), phone_mic_enabled=self.phone_mic_on.isChecked(),
                phone_mic_gain=self.phone_mic_volume.value(), phone_port=self.port.value(),
                phone_auto_ip=self.auto_ip.isChecked(), phone_ip=self.ip.text().strip()).normalize()
            super().accept()
        except Exception as exc:
            self.error.setText(f'Settings could not be saved: {exc}')


class DiagnosticsDialog(QDialog):
    worker_created = Signal(object)

    def __init__(self, frames, devices, audio_state, phone_info, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Nexus · Diagnostics')
        self.resize(860, 480)
        self.arguments = frames, devices, audio_state, phone_info
        self.worker = None
        layout = QVBoxLayout(self)
        self.heading = QLabel('Testing real components…')
        self.heading.setObjectName('Heading')
        layout.addWidget(self.heading)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Component', 'Result', 'Details'])
        self.tree.setColumnWidth(0, 130)
        self.tree.setColumnWidth(1, 110)
        layout.addWidget(self.tree)
        layout.addWidget(note('A PASS is a performed test, not a promise about unconnected hardware. Phone Server PASS verifies HTTPS; it does not prove an Android device is connected.'))
        row = QHBoxLayout()
        self.run_button = QPushButton('Run Again')
        self.run_button.clicked.connect(self.run_tests)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(self.run_button)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)

    def run_tests(self):
        if self.worker and self.worker.isRunning():
            return
        self.tree.clear()
        self.heading.setText('Testing real components…')
        self.run_button.setEnabled(False)
        self.worker = DiagnosticWorker(*self.arguments)
        self.worker_created.emit(self.worker)
        self.worker.tested.connect(self.add_result)
        self.worker.complete.connect(self.finished_tests)
        self.worker.start()

    def add_result(self, name, status, detail):
        item = QTreeWidgetItem([name, status, detail])
        item.setToolTip(2, detail)
        item.setForeground(1, QColor('#79dfba' if status == 'PASS' else '#f2c079' if status == 'UNAVAILABLE' else '#f190a5'))
        self.tree.addTopLevelItem(item)

    def finished_tests(self, results):
        failures = [name for name, state, _ in results if state != 'PASS']
        self.heading.setText('SYSTEM READY' if len(results) == 8 and not failures else 'Check components: ' + ', '.join(failures or ['test cancelled']))
        self.run_button.setEnabled(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.heading.setText('Finishing the current diagnostic before closing…')
            self.worker.finished.connect(self.close)
            event.ignore()
        else:
            super().closeEvent(event)
