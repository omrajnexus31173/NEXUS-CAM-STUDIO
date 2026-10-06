import logging
import math
import queue
import sys
import threading
import time
from dataclasses import dataclass
import numpy as np
from PySide6.QtCore import QThread, Signal
from app.utils.windows import com_thread
from app.audio.clock import CaptureSampleClock

RATE = 48000


@dataclass
class AudioDevice:
    id: object
    name: str
    key: str
    rate: int = RATE
    channels: int = 2
    default: bool = False


def microphones():
    import sounddevice as sd
    devices, apis = sd.query_devices(), sd.query_hostapis()
    default = sd.default.device[0]
    result = []
    for index, d in enumerate(devices):
        if d['max_input_channels']:
            api = apis[d['hostapi']]['name']
            result.append(AudioDevice(index, f"{d['name']} · {api}", f"{index}:{d['name']}",
                                      round(d['default_samplerate']), min(2, d['max_input_channels']), index == default))
    return sorted(result, key=lambda d: not d.default)


def system_outputs():
    if sys.platform != 'win32':
        return []
    with com_thread():
        import soundcard as sc
        try:
            default = sc.default_speaker()
        except RuntimeError:
            default = None
        return [AudioDevice(s.id, s.name, str(s.id), default=bool(default and s.id == default.id))
                for s in sc.all_speakers()]


def stereo(data):
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return np.ascontiguousarray(data)


def resample(data, source_rate, target_rate=RATE):
    if source_rate == target_rate:
        return data
    count = round(len(data) * target_rate / source_rate)
    x = np.arange(count) * source_rate / target_rate
    old = np.arange(len(data))
    return np.column_stack([np.interp(x, old, data[:, c]) for c in range(data.shape[1])]).astype(np.float32)


class AudioWorker(QThread):
    ready = Signal(str)
    level = Signal(str, float)
    failed = Signal(str, str)

    def __init__(self, kind, device, callback, gain=1., parent=None):
        super().__init__(parent)
        self.kind, self.device, self.callback = kind, device, callback
        self.gain = gain
        self._stop = threading.Event()
        self._meter_time = 0.
        self.sample_clock = CaptureSampleClock()

    def stop(self):
        self._stop.set()

    def deliver(self, data, rate, end, discontinuity=False):
        data = resample(stereo(data), rate) * self.gain
        start = self.sample_clock.stamp(len(data), end - len(data) / RATE, discontinuity)
        self.callback(self.kind, data, start)
        if end - self._meter_time >= .08:
            rms = float(np.sqrt(np.mean(data * data))) if len(data) else 0.
            db = 20 * math.log10(max(rms, 1e-6))
            self.level.emit(self.kind, max(0., min(1., (db + 60) / 60)))
            self._meter_time = end

    def run(self):
        try:
            if self.kind == 'mic':
                import sounddevice as sd
                rate = RATE
                try:
                    sd.check_input_settings(device=self.device.id, channels=self.device.channels, samplerate=rate)
                except Exception:
                    rate = self.device.rate
                count = max(128, round(rate * .02))
                blocks = queue.Queue(maxsize=100)
                callback_error = threading.Event()
                def capture(data, frames, timing, status):
                    # PortAudio's ADC timestamp compensates for driver input latency.
                    now = time.monotonic()
                    start = now + float(timing.inputBufferAdcTime - timing.currentTime)
                    try:
                        blocks.put_nowait((data.copy(), start + frames / rate, bool(status.input_overflow)))
                    except queue.Full:
                        callback_error.set()
                with sd.InputStream(device=self.device.id, samplerate=rate, channels=self.device.channels,
                                    dtype='float32', blocksize=count, latency='low', callback=capture):
                    first, overflow_count = True, 0
                    while not self._stop.is_set():
                        if callback_error.is_set():
                            raise RuntimeError('Microphone processing queue overflowed; lower recording quality or close other capture apps')
                        try:
                            data, end, overflow = blocks.get(timeout=.2)
                        except queue.Empty:
                            continue
                        if first:
                            self.ready.emit(self.kind)
                            first = False
                        overflow_count = overflow_count + 1 if overflow else 0
                        if overflow_count > 50:
                            raise RuntimeError('Audio input repeatedly overflowed; select another device or close other recorders')
                        self.deliver(data, rate, end, overflow)
            else:
                if sys.platform != 'win32':
                    raise RuntimeError('System audio uses Windows WASAPI loopback and is unavailable on this OS')
                with com_thread():
                    import soundcard as sc
                    device = sc.get_microphone(id=self.device.id, include_loopback=True)
                    if not device or not device.isloopback:
                        raise RuntimeError('The selected Windows output does not expose WASAPI loopback')
                    with device.recorder(samplerate=RATE, blocksize=960) as recorder:
                        first = True
                        while not self._stop.is_set():
                            data = recorder.record(numframes=960)
                            if first:
                                self.ready.emit(self.kind)
                                first = False
                            self.deliver(data, RATE, time.monotonic())
        except Exception as exc:
            logging.exception('%s audio failed', self.kind)
            message = ('Microphone unavailable' if self.kind == 'mic' else 'System audio unavailable')
            self.failed.emit(self.kind, f'{message}: {exc}. Check Windows audio/privacy settings and the selected device.')
        finally:
            self.level.emit(self.kind, 0.)
