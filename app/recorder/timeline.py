"""One monotonic clock shared by the encoder, timer, and both audio tracks."""
import math
import threading
import time


class Timeline:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.segments = []
        self.active_start = None
        self.total = 0.
        self.started = False
        self.stopped = False

    def start(self):
        with self.lock:
            if self.started:
                raise RuntimeError('Timeline is already started')
            self.started = True
            self.active_start = self.clock()

    def pause(self):
        with self.lock:
            if self.active_start is not None:
                now = self.clock()
                self.segments.append((self.active_start, now, self.total))
                self.total += now - self.active_start
                self.active_start = None

    def resume(self):
        with self.lock:
            if self.started and not self.stopped and self.active_start is None:
                self.active_start = self.clock()

    def stop(self):
        with self.lock:
            self.pause()
            self.stopped = True

    @property
    def paused(self):
        with self.lock:
            return self.started and not self.stopped and self.active_start is None

    def elapsed(self):
        with self.lock:
            return self.total + (self.clock() - self.active_start if self.active_start is not None else 0.)

    def map_block(self, start, count, rate):
        """Clip a captured audio block against active intervals, excluding every pause.
        Returns (first sample, last sample exclusive, destination sample offset).
        """
        end = start + count / rate
        with self.lock:
            segments = list(self.segments)
            if self.active_start is not None:
                segments.append((self.active_start, float('inf'), self.total))
            result = []
            for begin, finish, offset in segments:
                a, b = max(start, begin), min(end, finish)
                if b <= a:
                    continue
                lo = 0 if a <= start else max(0, min(count, round((a - start) * rate)))
                hi = count if b >= end else max(lo, min(count, round((b - start) * rate)))
                dest = max(0, round((offset + a - begin) * rate))
                if hi > lo:
                    result.append((lo, hi, dest))
            return result
