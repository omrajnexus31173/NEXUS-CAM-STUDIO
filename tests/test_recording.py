import os
import shutil
import threading
import time
from pathlib import Path
import av
import mss
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget
from app.recorder.compositor import CompositionWorker
from app.recorder.worker import RecorderWorker
from app.screen.capture import ScreenWorker, monitors
from app.settings.store import Settings, SettingsStore
from app.ui.main_window import MainWindow
from app.utils.frames import FrameStore, Scene, SceneState
from app.camera.capture import CameraDevice, CameraWorker
from app.audio.capture import AudioDevice, AudioWorker
from app.utils.diagnostics import DiagnosticWorker


def require_desktop():
    if os.name != 'nt' and not os.environ.get('DISPLAY'):
        pytest.skip('An actual desktop/Xvfb display is required')


def test_missing_devices_report_errors_without_crashing(qtbot):
    frames = FrameStore()
    camera = CameraWorker(frames, CameraDevice(9999, 'Invalid-device test', 0, 'missing'))
    errors = []
    camera.failed.connect(errors.append)
    camera.start()
    qtbot.waitUntil(lambda: not camera.isRunning(), timeout=8000)
    qtbot.waitUntil(lambda: bool(errors), timeout=2000)
    assert 'unavailable' in errors[0].lower() and frames.get('camera_raw')[0].isNull()
    microphone = AudioWorker('mic', AudioDevice(9999, 'Invalid-device test', 'missing'), lambda *a: None)
    mic_errors = []
    microphone.failed.connect(lambda kind, message: mic_errors.append(message))
    microphone.start()
    qtbot.waitUntil(lambda: not microphone.isRunning(), timeout=5000)
    qtbot.waitUntil(lambda: bool(mic_errors), timeout=2000)
    assert 'Microphone unavailable' in mic_errors[0]


@pytest.mark.desktop
def test_real_screen_capture_pixels(qtbot):
    require_desktop()
    widget = QWidget()
    widget.setStyleSheet('background:#3175bc;')
    widget.setGeometry(50, 60, 300, 200)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.wait(80)
    frames = FrameStore()
    target = {'left': 60, 'top': 70, 'width': 160, 'height': 120}
    worker = ScreenWorker(frames, target)
    try:
        worker.start()
        qtbot.waitUntil(lambda: not frames.get('screen')[0].isNull(), timeout=3000)
        image = frames.get('screen')[0]
        assert (image.width(), image.height()) == (160, 120)
        assert image.pixelColor(50, 50) == QColor('#3175bc')
    finally:
        worker.stop()
        assert worker.wait(3000)


@pytest.mark.desktop
@pytest.mark.parametrize('fmt', ['mp4', 'mkv', 'webm'])
def test_real_encoding_audio_mux_pause_and_burned_overlay(tmp_path, qtbot, fmt):
    require_desktop()
    backdrop = QWidget()
    backdrop.setStyleSheet('background:#24486c;')
    qtbot.addWidget(backdrop)
    backdrop.showFullScreen()
    qtbot.wait(80)
    frames = FrameStore()
    scene = Scene(width=854, height=480, fps=30, x=.72, y=.64, w=.17, h=.17 * 854 / 480,
                  border=4, shadow=False, color='#ff0000', camera_source='phone')
    state = SceneState(scene)
    camera = QImage(200, 200, QImage.Format.Format_RGB32)
    camera.fill(QColor('#00ee44'))
    # Explicit synthetic overlay test fixture, NOT a webcam/phone hardware claim.
    frames.put('camera', camera)
    screen = ScreenWorker(frames, monitors()[0])
    composer = CompositionWorker(frames, state)
    settings = Settings(output_folder=str(tmp_path), resolution='854x480', format=fmt, quality='Low').normalize()
    recorder = RecorderWorker(frames, settings, ('mic', 'system'))
    errors, saved = [], []
    recorder.failed.connect(errors.append)
    recorder.saved.connect(lambda path, duration, warning: saved.append((path, duration, warning)))
    stop_audio = threading.Event()
    def fixture_audio():
        while not stop_audio.is_set():
            now = time.monotonic()
            sine = (.15 * np.sin(2 * np.pi * 220 * np.arange(960) / 48000)).astype(np.float32)
            data = np.column_stack((sine, sine))
            recorder.submit_audio('mic', data, now - .02)
            recorder.submit_audio('system', data * .5, now - .02)
            stop_audio.wait(.02)
    audio = threading.Thread(target=fixture_audio)
    try:
        screen.start()
        composer.start()
        qtbot.waitUntil(lambda: frames.has_live_source() and not frames.get('composed')[0].isNull(), timeout=4000)
        recorder.start()
        audio.start()
        qtbot.waitUntil(lambda: recorder.timeline.started or bool(errors), timeout=8000)
        assert not errors
        qtbot.wait(420)
        recorder.pause()
        pause_time = recorder.timeline.elapsed()
        qtbot.wait(260)
        assert abs(recorder.timeline.elapsed() - pause_time) < .002
        recorder.resume()
        qtbot.wait(400)
        recorder.stop()
        qtbot.waitUntil(lambda: not recorder.isRunning(), timeout=30000)
        qtbot.waitUntil(lambda: bool(saved) or bool(errors), timeout=3000)
        assert not errors, errors
        path, duration, warning = saved[0]
        assert Path(path).stat().st_size > 5000 and path.endswith('.' + fmt)
        with av.open(path) as container:
            assert len(container.streams.video) == 1 and len(container.streams.audio) == 1
            video = container.streams.video[0]
            assert video.width == 854 and video.height == 480
            assert float(video.average_rate) == 30
            if fmt == 'mp4':
                assert video.codec_context.name == 'h264'
            image = next(container.decode(video)).to_ndarray(format='rgb24')
            center = image[round((scene.y + scene.h / 2) * 480), round((scene.x + scene.w / 2) * 854)]
            corner = image[round(scene.y * 480 + 7), round(scene.x * 854 + 7)]
            assert center[1] > 200 and center[0] < 30  # Camera is burned into final video.
            assert corner[1] < 150  # Circle corner is the captured screen, not a rectangle.
            assert abs(container.duration / av.time_base - duration) < .10
        with av.open(path) as container:
            samples = [f.to_ndarray() for f in container.decode(audio=0)]
            assert samples and max(float(np.max(np.abs(s))) for s in samples) > .01
        assert .7 < duration < 1.1  # Pause was removed, not silently recorded.
        if os.environ.get('NEXUS_TEST_ARTIFACTS'):
            shutil.copy(path, Path(os.environ['NEXUS_TEST_ARTIFACTS']) / f'pipeline-tested.{fmt}')
    finally:
        stop_audio.set()
        if audio.is_alive():
            audio.join(3)
        if recorder.isRunning():
            recorder.stop()
            recorder.wait(30000)
        screen.stop()
        composer.stop()
        assert screen.wait(5000) and composer.wait(5000)


