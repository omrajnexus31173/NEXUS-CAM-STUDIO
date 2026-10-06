import json
import time
import wave
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from app.audio.capture import resample, stereo
from app.audio.session import AudioSession
from app.effects.background import BackgroundProcessor, BACKGROUNDS
from app.recorder.compositor import compose
from app.recorder.timeline import Timeline
from app.settings.store import History, Settings, SettingsStore
from app.ui.dialogs import WelcomeDialog, SettingsDialog
from app.ui.preview import PreviewWidget
from app.utils.frames import FrameStore, Scene, SceneState, bgr_image, image_bgr


def solid(width, height, color):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


def test_settings_and_history_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / 'settings.json')
    settings = store.load()
    assert settings.dimensions == (1920, 1080) and settings.fps == 30 and settings.bitrate == 8000
    settings.fps = 60
    assert settings.bitrate == 12800
    settings.camera_key = 'usb-real-key'
    settings.overlay_x = -100
    settings.format = 'invalid'
    store.save(settings)
    read = store.load()
    assert read.camera_key == 'usb-real-key' and read.overlay_x == 0 and read.format == 'mp4'
    store.path.write_text('{invalid json')
    assert store.load().dimensions == (1920, 1080) and store.warning
    file = tmp_path / 'actual-test-file.mp4'
    file.write_bytes(b'unit-test-history-not-a-recording')
    history = History(tmp_path / 'history.json')
    history.add(file, 1.25)
    assert History(history.path).items[0]['size'] == file.stat().st_size
    history.remove(str(file), delete_file=True)
    assert not file.exists() and not history.items


def test_shared_pause_timeline_clips_audio():
    clock = [10.]
    timeline = Timeline(lambda: clock[0])
    timeline.start()
    clock[0] = 11.
    timeline.pause()
    clock[0] = 13.
    assert timeline.elapsed() == 1. and timeline.paused
    timeline.resume()
    clock[0] = 14.
    timeline.stop()
    assert timeline.elapsed() == 2.
    assert timeline.map_block(10., 400, 100) == [(0, 100, 0), (300, 400, 100)]


@pytest.mark.parametrize('shape', ['Circle', 'Oval', 'Rectangle', 'Rounded Rectangle', 'Square'])
def test_compositor_shapes_borders_and_opacity(shape):
    scene = Scene(width=640, height=360, x=.5, y=.3, w=.25, h=160 / 360,
                  shape=shape, border=4, shadow=False, color='#ff0000')
    screen, camera = solid(640, 360, '#102030'), solid(200, 200, '#00ff00')
    image = compose(scene, screen, camera)
    assert image.pixelColor(400, 188).green() > 240
    corner = image.pixelColor(325, 113)
    if shape in ('Circle', 'Oval', 'Rounded Rectangle'):
        assert corner == QColor('#102030')
    else:
        assert corner.green() > 240
    if shape == 'Circle':
        assert image.pixelColor(400, 108).red() > 180
    scene.opacity = .5
    translucent = compose(scene, screen, camera)
    assert 125 < translucent.pixelColor(400, 188).green() < 160
    # Turning the camera off also turns it off in camera-only recording.
    scene.camera_only, scene.camera_enabled = True, False
    assert compose(scene, screen, camera).pixelColor(400, 188).green() < 200


def test_image_conversion_and_stereo_resampling():
    array = np.full((91, 153, 3), (25, 70, 190), np.uint8)
    assert np.array_equal(image_bgr(bgr_image(array)), array)
    mono = np.zeros((441, 1), np.float32)
    assert resample(stereo(mono), 44100).shape == (480, 2)


def test_audio_writer_removes_paused_samples(tmp_path):
    clock = [100.]
    timeline = Timeline(lambda: clock[0])
    timeline.start()
    clock[0] = 100.1
    timeline.pause()
    clock[0] = 100.3
    timeline.resume()
    clock[0] = 100.4
    timeline.stop()
    session = AudioSession(timeline, tmp_path, ('mic',))
    # Deliberately feed a timestamped test fixture (not hardware microphone input).
    session.queue.put(('mic', np.full((19200, 2), .25, np.float32), 100.))
    paths = session.close(.2)
    with wave.open(str(paths[0]), 'rb') as wav:
        assert wav.getnframes() == 9600 and wav.getnchannels() == 2
        samples = np.frombuffer(wav.readframes(9600), '<i2')
        assert np.mean(samples) > 8000


