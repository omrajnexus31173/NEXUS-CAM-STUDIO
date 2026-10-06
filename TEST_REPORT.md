# NEXUS CAM STUDIO 1.1 — verification report

**Release:** 1.1.0 · **Report date:** 2026-10-06 (user-local date)

## Result and scope

**37 automated software tests passed; the rebuilt Windows executable recorded and decoded actual received phone-fixture audio/video successfully.** Physical Android USB-microphone routing and the user's original distorted recording were unavailable and are **not marked verified or repaired**.

Development/test host: Linux, Python 3.11.17, Qt 6.8.3, Xvfb 1600×1000 desktop. A genuine **Windows PE32+ x64 GUI executable**, version **1.1.0**, was built with Windows Python 3.11.9 / PyInstaller 6.22.3 under Wine 10. The final frozen EXE used its bundled libraries and compact Windows FFmpeg. Wine is **not** bare-metal Windows 10/11 acceptance.

The phone fixture is an explicitly synthetic Chromium camera plus a **known 440 Hz WAV microphone** passed through real `getUserMedia`, encrypted WebRTC/Opus, reception, PCM writing and AAC export. No fixture source is offered in the normal application's UI. The browser's test-only certificate bypass flags are not in the app or mobile page.

## What changed from 1.0

The previous phone page used `audio:false`: it sent video but **did not send the phone microphone**. Version 1.1 adds independent phone audio, a real microphone picker, raw/voice processing controls, mono/stereo request, actual local analyser, desktop meter/volume/clipping warnings, and **Use Phone Mic Only** (PC mic off; system sound unchanged).

Packet arrival/callback jitter no longer chops or re-anchors continuous audio. Delayed RTP packets keep their captured media time. Slow phone video conversion runs off the audio/UDP loop and retains only the newest waiting video frame. Stop drains late, pre-Stop PCM with a bounded wait; missing final audio is explicitly warned. A non-modal pairing dialog is also closed during shutdown so it cannot keep the app alive after its main window has closed.

## Automated regression suite

**37 passed, 17.50 seconds; no skipped tests** on the final run.

Evidence: `reports/pytest-results-v1.1.xml`.

The suite executes real file encoding/decoding, screen capture, HTTPS/WebRTC transport, browser controls and native widget behavior. Explicit fixtures also test:

- Continuous sample/PTS timestamps despite scheduling/Wi-Fi jitter and multi-second delayed delivery; genuine backward sender-clock restart.
- Opus/PyAV conversion to finite float32 stereo 48 kHz; real clipping detection and invalid-PCM rejection.
- Exact PCM sample retention: no jitter-induced zero padding, chopped packet tails or per-packet sample loss.
- Late packets captured before Stop; synchronized close cannot overtake an in-flight final PCM copy.
- Real Opus → WAV → MP4/AAC recording with pause/resume and decoded tone-frequency/level checks.
- Slow video-conversion fixture does not starve real incoming Opus packets.
- Real browser input enumeration/picker, actual accepted raw/voice settings, microphone-track replacement, stereo request, microphone-only WebRTC and Stop/track cleanup.
- Legacy-settings migration, desktop phone-mic selection/solo action, saved gain, actual gain-scaled PCM, clipping notification, unavailable-phone-audio refusal, and visible pairing-dialog shutdown.
- Existing screen/region, overlay geometry/style, background inference/fallback, screenshot, history/settings, microphone callback logic, encoder formats and unavailable-device tests.

## Final frozen Windows EXE audit

Evidence: `reports/runtime-windows-v1.1.json`, `reports/browser-phone-v1.1.json`, `reports/windows-build-v1.1.txt`, `reports/portable-v1.1-check.json`.

