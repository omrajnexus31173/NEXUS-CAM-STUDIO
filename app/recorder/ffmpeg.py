import os
import re
import shutil
import subprocess
from dataclasses import dataclass

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def executable():
    override = os.environ.get('NEXUS_FFMPEG')
    if override:
        if not os.path.isfile(override):
            raise RuntimeError(f'FFmpeg override does not exist: {override}')
        return override
    from app.utils.paths import resource
    compact = resource('ffmpeg/ffmpeg.exe')
    if compact.is_file():
        return str(compact)
    import imageio_ffmpeg
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        result = shutil.which('ffmpeg')
        if result:
            return result
        raise RuntimeError('FFmpeg unavailable. Reinstall Nexus Cam Studio or install imageio-ffmpeg.')


def run_checked(command, timeout=120):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, creationflags=CREATE_FLAGS)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-4000:] or 'FFmpeg command failed')
    return result


@dataclass
class Encoding:
    executable: str
    codec: str
    format: str
    warning: str = ''


def choose_encoding(requested='mp4'):
    exe = executable()
    output = run_checked([exe, '-hide_banner', '-encoders'], timeout=20).stdout.decode('utf-8', errors='replace')
    encoders = set(re.findall(r'^\s*V\S{5}\s+(\S+)', output, re.MULTILINE))
    if requested == 'webm':
        for codec in ('libvpx-vp9', 'libvpx'):
            if codec in encoders:
                return Encoding(exe, codec, 'webm')
    elif 'libx264' in encoders:
        return Encoding(exe, 'libx264', requested)
    elif 'mpeg4' in encoders:
        return Encoding(exe, 'mpeg4', requested, 'H.264 unavailable; MPEG-4 video will be used.')
    for fmt, codec in [('webm', 'libvpx-vp9'), ('mkv', 'ffv1'), ('mkv', 'mpeg4')]:
        if codec in encoders:
            return Encoding(exe, codec, fmt, f'{requested.upper()} encoder unavailable; saving {fmt.upper()} instead.')
    raise RuntimeError('FFmpeg has no supported video encoder. Install a full FFmpeg build.')


def video_command(encoding, width, height, fps, bitrate, output):
    args = [encoding.executable, '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s:v', f'{width}x{height}',
            '-framerate', str(fps), '-i', 'pipe:0', '-an', '-c:v', encoding.codec]
    if encoding.codec == 'libx264':
        args += ['-preset', 'veryfast', '-b:v', f'{bitrate}k', '-maxrate', f'{round(bitrate * 1.5)}k',
                 '-bufsize', f'{bitrate * 2}k']
    elif encoding.codec.startswith('libvpx'):
        args += ['-deadline', 'realtime', '-cpu-used', '6', '-b:v', f'{bitrate}k']
    elif encoding.codec != 'ffv1':
        args += ['-b:v', f'{bitrate}k']
    args += ['-threads', '4', '-pix_fmt', 'yuv420p']
    if encoding.format == 'mp4':
        args += ['-movflags', '+faststart']
    return args + [str(output)]


def mux(encoding, video, tracks, final):
    args = [encoding.executable, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video)]
    for track in tracks:
        args += ['-i', str(track)]
    args += ['-map', '0:v:0', '-c:v', 'copy']
    if len(tracks) == 1:
        args += ['-map', '1:a:0']
    elif tracks:
        inputs = ''.join(f'[{i}:a]' for i in range(1, len(tracks) + 1))
        args += ['-filter_complex', f'{inputs}amix=inputs={len(tracks)}:duration=longest:normalize=0,alimiter=limit=0.95:latency=1[mix]',
                 '-map', '[mix]']
    if tracks:
        args += ['-c:a', 'libopus' if encoding.format == 'webm' else 'aac', '-b:a', '256k', '-shortest']
    if encoding.format == 'mp4':
        args += ['-movflags', '+faststart']
    args += [str(final)]
    run_checked(args, timeout=600)
