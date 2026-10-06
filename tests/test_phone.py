import asyncio
import json
import socket
import ssl
from pathlib import Path
import av
import cv2
import numpy as np
import qrcode
from aiohttp import ClientSession, TCPConnector
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, VideoStreamTrack
from cryptography import x509
from app.phone.certificates import certificate_files
from app.phone.server import PhoneService
from app.utils.frames import FrameStore, image_bgr


def free_pair():
    for base in range(19700, 21000, 2):
        try:
            with socket.socket() as a, socket.socket() as b:
                a.bind(('0.0.0.0', base))
                b.bind(('0.0.0.0', base + 1))
                return base
        except OSError:
            pass
    raise RuntimeError('No test port pair available')


class TestVideoTrack(VideoStreamTrack):
    __test__ = False
    def __init__(self, color):
        super().__init__()
        self.color = color

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        array = np.full((180, 320, 3), self.color, np.uint8)
        frame = av.VideoFrame.from_ndarray(array, format='bgr24')
        frame.pts, frame.time_base = pts, time_base
        return frame


def test_local_certificate_has_ip_sans_and_unique_ca(tmp_path):
    _, _, ca = certificate_files(['192.168.12.34'], tmp_path / 'one')
    cert = x509.load_pem_x509_certificate((tmp_path / 'one' / 'server-chain.pem').read_bytes())
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert '192.168.12.34' in [str(a) for a in sans.get_values_for_type(x509.IPAddress)]
    assert x509.load_pem_x509_certificate(ca.read_bytes()).extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    _, _, other = certificate_files(['192.168.12.34'], tmp_path / 'two')
    assert ca.read_bytes() != other.read_bytes()


def test_real_https_webrtc_pair_reconnect_disconnect_and_qr(tmp_path):
    async def scenario():
        frames = FrameStore()
        ready, media = asyncio.Event(), asyncio.Event()
        service = PhoneService(frames, port=free_pair(), on_ready=lambda info: ready.set(),
                               on_connected=lambda flag, text: media.set() if flag else None,
                               cert_folder=tmp_path / 'cert')
        task = asyncio.create_task(service.run())
        peers = []
        try:
            await asyncio.wait_for(ready.wait(), 8)
            info = service.info
            assert 'localhost' not in info['https_url'] and '127.0.0.1' not in info['https_url']
            qr = np.asarray(qrcode.make(info['https_url']).convert('RGB'))
            decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(qr)
            assert decoded == info['https_url']
            tls = ssl.create_default_context(cafile=info['certificate'])
            secure = f"https://127.0.0.1:{info['https_port']}"
            plain = f"http://127.0.0.1:{info['port']}"
            token = '?token=' + info['token']
            async with ClientSession(connector=TCPConnector(ssl=tls)) as client:
                async with client.get(secure + '/status') as response:
                    assert response.status == 403
                async with client.get(plain + '/' + token) as response:
                    guide = await response.text()
                    assert info['https_url'] in guide and 'CA certificate' in guide
                async with client.get(secure + '/' + token) as response:
                    page = await response.text()
                    assert all(label in page for label in ('START CAMERA', 'SWITCH CAMERA', 'STOP CAMERA'))
                async with client.get(plain + '/root-ca.crt' + token) as response:
                    assert await response.read() == Path(info['certificate']).read_bytes()
                for color in [(20, 210, 40), (205, 35, 20)]:
                    media.clear()
                    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
                    peers.append(peer)
                    peer.addTrack(TestVideoTrack(color))  # Real transport, explicit synthetic camera fixture.
                    await peer.setLocalDescription(await peer.createOffer())
                    async with client.post(secure + '/offer' + token,
                                           json={'type': peer.localDescription.type, 'sdp': peer.localDescription.sdp}) as response:
                        assert response.status == 200, await response.text()
                        answer = await response.json()
                    await peer.setRemoteDescription(RTCSessionDescription(**answer))
                    await asyncio.wait_for(media.wait(), 8)
                    first_sequence = frames.get('phone_raw')[1]
                    await asyncio.sleep(.2)
                    image, sequence = frames.get('phone_raw', 2)
                    assert sequence > first_sequence and image.width() == 320
                    pixel = image_bgr(image)[90, 160]
                    assert np.max(np.abs(pixel.astype(int) - np.array(color))) < 12
                    async with client.get(secure + '/status' + token) as response:
                        assert (await response.json())['connected'] is True
                async with client.post(secure + '/disconnect' + token) as response:
                    assert response.status == 200
                assert frames.get('phone_raw')[0].isNull()
                async with client.get(secure + '/status' + token) as response:
                    assert (await response.json())['connected'] is False
        finally:
            for peer in peers:
                await peer.close()
            service.stop()
            await asyncio.wait_for(task, 10)
    asyncio.run(scenario())


def test_actual_mobile_page_start_switch_stop_with_explicit_browser_fixture(tmp_path):
    import pytest
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Optional Chromium test browser not installed')
    from tools.check_mobile_browser import check_browser
    result = asyncio.run(check_browser(tmp_path))
    assert result['result'] == 'PASS'
