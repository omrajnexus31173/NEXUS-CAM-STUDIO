# NEXUS CAM STUDIO · 1.1

A **native Windows x64 desktop recorder**, implemented in Python 3.11 + PySide6. It uses real screen/camera/audio capture, one shared composition rasterizer, and a real local FFmpeg recording pipeline. No Node.js, cloud account, external backend, or database is required.

**Read `TEST_REPORT.md` before interpreting this release as hardware-certified.** The Windows executable was built with Windows Python/PyInstaller and exercised under Wine. Physical Windows 10/11 hardware, webcam/microphone/WASAPI inputs, and an Android handset with a USB microphone on Wi-Fi were not available in the build environment.

## 1.1 update: USB microphone connected to your phone

Version 1.0 sent **phone video only**. Version 1.1 adds a real, independent **Phone Microphone** source: browser microphone capture → encrypted local Opus/WebRTC → stereo 48 kHz PCM → the same actual recording/pause timeline → AAC/Opus export. It is not a simulated meter or a phone label on the PC microphone.

**Updating:** close the old app, extract this ZIP to a new folder, and launch its EXE. The title/version says **1.1**. Existing per-user settings, history, output location, and local certificate are retained; old settings gain safe new defaults. Scan the new pairing QR rather than reusing an old phone tab. See `UPDATE_1.1.txt` for the short USB-mic procedure.

## Run the portable Windows release

1. Extract **all** of `NexusCamStudio-Windows-v1.1.zip`.
2. Open `NexusCamStudio/StartNexusCamStudio.cmd`, or run `NexusCamStudio/dist/NexusCamStudio.exe` directly.
3. On first launch, select your camera, microphone, and output folder.
4. The selected desktop starts previewing. Review the composition and audio meters, then click **START RECORDING**.
5. Use **PAUSE / RESUME / STOP**. Stop finalizes video/audio and automatically saves the file. Wait for **Recording Saved ✓** before closing or moving files.

The EXE includes Python, Qt, the portrait model, WebRTC libraries, and a compact FFmpeg binary. **Python does not need to be installed to run the EXE.** Initial extraction/startup may take several seconds. Run it as a normal user; the manifest does not request administrator privileges.

This build is unsigned. Check `SHA256SUMS.txt` and only run a download you trust. If your security policy blocks unsigned applications, use the source/rebuild route or ask your administrator; do not disable antivirus or browser security globally.

## Run from source (Windows, Python 3.11)

Double-click `LaunchSource.cmd`, or use:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Dependency installation needs internet access once. Normal desktop recording and phone streaming are local/offline. `opencv-python-headless` still supports camera capture; Qt supplies the UI instead of OpenCV HighGUI. `PySide6-Essentials` is the native PySide6 distribution without unnecessary QtWebEngine modules.

## Record screen, a region, or a visible window

- **Entire Screen:** choose a detected display and click START SCREEN (or STOP SCREEN to release it).
- **Selected Region:** click SELECT REGION. Drag to create/move the selection; drag a corner to resize it. **Enter confirms**, **Escape cancels**. The picker works on the selected display.
- **Window · visible area:** Windows only. Select a visible window. Its bounds are tracked and that desktop area is captured. **Keep it unobscured and restored.** This is deliberately labelled visible-area capture: hidden/minimized-window capture using Windows Graphics Capture is **not implemented**.
- **Camera only:** the selected live camera fills/letterboxes the output. Overlay geometry/style controls are disabled because there is no separate overlay in this mode. Background effects still apply.

Minimize Nexus while recording the entire desktop to avoid recording its own UI recursively. Returning to the window does not stop recording. Protected video, secure/UAC desktops, and DRM content are subject to Windows restrictions.

## Laptop/USB camera and overlays

Real webcams are enumerated with their device names. Choose one in Camera Source and enable **Camera overlay**. If none are present, the app says so and offers **Refresh Devices**; it never substitutes a sample video.

The default is a small circle at bottom-right. Click the live overlay to select it, drag to move, and drag its corners to resize. Arrow keys nudge; Shift+arrow moves 10 output pixels. Circle/square resizing keeps equal pixel dimensions. Choose Circle, Oval, Rectangle, Rounded Rectangle, or Square. Size, X/Y, border width/radius/color, shadow, opacity, and mirror controls alter the shared composition, including during recording.

**Selection handles are UI-only.** The camera's actual style border, shadow, opacity, clipping, and effects are burned into the export. The screen is aspect-fitted with letterboxing, matching the preview.

### Background effects

