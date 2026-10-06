import logging
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from app.audio.session import AudioSession
from app.recorder.ffmpeg import CREATE_FLAGS, choose_encoding, video_command, mux
from app.recorder.timeline import Timeline
from app.utils.paths import data_dir, unique_path, writable_folder


class RecorderWorker(QThread):
    status = Signal(str)
    saved = Signal(str, float, str)
    failed = Signal(str)

    def __init__(self, frames, settings, audio_sources=(), parent=None, audit=False):
        super().__init__(parent)
        self.frames, self.settings = frames, settings
        self.sources = tuple(audio_sources)
        self.audit = audit
        self.timeline = Timeline()
        self.audio = None
        self._stop = threading.Event()
        self.frame_count = 0
        self.first_frame = None  # One retained frame permits an exact export audit.
        self.folder = None
        self.output = None

    def submit_audio(self, kind, data, start):
        session = self.audio
        if session:
            session.submit(kind, data, start)

    def pause(self):
        self.timeline.pause()
        self.status.emit('paused')

    def resume(self):
        self.timeline.resume()
        self.status.emit('recording')

    def stop(self):
        self.timeline.stop()
        self._stop.set()

    def run(self):
        process, audio_closed = None, False
        try:
            self.status.emit('starting')
            settings = self.settings
            width, height = settings.dimensions
            encoding = choose_encoding(settings.format)
            output_folder = writable_folder(settings.output_folder)
            self.output = unique_path(output_folder, 'NexusCam_', encoding.format)
            recover = data_dir() / 'recovery'
            recover.mkdir(exist_ok=True)
            self.folder = Path(tempfile.mkdtemp(prefix='recording-', dir=recover))
            video = self.folder / f'video.{encoding.format}'
            partial = self.output.with_name(self.output.stem + '.partial.' + encoding.format)
            self.audio = AudioSession(self.timeline, self.folder, self.sources)
            with (self.folder / 'ffmpeg.log').open('wb') as log:
                process = subprocess.Popen(video_command(encoding, width, height, settings.fps, settings.bitrate, video),
                                           stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                           bufsize=1024 * 1024, creationflags=CREATE_FLAGS)
                if not self._stop.is_set():
                    self.timeline.start()
                    self.status.emit('recording')
                while True:
                    elapsed = self.timeline.elapsed()
                    desired = max(1, math.ceil(elapsed * settings.fps))
                    if self._stop.is_set() and self.frame_count >= desired:
                        break
                    if self.frame_count >= desired:
                        self._stop.wait(.003)
                        continue
                    image, _ = self.frames.get('composed', 2)
                    if image.isNull():
                        raise RuntimeError('Live composition stopped; no frame is available for recording')
                    if image.width() != width or image.height() != height:
                        raise RuntimeError('Recording resolution changed unexpectedly')
                    image = image.convertToFormat(QImage.Format.Format_RGB32)
                    if self.audit and self.frame_count == 0:
                        self.first_frame = QImage(image)
                    view = image.constBits()
                    remaining = memoryview(view)
                    while remaining:
                        written = process.stdin.write(remaining)
                        if not written:
                            raise RuntimeError('FFmpeg closed its video pipe')
                        remaining = remaining[written:]
                    self.frame_count += 1
                    if process.poll() is not None:
                        raise RuntimeError('FFmpeg stopped unexpectedly')
                self.status.emit('saving')
                process.stdin.close()
                returncode = process.wait(timeout=180)
                if returncode:
                    raise RuntimeError((self.folder / 'ffmpeg.log').read_text(errors='replace')[-4000:])
            self.timeline.stop()
            duration = self.frame_count / settings.fps
            # Retain late phone packets captured BEFORE Stop, not post-Stop speech.
            # Busy video/UDP can build a backlog; never re-anchor/discard captured words.
            warning = encoding.warning
            if self.timeline.segments and self.sources:
                captured_end = self.timeline.segments[-1][1]
                lag = max(0., captured_end-self.audio.latest_end.get('phone', captured_end))
                timeout = min(8., max(1., lag+1.)) if 'phone' in self.sources else .45
                missing = self.audio.drain_until(captured_end, timeout=timeout)
                if missing:
                    warning = (warning+' ' if warning else '') + 'Some audio did not arrive before finalization (' + ', '.join(missing) + '); inspect the end of the clip for silence.'
            tracks = self.audio.close(duration)
            audio_closed = True
            mux(encoding, video, tracks, partial)
            if not partial.exists() or partial.stat().st_size < 500:
                raise RuntimeError('FFmpeg did not produce a valid recording')
            os.replace(partial, self.output)
            self.saved.emit(str(self.output), duration, warning)
            shutil.rmtree(self.folder, ignore_errors=True)
        except Exception as exc:
            logging.exception('Recording failed')
            self.timeline.stop()
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            if self.audio and not audio_closed:
                try:
                    self.audio.close(max(.05, self.frame_count / self.settings.fps))
                except Exception:
                    logging.exception('Failed to close recovery audio')
            recovery = f' Recoverable media/logs are in {self.folder}.' if self.folder else ''
            self.failed.emit(f'Recording could not be saved: {exc}.{recovery}')
        finally:
            if process and process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except Exception:
                    pass
