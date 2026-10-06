"""All audio inputs here are explicitly synthetic test fixtures, NOT USB hardware proof."""
import asyncio
import math
import time
import wave
from fractions import Fraction
from pathlib import Path
import av
import pytest
import numpy as np
from aiohttp import ClientSession, TCPConnector
from aiortc import AudioStreamTrack, RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage, QColor
from app.audio.clock import CaptureSampleClock, MediaSampleClock
from app.audio.session import AudioSession
from app.phone.audio import PhoneAudioDecoder
from app.phone.server import PhoneService
from app.recorder.timeline import Timeline
from app.recorder.worker import RecorderWorker
from app.settings.store import Settings, SettingsStore
from app.utils.frames import FrameStore
from app.ui.main_window import MainWindow
from tests.test_phone import free_pair


def sine(count, offset=0, freq=440, amplitude=.25):
    return (amplitude * np.sin(2 * np.pi * freq * (np.arange(count) + offset) / 48000)).astype(np.float32)


def test_media_clock_uses_pts_not_wifi_arrival_jitter():
    clock = MediaSampleClock()
    for i in range(100):
        arrival = 10 + (i + 1) * .02 + (0 if i == 0 else (.018 if i % 3 else -.012))
        start, reset = clock.stamp(960, i * .02, arrival)
        assert abs(start - (10 + i * .02)) < 1e-8
        assert not reset


def test_capture_clock_removes_callback_scheduling_jitter():
    clock = CaptureSampleClock()
    for i in range(100):
        measured = 20 + i * .02 + (0 if i == 0 else (.003 if i % 2 else -.002))
        assert abs(clock.stamp(960, measured) - (20 + i * .02)) < 1e-8
    assert clock.stamp(960, 24., discontinuity=True) == 24.


def test_active_timeline_does_not_cut_early_audio_frames():
    now = [10.]
    timeline = Timeline(lambda: now[0])
    timeline.start()
    now[0] = 10.021
    assert timeline.map_block(10.020, 960, 48000) == [(0, 960, 960)]


def test_phone_decoder_48k_stereo_and_pts_continuity():
    decoder = PhoneAudioDecoder()
    for i in range(15):
        pcm = (sine(960, i * 960) * 32767).astype('<i2')[None, :]
        frame = av.AudioFrame.from_ndarray(pcm, format='s16', layout='mono')
        frame.sample_rate, frame.pts, frame.time_base = 48000, i * 960, Fraction(1, 48000)
        blocks = decoder.convert(frame, 10 + (i + 1) * .02 + (0 if i == 0 else .006 * (i % 3)))
        assert len(blocks) == 1
        data, start, level, clipping, reset = blocks[0]
        assert data.shape == (960, 2) and data.dtype == np.float32
        assert np.array_equal(data[:, 0], data[:, 1])
        assert abs(start - (10 + i * .02)) < 1e-8
        assert level > .5 and not clipping and not reset


def test_recorded_pcm_has_no_jitter_induced_gaps_or_missing_samples(tmp_path):
    now = [10.]
    timeline = Timeline(lambda: now[0])
    timeline.start()
    clock = MediaSampleClock()
    session = AudioSession(timeline, tmp_path, ('phone',))
    all_data = []
    for i in range(100):
        data = np.repeat(sine(960, i * 960)[:, None], 2, axis=1)
        start, _ = clock.stamp(960, i * .02, 10 + (i + 1) * .02 + (0 if i == 0 else .008 * (i % 4 - 2)))
        now[0] = 10 + (i + 1) * .02
        session.submit('phone', data, start)
        all_data.append(data)
    timeline.stop()
    paths = session.close(2.)
    with wave.open(str(paths[0]), 'rb') as wav:
        actual = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').reshape(-1, 2)
    expected = (np.concatenate(all_data) * 32767).astype('<i2')
    assert actual.shape == expected.shape
    assert np.array_equal(actual, expected)  # No per-packet clicks/cuts/zero padding.