Original, Blur, Strong Blur, Plain Blue/Green/Gray/Cream are implemented. The bundled OpenCV Zoo **PPHumanSeg** ONNX network performs real portrait segmentation on the CPU; this avoids the much larger MediaPipe dependency stack. Inference is throttled to 15 Hz, and a cached soft mask is applied to incoming camera frames. Quality depends on lighting/scene/person visibility. It is not a chroma-key trick or a fake background panel.

A missing/failed model or inference error restores **Original**, shows an error, and does not crash the recorder. The model and its Apache-2.0 license are included in `assets/models/`.

## Connect an Android phone camera + microphone

1. Put the PC and phone on the **same non-guest Wi-Fi** (Ethernet PC + same router Wi-Fi also works).
2. Click **Connect Phone** in Nexus. It detects the PC's LAN IPv4 address, starts its embedded receiver, selects Phone Camera, and generates a real QR.
3. Scan the **HTTPS camera QR**. Do not replace the LAN address with localhost.
4. **Important: mobile camera APIs require trusted HTTPS.** If the page isn't trusted, first copy/open the **HTTP setup-guide link** displayed below the QR. Download this PC's `nexus-phone-root.crt`.
5. On Android, install it under Settings → Security & privacy → More security settings → Encryption & credentials → Install a certificate → **CA certificate** (names vary). A screen lock/PIN may be required. Restart Chrome, then reopen the HTTPS QR link.
6. Plug in the USB microphone/receiver first. Tap **START CAMERA** and allow **camera and microphone** permission. **SWITCH CAMERA** replaces only the video track, leaving the microphone connected. **STOP CAMERA** stops both tracks and disconnects.
7. Nexus shows **PHONE CONNECTED ✓ only after receiving an actual video frame**. Select/resize/style the phone overlay just like a webcam.

Default ports: HTTP setup **8765**, HTTPS camera **8766**. Settings → Phone changes the first port; HTTPS always uses the next one. The dialog displays both exact token-bearing URLs with working Copy buttons. Manual IP override is available if a VPN/extra adapter causes incorrect auto-selection.

The receiver is embedded inside the desktop process and runs only after Connect Phone. It serves local mobile HTML, token-protected signaling, and certificate setup; audio/video use local encrypted WebRTC with **no external signaling/STUN/TURN service**. The certificate CA/private key is unique per installation; no private certificate or key is shipped in this ZIP. Never trust a CA from an unknown PC. Remove the Nexus local CA from Android when no longer needed.

Allow Nexus/Python on **Private networks** if Windows Firewall prompts. WebRTC also uses ephemeral local UDP ports. Guest-network isolation, managed firewalls, VPN routing, or corporate phones that prohibit user CAs can prevent connection. Nexus cannot bypass those policies. Plain HTTP is a **guide only**, not a falsely working mobile camera page.

**The Android handset/same-Wi-Fi path has not been physically tested in this environment.** Local HTTPS, QR, WebRTC packet transport, and mobile-page controls were tested using an explicit synthetic Chromium camera and known WAV tone, including delivery into the frozen Windows app and its real audio/video export. This does not prove USB routing on your handset.

## Audio

### Use the USB-C microphone attached to your Android phone

1. Plug in the USB mic/receiver **before** opening the new HTTPS phone page. Pair using **Connect Phone**; this selects phone audio and switches off the PC mic to avoid duplicate voice.
2. On the phone, leave **Send microphone** on. Tap **Allow / Refresh Microphones**, then select the **actual USB input** if it appears in **MICROPHONE INPUT**. Only real `enumerateDevices()` inputs are listed.
3. Choose **USB / Raw** (default): request auto gain, noise suppression and echo cancellation **off**. The phone shows actual accepted input settings and warns if the browser retains processing. **Voice cleanup** is optional; automatic gain remains off. Use **Mono voice** unless your input genuinely supplies stereo.
4. Tap **START CAMERA**. Speak into the USB mic and verify both the phone's local analyser and the desktop's **Phone Microphone** meter respond. **Use Phone Mic Only** disables the PC mic but deliberately leaves System Audio unchanged. Turn System Audio off as well if you want no computer sound.
5. Leave the desktop phone volume at 100% initially. Record 10–15 seconds, pause/resume, stop, wait for **Recording Saved**, and play the actual saved file before recording an important session.

**Android routing limit:** some phones expose only **Default microphone** to Chrome. In that case Android, not Nexus, selects the physical USB input; a separate USB entry cannot be invented or forced. Test by speaking/tapping gently near the external mic while covering/moving away from the phone mic. Check Android's USB/OTG input routing, receiver power/cable, or the mic manufacturer's Android compatibility if the wrong source responds.

