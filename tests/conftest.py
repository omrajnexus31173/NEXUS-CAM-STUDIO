import os
import pytest
import cv2

cv2.setNumThreads(2)


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch, qapp):
    monkeypatch.setenv('NEXUS_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('NEXUS_OUTPUT_DIR', str(tmp_path / 'videos'))
    qapp.setQuitOnLastWindowClosed(False)
    from app.ui.theme import STYLE
    qapp.setStyle('Fusion')
    qapp.setStyleSheet(STYLE)