| Check | Observed result |
|---|---|
| Windows executable/version | PE32+ x64, GUI subsystem, file/product version 1.1.0 |
| Default actual desktop export | H.264, 1920×1080, 30 FPS, 477,000 bytes, 2.066667 s |
| Actual phone-fixture overlay + audio export | H.264/AAC, 1920×1080, 30 FPS, 661,632 bytes, 2.400000 s |
| Exact composition vs decoded first frame | Mean absolute pixel error 0.9209/255 desktop; 0.9870/255 phone overlay (ordinary lossy H.264/YUV difference) |
| Phone audio stream in saved file | AAC, stereo, 48,000 Hz; 115,712 decoded samples/channel including codec framing/padding |
| Known external 440 Hz fixture | Decoded dominant frequency 440.127 Hz, RMS 0.176023, peak 0.259878 (not clipped) |
| Internal silent-gap audit | 0.00 s detected in 10 ms RMS windows, excluding first/last 100 ms; not a general zero-packet-loss guarantee |
| Phone/PC microphone selection | Phone selected, PC mic off; actual desktop RMS meter value 71 |
| Live phone microphone diagnostic | PASS based on received PCM, label “Fake Default Audio Input”; hardware identity explicitly not certified |
| Raw processing accepted by test browser | Echo cancellation, noise suppression and auto gain all false; input 44,100 Hz/two channels, transported/exported at 48 kHz |
| Pause/resume | Actual recording controls shared the audio/video active timeline; paused time excluded |
| Overlay / screenshot / history | Real movement/resizing, composed PNG save, and actual export/history files |
| Camera switch | Video track changed while microphone track ID remained unchanged |
| Microphone selection/processing/stereo | Actual audio track replaced without replacing video; capture settings/PC metadata changed |
| Audio-only phone | Real audio WebRTC without a video track; camera-switch control correctly unavailable |
| Portable extracted ZIP binary | Same SHA256 executable launched from an isolated path with spaces, real UI snapshot, exit 0 |
| Stop / clean shutdown | Browser tracks ended; final frozen EXE exited 0; local phone ports released |

Retained sample outputs are clearly labelled **fixtures**:

- `reports/native-desktop-v1.1-1080p30.mp4`
- `reports/native-phone-audio-fixture-v1.1-1080p30.mp4`
- `reports/native-live-phone-audio-fixture.png`

Diagnostics after the browser pressed Stop correctly returned Phone Microphone **UNAVAILABLE**. Its earlier live-PCM diagnostic passed while packets were arriving. Physical webcam/PC microphone were also **UNAVAILABLE**, never faked.

A Windows-under-Wine stress run initially exposed audio backlog loss when video conversion blocked the receiver loop and delayed packets were re-anchored. Those checks failed; the timing, conversion isolation and finalization fixes were implemented before the final successful build above. Changing the Windows event-loop policy alone did not fix it and was not shipped.

## Predecessor evidence

`reports/v1.0/` retains the prior delivered build's 25-test results and encoder/portable/runtime artifacts. They are **version 1.0 evidence**, not renamed 1.1 results. Its physical-hardware limits remain applicable. Current regression testing re-executes its software suite plus the added audio tests.

## Not tested / not guaranteed

- Physical Android handset, USB-C/OTG receiver compatibility, USB routing/input names, microphone hardware gain/clipping, Android CA-install flow, front/back sensors, Wi-Fi router/firewall setup or screen-lock lifecycle.
- The user's distorted audio sample: no original sample was provided; existing distortion is not repaired.
- Bare-metal Windows 10/11; real PC/USB webcam/microphone driver permissions/busy-device behavior; Windows WASAPI speaker/headphone loopback or protected audio.
- Human portrait segmentation quality, mixed-DPI multi-monitor picking, hidden/minimized windows, populated Windows video-player/Explorer integration.
- Calibrated physical A/V lip-sync or zero latency. Network/CPU backlog can delay live meters. Missing packets cannot be reconstructed by a volume slider; bounded finalization can warn and leave silence.

Hidden/minimized-window capture is **not implemented**; Window mode captures visible desktop bounds. The EXE is unsigned. Managed devices/networks may disallow local certificates/peers; no unsafe bypass, cloud relay, GPU encoder, editor or virtual-camera output is claimed.

## Acceptance on your own phone/PC

1. Close the old app and extract the new ZIP; check title/version 1.1. Existing user settings/history/recordings are retained.
2. Connect USB mic to phone **first**, pair using a fresh HTTPS QR and allow camera/microphone permission.
3. Refresh real microphone inputs. Select USB if exposed; if only Default appears, verify Android is actually routing the external mic. Nexus cannot force a device hidden by the browser.
4. Use USB / Raw, Mono voice, desktop **Use Phone Mic Only**; disable System Audio too if unwanted. Verify both real meters.
5. Record 10–15 seconds of speech, pause/resume, Stop, wait for Recording Saved, and play the saved clip. Lower **hardware receiver/mic gain** if it clips; desktop attenuation cannot undo clipping.
6. Test switching camera, mic-only mode and intended PC/system sources separately. Keep the phone awake on stable Wi-Fi.
7. Run Diagnostics while the intended devices are active. Treat only checks actually performed on your equipment as hardware-verified.