**Clipping/distortion:** red clipping warnings come from real PCM peaks **before** desktop attenuation. Reduce the USB microphone/receiver's **hardware input gain** or move it farther from your mouth. Lowering Nexus's slider changes recorded volume but cannot repair an already-clipped input. Existing distorted recordings are not repaired by this update.

**Audio only from the phone:** turn **Send camera** off and leave **Send microphone** on. Your screen can still be recorded, or select your PC camera again in the desktop Camera Source. No phone video is required for audio. You still need a live screen/camera composition to make a video recording.

### PC and system audio / recording timing

- **PC Microphone** uses the selected real native input. **System Audio** uses Windows WASAPI loopback of the selected playback output. Choose the speakers/headphones actually playing sound. Loopback is explicitly unavailable outside Windows/without real outputs; DRM/protected sound can remain silent.
- All three sources have independent real RMS/dB meters and recording volumes. Volumes remain adjustable while recording; source/device selections on the desktop are locked until Stop.
- Native callback and phone RTP/sample clocks are continuous: ordinary scheduling/Wi-Fi jitter does **not** chop packets, re-anchor delayed words, or insert artificial per-packet gaps. Stereo 48 kHz tracks share the video's active/pause timeline; paused time is removed.
- Phone video conversion runs outside the audio/UDP loop and retains only the latest waiting video frame. Slow raster work must not block incoming microphone packets.
- Stop retains in-flight audio captured **before** Stop and waits briefly for a phone backlog (bounded at 8 seconds when needed). Post-Stop speech is clipped out. A timeout reports an audio-finalization warning rather than pretending missing samples arrived.
- MP4/MKV audio requests **256 kbps AAC**; WebM uses Opus. Mixed sources are limited during finalization. Phone Opus quality parameters are negotiated with the browser; actual rates/channels are browser/device-dependent, not forced hardware capabilities.
- Keep the phone awake on stable non-guest Wi-Fi. Connection loss/stalled PCM, unavailable sources, queue overflow and decoder failures are reported. Missing audio can be silent; inspect the saved clip. No zero-latency/lip-sync calibration or recovery of packets never received is promised.

**Test scope:** transport/PCM continuity, real meters, raw processing controls, microphone selection, audio-only capture, pause/resume and final exported audio were tested with labelled software fixtures. The physical Android USB microphone and the user's original distorted recording were not available here.

## Settings, output and history

- Default: **1920×1080, 30 FPS, High, MP4/H.264**.
- Resolution: 1920×1080, 1280×720, 854×480. FPS: 30/60. Quality: Low/Medium/High. Bitrate auto-scales with resolution/FPS; a custom kbps override is available.
- Formats: MP4 (H.264/AAC), MKV (H.264/AAC), WebM (VP9/Opus). Encoder unavailability is reported; fallback codec/container names and actual extensions are exposed.
- Default output: the user's Windows **Videos/NexusCamStudio** known folder, including redirected Videos folders. No `C:\Users\...` path is hardcoded.
- Names: `NexusCam_YYYY-MM-DD_HH-MM-SS.mp4` and `NexusCam_Screenshot_YYYY-MM-DD_HH-MM-SS.png`. Runtime uses the PC's local clock and collision suffixes when needed.
- **Screenshot** saves the actual composed screen + camera + effects, not the application chrome/selection guides (unless the desktop source itself includes the app).
- Recent Recordings shows real filename/date/duration/size. Play uses the OS-associated player, Open Folder uses Explorer, and Delete requires confirmation and really removes the file.
- Settings/history/logs: `%APPDATA%/NexusCamStudio`. They are local JSON/rotating logs. Phone certificates live there too.
- Output settings are write-checked. Recording failures keep temporary media/logs under `recovery/` in the local data folder; incomplete MP4s are not guaranteed recoverable. No failed or partial file is falsely labelled saved.

## Diagnostics

Settings → Diagnostics → **Run Diagnostics** tests Application, Camera, PC Microphone, **Phone Microphone**, Screen Capture, FFmpeg, Phone Server, and a short real Recording encode/decode probe. It reports PASS, FAIL, or UNAVAILABLE and exact details.

Start Connect Phone before running the Phone Server diagnostic. A Phone Server PASS proves a verified HTTPS response, **not** a physically connected Android phone. A Recording PASS in this panel is a 5-frame pipeline probe; hardware audio is reported separately. Phone Microphone PASS requires actual recent phone PCM packets and reports the browser-provided input label; it cannot independently certify USB hardware identity. Missing components are never silently marked ready.

