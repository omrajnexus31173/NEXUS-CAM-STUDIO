# Third-party notices

Nexus Cam Studio's original application source is licensed GPL-3.0-or-later (`LICENSE`). Dependencies retain their own licenses. The EXE contains dynamically loaded Qt and other runtime libraries; source/build scripts and package versions are included so the application can be rebuilt. This is an unsigned, locally built artifact, not an official Qt/OpenCV/FFmpeg product.

| Component | License / source |
|---|---|
| Python 3.11 runtime | PSF license; https://www.python.org/downloads/source/ |
| PySide6/Shiboken/Qt 6.8.3 | LGPL-3.0 / GPL alternatives and Qt exception notices; https://code.qt.io/cgit/pyside/pyside-setup.git/ ; https://download.qt.io/archive/qt/6.8/6.8.3/ |
| OpenCV 4.10.0 | Apache-2.0; https://github.com/opencv/opencv/tree/4.10.0 |
| NumPy 1.26.4 / OpenBLAS | BSD-3-Clause; https://github.com/numpy/numpy/tree/v1.26.4 ; https://github.com/OpenMathLib/OpenBLAS |
| FFmpeg 7.1.5 (supplied compact build) | GPL-3.0-or-later configuration; https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz ; full build configuration and source checksums: `vendor/encoder-build/` |
| x264 | GPL; https://code.videolan.org/videolan/x264/ ; source URL/config in `tools/build_small_ffmpeg.sh` |
| libvpx 1.15.0 | BSD-3-Clause; https://github.com/webmproject/libvpx/tree/v1.15.0 |
| Opus 1.5.2 | BSD-3-Clause; https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz |
| imageio-ffmpeg 0.6.0 | BSD-2-Clause Python wrapper; packaged encoder retains its own FFmpeg license; https://github.com/imageio/imageio-ffmpeg |
| PyAV 17.1.0 / its FFmpeg DLLs | PyAV BSD-3-Clause, DLLs retain upstream codec/FFmpeg licenses; https://github.com/PyAV-Org/PyAV ; https://github.com/PyAV-Org/pyav-build |
| aiortc / aioice | BSD-3-Clause; https://github.com/aiortc/aiortc ; https://github.com/aiortc/aioice |
| aiohttp | Apache-2.0; https://github.com/aio-libs/aiohttp |
| pylibsrtp / libSRTP | BSD-3-Clause; https://github.com/aiortc/pylibsrtp ; https://github.com/cisco/libsrtp |
| cryptography / OpenSSL / PyOpenSSL | Apache-2.0/BSD and upstream OpenSSL licenses; https://github.com/pyca/cryptography ; https://github.com/openssl/openssl ; https://github.com/pyca/pyopenssl |
| SoundCard / sounddevice / PortAudio | BSD/MIT-style upstream licenses; https://github.com/bastibe/SoundCard ; https://github.com/spatialaudio/python-sounddevice ; https://github.com/PortAudio/portaudio |
| MSS | MIT; https://github.com/BoboTiG/python-mss |
| cv2-enumerate-cameras | MIT; https://github.com/chinaheyu/cv2_enumerate_cameras |
| qrcode | BSD; https://github.com/lincolnloop/python-qrcode |
| psutil | BSD-3-Clause; https://github.com/giampaolo/psutil |
| Portrait segmentation weights | OpenCV Zoo PPHumanSeg, Apache-2.0; license is included at `assets/models/LICENSE.txt`; https://github.com/opencv/opencv_zoo/tree/main/models/human_segmentation_pphumanseg |
| PyInstaller | GPL with bootloader exception; https://github.com/pyinstaller/pyinstaller |

## Portrait model provenance

File: `assets/models/portrait.onnx` (the OpenCV Zoo `human_segmentation_pphumanseg_2023mar.onnx` weights).

Download: https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/human_segmentation_pphumanseg/human_segmentation_pphumanseg_2023mar.onnx

The adapter uses the documented 192×192 RGB / mean=.5 / std=.5 preprocessing and foreground probability output. Original repository copyright and Apache license are preserved in `assets/models/LICENSE.txt`.

## Compact encoder reproduction

`tools/build_small_ffmpeg.sh` contains all configure/build steps, versions and download locations for the supplied local encoder. `vendor/encoder-build/source-checksums.txt` identifies the source archives used. `config.h` / `config.mak` and the FFmpeg GPL license are retained. The encoder disables networking and unrelated tools; it preserves all formats/codecs/filters actually used by Nexus. A normal Windows source rebuild uses the full encoder from the pinned imageio-ffmpeg wheel instead unless the compact binary is supplied in `build/encoder/`.

No proprietary model, sample human portrait, private CA/key, user recording, cloud credential, or synthetic camera source is included in the normal application. Synthetic media is used **only in explicitly labelled contributor tests**.
