import asyncio
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QVBoxLayout, QWidget)
from app.audio.capture import AudioWorker
from app.camera.capture import CameraWorker
from app.effects.background import BACKGROUNDS, EffectWorker
from app.phone.server import PhoneWorker
from app.recorder.compositor import CompositionWorker
from app.recorder.worker import RecorderWorker
from app.screen.capture import ScreenWorker, windows
from app.settings.store import History, SettingsStore
from app.ui.dialogs import DiagnosticsDialog, PhoneDialog, SettingsDialog, WelcomeDialog, note
from app.ui.preview import PreviewWidget
from app.ui.region import RegionSelector
from app.utils.devices import DeviceWorker
from app.utils.frames import FrameStore, Scene, SceneState
from app.utils.paths import resource, unique_path, writable_folder


def duration_text(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def section(text):
    result = QLabel(text.upper())
    result.setObjectName('Section')
    result.setContentsMargins(0, 12, 0, 3)
    return result


def button(text, action, name=None):
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    result.clicked.connect(action)
    return result


def slider(value, action):
    result = QSlider(Qt.Orientation.Horizontal)
    result.setRange(0, 100)
    result.setValue(value)
    result.valueChanged.connect(action)
    return result


def scroll_panel(frame):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(frame)
    return scroll


class MainWindow(QMainWindow):
    def __init__(self, skip_welcome=False, auto_capture=True):
        super().__init__()
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.history = History()
        self.frames = FrameStore()
        self.state = SceneState()
        self.devices = {}
        self._workers = []
        self.screen_worker = None
        self.camera_worker = None
        self.audio_workers = {}
        self._audio_generation = {'mic': 0, 'system': 0}
        self.audio_ready = {'mic': False, 'system': False, 'phone': False}
        self.last_audio_block = {'mic': 0., 'system': 0., 'phone': 0.}
        self._phone_clipping_count = 0
        self._phone_clip_warning_time = 0.
        self._phone_mic_name = ''
        self.phone_worker = None
        self.phone_info = None
        self.phone_connected = False
        self.phone_dialog = None
        self.recorder = None
        self.last_saved = None
        self.last_screenshot = None
        self._last_duration = 0.
        self._record_state = 'ready'
        self._record_audit = False
        self._region_target = None
        self._screen_target = None
        self._region_dialog = None
        self._camera_generation = 0
        self._first_scan = True
        self._skip_welcome = skip_welcome
        self._auto_capture = auto_capture
        self._closing_requested = False
        self._shutdown = False
        self._can_close = False
        self._reset_after_save = False
        self._form_sync = False
        self._encoding_available = False
        self.composition_ok = True
        self.setWindowTitle('Nexus Cam Studio · 1.1')
        self.setWindowIcon(QIcon(str(resource('assets/nexus.svg'))))
        self.resize(1440, 940)
        self.setMinimumSize(1080, 710)
        self._build_ui()
        for widget in self.findChildren(QComboBox):
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(12)
        self._apply_scene()
        self._sync_overlay_form()
        self._refresh_history()
        self.composer = CompositionWorker(self.frames, self.state)
        self.composer.failed.connect(self._composition_failed)
        self._watch(self.composer)
        self.composer.start()
        self.effects = EffectWorker(self.frames, self.state)
        self.effects.failed.connect(self._effect_failed)
        self._watch(self.effects)
        self.effects.start()
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(33)
        self.ui_timer.timeout.connect(self._tick)
        self.ui_timer.start()
        QTimer.singleShot(0, self.refresh_devices)
        warning = self.store.warning or self.history.warning
        if warning:
            QTimer.singleShot(100, lambda: self.message(warning, True))

    def _watch(self, worker):
        self._workers.append(worker)
        worker.finished.connect(lambda item=worker: self._forget_worker(item))

    def _forget_worker(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)

    def _build_ui(self):
        base = QWidget()
        root = QVBoxLayout(base)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(base)
        top = QFrame()
        top.setObjectName('TopBar')
        bar = QHBoxLayout(top)
        bar.setContentsMargins(22, 15, 22, 15)
        mark = QLabel('N')
        mark.setStyleSheet('color:#b4a6ff;border:2px solid #9484f6;border-radius:10px;font-size:23px;font-weight:800;padding:2px 9px;')
        bar.addWidget(mark)
        brand = QLabel('NEXUS CAM STUDIO')
        brand.setObjectName('Title')
        bar.addWidget(brand)
        bar.addSpacing(20)
        self.new_button = button('+  New Recording', self.new_recording, 'Ghost')
        bar.addWidget(self.new_button)
        bar.addWidget(button('Open', self.open_recording, 'Ghost'))
        bar.addWidget(button('Settings', self.open_settings, 'Ghost'))
        bar.addStretch(1)
        self.status = QLabel('●  READY')
        self.status.setObjectName('Status')
        bar.addWidget(self.status)
        bar.addSpacing(12)
        self.timer_label = QLabel('00:00:00')
        self.timer_label.setObjectName('Timer')
        bar.addWidget(self.timer_label)
        root.addWidget(top)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 15, 18, 15)
        body_layout.setSpacing(12)
        self.notice = QFrame()
        self.notice.setStyleSheet('QFrame{background:#2d2941;border:1px solid #58496e;border-radius:8px;} QLabel{border:none;background:transparent;}')
        notification = QHBoxLayout(self.notice)
        self.notice_label = QLabel('')
        self.notice_label.setWordWrap(True)
        self.notice_label.setTextFormat(Qt.TextFormat.PlainText)
        notification.addWidget(self.notice_label, 1)
        notification.addWidget(button('Dismiss', self.notice.hide, 'Ghost'))
        self.notice.hide()
        body_layout.addWidget(self.notice)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.sidebar = self._sidebar()
        left = scroll_panel(self.sidebar)
        left.setMinimumWidth(230)
        left.setMaximumWidth(310)
        splitter.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(9)
        live = QHBoxLayout()
        heading = QLabel('Live preview')
        heading.setStyleSheet('font-size:16px;font-weight:700;color:#eef0ff')
        live.addWidget(heading)
        self.source_status = QLabel('Initializing sources…')
        self.source_status.setObjectName('Muted')
        live.addStretch()
        live.addWidget(self.source_status)
        center_layout.addLayout(live)
        self.preview = PreviewWidget(self.frames, self.state)
        self.preview.overlay_changed.connect(self._overlay_changed)
        center_layout.addWidget(self.preview, 1)
        self.preview_hint = note('The exported video uses this composition. Selection handles are not recorded. Minimize Nexus to avoid screen-in-screen when capturing the whole desktop.')
        center_layout.addWidget(self.preview_hint)
        history = QFrame()
        history.setObjectName('History')
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(13, 10, 13, 10)
        row = QHBoxLayout()
        label = QLabel('RECENT RECORDINGS')
        label.setObjectName('Section')
        row.addWidget(label)
        row.addStretch()
        self.history_play = button('Play', self.play_history, 'Ghost')
        self.history_folder = button('Open Folder', self.folder_history, 'Ghost')
        self.history_delete = button('Delete', self.delete_history, 'Ghost')
        for btn in (self.history_play, self.history_folder, self.history_delete):
            btn.setStyleSheet('padding:5px 9px;')
            row.addWidget(btn)
        history_layout.addLayout(row)
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(60)
        self.history_list.setMaximumHeight(110)
        self.history_list.itemSelectionChanged.connect(self._history_selection)
        self.history_list.itemDoubleClicked.connect(lambda item: self.play_history())
        history_layout.addWidget(self.history_list)
        self.history_empty = note('Your saved recordings will appear here. Files are stored locally.')
        history_layout.addWidget(self.history_empty)
        center_layout.addWidget(history)
        self.saved_row = QWidget()
        saved_layout = QHBoxLayout(self.saved_row)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        self.saved_label = QLabel('')
        self.saved_label.setStyleSheet('color:#79dfba')
        saved_layout.addWidget(self.saved_label, 1)
        saved_layout.addWidget(button('Open Folder', lambda: self.open_folder(Path(self.last_saved).parent if self.last_saved else self.settings.output_folder)))
        saved_layout.addWidget(button('Play Recording', lambda: self.play_file(self.last_saved)))
        self.saved_row.hide()
        center_layout.addWidget(self.saved_row)
        splitter.addWidget(center)
        self.inspector = self._inspector()
        right = scroll_panel(self.inspector)
        right.setMinimumWidth(210)
        right.setMaximumWidth(290)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([250, 850, 235])
        body_layout.addWidget(splitter, 1)
        bottom = QFrame()
        bottom.setObjectName('ControlBar')
        controls = QHBoxLayout(bottom)
        controls.setContentsMargins(16, 13, 16, 13)
        self.record_button = button('●  START RECORDING', self.start_recording, 'Record')
        self.pause_button = button('Ⅱ  PAUSE', self.pause_recording)
        self.stop_button = button('■  STOP', self.stop_recording)
        self.screenshot_button = button('▣  Screenshot', self.screenshot, 'Ghost')
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.record_button.setEnabled(False)
        for widget in (self.record_button, self.pause_button, self.stop_button):
            controls.addWidget(widget)
        controls.addSpacing(12)
        self.bottom_timer = QLabel('00:00:00')
        self.bottom_timer.setStyleSheet('font:16px "Consolas";color:#e6e9f6;')
        controls.addWidget(self.bottom_timer)
        controls.addStretch()
        self.quality_info = QLabel('')
        self.quality_info.setObjectName('Muted')
        controls.addWidget(self.quality_info)
        controls.addWidget(self.screenshot_button)
        body_layout.addWidget(bottom)
        root.addWidget(body, 1)

    def _sidebar(self):
        frame = QFrame()
        frame.setObjectName('Sidebar')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(9)
        layout.addWidget(section('Recording'))
        self.source_mode = QComboBox()
        self.source_mode.addItems(['Entire Screen', 'Selected Region', 'Window · visible area', 'Camera only'])
        if sys.platform != 'win32':
            self.source_mode.model().item(2).setEnabled(False)
            self.source_mode.setItemText(2, 'Window · Windows only')
        self.source_mode.currentIndexChanged.connect(self._source_mode_changed)
        layout.addWidget(self.source_mode)
        self.screen_combo = QComboBox()
        self.screen_combo.addItem('Detecting screens…', None)
        self.screen_combo.currentIndexChanged.connect(self._monitor_changed)
        layout.addWidget(self.screen_combo)
        self.window_combo = QComboBox()
        self.window_combo.currentIndexChanged.connect(self._window_changed)
        self.window_combo.hide()
        layout.addWidget(self.window_combo)
        self.screen_note = note('Capture the selected display, with cursor when supported.')
        layout.addWidget(self.screen_note)
        self.screen_button = button('START SCREEN', self.toggle_screen, 'Primary')
        layout.addWidget(self.screen_button)
        layout.addWidget(section('Camera'))
        self.camera_enabled = QCheckBox('Camera overlay')
        self.camera_enabled.setChecked(self.settings.camera_enabled)
        self.camera_enabled.toggled.connect(self._camera_changed)
        layout.addWidget(self.camera_enabled)
        self.camera_combo = QComboBox()
        self.camera_combo.addItem('Detecting webcams…', None)
        self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        layout.addWidget(self.camera_combo)
        self.camera_note = note('Checking available cameras…')
        layout.addWidget(self.camera_note)
        self.phone_button = button('Connect Phone', self.connect_phone, 'Ghost')
        layout.addWidget(self.phone_button)
        self.phone_status = note('Phone not connected')
        layout.addWidget(self.phone_status)
        layout.addWidget(section('Audio'))
        self.mic_checkbox = QCheckBox('PC Microphone')
        self.mic_checkbox.toggled.connect(lambda enabled: self._audio_toggle('mic', enabled))
        layout.addWidget(self.mic_checkbox)
        self.mic_combo = QComboBox()
        self.mic_combo.addItem('Detecting microphones…', None)
        self.mic_combo.currentIndexChanged.connect(lambda index: self._audio_toggle('mic', self.mic_checkbox.isChecked()))
        layout.addWidget(self.mic_combo)
        self.mic_slider = slider(self.settings.mic_gain, lambda v: self._gain_changed('mic', v))
        layout.addWidget(self.mic_slider)
        self.mic_meter = QProgressBar()
        self.mic_meter.setRange(0, 100)
        self.mic_meter.setTextVisible(False)
        self.mic_meter.setFixedHeight(5)
        self.mic_meter.setValue(0)
        layout.addWidget(self.mic_meter)
        self.mic_state = note('Microphone off')
        layout.addWidget(self.mic_state)
        self.phone_mic_checkbox = QCheckBox('Phone Microphone · USB / built-in')
        self.phone_mic_checkbox.setChecked(self.settings.phone_mic_enabled)
        self.phone_mic_checkbox.toggled.connect(self._phone_mic_toggle)
        layout.addWidget(self.phone_mic_checkbox)
        self.phone_mic_slider = slider(self.settings.phone_mic_gain, self._phone_gain_changed)
        self.phone_mic_slider.setToolTip('Phone microphone recording volume; does not change hardware USB gain')
        layout.addWidget(self.phone_mic_slider)
        self.phone_mic_meter = QProgressBar()
        self.phone_mic_meter.setRange(0, 100)
        self.phone_mic_meter.setTextVisible(False)
        self.phone_mic_meter.setFixedHeight(6)
        self.phone_mic_meter.setValue(0)
        layout.addWidget(self.phone_mic_meter)
        self.phone_mic_state = note('Connect phone and enable Send microphone')
        self.phone_mic_state.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.phone_mic_state)
        self.phone_only_button = button('Use Phone Mic Only', self.use_phone_mic_only, 'Ghost')
        layout.addWidget(self.phone_only_button)
        self.sys_checkbox = QCheckBox('System Audio')
        self.sys_checkbox.toggled.connect(lambda enabled: self._audio_toggle('system', enabled))
        layout.addWidget(self.sys_checkbox)
        self.sys_combo = QComboBox()
        self.sys_combo.addItem('Detecting playback outputs…', None)
        self.sys_combo.currentIndexChanged.connect(lambda index: self._audio_toggle('system', self.sys_checkbox.isChecked()))
        layout.addWidget(self.sys_combo)
        self.sys_slider = slider(self.settings.system_gain, lambda v: self._gain_changed('system', v))
        layout.addWidget(self.sys_slider)
        self.sys_meter = QProgressBar()
        self.sys_meter.setRange(0, 100)
        self.sys_meter.setTextVisible(False)
        self.sys_meter.setFixedHeight(5)
        self.sys_meter.setValue(0)
        layout.addWidget(self.sys_meter)
        self.sys_state = note('System audio off')
        layout.addWidget(self.sys_state)
        layout.addWidget(section('Effects'))
        layout.addWidget(note('Camera Background'))
        self.background_combo = QComboBox()
        self.background_combo.addItems(BACKGROUNDS)
        self.background_combo.setCurrentText(self.settings.background if self.settings.background in BACKGROUNDS else 'Original')
        self.background_combo.currentTextChanged.connect(self._background_changed)
        layout.addWidget(self.background_combo)
        self.effects_edit = button('Shape & Border →', self.focus_overlay, 'Ghost')
        layout.addWidget(self.effects_edit)
        layout.addStretch()
        self.refresh_button = button('Refresh Devices', self.refresh_devices, 'Ghost')
        layout.addWidget(self.refresh_button)
        return frame

    def _inspector(self):
        frame = QFrame()
        frame.setObjectName('Inspector')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(section('Camera overlay'))
        layout.addWidget(note('Drag on preview to move.\nDrag a corner to resize.'))
        layout.addWidget(QLabel('Camera Shape'))
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(['Circle', 'Oval', 'Rectangle', 'Rounded Rectangle', 'Square'])
        self.shape_combo.currentTextChanged.connect(self._shape_changed)
        layout.addWidget(self.shape_combo)
        layout.addWidget(section('Size & position'))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(3, 65)
        self.size_slider.valueChanged.connect(self._size_changed)
        layout.addWidget(QLabel('Size · width as % of canvas'))
        layout.addWidget(self.size_slider)
        self.overlay_height = QSpinBox()
        self.overlay_height.setSuffix(' px')
        self.overlay_height.valueChanged.connect(self._geometry_changed)
        self.position_x, self.position_y = QSpinBox(), QSpinBox()
        for spin in (self.position_x, self.position_y):
            spin.setSuffix(' px')
            spin.valueChanged.connect(self._geometry_changed)
        for label, widget in [('Height', self.overlay_height), ('Position X', self.position_x), ('Position Y', self.position_y)]:
            layout.addWidget(QLabel(label))
            layout.addWidget(widget)
        layout.addWidget(section('Border & style'))
        self.border_spin, self.radius_spin = QSpinBox(), QSpinBox()
        self.border_spin.setRange(0, 24)
        self.radius_spin.setRange(0, 200)
        self.border_spin.setSuffix(' px')
        self.radius_spin.setSuffix(' px')
        self.border_spin.valueChanged.connect(lambda value: self._scene_field('border', value))
        self.radius_spin.valueChanged.connect(lambda value: self._scene_field('radius', value))
        layout.addWidget(QLabel('Border thickness'))
        layout.addWidget(self.border_spin)
        layout.addWidget(QLabel('Corner radius · rounded rectangle'))
        layout.addWidget(self.radius_spin)
        self.color_button = button('Border Color', self.choose_border_color)
        layout.addWidget(self.color_button)
        self.shadow_checkbox = QCheckBox('Shadow')
        self.shadow_checkbox.toggled.connect(lambda enabled: self._scene_field('shadow', enabled))
        layout.addWidget(self.shadow_checkbox)
        layout.addWidget(QLabel('Opacity'))
        self.opacity_slider = slider(self.settings.opacity, lambda value: self._scene_field('opacity', value / 100))
        layout.addWidget(self.opacity_slider)
        self.mirror_checkbox = QCheckBox('Mirror camera')
        self.mirror_checkbox.toggled.connect(lambda enabled: self._scene_field('mirror', enabled))
        layout.addWidget(self.mirror_checkbox)
        layout.addStretch()
        layout.addWidget(button('Reset Overlay', self.reset_overlay, 'Ghost'))
        return frame

    def message(self, text, error=False):
        logging.warning(text) if error else logging.info(text)
        self.notice_label.setText(text)
        self.notice_label.setToolTip(text)
        self.notice.setStyleSheet('QFrame{background:#342533;border:1px solid #754550;border-radius:8px;} QLabel{border:none;background:transparent;}' if error else 'QFrame{background:#25243b;border:1px solid #50466e;border-radius:8px;} QLabel{border:none;background:transparent;}')
        self.notice.show()

    def _save_settings(self):
        self._sync_settings_from_scene()
        try:
            self.store.save(self.settings)
        except Exception as exc:
            self.message(f'Settings could not be saved: {exc}', True)

    def _apply_scene(self):
        s = self.settings
        width, height = s.dimensions
        self.state.update(width=width, height=height, fps=s.fps, x=s.overlay_x, y=s.overlay_y,
                          w=s.overlay_w, h=s.overlay_h, shape=s.overlay_shape, border=s.border_width,
                          radius=s.border_radius, color=s.border_color, shadow=s.shadow,
                          opacity=s.opacity / 100, mirror=s.mirror, background=s.background)
        self.quality_info.setText(f'{s.resolution}  ·  {s.fps} FPS  ·  {s.format.upper()}')
        self.quality_info.setToolTip(f'{s.quality} quality · {s.bitrate:,} kbps. Change in Settings → Video.')

    def _sync_settings_from_scene(self):
        scene, s = self.state.get(), self.settings
        for dest, src in [('overlay_x', 'x'), ('overlay_y', 'y'), ('overlay_w', 'w'), ('overlay_h', 'h'),
                          ('overlay_shape', 'shape'), ('border_width', 'border'), ('border_radius', 'radius'),
                          ('border_color', 'color'), ('shadow', 'shadow'), ('mirror', 'mirror'), ('background', 'background')]:
            setattr(s, dest, getattr(scene, src))
        s.opacity = round(scene.opacity * 100)
        s.camera_enabled = scene.camera_enabled
        if s.remember_camera:
            camera = self.camera_combo.currentData()
            s.camera_key = 'phone' if camera == 'phone' else getattr(camera, 'key', '')
        else:
            s.camera_key = ''

    def refresh_devices(self):
        if self.recorder or self._shutdown:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText('Detecting devices…')
        worker = DeviceWorker()
        self._watch(worker)
        worker.result.connect(self._devices_detected)
        worker.start()

    def _populate(self, widget, values, selected_key='', empty='Unavailable'):
        widget.blockSignals(True)
        widget.clear()
        for label, data in values:
            widget.addItem(label, data)
        if not values:
            widget.addItem(empty, None)
        for index in range(widget.count()):
            d = widget.itemData(index)
            key = d if isinstance(d, str) else getattr(d, 'key', '')
            if key == selected_key and selected_key:
                widget.setCurrentIndex(index)
                break
        widget.blockSignals(False)

    def _devices_detected(self, devices):
        if self._shutdown:
            return
        self.devices = devices
        self._encoding_available = bool(devices.get('encoding'))
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText('Refresh Devices')
        selected = self.settings.camera_key if self._first_scan else ('phone' if self.camera_combo.currentData() == 'phone' else getattr(self.camera_combo.currentData(), 'key', ''))
        self._populate(self.camera_combo, [(d.name, d) for d in devices.get('cameras', [])] + [('Phone Camera · Android', 'phone')], selected)
        self._populate(self.mic_combo, [(d.name, d) for d in devices.get('microphones', [])], self.settings.microphone_key, 'No microphone available')
        self._populate(self.sys_combo, [(d.name, d) for d in devices.get('outputs', [])], self.settings.system_device_key, 'WASAPI loopback unavailable')
        self._populate(self.screen_combo, [(f'Display {i + 1} · {m["width"]} × {m["height"]}', {'index': i, 'rect': m}) for i, m in enumerate(devices.get('screens', []))], empty='No display available')
        self._populate(self.window_combo, [(name, hwnd) for hwnd, name in windows(int(self.winId()))], empty='No visible windows found')
        has_mic, has_sys = bool(devices.get('microphones')), bool(devices.get('outputs'))
        self.mic_checkbox.setEnabled(has_mic)
        self.sys_checkbox.setEnabled(has_sys)
        self.mic_combo.setEnabled(has_mic)
        self.sys_combo.setEnabled(has_sys)
        self.mic_slider.setEnabled(has_mic)
        self.sys_slider.setEnabled(has_sys)
        self.mic_state.setText('Microphone off' if has_mic else 'No microphone detected')
        self.sys_state.setText('System audio off' if has_sys else 'Unavailable · requires Windows WASAPI')
        if not devices.get('cameras') and selected != 'phone':
            self.camera_enabled.blockSignals(True)
            self.camera_enabled.setChecked(False)
            self.camera_enabled.blockSignals(False)
            self.state.update(camera_enabled=False)
            self.camera_note.setText('No camera detected. Connect a webcam and click Refresh.')
        first = self._first_scan
        self._first_scan = False
        if first and not self.settings.welcomed and not self._skip_welcome:
            welcome = WelcomeDialog(self.settings, devices, self)
            if welcome.exec() == QDialog.DialogCode.Accepted:
                try:
                    self.store.save(self.settings)
                except Exception as exc:
                    self.message(f'Settings could not be saved: {exc}', True)
                self._populate(self.camera_combo, [(d.name, d) for d in devices.get('cameras', [])] + [('Phone Camera · Android', 'phone')], self.settings.camera_key)
                self.camera_enabled.blockSignals(True)
                self.camera_enabled.setChecked(bool(self.settings.camera_key))
                self.camera_enabled.blockSignals(False)
                self._populate(self.mic_combo, [(d.name, d) for d in devices.get('microphones', [])], self.settings.microphone_key, 'No microphone available')
            else:
                self.message('Setup skipped. Select your devices in the sidebar; the default output folder is shown in Settings.')
        self._camera_changed()
        for kind, checkbox, enabled in [('mic', self.mic_checkbox, self.settings.mic_enabled and has_mic),
                                        ('system', self.sys_checkbox, self.settings.system_enabled and has_sys)]:
            checkbox.blockSignals(True)
            checkbox.setChecked(enabled)
            checkbox.blockSignals(False)
            self._audio_toggle(kind, enabled)
        if first and self._auto_capture and devices.get('screens'):
            self.start_screen()
        if devices.get('errors'):
            self.message(' · '.join(devices['errors']), True)
        if first and self.settings.start_minimized and self.settings.welcomed:
            self.showMinimized()
        self._tick()

    def _source_mode_changed(self, index):
        if self.screen_worker:
            self.stop_screen()
        self._region_target = None
        self.state.update(camera_only=index == 3)
        self.screen_combo.setVisible(index in (0, 1))
        self.window_combo.setVisible(index == 2)
        self.screen_button.setEnabled(index != 3)
        self.inspector.setEnabled(index != 3)
        self.effects_edit.setEnabled(index != 3)
        self.camera_enabled.setText('Camera enabled' if index == 3 else 'Camera overlay')
        hints = ['Captures the selected display, with cursor when supported.',
                 'Select a region, resize its corners, then press Enter to confirm.',
                 'Captures the visible window area. Keep it unobscured; minimized/occluded windows are not supported.',
                 'Camera-only fills the canvas. Enable a webcam or connect a phone.']
        self.screen_note.setText(hints[index])
        self.screen_button.setText('SELECT REGION' if index == 1 else 'START SCREEN')
        if index == 3 and not self.camera_enabled.isChecked():
            self.camera_enabled.setChecked(True)

    def _monitor_changed(self, index):
        self._region_target = None
        if self.screen_worker and not self.recorder:
            self.stop_screen()
            if self.source_mode.currentIndex() == 0:
                self.start_screen()

    def _window_changed(self, index):
        if self.screen_worker and not self.recorder:
            self.stop_screen()
            self.start_screen()

    def toggle_screen(self):
        self.stop_screen() if self.screen_worker else self.start_screen()

    def start_screen(self):
        mode = self.source_mode.currentIndex()
        if mode == 3 or self._shutdown:
            return
        if mode == 2:
            hwnd = self.window_combo.currentData()
            if sys.platform != 'win32' or not hwnd:
                self.message('Selected-window capture is unavailable. Choose an entire screen or selected region.', True)
                return
            target = {'hwnd': hwnd}
            self.message('Window capture uses its visible desktop area. Keep the window unobscured and do not minimize it.')
        else:
            display = self.screen_combo.currentData()
            if not display:
                self.message('No screen detected. Check display permissions and click Refresh Devices.', True)
                return
            if mode == 1 and not self._region_target:
                try:
                    self._region_dialog = RegionSelector(display['rect'], display['index'])
                    self._region_dialog.selected.connect(self._region_selected)
                    self._region_dialog.show()
                    self._region_dialog.activateWindow()
                    self._region_dialog.setFocus()
                except Exception as exc:
                    self.message(f'Cannot select a screen region: {exc}', True)
                return
            target = self._region_target if mode == 1 else display['rect']
        self._start_screen_target(target)

    def _region_selected(self, target):
        self._region_target = target
        QTimer.singleShot(80, lambda: self._start_screen_target(target))

    def _start_screen_target(self, target):
        if self._shutdown:
            return
        self.stop_screen()
        self._screen_target = dict(target)
        worker = ScreenWorker(self.frames, target, self.settings.fps)
        self.screen_worker = worker
        self._watch(worker)
        worker.ready.connect(lambda item=worker: self._screen_ready(item))
        worker.failed.connect(lambda text, item=worker: self._screen_failed(item, text))
        self.screen_button.setText('Starting capture…')
        worker.start()

    def _screen_ready(self, worker):
        if self.screen_worker is worker:
            self.screen_button.setText('STOP SCREEN')

    def _screen_failed(self, worker, text):
        if self.screen_worker is worker:
            self.screen_worker = None
            self.frames.clear('screen')
            self.screen_button.setText('START SCREEN')
            self.message(text, True)

    def stop_screen(self):
        if self.screen_worker:
            self.screen_worker.stop()
            self.screen_worker = None
        self.frames.clear('screen')
        self.screen_button.setText('SELECT REGION' if self.source_mode.currentIndex() == 1 else 'START SCREEN')

    def _camera_changed(self, *args):
        if self._shutdown:
            return
        self._camera_generation += 1
        generation = self._camera_generation
        old, self.camera_worker = self.camera_worker, None
        if old:
            old.stop()
        self.frames.clear('camera_raw')
        self.frames.clear('camera')
        selected = self.camera_combo.currentData()
        enabled = self.camera_enabled.isChecked()
        self.state.update(camera_enabled=enabled, camera_source='phone' if selected == 'phone' else 'webcam')
        if not enabled:
            self.camera_note.setText('Camera overlay off' if self.devices.get('cameras') else 'No camera detected. Connect a webcam and click Refresh.')
            return
        if selected == 'phone':
            self.camera_note.setText('Live phone camera selected' if self.phone_connected else 'Phone not connected. Click Connect Phone.')
            return
        if selected is None:
            self.camera_note.setText('No camera selected. Refresh devices or connect a phone.')
            return
        launched = [False]
        self.camera_note.setText('Switching camera…')
        def launch():
            if launched[0] or generation != self._camera_generation or self._shutdown:
                return
            launched[0] = True
            worker = CameraWorker(self.frames, selected, self.settings.fps)
            self.camera_worker = worker
            self._watch(worker)
            worker.ready.connect(lambda item=worker: self._camera_ready(item))
            worker.failed.connect(lambda text, item=worker: self._camera_failed(item, text))
            self.camera_note.setText('Opening real camera…')
            worker.start()
        if old:
            old.finished.connect(launch)
            if not old.isRunning():
                launch()
        else:
            launch()

    def _camera_ready(self, worker):
        if self.camera_worker is worker:
            self.camera_note.setText('● Live · ' + worker.device.name)

    def _camera_failed(self, worker, text):
        if self.camera_worker is worker:
            self.camera_worker = None
            self.camera_enabled.blockSignals(True)
            self.camera_enabled.setChecked(False)
            self.camera_enabled.blockSignals(False)
            self.state.update(camera_enabled=False)
            self.camera_note.setText('Camera unavailable. Check permissions and Refresh Devices.')
            self.message(text, True)

    def _audio_toggle(self, kind, enabled):
        if self._shutdown:
            return
        self._audio_generation[kind] += 1
        generation = self._audio_generation[kind]
        old = self.audio_workers.pop(kind, None)
        if old:
            old.stop()
        self.audio_ready[kind] = False
        target = self.mic_combo if kind == 'mic' else self.sys_combo
        checkbox = self.mic_checkbox if kind == 'mic' else self.sys_checkbox
        label = self.mic_state if kind == 'mic' else self.sys_state
        meter = self.mic_meter if kind == 'mic' else self.sys_meter
        meter.setValue(0)
        device = target.currentData()
        setattr(self.settings, 'mic_enabled' if kind == 'mic' else 'system_enabled', enabled and device is not None)
        if device:
            setattr(self.settings, 'microphone_key' if kind == 'mic' else 'system_device_key', device.key)
        if not enabled:
            label.setText('Microphone off' if kind == 'mic' else 'System audio off')
            return
        if device is None:
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
            label.setText('No available audio device')
            self.message('Microphone unavailable. Connect one and Refresh Devices.' if kind == 'mic' else 'System audio requires a Windows WASAPI playback device.', True)
            return
        launched = [False]
        def launch():
            if launched[0] or generation != self._audio_generation[kind] or self._shutdown:
                return
            launched[0] = True
            worker = AudioWorker(kind, device, self._submit_audio,
                                 (self.settings.mic_gain if kind == 'mic' else self.settings.system_gain) / 100)
            self.audio_workers[kind] = worker
            self._watch(worker)
            worker.ready.connect(lambda source, item=worker: self._audio_ready(source, item))
            worker.level.connect(lambda source, value, item=worker: self._audio_level(source, value, item))
            worker.failed.connect(lambda source, text, item=worker: self._audio_failed(source, text, item))
            label.setText('Opening audio input…')
            worker.start()
        label.setText('Switching audio device…')
        if old:
            old.finished.connect(launch)
            if not old.isRunning():
                launch()
        else:
            launch()

    def _submit_audio(self, kind, data, start):
        # Called by the audio capture thread. Only thread-safe mailboxes / atomic refs here.
        self.last_audio_block[kind] = time.monotonic()
        recorder = self.recorder
        if recorder:
            recorder.submit_audio(kind, data, start)

    def _audio_ready(self, kind, worker):
        if self.audio_workers.get(kind) is worker:
            self.audio_ready[kind] = True
            (self.mic_state if kind == 'mic' else self.sys_state).setText('● Receiving microphone' if kind == 'mic' else '● Receiving system audio')

    def _audio_level(self, kind, value, worker):
        if self.audio_workers.get(kind) is worker:
            (self.mic_meter if kind == 'mic' else self.sys_meter).setValue(round(value * 100))

    def _audio_failed(self, kind, text, worker):
        if self.audio_workers.get(kind) is worker:
            self.audio_workers.pop(kind, None)
            self.audio_ready[kind] = False
            checkbox = self.mic_checkbox if kind == 'mic' else self.sys_checkbox
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
            setattr(self.settings, 'mic_enabled' if kind == 'mic' else 'system_enabled', False)
            (self.mic_state if kind == 'mic' else self.sys_state).setText('Unavailable · check device/permissions')
            (self.mic_meter if kind == 'mic' else self.sys_meter).setValue(0)
            self.message(text, True)

    def _gain_changed(self, kind, value):
        setattr(self.settings, 'mic_gain' if kind == 'mic' else 'system_gain', value)
        if kind in self.audio_workers:
            self.audio_workers[kind].gain = value / 100
        (self.mic_slider if kind == 'mic' else self.sys_slider).setToolTip(f'{value}% gain')

    def _phone_mic_toggle(self, enabled):
        self.settings.phone_mic_enabled = enabled
        if not enabled:
            self.phone_mic_state.setText('Phone mic not selected for recording')
        elif self.audio_ready.get('phone'):
            self.phone_mic_state.setText(self._phone_mic_name or '● Receiving phone microphone')
        else:
            self.phone_mic_state.setText('Waiting for phone mic · enable Send microphone and allow access')

    def _phone_gain_changed(self, value):
        self.settings.phone_mic_gain = value
        self.phone_mic_slider.setToolTip(f'{value}% phone mic recording volume (hardware gain unchanged)')

    def use_phone_mic_only(self):
        if self.recorder:
            self.message('Stop the current recording before changing microphone sources.', True)
            return
        self.mic_checkbox.setChecked(False)
        self.phone_mic_checkbox.setChecked(True)
        self.message('Phone microphone selected; PC mic is off to avoid double voice/echo. Choose your USB mic on the phone. System audio keeps its current setting.')

    def _submit_phone_audio(self, data, start):
        # Called in the receiver thread. No GUI calls or per-PCM Qt signal queue.
        self.last_audio_block['phone'] = time.monotonic()
        recorder = self.recorder
        if recorder and self.settings.phone_mic_enabled:
            recorder.submit_audio('phone', data * (self.settings.phone_mic_gain / 100), start)

    def _phone_audio_state(self, enabled, text, worker):
        if self.phone_worker is not worker:
            return
        self.audio_ready['phone'] = enabled
        self._phone_mic_name = text
        self.phone_mic_state.setText(text if self.phone_mic_checkbox.isChecked() else 'Phone input available; not selected for recording' if enabled else text)
        if enabled and not self.phone_connected:
            self.phone_status.setText('Phone microphone connected · audio-only is supported')
            if self.phone_dialog:
                self.phone_dialog.set_connection(True, 'Phone microphone connected · no camera frame yet')
        elif not enabled and not self.phone_connected and self.phone_dialog:
            self.phone_dialog.set_connection(False, text)
        if not enabled:
            self.phone_mic_meter.setValue(0)
            if self.recorder and 'phone' in self.recorder.sources:
                self.message('Phone microphone disconnected during recording. Reconnect on the phone; missing audio may be silent. Video continues.', True)

    def _phone_audio_level(self, value, clipping, worker):
        if self.phone_worker is not worker:
            return
        self.phone_mic_meter.setValue(round(value * 100))
        self.phone_mic_meter.setStyleSheet('QProgressBar::chunk{background:#f08090;}' if clipping else '')
        self._phone_clipping_count = self._phone_clipping_count + 1 if clipping else 0
        now = time.monotonic()
        if self._phone_clipping_count >= 5 and now - self._phone_clip_warning_time > 6:
            self._phone_clip_warning_time = now
            self.message('Phone mic input is clipping. Lower gain on the USB microphone/receiver or move it away from your mouth. Lowering the PC slider cannot restore already-distorted input.', True)

    def _phone_audio_error(self, text, worker):
        if self.phone_worker is worker:
            self.message(text, True)

    def connect_phone(self):
        if not self.recorder:
            self.use_phone_mic_only()
        else:
            self.message('Phone video can connect now. Stop the recording before changing microphone sources.')
        index = self.camera_combo.findData('phone')
        if index >= 0:
            self.camera_combo.setCurrentIndex(index)
        self.camera_enabled.setChecked(True)
        if not self.phone_dialog:
            self.phone_dialog = PhoneDialog(self)
            self.phone_dialog.disconnect_requested.connect(self.disconnect_phone)
            self.phone_dialog.retry_requested.connect(self._retry_phone)
        if self.phone_info:
            self.phone_dialog.set_info(self.phone_info)
            self.phone_dialog.set_connection(self.phone_connected or self.audio_ready.get('phone', False), 'PHONE CONNECTED ✓' if self.phone_connected else 'Phone microphone connected · camera is off' if self.audio_ready.get('phone') else 'Receiver ready · waiting for real phone audio/video')
        self.phone_dialog.show()
        self.phone_dialog.raise_()
        self.ensure_phone_server()

    def ensure_phone_server(self):
        if self._shutdown or (self.phone_worker and self.phone_worker.isRunning()):
            return
        worker = PhoneWorker(self.frames, self.settings, audio_callback=self._submit_phone_audio)
        self.phone_worker = worker
        self._watch(worker)
        worker.ready.connect(lambda info, item=worker: self._phone_ready(info, item))
        worker.connected.connect(lambda flag, text, item=worker: self._phone_connection(flag, text, item))
        worker.audio_state.connect(lambda flag, text, item=worker: self._phone_audio_state(flag, text, item))
        worker.audio_level.connect(lambda value, clip, item=worker: self._phone_audio_level(value, clip, item))
        worker.audio_error.connect(lambda text, item=worker: self._phone_audio_error(text, item))
        worker.failed.connect(lambda text, item=worker: self._phone_failed(text, item))
        worker.finished.connect(lambda item=worker: self._phone_finished(item))
        self.phone_status.setText('Starting local phone receiver…')
        worker.start()

    def _phone_ready(self, info, worker):
        if self.phone_worker is worker:
            self.phone_info = info
            self.phone_status.setText(f"Receiver ready · {info['ip']}:{info['https_port']}")
            if self.phone_dialog:
                self.phone_dialog.set_info(info)

    def _phone_connection(self, connected, text, worker):
        if self.phone_worker is worker:
            self.phone_connected = connected
            audio_only = not connected and self.audio_ready.get('phone', False)
            display_text = 'Phone microphone connected · camera is off' if audio_only else text
            self.phone_status.setText(display_text)
            if self.camera_combo.currentData() == 'phone':
                self.camera_note.setText('● Live · Android phone' if connected else 'Phone not connected. Click Connect Phone.')
            if self.phone_dialog:
                self.phone_dialog.set_connection(connected or audio_only, display_text)

    def _phone_failed(self, text, worker):
        if self.phone_worker is worker:
            self.phone_info = None
            self.phone_connected = False
            self.phone_status.setText('Phone receiver unavailable')
            self.message(text, True)
            if self.phone_dialog:
                self.phone_dialog.set_error(text)

    def _phone_finished(self, worker):
        if self.phone_worker is worker:
            self.phone_worker = None
            self.phone_info = None
            self.phone_connected = False
            self.phone_status.setText('Phone receiver stopped')

    def disconnect_phone(self):
        if self.phone_worker and self.phone_worker.service.loop:
            future = asyncio.run_coroutine_threadsafe(self.phone_worker.service._close_peer(), self.phone_worker.service.loop)
            def finished(task):
                try:
                    task.result()
                except Exception:
                    logging.exception('Phone disconnect failed')
            future.add_done_callback(finished)
        else:
            self.message('No phone connection is active.')

    def _retry_phone(self):
        if self.phone_worker and self.phone_worker.isRunning():
            old = self.phone_worker
            old.finished.connect(self.ensure_phone_server)
            old.stop()
            self.phone_info = None
        else:
            self.ensure_phone_server()

    def _background_changed(self, mode):
        self.state.update(background=mode)

    def _effect_failed(self, text):
        self.background_combo.blockSignals(True)
        self.background_combo.setCurrentText('Original')
        self.background_combo.blockSignals(False)
        self.message(text, True)

    def _composition_failed(self, text):
        self.composition_ok = False
        self.message(text, True)

    def _scene_field(self, name, value):
        if not self._form_sync:
            self.state.update(**{name: value})
            self.preview.update()

    def _shape_changed(self, shape):
        if self._form_sync:
            return
        scene = self.state.get()
        self.state.update(shape=shape)
        if shape in ('Circle', 'Square'):
            side = min(scene.w * scene.width, scene.h * scene.height)
            self.state.overlay(scene.x, scene.y, side / scene.width, side / scene.height)
        self._sync_overlay_form()

    def _size_changed(self, percent):
        if self._form_sync:
            return
        scene = self.state.get()
        w = percent / 100
        h = min(.95, w * scene.width / scene.height) if scene.shape in ('Circle', 'Square') else scene.h
        if scene.shape in ('Circle', 'Square'):
            w = h * scene.height / scene.width
        self.state.overlay(scene.x, scene.y, w, h)
        self._sync_overlay_form()

    def _geometry_changed(self, *args):
        if self._form_sync:
            return
        scene = self.state.get()
        self.state.overlay(self.position_x.value() / scene.width, self.position_y.value() / scene.height,
                           scene.w, self.overlay_height.value() / scene.height)
        self._sync_overlay_form()

    def _sync_overlay_form(self):
        self._form_sync = True
        scene = self.state.get()
        self.shape_combo.setCurrentText(scene.shape)
        self.size_slider.setValue(round(scene.w * 100))
        self.overlay_height.setRange(30, scene.height)
        self.overlay_height.setValue(round(scene.h * scene.height))
        self.overlay_height.setEnabled(scene.shape not in ('Circle', 'Square'))
        self.position_x.setRange(0, max(0, round((1 - scene.w) * scene.width)))
        self.position_y.setRange(0, max(0, round((1 - scene.h) * scene.height)))
        self.position_x.setValue(round(scene.x * scene.width))
        self.position_y.setValue(round(scene.y * scene.height))
        self.border_spin.setValue(scene.border)
        self.radius_spin.setValue(scene.radius)
        self.radius_spin.setEnabled(scene.shape == 'Rounded Rectangle')
        self.shadow_checkbox.setChecked(scene.shadow)
        self.mirror_checkbox.setChecked(scene.mirror)
        self.opacity_slider.setValue(round(scene.opacity * 100))
        self.color_button.setStyleSheet(f'border:1px solid {scene.color};color:{scene.color};')
        self._form_sync = False
        self.preview.update()

    def _overlay_changed(self):
        self._sync_overlay_form()

    def choose_border_color(self):
        color = QColorDialog.getColor(QColor(self.state.get().color), self, 'Camera border color')
        if color.isValid():
            self.state.update(color=color.name())
            self._sync_overlay_form()

    def focus_overlay(self):
        self.shape_combo.setFocus()
        self.shape_combo.showPopup()
        self.preview.selected = self.preview.live_overlay()
        self.preview.update()

    def reset_overlay(self):
        scene = self.state.get()
        w, h = .15, .15 * scene.width / scene.height
        self.state.update(shape='Circle', border=4, radius=32, color='#8b8aff', shadow=True, opacity=1.)
        self.state.overlay(1 - w - .025, 1 - h - .035, w, h)
        self._sync_overlay_form()

    def _has_source(self):
        scene = self.state.get()
        camera = scene.camera_enabled and not self.frames.get('camera', 2)[0].isNull()
        return camera if scene.camera_only else (camera or not self.frames.get('screen', 2)[0].isNull())

    def start_recording(self):
        if self.recorder or self._shutdown:
            return
        if not self._has_source() or not self.composition_ok:
            self.message('No live source available. Start screen capture or enable a working camera first.', True)
            return
        if not self._encoding_available:
            self.message('FFmpeg unavailable. Refresh devices or reinstall the bundled dependencies.', True)
            return
        sources = []
        for kind, enabled in [('mic', self.mic_checkbox.isChecked()), ('phone', self.phone_mic_checkbox.isChecked()), ('system', self.sys_checkbox.isChecked())]:
            if enabled:
                if not self.audio_ready.get(kind) or time.monotonic() - self.last_audio_block[kind] > 1:
                    label = {'mic': 'PC microphone', 'phone': 'Phone microphone', 'system': 'System audio'}[kind]
                    self.message(f'{label} is not delivering samples. For phone audio, allow microphone access and select the USB input on the phone page; otherwise switch this source off.', True)
                    return
                sources.append(kind)
        try:
            writable_folder(self.settings.output_folder)
        except Exception as exc:
            self.message(f'Invalid recording path: {exc}. Choose another folder in Settings.', True)
            return
        self._sync_settings_from_scene()
        self.saved_row.hide()
        self.notice.hide()
        worker = RecorderWorker(self.frames, replace(self.settings), sources, audit=self._record_audit)
        self.recorder = worker
        self._watch(worker)
        worker.status.connect(self._on_record_status)
        worker.saved.connect(self._on_record_saved)
        worker.failed.connect(self._on_record_failed)
        self._on_record_status('starting')
        worker.start()

    def _lock_record_controls(self, active):
        for widget in (self.source_mode, self.screen_combo, self.window_combo, self.screen_button, self.refresh_button,
                       self.mic_checkbox, self.mic_combo, self.sys_checkbox, self.sys_combo, self.phone_mic_checkbox, self.phone_only_button):
            widget.setEnabled(not active)
        if not active:
            self.mic_checkbox.setEnabled(bool(self.devices.get('microphones')))
            self.mic_combo.setEnabled(bool(self.devices.get('microphones')))
            self.sys_checkbox.setEnabled(bool(self.devices.get('outputs')))
            self.sys_combo.setEnabled(bool(self.devices.get('outputs')))
            self.screen_button.setEnabled(self.source_mode.currentIndex() != 3)

    def _on_record_status(self, status):
        self._record_state = status
        colors = {'recording': ('#f193a4', '#392631'), 'paused': ('#efd29d', '#3b3326'), 'saving': ('#b6a3ff', '#302941'), 'starting': ('#b6a3ff', '#302941'), 'ready': ('#78d7ba', '#1b2e31')}
        fg, bg = colors.get(status, colors['ready'])
        self.status.setText('●  ' + status.upper())
        self.status.setStyleSheet(f'color:{fg};background:{bg};padding:7px 13px;border-radius:10px;font-size:10px;font-weight:700;')
        active = status in ('starting', 'recording', 'paused', 'saving')
        self._lock_record_controls(active)
        self.pause_button.setText('▶  RESUME' if status == 'paused' else 'Ⅱ  PAUSE')
        self.pause_button.setEnabled(status in ('recording', 'paused'))
        self.stop_button.setEnabled(status in ('starting', 'recording', 'paused'))
        self.record_button.setEnabled(not active and self._has_source() and self._encoding_available)
        if status == 'saving':
            self.message('Finalizing real video and audio. Please wait; the recording is saved automatically.')

    def pause_recording(self):
        if self.recorder and self._record_state in ('recording', 'paused'):
            self.recorder.resume() if self.recorder.timeline.paused else self.recorder.pause()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self._on_record_status('saving')

    def _on_record_saved(self, path, duration, warning):
        self.last_saved, self._last_duration = path, duration
        self.recorder = None
        try:
            self.history.add(path, duration)
            self._refresh_history()
        except Exception as exc:
            self.message(f'The recording is saved, but history could not be updated: {exc}', True)
        self._on_record_status('ready')
        self.saved_label.setText('Recording Saved ✓  ' + Path(path).name)
        self.saved_label.setToolTip(path)
        self.saved_row.show()
        self.message(f'Recording saved: {path}' + (f' · {warning}' if warning else ''))
        if self._reset_after_save:
            self._reset_after_save = False
            self._last_duration = 0.
        if self._closing_requested:
            QTimer.singleShot(0, self.close)

    def _on_record_failed(self, text):
        self.recorder = None
        self._on_record_status('ready')
        self.message(text, True)
        if self._closing_requested:
            self._closing_requested = False
            self.message(text + ' The application will remain open so you can inspect the recovery files.', True)

    def new_recording(self):
        if self.recorder:
            answer = QMessageBox.question(self, 'New recording', 'Stop and save the current recording before starting a new session?')
            if answer == QMessageBox.StandardButton.Yes:
                self._reset_after_save = True
                self.stop_recording()
        else:
            self._last_duration = 0.
            self.saved_row.hide()
            self.message('New session ready. Review your live sources, then click START RECORDING.')

    def screenshot(self):
        if not self._has_source():
            self.message('Start a live screen or camera before taking a screenshot.', True)
            return
        try:
            image, _ = self.frames.get('composed', 2)
            if image.isNull():
                raise RuntimeError('No composed frame available')
            output = unique_path(writable_folder(self.settings.output_folder), 'NexusCam_Screenshot_', 'png')
            if not image.save(str(output), 'PNG'):
                raise RuntimeError('PNG writing failed; check folder permissions and disk space')
            self.last_screenshot = str(output)
            self.message(f'Screenshot saved: {output}')
        except Exception as exc:
            self.message(f'Screenshot could not be saved: {exc}', True)

    def open_settings(self):
        self._sync_settings_from_scene()
        dialog = SettingsDialog(self.settings, self.devices, self.show_diagnostics, bool(self.recorder), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            old = self.settings
            self.settings = dialog.value
            self._apply_scene()
            self._sync_overlay_form()
            self._save_settings()
            if not self.recorder:
                self.phone_mic_checkbox.setChecked(self.settings.phone_mic_enabled)
                self.phone_mic_slider.setValue(self.settings.phone_mic_gain)
                if self.screen_worker and (old.fps != self.settings.fps):
                    self._start_screen_target(self._screen_target)
                if old.fps != self.settings.fps:
                    self._camera_changed()
                for kind, box, widget, key, enabled in [
                    ('mic', self.mic_checkbox, self.mic_combo, self.settings.microphone_key, self.settings.mic_enabled),
                    ('system', self.sys_checkbox, self.sys_combo, self.settings.system_device_key, self.settings.system_enabled)]:
                    widget.blockSignals(True)
                    for i in range(widget.count()):
                        if getattr(widget.itemData(i), 'key', '') == key:
                            widget.setCurrentIndex(i)
                    widget.blockSignals(False)
                    box.blockSignals(True)
                    box.setChecked(enabled)
                    box.blockSignals(False)
                    self._audio_toggle(kind, enabled)
                if (old.phone_port, old.phone_auto_ip, old.phone_ip) != (self.settings.phone_port, self.settings.phone_auto_ip, self.settings.phone_ip) and self.phone_worker:
                    self.message('Phone settings changed. Restarting the local receiver; reconnect using the new QR.')
                    self._retry_phone()

    def show_diagnostics(self, parent=None):
        state = {kind: self.audio_ready.get(kind, False) and time.monotonic() - self.last_audio_block[kind] < 1 for kind in ('mic', 'system', 'phone')}
        dialog = DiagnosticsDialog(self.frames, self.devices, state, self.phone_info, parent or self)
        dialog.worker_created.connect(self._watch)
        QTimer.singleShot(0, dialog.run_tests)
        dialog.exec()

    def open_recording(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open a recording', self.settings.output_folder, 'Video recordings (*.mp4 *.mkv *.webm *.avi);;All files (*)')
        if path:
            self.play_file(path)

    def play_file(self, path):
        if not path or not Path(path).is_file():
            self.message('The recording file is missing. Select an existing recording.', True)
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve()))):
            self.message(f'The OS could not launch a player for {path}. Install a player such as VLC or open the file manually.', True)

    def open_folder(self, folder):
        try:
            folder = writable_folder(folder)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise RuntimeError('The OS could not launch the file explorer')
        except Exception as exc:
            self.message(f'Cannot open folder: {exc}. Path: {folder}', True)

    def _refresh_history(self):
        self.history_list.clear()
        for entry in self.history.items[:30]:
            mb = entry['size'] / 1024 / 1024
            text = f"{entry['filename']}\n{entry['date'].replace('T', '  ')}   ·   {duration_text(entry['duration'])}   ·   {mb:.1f} MB"
            if not Path(entry['path']).exists():
                text += ' · missing'
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry['path'])
            item.setToolTip(entry['path'])
            self.history_list.addItem(item)
        self.history_empty.setVisible(not self.history.items)
        if self.history_list.count():
            self.history_list.setCurrentRow(0)
        self._history_selection()

    def _history_path(self):
        item = self.history_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _history_selection(self):
        present = bool(self._history_path())
        for widget in (self.history_play, self.history_folder, self.history_delete):
            widget.setEnabled(present)

    def play_history(self):
        self.play_file(self._history_path())

    def folder_history(self):
        path = self._history_path()
        if path:
            self.open_folder(Path(path).parent)

    def delete_history(self):
        path = self._history_path()
        if not path:
            return
        answer = QMessageBox.question(self, 'Delete recording', f'Delete this recording from disk?\n{Path(path).name}\nThis cannot be undone.')
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.history.remove(path, delete_file=True)
                self._refresh_history()
                if self.last_saved == path:
                    self.last_saved = None
                    self.saved_row.hide()
            except Exception as exc:
                self.message(f'Recording could not be deleted: {exc}', True)

    def _tick(self):
        self.preview.update()
        seconds = self.recorder.timeline.elapsed() if self.recorder else self._last_duration
        text = duration_text(seconds)
        self.timer_label.setText(text)
        self.bottom_timer.setText(text)
        scene = self.state.get()
        live = []
        if not scene.camera_only and not self.frames.get('screen', 2)[0].isNull():
            live.append('screen')
        if scene.camera_enabled and not self.frames.get('camera', 2)[0].isNull():
            live.append('phone' if scene.camera_source == 'phone' else 'camera')
        self.source_status.setText('● LIVE  ·  ' + ' + '.join(live) if live else 'No live source')
        self.source_status.setStyleSheet('color:#81daba' if live else 'color:#9aa6bc')
        self.record_button.setEnabled(not self.recorder and bool(live) and self._encoding_available and self.composition_ok and not self._shutdown)
        self.screenshot_button.setEnabled(bool(live) and not self._shutdown)
        if self.audio_ready.get('phone') and time.monotonic() - self.last_audio_block['phone'] > 2:
            self.audio_ready['phone'] = False
            self.phone_mic_meter.setValue(0)
            self.phone_mic_state.setText('Phone audio stalled · keep phone awake and check Wi-Fi')
            if self.recorder and 'phone' in self.recorder.sources:
                self.message('Phone audio stalled. Keep the phone awake and reconnect its microphone; missing audio may be silent.', True)
        if self.phone_connected and self.frames.get('phone_raw', 5)[0].isNull():
            self.phone_connected = False
            self.phone_status.setText('Phone video stalled. Reconnect from the phone page.')
            if self.phone_dialog:
                self.phone_dialog.set_connection(False, 'Phone video stalled. STOP then START on the phone page.')

    def closeEvent(self, event):
        if self._can_close:
            self._save_settings()
            event.accept()
            return
        if self.recorder:
            if not self._closing_requested:
                answer = QMessageBox.question(self, 'Save before closing', 'Stop and save the current recording, then close Nexus?')
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self._closing_requested = True
                self.stop_recording()
            event.ignore()
            return
        if not self._shutdown:
            self._shutdown = True
            self.ui_timer.stop()
            # A visible non-modal pairing dialog otherwise keeps QApplication alive
            # after its main window/capture threads have closed.
            for dialog in self.findChildren(QDialog):
                dialog.close()
            self.centralWidget().setEnabled(False)
            self.setWindowTitle('Nexus Cam Studio · closing capture devices…')
            for worker in list(self._workers):
                if hasattr(worker, 'stop'):
                    worker.stop()
            self._close_timer = QTimer(self)
            self._close_timer.setInterval(100)
            self._close_timer.timeout.connect(self._finish_close)
            self._close_timer.start()
            self._close_started = time.monotonic()
            self._close_warning_shown = False
        event.ignore()
        self._finish_close()

    def _finish_close(self):
        if not any(worker.isRunning() for worker in self._workers):
            self._close_timer.stop()
            self._can_close = True
            self.close()
        elif time.monotonic() - self._close_started > 10 and not self._close_warning_shown:
            self._close_warning_shown = True
            self.message('A capture driver is still closing. If a webcam is disconnected or unresponsive, reconnect it. Nexus will close after capture threads release their devices.', True)
