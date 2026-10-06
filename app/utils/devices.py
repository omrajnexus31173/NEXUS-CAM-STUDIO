from PySide6.QtCore import QThread, Signal
from app.camera.capture import cameras
from app.audio.capture import microphones, system_outputs
from app.screen.capture import monitors
from app.recorder.ffmpeg import choose_encoding


class DeviceWorker(QThread):
    result = Signal(object)

    def run(self):
        result = {'errors': []}
        for name, callback in [('cameras', cameras), ('microphones', microphones),
                               ('outputs', system_outputs), ('screens', monitors), ('encoding', choose_encoding)]:
            try:
                result[name] = callback()
            except Exception as exc:
                result[name] = [] if name != 'encoding' else None
                label = {'outputs': 'System audio', 'microphones': 'Microphone', 'screens': 'Screen capture', 'encoding': 'FFmpeg', 'cameras': 'Camera'}[name]
                result['errors'].append(f'{label} unavailable: {exc}. Check the device/permissions and click Refresh Devices.')
        self.result.emit(result)
