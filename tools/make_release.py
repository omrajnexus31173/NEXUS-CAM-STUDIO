"""Package the real Windows EXE, complete source/assets, licenses and test report.
Never includes user settings, recordings, certificates, private keys or dependencies.
"""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', 'node_modules', '__pycache__', '.pytest_cache', '.git', 'build', 'dist', '.cache'}


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    exe = ROOT / 'dist' / 'NexusCamStudio.exe'
    if not exe.is_file():
        raise SystemExit('No real EXE exists. Build on Windows using PyInstaller first.')
    if exe.open('rb').read(2) != b'MZ':
        raise SystemExit('Refusing to label a non-Windows binary as a Windows executable.')
    (ROOT / 'SHA256SUMS.txt').write_text(checksum(exe) + '  dist/NexusCamStudio.exe\n', encoding='ascii')
    release = ROOT.parent / 'NexusCamStudio-Windows-v1.1.zip'
    files = []
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(p in EXCLUDED for p in rel.parts):
            continue
        if path.suffix.lower() in ('.zip', '.pem', '.crt', '.cer', '.key', '.log', '.pyc'):
            continue
        if rel.parts[0] == 'output' and path.name != '.gitkeep':
            continue
        files.append((path, str(Path('NexusCamStudio') / rel)))
    files.append((exe, 'NexusCamStudio/dist/NexusCamStudio.exe'))
    with ZipFile(release, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in sorted(files, key=lambda v: v[1]):
            archive.write(path, name)
    bad = ZipFile(release).testzip()
    if bad:
        raise SystemExit('ZIP integrity failed at ' + bad)
    (ROOT.parent / 'NexusCamStudio-Windows-v1.1.sha256').write_text(checksum(release) + '  NexusCamStudio-Windows-v1.1.zip\n', encoding='ascii')
    print(f'Windows EXE: {exe} ({exe.stat().st_size:,} bytes)')
    print(f'Windows ZIP: {release} ({release.stat().st_size:,} bytes)')
    print(f'ZIP SHA256: {checksum(release)}')


if __name__ == '__main__':
    main()
