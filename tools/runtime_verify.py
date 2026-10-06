"""Optional acceptance runner for the *same* native app, including its frozen EXE.
It invokes real UI controls. It NEVER supplies a synthetic camera/audio/screen source.
A browser fixture can connect separately; that is recorded as transport, not hardware proof.
"""
import json
import ssl
import time
import urllib.request
from pathlib import Path
import av
import numpy as np
from PySide6.QtCore import QObject, QTimer, QPoint, Qt
from PySide6.QtTest import QTest
from app.ui.dialogs import PhoneDialog
from app.utils.diagnostics import DiagnosticWorker
from app.utils.frames import image_bgr


class RuntimeVerifier(QObject):
    def __init__(self, window, report_path, phone_wait=0., expected_audio_tone=0.):
        super().__init__(window)
        self.window = window
        self.path = Path(report_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.phone_wait = phone_wait
        self.expected_audio_tone = expected_audio_tone
        self.report = {'release': '1.1.0', 'environment': 'runtime verification; hardware must be verified separately',
                       'checks': {}, 'hardware': {'webcam': 'NOT TESTED', 'microphone': 'NOT TESTED',
                       'system_audio': 'NOT TESTED', 'android_same_wifi': 'NOT TESTED',
                       'android_usb_microphone': 'NOT TESTED'}, 'state': 'starting'}
        self.phase = 'live'
        self.phase_start = time.monotonic()
        self.record_worker = None
        self.first_frame = None
        self.phone_recorded = False
        self.diagnostic_worker = None
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.write()

    def write(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.report, indent=2), encoding='utf-8')
        tmp.replace(self.path)

    def mark(self, name, detail=True):
        self.report['checks'][name] = detail

    def transition(self, phase):
        self.phase, self.phase_start = phase, time.monotonic()

    def record_start(self):
        self.window._record_audit = True
        self.window.start_recording()
        if not self.window.recorder:
            raise RuntimeError('Real recording did not start: ' + self.window.notice_label.text())
        self.record_worker = self.window.recorder
        self.record_worker.saved.connect(self.capture_audit_frame)

    def capture_audit_frame(self, path, duration, warning):
        from PySide6.QtGui import QImage
        if self.record_worker.first_frame is not None:
            self.first_frame = QImage(self.record_worker.first_frame)

    def audit_recording(self, name):
        path = self.window.last_saved
        if not path or not Path(path).is_file():
            raise RuntimeError('No real exported recording exists')
        with av.open(path) as container:
            video = container.streams.video[0]
            decoded = next(container.decode(video)).to_ndarray(format='bgr24')
            expected = image_bgr(self.first_frame)
            error = float(np.mean(np.abs(decoded.astype(float) - expected.astype(float))))
            if error > 8:
                raise RuntimeError(f'Recorded first frame differs from composition: MAE {error}')
            self.mark(name, dict(path=path, bytes=Path(path).stat().st_size,
                duration_seconds=self.window._last_duration, codec=video.codec_context.name,
                dimensions=[video.width, video.height], fps=float(video.average_rate),
                preview_to_export_mean_absolute_pixel_error=round(error, 4)))
        self.record_worker.first_frame = None
        self.first_frame = None

    def audit_phone_audio(self):
        path = self.window.last_saved
        with av.open(path) as container:
            if len(container.streams.audio)!=1:
                raise RuntimeError('Phone recording has no single mixed audio stream')
            stream=container.streams.audio[0]
            rate=stream.codec_context.sample_rate
            resampler=av.AudioResampler(format='fltp',layout='stereo',rate=48000)
            parts=[f.to_ndarray() for decoded in container.decode(stream) for f in resampler.resample(decoded)]
        values=np.concatenate(parts,axis=1)[0]
        rms=float(np.sqrt(np.mean(values*values)))
        peak=float(np.max(np.abs(values)))
        frequency=float(np.fft.rfftfreq(len(values),1/48000)[np.argmax(np.abs(np.fft.rfft(values)))])
        core=values[4800:-4800]
        windows=np.array([np.sqrt(np.mean(v*v)) for v in np.array_split(core,max(1,len(core)//480))])
        silent_run=longest=0
        for value in windows:
            silent_run=silent_run+1 if value<.001 else 0
            longest=max(longest,silent_run)
        gap=longest*.01
        if self.expected_audio_tone:
            if abs(frequency-self.expected_audio_tone)>3 or rms<.07 or peak>=.98 or gap>.05:
                raise RuntimeError(f'Phone audio fixture failed decode quality: tone={frequency}, RMS={rms}, peak={peak}, gap={gap}')
        self.mark('phone_audio_burned_into_export',dict(codec=stream.codec_context.name,
            sample_rate=rate,channels=2,decoded_samples=len(values),rms=round(rms,6),peak=round(peak,6),
            dominant_frequency_hz=round(frequency,3),maximum_internal_silent_gap_seconds=gap,
            expected_external_fixture_frequency_hz=self.expected_audio_tone or None,
            hardware_note='External sender identity/physical USB routing NOT verified'))

    def tick(self):
        try:
            window, elapsed = self.window, time.monotonic() - self.phase_start
            if elapsed > 50 and self.phase not in ('phone',):
                raise RuntimeError(f'Acceptance step timed out: {self.phase}')
            if self.phase == 'live':
                if not (window._has_source() and window._encoding_available and window.record_button.isEnabled()):
                    return
                self.mark('native_application_launch', window.isVisible())
                self.mark('real_screen_capture', not window.frames.get('screen', 2)[0].isNull())
                window.grab().save(str(self.path.with_name('verified-native-ui.png')))
                window.screenshot()
                if not window.last_screenshot or not Path(window.last_screenshot).exists():
                    raise RuntimeError('Screenshot button did not create a PNG')
                self.mark('composed_screenshot', window.last_screenshot)
                self.record_start()
                self.transition('record')
            elif self.phase == 'record':
                if window._record_state != 'recording' or not self.record_worker.timeline.started:
                    return
                if self.record_worker.timeline.elapsed() < 1.25:
                    return
                self.mark('real_recording_timer', window.timer_label.text())
                window.pause_button.click()
                self.pause_duration = self.record_worker.timeline.elapsed()
                if not self.record_worker.timeline.paused:
                    raise RuntimeError('Pause control did not pause the recording clock')
                self.transition('pause')
            elif self.phase == 'pause':
                if elapsed < .35:
                    return
                if abs(self.record_worker.timeline.elapsed() - self.pause_duration) > .005:
                    raise RuntimeError('Recording clock advanced while paused')
                self.mark('pause_excludes_time', True)
                window.pause_button.click()
                if self.record_worker.timeline.paused:
                    raise RuntimeError('Resume control did not resume the clock')
                self.transition('resume')
            elif self.phase == 'resume':
                if elapsed < .7:
                    return
                window.stop_button.click()
                self.transition('save')
            elif self.phase == 'save':
                if window.recorder:
                    return
                self.audit_recording('real_mp4_export')
                self.mark('saved_history', bool(window.history.items))
                window.ensure_phone_server()
                self.transition('phone')
            elif self.phase == 'phone':
                if not window.phone_info:
                    if elapsed > 20:
                        raise RuntimeError('Local HTTPS phone server did not start')
                    return
                if 'phone_server_https' not in self.report['checks']:
                    info = window.phone_info
                    context = ssl.create_default_context(cafile=info['certificate'])
                    url = f"https://127.0.0.1:{info['https_port']}/status?token={info['token']}"
                    with urllib.request.urlopen(url, context=context, timeout=4) as response:
                        status = json.loads(response.read())
                    self.mark('phone_server_https', status['server'])
                    dialog = PhoneDialog(window)
                    dialog.set_info(info)
                    if not dialog.qr.pixmap() or dialog.qr.pixmap().isNull():
                        raise RuntimeError('QR generation failed')
                    dialog.qr.pixmap().save(str(self.path.with_name('verified-phone-qr.png')))
                    self.mark('phone_qr_generated', True)
                    self.report['state'] = 'awaiting_phone'
                    self.report['phone_info'] = info  # Temporary token; server is shut down at exit.
                    self.write()
                    window.connect_phone()
                if (self.phone_wait > 0 and window.phone_connected and window.preview.live_overlay()
                        and window.audio_ready.get('phone') and time.monotonic()-window.last_audio_block['phone']<1):
                    self.mark('phone_real_webrtc_frames_in_preview', True)
                    if not window.phone_mic_checkbox.isChecked() or window.mic_checkbox.isChecked():
                        raise RuntimeError('Connect Phone did not select phone mic / disable PC mic')
                    self.mark('phone_microphone_real_pcm_and_meter', dict(
                        recent_real_pcm=True, rms_meter_value=window.phone_mic_meter.value(),
                        phone_mic_selected=window.phone_mic_checkbox.isChecked(),
                        pc_mic_off=not window.mic_checkbox.isChecked()))
                    if self.expected_audio_tone and window.phone_mic_meter.value()<25:
                        raise RuntimeError('Known tone fixture does not reach the real desktop meter')
                    self.mark('phone_input_note', 'Received external WebRTC audio/video; this does NOT identify or prove Android/USB hardware.')
                    diagnostic = DiagnosticWorker(window.frames, window.devices, window.audio_ready, window.phone_info)
                    result = diagnostic.phone_microphone()
                    if result[0] != 'PASS':
                        raise RuntimeError('Live phone audio diagnostic failed: ' + result[1])
                    self.mark('phone_microphone_diagnostic_while_receiving', result)
                    initial = window.state.get()
                    point = window.preview.camera_rect().center().toPoint()
                    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=point)
                    QTest.mouseMove(window.preview, point + QPoint(-45, -25), delay=35)
                    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=point + QPoint(-45, -25))
                    moved = window.state.get()
                    if moved.x == initial.x:
                        raise RuntimeError('Camera overlay did not move')
                    corner = window.preview.camera_rect().bottomRight().toPoint()
                    QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=corner)
                    QTest.mouseMove(window.preview, corner + QPoint(25, 25), delay=35)
                    QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=corner + QPoint(25, 25))
                    if window.state.get().w <= moved.w:
                        raise RuntimeError('Camera overlay did not resize')
                    self.mark('live_overlay_move_resize', True)
                    window.shape_combo.setCurrentText('Rectangle')
                    self.transition('overlay_record_start')
                elif elapsed >= self.phone_wait + 2:
                    self.start_diagnostics()
            elif self.phase == 'overlay_record_start':
                if elapsed < .3:
                    return
                window.screenshot()
                self.record_start()
                self.transition('overlay_record')
            elif self.phase == 'overlay_record':
                if self.record_worker.timeline.elapsed() < 1.25:
                    return
                window.pause_button.click()
                self.pause_duration = self.record_worker.timeline.elapsed()
                self.transition('overlay_pause')
            elif self.phase == 'overlay_pause':
                if elapsed < .35:
                    return
                if abs(self.record_worker.timeline.elapsed()-self.pause_duration)>.005:
                    raise RuntimeError('Phone recording clock advanced during pause')
                window.pause_button.click()
                self.mark('phone_audio_video_shared_pause_resume', True)
                self.transition('overlay_resume')
            elif self.phase == 'overlay_resume':
                if elapsed < .8:
                    return
                window.grab().save(str(self.path.with_name('verified-phone-overlay-ui.png')))
                window.stop_recording()
                self.transition('overlay_save')
            elif self.phase == 'overlay_save':
                if window.recorder:
                    return
                self.audit_recording('phone_overlay_burned_into_export')
                self.audit_phone_audio()
                self.phone_recorded = True
                window.shape_combo.setCurrentText('Circle')
                self.report['state'] = 'phone_overlay_recorded'
                self.write()
                self.transition('browser_hold')
            elif self.phase == 'browser_hold':
                if elapsed < 12:
                    return
                self.start_diagnostics()
            elif self.phase == 'diagnostics':
                return  # Worker completion writes the final report and closes cleanly.
        except Exception as exc:
            self.report['state'] = 'FAILED'
            self.report['error'] = str(exc)
            self.write()
            self.timer.stop()
            if self.window.recorder:
                self.window.recorder.stop()
                self.window.recorder.finished.connect(self.window.close)
            else:
                self.window.close()

    def start_diagnostics(self):
        self.transition('diagnostics')
        self.diagnostic_worker = DiagnosticWorker(self.window.frames, self.window.devices,
                                                  self.window.audio_ready, self.window.phone_info)
        self.window._watch(self.diagnostic_worker)
        self.diagnostic_worker.complete.connect(self.diagnostics_done)
        self.diagnostic_worker.start()

    def diagnostics_done(self, results):
        self.report['diagnostics'] = results
        software = [r for r in results if r[0] in ('Application', 'Screen Capture', 'FFmpeg', 'Phone Server', 'Recording')]
        self.report['state'] = 'PASS_SOFTWARE_CHECKS' if all(r[1] == 'PASS' for r in software) else 'FAILED'
        self.report['phone_info'] = {'ip': self.window.phone_info['ip'],
            'http_port': self.window.phone_info['port'], 'https_port': self.window.phone_info['https_port']}
        self.write()
        self.timer.stop()
        QTimer.singleShot(0, self.window.close)