def test_audio_captured_before_stop_is_not_dropped_if_delivered_late(tmp_path):
    now = [30.]
    timeline = Timeline(lambda: now[0]); timeline.start()
    now[0] = 30.02; timeline.stop()
    session = AudioSession(timeline, tmp_path, ('phone',))
    session.submit('phone', np.full((960, 2), .3, np.float32), 30.)
    path = session.close(.02)[0]
    with wave.open(str(path), 'rb') as wav:
        pcm = np.frombuffer(wav.readframes(960), '<i2')
    assert np.mean(pcm) > 9000


class ExplicitToneTrack(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        self.i = 0
        self.started_at = None
    async def recv(self):
        if self.started_at is None:
            self.started_at = time.monotonic()
        else:
            await asyncio.sleep(max(0., self.started_at + self.i * .02 - time.monotonic()))
        pcm = (sine(960, self.i * 960) * 32767).astype('<i2')[None, :]
        frame = av.AudioFrame.from_ndarray(pcm, format='s16', layout='mono')
        frame.sample_rate, frame.pts, frame.time_base = 48000, self.i * 960, Fraction(1, 48000)
        self.i += 1
        return frame


def test_real_phone_audio_webrtc_to_actual_mp4_with_pause_resume(tmp_path):
    async def scenario():
        frames = FrameStore()
        image = QImage(854, 480, QImage.Format.Format_RGB32); image.fill(QColor('#244a69'))
        frames.put('composed', image)  # Explicit video fixture, not a desktop hardware claim.
        settings = Settings(output_folder=str(tmp_path), resolution='854x480').normalize()
        recorder = RecorderWorker(frames, settings, ('phone',))
        ready, audio_live = asyncio.Event(), asyncio.Event()
        blocks, failures, saved = [], [], []
        def audio(data, start):
            blocks.append((len(data), start, float(np.max(np.abs(data)))))
            recorder.submit_audio('phone', data, start)
        service = PhoneService(frames, free_pair(), cert_folder=tmp_path/'cert', on_ready=lambda i: ready.set(),
            on_audio=audio, on_audio_state=lambda flag, text: audio_live.set() if flag else None)
        task = asyncio.create_task(service.run())
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        recorder.failed.connect(failures.append)
        recorder.saved.connect(lambda path, duration, warning: saved.append((path, duration)))
        try:
            await asyncio.wait_for(ready.wait(), 8)
            import ssl
            context = ssl.create_default_context(cafile=service.info['certificate'])
            url = f"https://127.0.0.1:{service.port+1}"
            token = '?token=' + service.token
            peer.addTrack(ExplicitToneTrack())
            await peer.setLocalDescription(await peer.createOffer())
            async with ClientSession(connector=TCPConnector(ssl=context)) as client:
                async with client.post(url+'/offer'+token, json={'type':'offer','sdp':peer.localDescription.sdp,
                    'audioInfo':{'label':'EXPLICIT SYNTHETIC TONE FIXTURE','sampleRate':48000}}) as r:
                    assert r.status == 200
                    answer = await r.json()
                await peer.setRemoteDescription(RTCSessionDescription(**answer))
                await asyncio.wait_for(audio_live.wait(), 8)
                async with client.get(url+'/status'+token) as r:
                    status = await r.json()
                    assert status['audio_connected'] and not status['video_connected']
                recorder.start()
                async def wait_for(predicate, seconds=10):
                    deadline=time.monotonic()+seconds
                    while not predicate():
                        QCoreApplication.processEvents()
                        if time.monotonic()>deadline:
                            raise TimeoutError('Audio recording pipeline timed out: '+str(failures))
                        await asyncio.sleep(.005)
                await wait_for(lambda: recorder.timeline.started or failures)
                assert not failures
                await asyncio.sleep(.45)
                recorder.pause(); before=recorder.timeline.elapsed()
                await asyncio.sleep(.25)
                assert abs(recorder.timeline.elapsed()-before)<.001
                recorder.resume()
                await asyncio.sleep(.5)
                recorder.stop()
                await wait_for(lambda: not recorder.isRunning(), 20)
                QCoreApplication.processEvents()
                assert saved and not failures, failures
                path,duration=saved[0]
                with av.open(path) as c:
                    assert len(c.streams.audio)==1 and c.streams.audio[0].codec_context.name=='aac'
                    audio_frames=[f.to_ndarray() for f in c.decode(audio=0)]
                values=np.concatenate(audio_frames,axis=1)[0]
                assert len(blocks)>30 and len(values)>40000
                assert np.sqrt(np.mean(values*values))>.07
                # Tone survives two real lossy codecs without clipping/wrong-rate artifacts.
                spectrum=np.abs(np.fft.rfft(values))
                frequency=np.fft.rfftfreq(len(values),1/48000)[int(np.argmax(spectrum))]
                assert abs(frequency-440)<3
                assert np.max(np.abs(values))<.8
                assert .85<duration<1.2
        finally:
            recorder.stop()
            if recorder.isRunning():
                recorder.wait(20000)
            await peer.close()
            service.stop();await asyncio.wait_for(task,10)
    asyncio.run(scenario())


@pytest.mark.desktop
def test_phone_mic_controls_and_legacy_settings_migration(qtbot, tmp_path):
    store=SettingsStore();store.path.parent.mkdir(parents=True,exist_ok=True)
    store.path.write_text('{"welcomed":true,"mic_enabled":false}')
    settings=store.load()
    assert not settings.phone_mic_enabled and settings.phone_mic_gain==100
    window=MainWindow(skip_welcome=True,auto_capture=True);qtbot.addWidget(window);window.show()
    try:
        qtbot.waitUntil(lambda: bool(window.devices) and window._has_source() and window._encoding_available,timeout=12000)
        window.connect_phone()
        qtbot.waitUntil(lambda: bool(window.phone_info),timeout=8000)
        assert window.phone_dialog.isVisible()
        assert window.phone_mic_checkbox.isChecked() and not window.mic_checkbox.isChecked()
        window.phone_mic_slider.setValue(65)
        assert window.settings.phone_mic_gain==65
        window._save_settings()
        assert store.load().phone_mic_enabled and store.load().phone_mic_gain==65
        # Explicit PCM fixture through the real desktop gain callback/writer.
        folder=tmp_path/'gain-check';folder.mkdir()
        recorder=RecorderWorker(window.frames,window.settings,('phone',))
        recorder.timeline=Timeline(lambda:10.);recorder.timeline.start()
        recorder.audio=AudioSession(recorder.timeline,folder,('phone',))
        window.recorder=recorder
        window._submit_phone_audio(np.full((960,2),.5,np.float32),10.)
        window.recorder=None
        gain_path=recorder.audio.close(.02)[0]
        with wave.open(str(gain_path),'rb') as wav:
            assert np.all(np.frombuffer(wav.readframes(960),'<i2')==int(.5*.65*32767))
        # A clipping signal is displayed before attenuation; never claims repair.
        for i in range(5):window._phone_audio_level(1.,True,window.phone_worker)
        assert window.phone_mic_meter.value()==100
        assert 'input is clipping' in window.notice_label.text()
        window.start_recording()
        assert window.recorder is None  # No invented phone audio/source.
        assert 'Phone microphone is not delivering samples' in window.notice_label.text()
    finally:
        window.close();qtbot.waitUntil(lambda: window._can_close,timeout=8000)
        assert not window.phone_dialog.isVisible()


def test_phone_clock_retains_media_timing_for_long_delayed_packets():
    clock=MediaSampleClock()
    start,reset=clock.stamp(960,0.,10.02)
    assert start==10. and not reset
    start,reset=clock.stamp(960,.02,12.02)
    assert abs(start-10.02)<1e-8 and not reset
    for i in range(2,120):
        start,reset=clock.stamp(960,i*.02,max(10+(i+1)*.02,12.02 + (i-2)*.001))
        assert abs(start-(10+i*.02))<1e-8 and not reset
    start,reset=clock.stamp(960,0.,15.)
    assert abs(start-14.98)<1e-8 and reset  # A real timestamp restart, not mere backlog.


def test_real_phone_decoder_clipping_and_invalid_pcm():
    import pytest
    decoder=PhoneAudioDecoder()
    values=np.vstack([sine(960,amplitude=1.),sine(960,amplitude=1.)])
    frame=av.AudioFrame.from_ndarray(values,format='fltp',layout='stereo')
    frame.sample_rate,frame.pts,frame.time_base=48000,0,Fraction(1,48000)
    assert decoder.convert(frame,10.)[0][3] is True
    values[:]=np.nan
    frame=av.AudioFrame.from_ndarray(values,format='fltp',layout='stereo')
    frame.sample_rate,frame.pts,frame.time_base=48000,960,Fraction(1,48000)
    with pytest.raises(RuntimeError,match='invalid audio samples'):
        decoder.convert(frame,10.02)


def test_close_cannot_overtake_inflight_pcm_copy(tmp_path):
    import threading
    now=[10.]
    timeline=Timeline(lambda:now[0]);timeline.start()
    entered,release,done=threading.Event(),threading.Event(),threading.Event()
    session=AudioSession(timeline,tmp_path,('phone',))
    class SlowExplicitFixture:
        def __len__(self): return 960
        def copy(self):
            entered.set();assert release.wait(3)
            return np.full((960,2),.2,np.float32)
    producer=threading.Thread(target=lambda:session.submit('phone',SlowExplicitFixture(),10.))
    producer.start();assert entered.wait(2)
    now[0]=10.02;timeline.stop()
    paths=[]
    def close():
        paths.extend(session.close(.02));done.set()
    closer=threading.Thread(target=close);closer.start()
    assert not done.wait(.05)
    release.set();producer.join(2);closer.join(2)
    assert done.is_set()
    with wave.open(str(paths[0]),'rb') as wav:
        assert np.mean(np.frombuffer(wav.readframes(960),'<i2'))>6000


def test_slow_video_conversion_does_not_block_actual_opus_audio(monkeypatch,tmp_path):
    """Explicit slow-conversion fixture; real peer audio must keep flowing independently."""
    from tests.test_phone import TestVideoTrack
    from app.phone import server
    original=server.bgr_image
    def slow(frame):
        time.sleep(.15)
        return original(frame)
    monkeypatch.setattr(server,'bgr_image',slow)
    async def scenario():
        frames=FrameStore();ready,heard=asyncio.Event(),asyncio.Event();blocks=[]
        def pcm(data,start):blocks.append((len(data),start));heard.set()
        service=PhoneService(frames,free_pair(),cert_folder=tmp_path/'cert',on_ready=lambda i:ready.set(),on_audio=pcm)
        task=asyncio.create_task(service.run())
        peer=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        try:
            await asyncio.wait_for(ready.wait(),8)
            import ssl
            context=ssl.create_default_context(cafile=service.info['certificate'])
            peer.addTrack(ExplicitToneTrack());peer.addTrack(TestVideoTrack((30,150,50)))
            await peer.setLocalDescription(await peer.createOffer())
            async with ClientSession(connector=TCPConnector(ssl=context)) as client:
                url=f'https://127.0.0.1:{service.port+1}/offer?token={service.token}'
                async with client.post(url,json={'type':'offer','sdp':peer.localDescription.sdp}) as response:
                    assert response.status==200
                    answer=await response.json()
                await peer.setRemoteDescription(RTCSessionDescription(**answer))
                await asyncio.wait_for(heard.wait(),8)
                count=len(blocks);await asyncio.sleep(.85)
                assert len(blocks)-count>=32  # Old synchronous video loop starved audio.
                assert not frames.get('phone_raw',2)[0].isNull()
                for (n,old),(m,new) in zip(blocks[:-1],blocks[1:]):
                    assert abs(new-old-n/48000)<.0001
        finally:
            await peer.close();service.stop();await asyncio.wait_for(task,10)
    asyncio.run(scenario())
