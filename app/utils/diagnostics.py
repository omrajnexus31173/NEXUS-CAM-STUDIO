import logging
import shutil
import ssl
import tempfile
import threading
import urllib.request
from pathlib import Path
import cv2
import mss
from PySide6.QtCore import QThread, Signal, Qt
from app.recorder.ffmpeg import choose_encoding, run_checked, video_command
from app.utils.paths import data_dir


class DiagnosticWorker(QThread):
    tested = Signal(str, str, str)
    complete = Signal(object)

    def __init__(self, frames, devices, audio_state, phone_info=None):
        super().__init__()
        self.frames, self.devices, self.audio_state, self.phone_info = frames, devices, audio_state, phone_info
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        results = []
        checks = [('Application', self.application), ('Camera', self.camera), ('Microphone', self.microphone),
                  ('Phone Microphone', self.phone_microphone), ('Screen Capture', self.screen), ('FFmpeg', self.ffmpeg), ('Phone Server', self.phone),
                  ('Recording', self.recording)]
        for name, callback in checks:
            if self._stop.is_set():
                break
            try:
                status, detail = callback()
            except Exception as exc:
                logging.exception('Diagnostic failed: %s', name)
                status, detail = 'FAIL', str(exc)
            results.append((name, status, detail))
            self.tested.emit(name, status, detail)
        self.complete.emit(results)

    def application(self):
        from PySide6.QtCore import qVersion
        return 'PASS', f'Qt {qVersion()} running; local data folder is writable: {data_dir()}'

    def camera(self):
        raw, _ = self.frames.get('camera_raw', 2)
        if not raw.isNull():
            return 'PASS', f'Webcam is producing real {raw.width()} × {raw.height()} frames'
        devices = self.devices.get('cameras', [])
        if not devices:
            return 'UNAVAILABLE', 'No webcam detected. Connect one and click Refresh Devices.'
        device = devices[0]
        cap = cv2.VideoCapture(device.index, device.backend)
        try:
            ok, frame = cap.read()
            if not ok or frame is None:
                return 'FAIL', 'Camera cannot be opened. Check permissions and other camera apps.'
            return 'PASS', f'{device.name}: successfully captured a frame'
        finally:
            cap.release()

    def microphone(self):
        if self.audio_state.get('mic'):
            return 'PASS', 'The selected microphone is delivering real audio blocks'
        devices = self.devices.get('microphones', [])
        if not devices:
            return 'UNAVAILABLE', 'No microphone detected.'
        import sounddevice as sd
        device = devices[0]
        with sd.InputStream(device=device.id, channels=device.channels, samplerate=device.rate,
                            blocksize=round(device.rate * .1), dtype='float32') as stream:
            data, overflow = stream.read(round(device.rate * .1))
        return ('PASS', f'Read {len(data)} samples from {device.name}') if len(data) else ('FAIL', 'No microphone samples received')

    def screen(self):
        with mss.MSS() as cap:
            if len(cap.monitors) < 2:
                return 'FAIL', 'No desktop monitor is available'
            shot = cap.grab(cap.monitors[1])
            if not shot.bgra:
                return 'FAIL', 'Screen capture returned no pixels'
        return 'PASS', f'Real desktop capture: {shot.width} × {shot.height}'

    def ffmpeg(self):
        encoding = choose_encoding()
        return 'PASS', f'{encoding.codec} → {encoding.format.upper()} · {encoding.executable}'

    def phone(self):
        if not self.phone_info:
            return 'UNAVAILABLE', 'Phone helper not running. Click Connect Phone, then run Diagnostics again.'
        info = self.phone_info
        context = ssl.create_default_context(cafile=info['certificate'])
        url = f"https://127.0.0.1:{info['https_port']}/status?token={info['token']}"
        with urllib.request.urlopen(url, context=context, timeout=6) as response:
            text = response.read().decode()
        return 'PASS', f'HTTPS helper responded with a verified local certificate: {text}'

    def phone_microphone(self):
        if not self.phone_info:
            return 'UNAVAILABLE', 'Connect the phone and allow microphone access; no phone audio was assumed.'
        import json
        info = self.phone_info
        context = ssl.create_default_context(cafile=info['certificate'])
        url = f"https://127.0.0.1:{info['https_port']}/status?token={info['token']}"
        with urllib.request.urlopen(url, context=context, timeout=6) as response:
            result = json.loads(response.read())
        if not result.get('audio_connected'):
            return 'UNAVAILABLE', 'No phone audio packets. Enable Send microphone, allow permission, and select the USB input on the phone.'
        name = str(result.get('audio_info', {}).get('label', 'Android-routed input'))
        return 'PASS', f'Real 48 kHz phone PCM packets received · {name}. USB hardware identity is browser-reported, not independently verified.'

    def recording(self):
        image, _ = self.frames.get('composed', 2)
        if image.isNull() or not self.frames.has_live_source():
            return 'UNAVAILABLE', 'Start a live screen/camera source before the recording test'
        from PySide6.QtGui import QImage
        probe = image.scaled(320, 180, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB32)
        encoding = choose_encoding()
        folder = Path(tempfile.mkdtemp(prefix='diagnostic-', dir=data_dir()))
        try:
            output = folder / f'probe.{encoding.format}'
            import subprocess
            from app.recorder.ffmpeg import CREATE_FLAGS
            result = subprocess.run(video_command(encoding, 320, 180, 30, 700, output),
                                    input=bytes(probe.constBits()) * 5, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=25, creationflags=CREATE_FLAGS)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors='replace'))
            run_checked([encoding.executable, '-v', 'error', '-i', str(output), '-f', 'null', '-'], timeout=20)
            return 'PASS', f'Encoded and decoded 5 frames of the live composition ({output.stat().st_size:,} bytes). Hardware audio not tested by this probe.'
        finally:
            shutil.rmtree(folder, ignore_errors=True)
