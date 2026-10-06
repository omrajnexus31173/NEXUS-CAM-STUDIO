"""Run with Windows Python 3.11, optionally under Wine. Real raw-video/audio encoding.
Audio data here is an explicit sine-wave fixture, not a physical microphone test.
"""
import json
import sys
import tempfile
from pathlib import Path
import wave
import numpy as np
import av
from app.recorder.ffmpeg import Encoding, run_checked, video_command, mux, CREATE_FLAGS
import subprocess


def main():
    executable = Path(sys.argv[1])
    folder = Path(sys.argv[2])
    folder.mkdir(parents=True, exist_ok=True)
    checks = []
    for fmt, codec in [('mp4', 'libx264'), ('mkv', 'libx264'), ('webm', 'libvpx-vp9')]:
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            config = Encoding(str(executable), codec, fmt)
            raw = np.full((480, 854, 4), (100, 65, 40, 255), dtype=np.uint8)
            raw[320:470, 650:800] = (30, 220, 25, 255)
            video = temp / f'video.{fmt}'
            encoded = subprocess.run(video_command(config, 854, 480, 30, 1400, video),
                input=raw.tobytes() * 30, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=CREATE_FLAGS, timeout=45)
            if encoded.returncode:
                raise RuntimeError(encoded.stderr.decode(errors='replace'))
            tracks = []
            for kind, freq in [('mic', 220), ('system', 330)]:
                track = temp / f'{kind}.wav'
                data = (np.sin(2 * np.pi * freq * np.arange(48000) / 48000) * 5000).astype('<i2')
                with wave.open(str(track), 'wb') as w:
                    w.setnchannels(2)
                    w.setsampwidth(2)
                    w.setframerate(48000)
                    w.writeframes(np.column_stack([data, data]).tobytes())
                tracks.append(track)
            output = folder / f'windows-encoder-tested.{fmt}'
            mux(config, video, tracks, output)
            run_checked([str(executable), '-v', 'error', '-i', str(output), '-f', 'null', '-'])
            with av.open(str(output)) as c:
                assert len(c.streams.video) == 1 and len(c.streams.audio) == 1
                frame = next(c.decode(video=0)).to_ndarray(format='bgr24')
                assert frame[390, 720, 1] > 200
                checks.append(dict(format=fmt, video_codec=c.streams.video[0].codec_context.name,
                    audio_codec=c.streams.audio[0].codec_context.name, size=output.stat().st_size,
                    result='PASS', note='Real encode/mix/mux/decode; synthetic PCM fixture, not hardware audio.'))
    report = folder / 'windows-encoder-results.json'
    report.write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(report.read_text())


if __name__ == '__main__':
    main()
