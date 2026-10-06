"""Nexus Cam Studio native entry point (Python 3.11 / Windows 10–11)."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys


def main():
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Nexus.CamStudio.1')
        except Exception:
            pass
    from PySide6.QtWidgets import QApplication
    from app.utils.paths import data_dir
    handler = RotatingFileHandler(data_dir() / 'nexus.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    import cv2
    cv2.setNumThreads(2)
    from app.ui.theme import STYLE
    app = QApplication(sys.argv)
    app.setApplicationName('Nexus Cam Studio')
    app.setOrganizationName('NexusCamStudio')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-welcome', action='store_true', help='Testing: skip the first-run dialog')
    parser.add_argument('--no-auto-capture', action='store_true', help='Do not start screen capture on launch')
    parser.add_argument('--smoke-seconds', type=float, default=0., help='Testing: close after this many seconds')
    parser.add_argument('--smoke-snapshot', default='', help='Testing: save a real UI screenshot before exit')
    parser.add_argument('--verify-output', default='', help='Contributors: run actual capture/export checks and write JSON')
    parser.add_argument('--verify-phone-wait', type=float, default=0., help='Contributors: seconds to wait for an external WebRTC sender')
    parser.add_argument('--verify-audio-tone', type=float, default=0., help='Contributors: expected Hz of an explicit external tone fixture; never generates audio')
    args = parser.parse_args()
    from app.ui.main_window import MainWindow
    window = MainWindow(args.skip_welcome or bool(args.verify_output), not args.no_auto_capture)
    def exception_hook(kind, value, traceback):
        logging.critical('Unhandled application error', exc_info=(kind, value, traceback))
        window.message(f'Application error: {value}. See the local nexus.log for details.', True)
    sys.excepthook = exception_hook
    window.show()
    verifier = None
    if args.verify_output:
        from tools.runtime_verify import RuntimeVerifier
        verifier = RuntimeVerifier(window, args.verify_output, args.verify_phone_wait, args.verify_audio_tone)
    if args.smoke_seconds:
        from PySide6.QtCore import QTimer
        def finish():
            if args.smoke_snapshot:
                window.grab().save(args.smoke_snapshot)
            window.close()
        QTimer.singleShot(round(args.smoke_seconds * 1000), finish)
    result = app.exec()
    if verifier and verifier.report.get('state') != 'PASS_SOFTWARE_CHECKS':
        return 1
    return result


if __name__ == '__main__':
    raise SystemExit(main())
