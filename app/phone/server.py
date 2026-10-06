"""Embedded local HTTPS signaling + WebRTC receiver. No external backend."""
import asyncio
import hmac
import logging
import secrets
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
from aiortc.mediastreams import MediaStreamError
from PySide6.QtCore import QThread, Signal
from app.phone.network import choose_ip, lan_addresses
from app.phone.certificates import certificate_files
from app.phone.audio import PhoneAudioDecoder
from app.utils.frames import bgr_image
from app.utils.paths import resource


class PhoneService:
    def __init__(self, frames, port=8765, auto_ip=True, manual_ip='', on_ready=None,
                 on_connected=None, on_error=None, cert_folder=None,
                 on_audio=None, on_audio_state=None, on_audio_level=None, on_audio_error=None):
        self.frames, self.port = frames, port
        self.auto_ip, self.manual_ip = auto_ip, manual_ip
        self.on_ready = on_ready or (lambda info: None)
        self.on_connected = on_connected or (lambda flag, text: None)
        self.on_error = on_error or (lambda text: None)
        self.cert_folder = cert_folder
        self.on_audio = on_audio or (lambda data, start: None)
        self.on_audio_state = on_audio_state or (lambda flag, text: None)
        self.on_audio_level = on_audio_level or (lambda level, clip: None)
        self.on_audio_error = on_audio_error or self.on_error
        self.last_audio = 0.
        self.audio_info = {}
        self._audio_meter_time = 0.
        self.token = secrets.token_urlsafe(24)
        self.loop = None
        self.quit_event = None
        self.peer = None
        self.tasks = set()
        self.last_frame = 0.
        self.info = None
        self._stop_requested = False
        self._offer_lock = None

    def stop(self):
        self._stop_requested = True
        if self.loop and self.quit_event:
            self.loop.call_soon_threadsafe(self.quit_event.set)

    def authenticated(self, request):
        return hmac.compare_digest(request.query.get('token', ''), self.token)

    async def home(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden(text='Invalid pairing link. Scan the QR code from your PC.')
        return web.Response(text=resource('app/phone/mobile.html').read_text(encoding='utf-8'), content_type='text/html', headers={'Cache-Control': 'no-store'})

    async def guide(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden(text='Open the setup link shown by Nexus Cam Studio on your PC.')
        text = resource('app/phone/instructions.html').read_text(encoding='utf-8')
        text = text.replace('__TOKEN__', self.token).replace('__SECURE_URL__', self.info['https_url'].replace('&', '&amp;'))
        return web.Response(text=text, content_type='text/html')

    async def certificate(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden(text='Invalid pairing token.')
        return web.Response(body=Path(self.info['certificate']).read_bytes(), content_type='application/x-x509-ca-cert',
                            headers={'Content-Disposition': 'attachment; filename="nexus-phone-root.crt"'})

    async def status(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden()
        now = time.monotonic()
        video, audio = now - self.last_frame < 5, now - self.last_audio < 2
        return web.json_response({'server': 'Nexus Cam Studio', 'connected': video or audio,
                                  'video_connected': video, 'audio_connected': audio,
                                  'audio_info': self.audio_info, 'transport': 'WebRTC'})

    async def disconnect(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden()
        await self._close_peer()
        return web.json_response({'stopped': True})

    async def _close_peer(self):
        peer, self.peer = self.peer, None
        if peer:
            await peer.close()
        self.last_frame = 0.
        self.last_audio = 0.
        self.audio_info = {}
        self.on_audio_state(False, 'Phone microphone disconnected')
        self.on_audio_level(0., False)
        self.frames.clear('phone_raw')
        self.on_connected(False, 'Phone disconnected')

    async def offer(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden(text='Invalid pairing token.')
        async with self._offer_lock:
            peer = None
            try:
                body = await request.json()
                if body.get('type') != 'offer' or not isinstance(body.get('sdp'), str):
                    raise ValueError('A valid WebRTC audio/video offer is required')
                await self._close_peer()
                self.audio_info = body.get('audioInfo', {}) if isinstance(body.get('audioInfo', {}), dict) else {}
                peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
                self.peer = peer
                @peer.on('track')
                def track_received(track):
                    if track.kind in ('video', 'audio'):
                        receiver = self.receive if track.kind == 'video' else self.receive_audio
                        task = asyncio.create_task(receiver(track, peer))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
                @peer.on('connectionstatechange')
                async def state_changed():
                    if self.peer is peer and peer.connectionState in ('failed', 'closed', 'disconnected'):
                        self.last_frame = 0.
                        self.last_audio = 0.
                        self.on_audio_state(False, 'Phone microphone connection lost')
                        self.on_audio_level(0., False)
                        self.frames.clear('phone_raw')
                        self.on_connected(False, f'Phone connection {peer.connectionState}; check same Wi-Fi and firewall.')
                await peer.setRemoteDescription(RTCSessionDescription(sdp=body['sdp'], type=body['type']))
                await peer.setLocalDescription(await peer.createAnswer())
                return web.json_response({'sdp': peer.localDescription.sdp, 'type': peer.localDescription.type})
            except Exception as exc:
                logging.exception('Phone offer failed')
                if peer and self.peer is peer:
                    await self._close_peer()
                self.on_error(f'Phone connection failed: {exc}')
                raise web.HTTPBadRequest(text=f'Could not negotiate phone audio/video connection: {exc}')

    async def receive(self, track, peer):
        # Keep only the newest decoded video frame while conversion is busy.
        # Audio/UDP processing must never wait for YUV/RGB/Qt raster work.
        latest, available = [None], asyncio.Event()
        async def render():
            first = True
            try:
                while self.peer is peer:
                    await available.wait()
                    frame = latest[0]
                    available.clear()
                    image = await asyncio.to_thread(lambda value=frame: bgr_image(value.to_ndarray(format='bgr24')))
                    if self.peer is not peer:
                        break
                    self.frames.put('phone_raw', image)
                    now = time.monotonic()
                    resumed = now - self.last_frame > 5
                    self.last_frame = now
                    if first or resumed:
                        self.on_connected(True, 'PHONE CONNECTED ✓')
                        first = False
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logging.exception('Phone video conversion failed')
                self.on_error(f'Phone video stopped: {exc}')
        renderer = asyncio.create_task(render())
        try:
            while self.peer is peer:
                frame = await track.recv()
                if self.peer is not peer:
                    break
                latest[0] = frame
                available.set()
        except (MediaStreamError, asyncio.CancelledError):
            pass
        except Exception as exc:
            logging.exception('Phone video failed')
            self.on_error(f'Phone video stopped: {exc}')
        finally:
            renderer.cancel()
            await asyncio.gather(renderer, return_exceptions=True)
            if self.peer is peer:
                self.frames.clear('phone_raw')
                self.last_frame = 0.
                self.on_connected(False, 'Phone camera stopped')

    async def audio_metadata(self, request):
        if not self.authenticated(request):
            raise web.HTTPForbidden()
        body = await request.json()
        self.audio_info = body if isinstance(body, dict) else {}
        if time.monotonic() - self.last_audio < 2:
            name = str(self.audio_info.get('label') or 'phone / Android-routed microphone')[:140]
            self.on_audio_state(True, 'Receiving phone mic · ' + name)
        return web.json_response({'updated': True})

    async def receive_audio(self, track, peer):
        decoder, first = PhoneAudioDecoder(), True
        try:
            while self.peer is peer:
                frame = await track.recv()
                if self.peer is not peer:
                    break
                now = time.monotonic()
                resumed = now - self.last_audio > 2
                for data, start, level, clipping, reset in decoder.convert(frame, now):
                    self.on_audio(data, start)  # Direct bounded writer path; no per-packet UI queue.
                    self.last_audio = now
                    if first or resumed:
                        name = str(self.audio_info.get('label') or 'phone / Android-routed microphone')[:140]
                        self.on_audio_state(True, 'Receiving phone mic · ' + name)
                        first = False
                    if now - self._audio_meter_time >= .08:
                        self.on_audio_level(level, clipping)
                        self._audio_meter_time = now
                    if reset:
                        self.on_audio_error('Phone audio clock restarted after a long gap. Check Wi-Fi and keep the phone awake.')
        except (MediaStreamError, asyncio.CancelledError):
            pass
        except Exception as exc:
            logging.exception('Phone microphone failed')
            self.on_audio_error(f'Phone microphone stopped: {exc}. Reconnect it and allow microphone permission on the phone.')
        finally:
            if self.peer is peer:
                self.last_audio = 0.
                self.on_audio_state(False, 'Phone microphone stopped; enable Send microphone on the phone')
                self.on_audio_level(0., False)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.quit_event = asyncio.Event()
        self._offer_lock = asyncio.Lock()
        ip = choose_ip(self.auto_ip, self.manual_ip)
        chain, key, root = certificate_files([ip, *lan_addresses()], self.cert_folder)
        params = urlencode({'token': self.token})
        self.info = dict(ip=ip, port=self.port, https_port=self.port + 1, token=self.token,
                         http_url=f'http://{ip}:{self.port}/?{params}',
                         https_url=f'https://{ip}:{self.port + 1}/?{params}', certificate=str(root))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(chain, key)
        secure = web.Application(client_max_size=256 * 1024)
        secure.add_routes([web.get('/', self.home), web.get('/status', self.status),
                           web.post('/offer', self.offer), web.post('/disconnect', self.disconnect),
                           web.post('/audio-info', self.audio_metadata),
                           web.get('/root-ca.crt', self.certificate)])
        plain = web.Application()
        plain.add_routes([web.get('/', self.guide), web.get('/root-ca.crt', self.certificate)])
        runners = []
        try:
            for app, port, tls in [(plain, self.port, None), (secure, self.port + 1, context)]:
                runner = web.AppRunner(app, access_log=None)
                runners.append(runner)
                await runner.setup()
                await web.TCPSite(runner, '0.0.0.0', port, ssl_context=tls).start()
            self.on_ready(self.info)
            if self._stop_requested:
                self.quit_event.set()
            await self.quit_event.wait()
        finally:
            await self._close_peer()
            for task in list(self.tasks):
                task.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            for runner in runners:
                await runner.cleanup()


class PhoneWorker(QThread):
    ready = Signal(object)
    connected = Signal(bool, str)
    failed = Signal(str)
    audio_state = Signal(bool, str)
    audio_level = Signal(float, bool)
    audio_error = Signal(str)

    def __init__(self, frames, settings, parent=None, audio_callback=None):
        super().__init__(parent)
        self.service = PhoneService(frames, settings.phone_port, settings.phone_auto_ip,
                                    settings.phone_ip, self.ready.emit, self.connected.emit, self.failed.emit,
                                    on_audio=audio_callback, on_audio_state=self.audio_state.emit,
                                    on_audio_level=self.audio_level.emit, on_audio_error=self.audio_error.emit)

    def stop(self):
        self.service.stop()

    def run(self):
        try:
            asyncio.run(self.service.run())
        except Exception as exc:
            logging.exception('Phone server failed')
            self.failed.emit(f'Phone server unavailable: {exc}. Check the LAN address and ports {self.service.port}–{self.service.port + 1}.')
