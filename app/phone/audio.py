"""Decode real WebRTC Opus frames into canonical float32 stereo 48 kHz PCM."""
import math
import time
import av
import numpy as np
from app.audio.clock import MediaSampleClock


class PhoneAudioDecoder:
    def __init__(self):
        self.resampler = av.AudioResampler(format='fltp', layout='stereo', rate=48000)
        self.clock = MediaSampleClock()

    def convert(self, frame, arrival=None):
        arrival = time.monotonic() if arrival is None else arrival
        blocks = []
        for converted in self.resampler.resample(frame):
            data = np.ascontiguousarray(converted.to_ndarray().T, dtype=np.float32)
            if data.ndim != 2 or data.shape[1] != 2 or not np.isfinite(data).all():
                raise RuntimeError('Phone sent invalid audio samples')
            media_time = float(converted.pts * converted.time_base) if converted.pts is not None and converted.time_base else None
            start, reset = self.clock.stamp(len(data), media_time, arrival)
            rms = float(np.sqrt(np.mean(data * data))) if data.size else 0.
            peak = float(np.max(np.abs(data))) if data.size else 0.
            level = max(0., min(1., (20 * math.log10(max(rms, 1e-6)) + 60) / 60))
            blocks.append((data, start, level, peak >= .985, reset))
        return blocks
