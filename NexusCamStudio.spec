# Build on Windows x64 with Python 3.11. Also buildable using Windows Python under Wine.
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
import imageio_ffmpeg

root = Path(SPECPATH)
compact = root / 'build' / 'encoder' / 'ffmpeg.exe'
ffmpeg = compact if compact.exists() else Path(imageio_ffmpeg.get_ffmpeg_exe())
data = [(str(root / 'assets'), 'assets'),
        (str(root / 'app' / 'phone' / 'mobile.html'), 'app/phone'),
        (str(root / 'app' / 'phone' / 'instructions.html'), 'app/phone')]
data += collect_data_files('soundcard', includes=['*.h'])
hidden = collect_submodules('av') + ['soundcard.mediafoundation', 'cv2_enumerate_cameras.windows_backend',
                                    'cv2_enumerate_cameras._windows_backend', '_cffi_backend']
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[], datas=data, hiddenimports=hidden,
    hookspath=[], runtime_hooks=[], excludes=['PyQt5', 'PyQt6', 'tkinter', 'matplotlib', 'scipy', 'PIL',
        'pandas', 'pytest', 'IPython', 'tensorflow', 'torch', 'mediapipe', 'PySide6.QtQml',
        'PySide6.QtQuick', 'PySide6.QtMultimedia', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'],
    noarchive=False)
# DirectShow webcams do not use OpenCV's optional FFmpeg video-file plugin.
# Video encoding uses the full, separately bundled imageio FFmpeg binary instead.
def keep(entry):
    name = entry[0].lower().replace('\\', '/')
    if 'opencv_videoio_ffmpeg' in name or 'opengl32sw.dll' in name:
        return False  # Pure 2D raster Qt UI; no OpenGL widgets or OpenCV video-file plugin.
    if compact.exists() and name.startswith('imageio_ffmpeg/binaries/'):
        return False
    return True
a.binaries = [entry for entry in a.binaries if keep(entry)]
a.datas = [entry for entry in a.datas if keep(entry)]
# Treat the encoder as data so it isn't dependency-scanned (it is a static build).
a.datas += [(('ffmpeg/ffmpeg.exe' if compact.exists() else f'imageio_ffmpeg/binaries/{ffmpeg.name}'), str(ffmpeg), 'DATA')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='NexusCamStudio', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon=str(root / 'assets' / 'nexus.ico'), version=str(root / 'assets' / 'version_info.txt'),
    uac_admin=False)