## Build `dist/NexusCamStudio.exe`

On a Windows x64 machine with Python 3.11, run `BuildWindows.cmd`:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean NexusCamStudio.spec
.\.venv\Scripts\python.exe -m tools.make_release
```

A normal Windows rebuild uses the tested full encoder provided by `imageio-ffmpeg`. The included release uses a smaller **FFmpeg 7.1.5 + x264 + libvpx + Opus** build. Optional Linux/WSL MinGW build steps are in `tools/build_small_ffmpeg.sh`; if `build/encoder/ffmpeg.exe` is present when packaging, the spec bundles it instead. This optional build tool is **not a runtime requirement**. Source download URLs, configuration and checksums for the supplied encoder are in `vendor/encoder-build/`.

The spec bundles the model, phone HTML, SoundCard headers, PortAudio/Qt/WebRTC dependencies, and FFmpeg. It deliberately excludes QtWebEngine, Pillow (QR raster uses Qt), and unused OpenGL/software-video-file plugins. DirectShow webcam capture and Qt raster preview are retained. The EXE is a real Windows PE32+ x64 GUI binary, not a renamed Linux build.

### Repeat software tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

The optional mobile-browser test skips if Python Playwright/Chromium are not installed. Playwright is a **contributor-only test tool**, not shipped in or required by Nexus.

For actual desktop capture/export checks of either source or frozen app:

```powershell
.\dist\NexusCamStudio.exe --verify-output "$env:TEMP\nexus-verify\report.json"
```

This runner invokes the same real native controls and capture pipeline; it does not supply any synthetic source. Use a separate test data/output folder (environment variables `NEXUS_DATA_DIR` / `NEXUS_OUTPUT_DIR`) to isolate test recordings from user history. `--verify-phone-wait 30` allows a separately connected sender to exercise live overlay movement/resizing, audio readiness, audio/video pause/resume and actual export auditing. Contributor flag `--verify-audio-tone 440` checks an explicitly supplied external 440 Hz fixture; it never generates or substitutes audio in the app. The JSON still leaves physical Android/microphone/webcam hardware explicitly unverified.

## Architecture

```text
NexusCamStudio/
  main.py                     native QApplication / entry point
  app/ui/                     native widgets, preview interactions, setup/settings
  app/camera/                 OpenCV DirectShow webcam worker + discovery
  app/screen/                 MSS worker + visible Windows window enumeration
  app/audio/                  microphone/loopback workers + aligned PCM writer
  app/recorder/               compositor, monotonic timeline, FFmpeg encoder/mux
  app/phone/                  token-protected HTTPS + local WebRTC + mobile page
  app/effects/                real portrait segmentation + graceful fallback
  app/settings/               user settings/history JSON
  app/utils/                  paths, devices, frame mailboxes, QR, COM, diagnostics
  assets/                     icon + bundled ONNX portrait model
  output/                     project directory; normal output goes to user Videos
  tests/                      unit/integration tests (fixtures are explicitly labelled)
  tools/                      build/package/acceptance tools
  vendor/                     dependency/encoder/model licensing and build info
  build/                      generated PyInstaller/optional encoder artifacts
  dist/NexusCamStudio.exe     packaged Windows application
```

Capture, camera, effects, composition, microphone/loopback, audio-file writing, and encoding do not run on the UI thread. Bounded latest-frame mailboxes avoid unbounded UI signal queues. Preview, PNG export, and encoding use the **same composed QImage**, with no separately approximated recording overlay.

## Genuine limitations / unverified components

- **Not implemented:** unoccluded/minimized-window capture; window mode captures only the visible desktop bounds.
- **Not physically verified:** bare-metal Windows 10/11, laptop/USB webcam, microphone, WASAPI playback loopback, Android USB input routing/front/back sensors/same-Wi-Fi/certificate-install flow, mixed-DPI multi-monitor region selection.
- Mobile camera requires trusted HTTPS and permissions; locked-down devices/networks may make the feature unavailable.
- Portrait segmentation can be imperfect. Original is the safe fallback, not a promise of professional green-screen quality.
- OS-associated playback/explorer integrations are implemented but weren't physically tested on a Windows desktop with a media player.
- No GPU encoder, virtual camera output, editing timeline, or internet/WAN phone relay is claimed or shown as working.

Original application code is GPL-3.0-or-later. See `LICENSE` and `THIRD_PARTY_NOTICES.md` for bundled dependencies and model/encoder sources.
