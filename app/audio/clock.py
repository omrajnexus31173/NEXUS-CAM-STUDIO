"""Sample-continuous clocks. Packet/callback scheduling jitter must not edit PCM.
RTP PTS represents media time; arrival time is only the initial wall-clock anchor.
"""


class CaptureSampleClock:
    def __init__(self, rate=48000):
        self.rate = rate
        self.next_start = None

    def stamp(self, count, measured_start, discontinuity=False):
        expected = self.next_start
        if expected is None or discontinuity or abs(measured_start - expected) > .08:
            start = measured_start
        else:
            start = expected
        self.next_start = start + count / self.rate
        return start


class MediaSampleClock:
    def __init__(self, rate=48000):
        self.rate = rate
        self.anchor = None
        self.next_media = 0.
        self.last_end = None

    def stamp(self, count, media_time, arrival):
        duration = count / self.rate
        media = self.next_media if media_time is None else float(media_time)
        reset = False
        if self.anchor is None:
            self.anchor = arrival - duration - media
        start = self.anchor + media
        # A delayed/backlogged packet is NOT a sender restart. Re-anchoring it
        # discards real captured words and inserts silence when the CPU/Wi-Fi is busy.
        # Keep RTP media time for late arrivals; only a backward restart or impossible
        # future clock needs a new anchor. Recording finalization drains late PCM.
        if ((self.last_end is not None and start < self.last_end - .005)
                or start - arrival > .15):
            self.anchor = arrival - duration - media
            start = self.anchor + media
            reset = True
        self.next_media = media + duration
        self.last_end = start + duration
        return start, reset