@pytest.mark.desktop
def test_native_ui_actual_recording_screenshot_history_and_diagnostics(tmp_path, qtbot):
    require_desktop()
    settings = Settings(welcomed=True, output_folder=str(tmp_path / 'videos'), resolution='1280x720', fps=60)
    SettingsStore().save(settings)
    window = MainWindow(skip_welcome=True)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window._has_source() and window._encoding_available and window.record_button.isEnabled() and window.source_status.text().startswith('● LIVE'), timeout=15000)
        assert window.isVisible() and window.source_status.text().startswith('● LIVE')
        qtbot.mouseClick(window.screenshot_button, Qt.MouseButton.LeftButton)
        assert window.last_screenshot and Path(window.last_screenshot).is_file()
        screenshot = QImage(window.last_screenshot)
        assert (screenshot.width(), screenshot.height()) == (1280, 720)
        qtbot.mouseClick(window.record_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: window._record_state == 'recording', timeout=10000)
        qtbot.wait(1150)
        assert window.timer_label.text() >= '00:00:01'
        qtbot.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
        assert window.recorder.timeline.paused
        qtbot.wait(120)
        qtbot.mouseClick(window.pause_button, Qt.MouseButton.LeftButton)
        assert not window.recorder.timeline.paused
        qtbot.wait(300)
        qtbot.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: window.recorder is None, timeout=30000)
        assert window.last_saved and Path(window.last_saved).exists()
        assert window.history_list.count() == 1
        assert window.saved_label.text().startswith('Recording Saved ✓')
        with av.open(window.last_saved) as container:
            assert container.streams.video[0].width == 1280
            assert float(container.streams.video[0].average_rate) == 60
            assert next(container.decode(video=0)).width == 1280
        results = []
        diagnostics = DiagnosticWorker(window.frames, window.devices, {'mic': False})
        diagnostics.complete.connect(results.extend)
        diagnostics.start()
        qtbot.waitUntil(lambda: not diagnostics.isRunning(), timeout=35000)
        qtbot.waitUntil(lambda: bool(results), timeout=2000)
        assert all(state == 'PASS' for name, state, detail in results if name in ('Application', 'Screen Capture', 'FFmpeg', 'Recording'))
        if not window.devices.get('cameras'):
            assert next(r for r in results if r[0] == 'Camera')[1] == 'UNAVAILABLE'
        if os.environ.get('NEXUS_TEST_ARTIFACTS'):
            folder = Path(os.environ['NEXUS_TEST_ARTIFACTS'])
            shutil.copy(window.last_saved, folder / 'ui-tested-720p60.mp4')
            shutil.copy(window.last_screenshot, folder / 'composed-screenshot-tested.png')
            window.grab().save(str(folder / 'ui-recording-saved.png'))
    finally:
        if window.recorder:
            window.recorder.stop()
            qtbot.waitUntil(lambda: window.recorder is None, timeout=30000)
        window.close()
        qtbot.waitUntil(lambda: window._can_close, timeout=12000)


@pytest.mark.desktop
def test_selected_region_resizable_picker_returns_real_coordinates(qtbot):
    require_desktop()
    from app.ui.region import RegionSelector
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    monitor = monitors()[0]
    picker = RegionSelector(monitor)
    qtbot.addWidget(picker)
    selected = []
    picker.selected.connect(selected.append)
    picker.show()
    qtbot.wait(40)
    width = picker.selection.width()
    corner = picker.selection.bottomRight().toPoint()
    QTest.mousePress(picker, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(picker, corner + QPoint(-60, -40), delay=25)
    QTest.mouseRelease(picker, Qt.MouseButton.LeftButton, pos=corner + QPoint(-60, -40))
    assert picker.selection.width() < width
    QTest.keyClick(picker, Qt.Key.Key_Return)
    assert selected and 32 <= selected[0]['width'] < monitor['width']
    assert selected[0]['left'] >= monitor['left']


def test_ffmpeg_missing_is_reported_not_simulated(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv('NEXUS_FFMPEG', str(tmp_path / 'missing-ffmpeg.exe'))
    worker = RecorderWorker(FrameStore(), Settings(output_folder=str(tmp_path)).normalize())
    errors, saved = [], []
    worker.failed.connect(errors.append)
    worker.saved.connect(lambda *args: saved.append(args))
    worker.start()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=5000)
    qtbot.waitUntil(lambda: bool(errors), timeout=2000)
    assert 'does not exist' in errors[0] and not saved
    assert not list(tmp_path.glob('*.mp4'))
