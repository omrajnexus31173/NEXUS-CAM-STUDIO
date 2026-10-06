# NEXUS CAM STUDIO — verification report

**Release:** 1.0.0 · **Report date:** 2026-10-06 (user-local date)

## Result and scope

**Software checks passed. Physical hardware acceptance remains pending.** This report does not mark unavailable hardware as working.

The development host was Linux. Python 3.11.17 + Qt 6.8.3 ran against a real Xvfb desktop. Windows Python 3.11.9 and Windows PyInstaller 6.22.3 ran under Wine 10 to build a genuine Windows x64 GUI EXE. The final frozen EXE was launched from an otherwise empty working directory and exercised using its own bundled dependencies. No Node.js file is present in its archive.

The test desktop is a real software-rendered desktop, **not a physical Windows 10/11 PC**. Where camera/audio APIs were supplied fixtures, that is stated below. Raw artifact filenames retain the test VM/Wine clock/time zone; dates were not hardcoded into recording filenames.

## Performed tests

| Check | Observed result |
|---|---|
| Install Python 3.11 + native dependencies | PASS, Linux and Windows wheels |
| Native source application startup/main UI | PASS, Linux Qt and Windows Python under Wine |
| PyInstaller Windows build | PASS, Windows PE32+ x64 GUI executable |
| Final frozen EXE startup/shutdown | PASS, under Wine, exit code 0; repeated from extracted ZIP in a path with spaces |
| Screen pixels | PASS, actual desktop/region captures; a displayed Qt window's color was read back from screen capture |
| Default 1920×1080 / 30 FPS / High MP4 | PASS, final frozen EXE created and decoded H.264 recording |
| 1280×720 / 60 FPS | PASS, native source UI created a real file with decoded 60 FPS stream |
| 854×480 / 30 FPS | PASS, MP4/MKV/WebM pipeline tests |
| Start / pause / resume / stop | PASS, real encoder and shared active clock; paused intervals excluded |
| Recording timer | PASS, frozen UI displayed 00:00:01 while actual encoder/timeline was active |
| Composed screenshot | PASS, real PNGs at selected output resolution |
| History / settings / first-run folder selection | PASS, real UI/local JSON roundtrip and recorded file metadata |
| Overlay movement/resizing | PASS, native preview with received WebRTC frames; drag/corner actions changed live geometry |
| Circle / Oval / Rectangle / Rounded Rectangle / Square | PASS, QPainter pixel/clipping tests; circle fixture encoded with transparent corners, rectangle phone overlay recorded by frozen app |
| Border / shadow / opacity | PASS, shared rasterizer assertions; recording uses that exact raster |
| Background segmentation | PASS, actual bundled ONNX network inference + all effect modes, Linux CPU; missing-model exception tested. Human portrait quality not measured |
| Microphone level / ADC timestamps | PASS, explicit PortAudio callback fixture through actual worker; **not a physical microphone test** |
| Audio pause alignment / mixing / encoding | PASS, explicit PCM fixtures; MP4/MKV AAC and WebM Opus muxes decoded successfully |
| Compact Windows FFmpeg | PASS, native Windows encoder under Wine encoded/mixed/muxed/decoded all three formats |
| QR | PASS, real dynamically generated Qt QR raster decoded back to its exact LAN URL |
| Local HTTPS helper / certificate | PASS, CA-verified HTTPS request; IP SANs and per-installation unique root checked |
| WebRTC receiver | PASS, real packet transport, repeated frames, reconnect/replacement/disconnect, invalid-token rejection |
| Mobile START / SWITCH / STOP | PASS, real Chromium getUserMedia/track/WebRTC actions with an **explicit synthetic browser camera**; track IDs changed and receiver cleared after Stop |
| Phone stream in frozen Windows preview/export | PASS, Chromium fixture → real WebRTC → frozen EXE → composition → real H.264 export |
| Diagnostics | PASS for available software components; camera/microphone returned UNAVAILABLE, not PASS |
| Missing camera/microphone/FFmpeg | PASS, unavailable/invalid devices emitted friendly errors, no fatal crash, no pretend recording files |
| Clean receiver/thread shutdown | PASS, frozen EXE exited with code 0 and its phone ports were released |

## Automated suite

**25 passed**, 11.61 seconds on the final run on this host.

Evidence: `reports/pytest-results.xml`. The suite includes genuine screen capture, real file encoding/decoding, mobile browser/receiver integration, and explicitly labelled unit fixtures. Fixtures are contributor tests only; they are not camera/audio sources selectable in the normal app.

## Final frozen EXE export audit

`reports/runtime-windows-final.json` was written by the final packaged application's real controls/pipeline.

- Default video: **1920×1080, H.264, 30 FPS**, **344,053 bytes**, **2.133333 s**.
- Received phone-fixture overlay video: **1920×1080, H.264, 30 FPS**, **338,029 bytes**, **1.066667 s**.
- First encoded frame was decoded and compared to the exact composed QImage fed to the encoder.
- Mean absolute channel error: **0.8929 / 255** for desktop export, **0.9664 / 255** for phone-overlay export. This small difference is ordinary lossy H.264/YUV conversion, not a missing/reconstructed overlay.
- The native app performed actual draggable/resizable overlay interactions and real screenshot/recording saves.

`reports/browser-phone-results.json` identifies the camera as a synthetic Chromium fixture. The transport and pipeline are real; it does **not** certify an Android phone or Wi-Fi router.

## Not tested / unavailable

These are **not passed**:

- Bare-metal Windows 10 or Windows 11.
- Laptop/USB webcam capture, real human portrait background quality, and camera driver permissions/busy-device behavior on actual Windows hardware.
- Physical microphone capture or microphone permission dialog.
- Physical Windows WASAPI speaker/headphone loopback capture, silence/discontinuity behavior, or protected audio.
- Actual Android front/back camera sensors, Android CA-install flow, phone screen-lock lifecycle, and same-Wi-Fi router/firewall setup.
- Mixed-DPI multi-monitor region picking and real Windows visible-window capture; implemented but only a single software desktop was available.
- OS-default video player/Explorer launch on a populated Windows desktop.

## Genuinely unavailable / intentionally limited

- Hidden/minimized/unobscured-window capture via Windows Graphics Capture is **not implemented**. Window mode explicitly captures its **visible desktop bounds**.
- A corporate phone/network that blocks user certificates or local peers may make phone streaming unavailable; there is no unsafe bypass.
- The executable is unsigned; no signing certificate was available.
- No GPU encoder, editor, cloud relay, or virtual-camera output is claimed.

## Repeat on your Windows PC

1. Extract and launch the EXE as a normal user.
2. Complete first-run setup with your real webcam/microphone and output folder.
3. Verify actual device frames/audio meters; test every shape and a background effect on a person.
4. Record a short screen + overlay + microphone clip; pause/resume, stop, and play it. Then separately enable/test system audio on the output actually playing sound.
5. Test the selected region and visible-window modes, including your monitor DPI layout.
6. Pair a real Android phone on the same Wi-Fi, trust this PC's local certificate if required, test front/back/Stop, and record its overlay.
7. Run Settings → Diagnostics. Only treat components that were actually checked on your machine as hardware-verified.

The implementation and runnable build are delivered; this environment's physical-hardware acceptance checklist is intentionally **not falsely declared complete**.