def test_real_bundled_segmentation_and_all_background_modes():
    processor = BackgroundProcessor()
    frame = np.full((240, 320, 3), 128, np.uint8)
    processor.segment(frame)  # Run the actual bundled neural network.
    assert processor.mask.shape == (240, 320, 1) and np.isfinite(processor.mask).all()
    assert 0 <= processor.mask.min() <= processor.mask.max() <= 1
    for mode in BACKGROUNDS:
        result = processor.apply(frame, mode)
        assert result.shape == frame.shape and result.dtype == np.uint8
    bad = BackgroundProcessor(Path('/nonexistent/nexus-model.onnx'))
    with pytest.raises(RuntimeError, match='missing'):
        bad.apply(frame, 'Plain Blue')


def test_overlay_drag_resize_and_keyboard(qtbot):
    frames = FrameStore()
    frames.put('camera', solid(160, 160, '#00ff00'))  # Explicit unit fixture.
    state = SceneState(Scene(width=640, height=360, x=.6, y=.4, w=.2, h=128 / 360))
    preview = PreviewWidget(frames, state)
    preview.resize(800, 500)
    qtbot.addWidget(preview)
    preview.show()
    qtbot.wait(30)
    point = preview.camera_rect().center().toPoint()
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(preview, point + QPoint(-80, -40), delay=30)
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=point + QPoint(-80, -40))
    moved = state.get()
    assert moved.x < .6 and moved.y < .4
    corner = preview.camera_rect().bottomRight().toPoint()
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(preview, corner + QPoint(50, 50), delay=30)
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=corner + QPoint(50, 50))
    resized = state.get()
    assert resized.w > moved.w
    assert abs(resized.w * 640 - resized.h * 360) < .01
    QTest.keyClick(preview, Qt.Key.Key_Left)
    assert state.get().x < resized.x


def test_first_run_and_video_settings_are_real(tmp_path, qtbot):
    from app.camera.capture import CameraDevice
    settings = Settings().normalize()
    devices = {'cameras': [CameraDevice(0, 'TEST ENUMERATION FIXTURE', 0, 'fixture')], 'microphones': []}
    welcome = WelcomeDialog(settings, devices)
    qtbot.addWidget(welcome)
    welcome.camera.setCurrentIndex(0)
    welcome.output.setText(str(tmp_path / 'chosen-output'))
    welcome.accept()
    assert settings.welcomed and not settings.camera_enabled and not settings.camera_key
    assert Path(settings.output_folder).is_dir()
    dialog = SettingsDialog(settings, devices, lambda p: None)
    qtbot.addWidget(dialog)
    dialog.resolution.setCurrentText('1280x720')
    dialog.fps.setCurrentText('60')
    dialog.quality.setCurrentText('Low')
    dialog.format.setCurrentText('webm')
    dialog.accept()
    assert dialog.value.dimensions == (1280, 720) and dialog.value.fps == 60
    assert dialog.value.format == 'webm' and dialog.value.bitrate == 1778


def test_real_qt_qr_raster_is_decodable():
    import cv2
    from app.utils.qr import qr_image
    value = 'https://192.168.12.34:8766/?token=valid-real-qr-test-value'
    raster = image_bgr(qr_image(value))
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(raster)
    assert decoded == value


def test_microphone_callback_meter_and_adc_timestamps_are_real_code(qtbot, monkeypatch):
    # Explicit hardware API fixture; this is NOT a physical-microphone pass.
    import threading
    from types import SimpleNamespace
    import sounddevice as sd
    from app.audio.capture import AudioDevice, AudioWorker
    delivered, levels = [], []
    class StreamFixture:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
            self.stop = threading.Event()
        def __enter__(self):
            def feed():
                while not self.stop.is_set():
                    self.callback(np.full((960, 1), .2, np.float32), 960,
                        SimpleNamespace(inputBufferAdcTime=12., currentTime=12.03), SimpleNamespace(input_overflow=False))
                    self.stop.wait(.02)
            self.thread = threading.Thread(target=feed)
            self.thread.start()
            return self
        def __exit__(self, *args):
            self.stop.set()
            self.thread.join(2)
    monkeypatch.setattr(sd, 'check_input_settings', lambda **kw: None)
    monkeypatch.setattr(sd, 'InputStream', StreamFixture)
    worker = AudioWorker('mic', AudioDevice(0, 'Explicit API test fixture', 'fixture', channels=1),
                         lambda kind, data, start: delivered.append((data, start)))
    worker.level.connect(lambda kind, value: levels.append(value))
    try:
        worker.start()
        qtbot.waitUntil(lambda: bool(delivered) and bool(levels), timeout=3000)
        assert delivered[0][0].shape == (960, 2)
        assert levels[0] > .5
        assert time.monotonic() - delivered[-1][1] >= .02  # ADC latency used.
    finally:
        worker.stop()
        assert worker.wait(3000)
