"""Optional real-browser integration. Fixtures are NOT Android/USB hardware proof.
Chromium explicitly uses a synthetic camera and a labelled 440 Hz WAV microphone.
Test-only certificate bypass flags never appear in the application or phone page.
"""
import argparse
import asyncio
from collections import deque
import json
import socket
import tempfile
import time
import wave
from pathlib import Path
import numpy as np
from playwright.async_api import async_playwright
from app.phone.server import PhoneService
from app.utils.frames import FrameStore


def test_port():
    for base in range(21100, 22000, 2):
        try:
            with socket.socket() as a, socket.socket() as b:
                a.bind(('0.0.0.0', base))
                b.bind(('0.0.0.0', base + 1))
                return base
        except OSError:
            continue
    raise RuntimeError('No free test ports')


async def report_state(path, states, timeout=50):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            report = json.loads(Path(path).read_text(encoding='utf-8'))
            if report.get('state') == 'FAILED':
                raise RuntimeError(report.get('error', 'Runtime verification failed'))
            if report.get('state') in states:
                return report
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        await asyncio.sleep(.1)
    raise TimeoutError('Runtime report did not reach ' + ', '.join(states))


async def eventually(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError('No live receiver PCM/video within timeout')
        await asyncio.sleep(.02)


def tone_fixture(path):
    data = (.25 * 32767 * np.sin(2 * np.pi * 440 * np.arange(48000 * 5) / 48000)).astype('<i2')
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(48000)
        wav.writeframes(data.tobytes())


def check_pcm(blocks):
    pcm = np.concatenate([v for v, start in blocks])[:, 0]
    rms = float(np.sqrt(np.mean(pcm * pcm)))
    peak = float(np.max(np.abs(pcm)))
    frequency = float(np.fft.rfftfreq(len(pcm), 1/48000)[np.argmax(np.abs(np.fft.rfft(pcm)))])
    assert rms > .07 and peak < .9, (rms, peak)
    assert abs(frequency - 440) < 3, frequency
    # Arrival jitter changes neither the RTP-based sample clock nor retained PCM length.
    maximum_gap = max(abs(start - (old_start + len(old)/48000))
        for (old, old_start), (new, start) in zip(list(blocks)[:-1], list(blocks)[1:]))
    assert maximum_gap < .0001, maximum_gap
    return dict(samples=len(pcm), rms=round(rms, 6), peak=round(peak, 6),
                dominant_frequency_hz=round(frequency, 3), maximum_sample_clock_gap_seconds=maximum_gap)


async def check_browser(output, external_report=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    task, service, temp, frames = None, None, None, None
    blocks, errors = deque(maxlen=120), []
    fixture_temp = tempfile.TemporaryDirectory()
    fixture = Path(fixture_temp.name) / 'EXPLICIT_SYNTHETIC_440Hz_MIC.wav'
    tone_fixture(fixture)
    if external_report:
        ready = await report_state(external_report, {'awaiting_phone'})
        info = ready['phone_info']
    else:
        temp = tempfile.TemporaryDirectory()
        frames = FrameStore()
        event = asyncio.Event()
        service = PhoneService(frames, test_port(), on_ready=lambda info: event.set(),
            cert_folder=Path(temp.name)/'cert', on_audio=lambda data, start: blocks.append((data.copy(), start)),
            on_audio_error=errors.append)
        task = asyncio.create_task(service.run())
        await asyncio.wait_for(event.wait(), 8)
        info = service.info
    result = {'release': '1.1.0',
              'environment': 'Chromium explicit synthetic camera + 440 Hz WAV microphone; real local WebRTC',
              'android_hardware': 'NOT TESTED', 'usb_microphone_hardware': 'NOT TESTED',
              'same_wifi': 'NOT TESTED', 'checks': {}}
    page = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
                '--use-file-for-fake-audio-capture='+str(fixture),
                '--ignore-certificate-errors', '--no-sandbox'])
            try:
                context = await browser.new_context(ignore_https_errors=True, viewport={'width': 430, 'height': 900})
                page = await context.new_page()
                await page.goto(info['https_url'], wait_until='domcontentloaded')
                await page.click('#refreshmic')
                await page.wait_for_function("document.querySelector('#micdevice').options.length>1")
                actual_inputs = await page.evaluate("(async()=> (await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='audioinput').map(d=>d.deviceId))()")
                listed_inputs = await page.eval_on_selector_all('#micdevice option', '(options)=>options.map(o=>o.value).filter(Boolean)')
                assert set(actual_inputs) == set(listed_inputs)
                result['checks']['microphone_picker_lists_only_actual_browser_devices'] = True
                await page.click('#start')
                await page.wait_for_function("document.querySelector('#status').textContent.includes('PHONE CONNECTED')", timeout=20000)
                assert await page.evaluate("document.querySelector('#preview').videoWidth > 0")
                assert await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks().length===1")
                result['checks']['start_camera_and_microphone_real_getusermedia_and_webrtc'] = True
                await page.wait_for_function("document.querySelector('#leveltext').textContent.startsWith('Live microphone') && parseFloat(document.querySelector('#level').style.width)>25", timeout=8000)
                result['checks']['actual_local_audio_analyser_meter'] = True
                processing = await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].getSettings()")
                assert all(processing.get(k) is False for k in ('echoCancellation','noiseSuppression','autoGainControl')), processing
                result['checks']['raw_mode_disables_browser_processing_on_test_browser'] = {k:processing.get(k) for k in ('echoCancellation','noiseSuppression','autoGainControl','sampleRate','channelCount')}
                await page.screenshot(path=str(output/'phone-page-connected.png'), full_page=True)
                video_track = await page.evaluate("document.querySelector('#preview').srcObject.getVideoTracks()[0].id")
                audio_track = await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].id")
                if external_report:
                    verified = await report_state(external_report, {'phone_overlay_recorded'}, timeout=30)
                    assert verified['checks'].get('phone_microphone_real_pcm_and_meter')
                    assert verified['checks'].get('phone_audio_burned_into_export')
                    result['checks']['external_native_application_recorded_actual_phone_pcm'] = verified['checks']['phone_audio_burned_into_export']
                else:
                    await eventually(lambda: len(blocks)>=25 and not frames.get('phone_raw', 2)[0].isNull())
                    result['checks']['receiver_got_actual_video_and_opus_audio_packets'] = True
                    result['checks']['received_known_tone_and_continuous_pcm'] = check_pcm(blocks)
                before = len(blocks)
                await page.click('#switch')
                await page.wait_for_function("document.querySelector('#status').textContent.includes('Camera switched')", timeout=15000)
                assert video_track != await page.evaluate("document.querySelector('#preview').srcObject.getVideoTracks()[0].id")
                assert audio_track == await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].id")
                if service:
                    await eventually(lambda: len(blocks)>before+4)
                    assert service.last_audio > time.monotonic()-1
                    assert not errors, errors
                result['checks']['camera_switch_replaces_only_video_and_preserves_microphone_track'] = True
                result['checks']['front_back_note'] = 'Facing-mode request/new track verified; physical Android sensors unavailable.'
                video_track = await page.evaluate("document.querySelector('#preview').srcObject.getVideoTracks()[0].id")
                chosen = next(v for v in reversed(listed_inputs) if v!='default')
                await page.select_option('#micdevice', chosen)
                await page.wait_for_function("document.querySelector('#status').textContent.includes('Selected microphone is streaming')", timeout=15000)
                assert video_track == await page.evaluate("document.querySelector('#preview').srcObject.getVideoTracks()[0].id")
                assert audio_track != await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].id")
                assert chosen == await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].getSettings().deviceId")
                if service:
                    await eventually(lambda: service.audio_info.get('deviceId')==chosen)
                result['checks']['selected_real_microphone_replaces_audio_only_and_updates_pc_metadata'] = True
                await page.select_option('#processing','voice')
                await page.wait_for_function("document.querySelector('#status').textContent.includes('Selected microphone is streaming')", timeout=15000)
                settings = await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].getSettings()")
                assert settings.get('echoCancellation') and settings.get('noiseSuppression') and not settings.get('autoGainControl')
                result['checks']['voice_cleanup_switch_changes_actual_capture_constraints'] = True
                await page.select_option('#processing','raw')
                await page.wait_for_function("document.querySelector('#status').textContent.includes('Selected microphone is streaming')", timeout=15000)
                await page.select_option('#channels','2')
                await page.wait_for_function("document.querySelector('#status').textContent.includes('Selected microphone is streaming')", timeout=15000)
                settings = await page.evaluate("document.querySelector('#preview').srcObject.getAudioTracks()[0].getSettings()")
                assert settings.get('channelCount') == 2
                result['checks']['stereo_control_requests_actual_two_channel_capture_on_test_browser'] = True
                await page.uncheck('#sendvideo')
                await page.wait_for_function("document.querySelector('#status').textContent.includes('Microphone-only audio streaming')", timeout=15000)
                assert await page.evaluate("document.querySelector('#preview').srcObject.getVideoTracks().length===0 && document.querySelector('#preview').srcObject.getAudioTracks().length===1")
                assert await page.is_disabled('#switch')
                if service:
                    await eventually(lambda: frames.get('phone_raw')[0].isNull() and time.monotonic()-service.last_audio<1)
                result['checks']['microphone_only_webrtc_without_phone_video'] = True
                tracks = await page.evaluate("(()=>{window.auditTracks=document.querySelector('#preview').srcObject.getTracks();return auditTracks.length})()")
                assert tracks > 0
                await page.click('#stop')
                await page.wait_for_function("document.querySelector('#preview').srcObject === null && window.auditTracks.every(t=>t.readyState==='ended')", timeout=5000)
                result['checks']['stop_stops_all_real_tracks_and_meter'] = True
                if service:
                    await eventually(lambda: service.last_audio==0 and frames.get('phone_raw')[0].isNull())
                    result['checks']['receiver_disconnect_clears_audio_and_video'] = True
                if external_report:
                    final = await report_state(external_report, {'PASS_SOFTWARE_CHECKS'}, timeout=40)
                    assert final['checks'].get('phone_overlay_burned_into_export') and final['checks'].get('phone_audio_burned_into_export')
                result['result'] = 'PASS'
            finally:
                await browser.close()
    except Exception as exc:
        result['result'], result['error'] = 'FAIL', str(exc)
        raise
    finally:
        if service:
            service.stop()
            await asyncio.wait_for(task, 10)
        if temp:
            temp.cleanup()
        fixture_temp.cleanup()
        (output/'browser-phone-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--runtime-report')
    args=parser.parse_args()
    print(json.dumps(asyncio.run(check_browser(args.output,args.runtime_report)),indent=2))
