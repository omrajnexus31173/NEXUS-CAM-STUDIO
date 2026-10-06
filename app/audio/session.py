"""Timestamp-aligned audio files for a real video/audio final mux.
Capture never blocks on disk. Silence is inserted ONLY for real capture gaps.
"""
import queue
import threading
import wave
from pathlib import Path
import numpy as np
from app.audio.capture import RATE


class AudioSession:
    def __init__(self, timeline, folder, sources):
        self.timeline = timeline
        self.folder = Path(folder)
        self.sources = tuple(sources)
        self.queue = queue.Queue(maxsize=400)
        self.error = ''
        self.latest_end = {kind: 0. for kind in sources}
        self._arrived = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name='Audio file writer', daemon=True)
        self._thread.start()

    def submit(self, kind, data, start):
        if kind not in self.sources or not self.timeline.started:
            return
        # Closing/sentinel and enqueue must be serialized, including the PCM copy.
        # A notified drain may not overtake an in-flight final packet.
        with self._arrived:
            if self._closed:
                return
            try:
                self.queue.put_nowait((kind, data.copy(), start))
                self.latest_end[kind] = max(self.latest_end[kind], start + len(data) / RATE)
                self._arrived.notify_all()
            except queue.Full:
                self.error = 'Audio disk queue overflowed. The recording could not retain all audio samples.'

    def _run(self):
        files, positions = {}, {}
        try:
            for kind in self.sources:
                files[kind] = (self.folder / f'{kind}.raw').open('wb')
                positions[kind] = 0
            while True:
                item = self.queue.get()
                if item is None:
                    break
                kind, data, start = item
                for lo, hi, dest in self.timeline.map_block(start, len(data), RATE):
                    # Float timestamp quantization must not insert/drop individual samples.
                    if abs(dest - positions[kind]) <= 1:
                        dest = positions[kind]
                    gap = dest - positions[kind]
                    while gap > 0:
                        count = min(gap, RATE)
                        files[kind].write(b'\0' * (count * 4))
                        positions[kind] += count
                        gap -= count
                    skip = max(0, positions[kind] - dest)
                    segment = data[lo + skip:hi]
                    if len(segment):
                        pcm = (np.clip(segment, -1, 1) * 32767).astype('<i2')
                        files[kind].write(pcm.tobytes())
                        positions[kind] += len(segment)
        except Exception as exc:
            self.error = f'Audio file writing failed: {exc}'
        finally:
            for handle in files.values():
                handle.close()

    def drain_until(self, captured_end, timeout=.45):
        import time
        deadline = time.monotonic() + timeout
        with self._arrived:
            while self.sources and any(self.latest_end[k] < captured_end for k in self.sources):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._arrived.wait(remaining)
            return [kind for kind in self.sources if captured_end-self.latest_end[kind]>.08]

    def close(self, duration):
        with self._arrived:
            if self._closed:
                return []
            self._closed = True
        # A failed writer must not leave the encoder blocked on a full queue.
        while self._thread.is_alive():
            try:
                self.queue.put(None, timeout=.1)
                break
            except queue.Full:
                continue
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            raise RuntimeError('Audio writer did not finish')
        if self.error:
            raise RuntimeError(self.error)
        count, paths = max(1, round(duration * RATE)), []
        for kind in self.sources:
            raw = self.folder / f'{kind}.raw'
            with raw.open('r+b') as handle:
                size = handle.seek(0, 2)
                target = count * 4
                if size < target:
                    handle.seek(target - 1)
                    handle.write(b'\0')
                handle.truncate(target)
            output = self.folder / f'{kind}.wav'
            with raw.open('rb') as handle, wave.open(str(output), 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(RATE)
                while chunk := handle.read(1024 * 1024):
                    wav.writeframesraw(chunk)
            raw.unlink()
            paths.append(output)
        return paths
