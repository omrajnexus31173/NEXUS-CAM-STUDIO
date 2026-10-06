import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from app.utils.paths import data_dir, videos_dir


@dataclass
class Settings:
    output_folder: str = ''
    welcomed: bool = False
    start_minimized: bool = False
    remember_camera: bool = True
    camera_key: str = ''
    camera_enabled: bool = True
    microphone_key: str = ''
    system_device_key: str = ''
    mic_enabled: bool = False
    system_enabled: bool = False
    phone_mic_enabled: bool = False
    phone_mic_gain: int = 100
    mic_gain: int = 100
    system_gain: int = 80
    resolution: str = '1920x1080'
    fps: int = 30
    quality: str = 'High'
    bitrate_kbps: int = 0
    format: str = 'mp4'
    phone_port: int = 8765
    phone_auto_ip: bool = True
    phone_ip: str = ''
    overlay_shape: str = 'Circle'
    overlay_x: float = .82
    overlay_y: float = .70
    overlay_w: float = .15
    overlay_h: float = .2666667
    border_width: int = 4
    border_radius: int = 32
    border_color: str = '#8b8aff'
    shadow: bool = True
    opacity: int = 100
    mirror: bool = True
    background: str = 'Original'

    def normalize(self):
        if not self.output_folder:
            self.output_folder = str(videos_dir())
        if self.resolution not in ('1920x1080', '1280x720', '854x480'):
            self.resolution = '1920x1080'
        if self.fps not in (30, 60):
            self.fps = 30
        if self.format not in ('mp4', 'mkv', 'webm'):
            self.format = 'mp4'
        if self.quality not in ('Low', 'Medium', 'High'):
            self.quality = 'High'
        self.phone_port = max(1024, min(65534, int(self.phone_port)))
        for key in ('mic_gain', 'system_gain', 'phone_mic_gain', 'opacity'):
            setattr(self, key, max(0, min(100, int(getattr(self, key)))))
        for key in ('overlay_w', 'overlay_h'):
            setattr(self, key, max(.02, min(1., float(getattr(self, key)))))
        self.overlay_x = max(0., min(1. - self.overlay_w, float(self.overlay_x)))
        self.overlay_y = max(0., min(1. - self.overlay_h, float(self.overlay_y)))
        if self.overlay_shape not in ('Circle', 'Oval', 'Rectangle', 'Rounded Rectangle', 'Square'):
            self.overlay_shape = 'Circle'
        self.border_width = max(0, min(24, int(self.border_width)))
        self.border_radius = max(0, min(200, int(self.border_radius)))
        self.bitrate_kbps = max(0, min(50000, int(self.bitrate_kbps)))
        return self

    @property
    def dimensions(self):
        return tuple(map(int, self.resolution.split('x')))

    @property
    def bitrate(self):
        if self.bitrate_kbps:
            return self.bitrate_kbps
        w, h = self.dimensions
        base = {'Low': 2500, 'Medium': 5000, 'High': 8000}[self.quality]
        return max(700, round(base * w * h / (1920 * 1080) * (1.6 if self.fps == 60 else 1)))


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'settings.json'
        self.warning = ''

    def load(self):
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding='utf-8'))
                allowed = {f.name for f in fields(Settings)}
                return Settings(**{k: v for k, v in raw.items() if k in allowed}).normalize()
        except Exception as exc:
            logging.exception('Settings could not be read')
            self.warning = f'Previous settings could not be read; defaults were loaded. {exc}'
        return Settings().normalize()

    def save(self, settings):
        settings.normalize()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding='utf-8')
        os.replace(tmp, self.path)


class History:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / 'history.json'
        self.items = []
        self.warning = ''
        try:
            if self.path.exists():
                self.items = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(self.items, list):
                    raise ValueError('History must be a list')
        except Exception as exc:
            self.items = []
            self.warning = f'Recording history could not be read: {exc}'
            logging.exception('History could not be read')

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.items[:200], indent=2), encoding='utf-8')
        os.replace(tmp, self.path)

    def add(self, path, duration):
        from datetime import datetime
        path = Path(path).resolve()
        self.items.insert(0, dict(path=str(path), filename=path.name,
                                 date=datetime.now().isoformat(timespec='seconds'),
                                 duration=round(duration, 3), size=path.stat().st_size))
        self.save()

    def remove(self, path, delete_file=False):
        if delete_file:
            Path(path).unlink(missing_ok=True)
        self.items = [i for i in self.items if i['path'] != str(path)]
        self.save()
