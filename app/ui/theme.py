STYLE = '''
QWidget { color: #dce3f2; font-family: "Segoe UI", "DejaVu Sans"; font-size: 12px; }
QMainWindow, QDialog { background: #101622; }
QFrame#TopBar { background: #121a28; border-bottom: 1px solid #263147; }
QFrame#Sidebar, QFrame#Inspector { background: #141c2a; border: 1px solid #263147; border-radius: 12px; }
QFrame#ControlBar { background: #151e2e; border: 1px solid #2a3650; border-radius: 12px; }
QFrame#History { background: #131b29; border: 1px solid #263147; border-radius: 12px; }
QLabel#Title { font-size: 17px; font-weight: 800; letter-spacing: 1.7px; color: #f3f4ff; }
QLabel#Section { color: #8390aa; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; }
QLabel#Muted { color: #8594ae; }
QLabel#Heading { font-size: 21px; font-weight: 700; color: #f0f3ff; }
QLabel#Timer { font-family: "Consolas", "DejaVu Sans Mono"; font-size: 23px; font-weight: 600; color: #f1f3ff; }
QLabel#Status { color: #78d7ba; background: #1b2e31; padding: 7px 13px; border-radius: 10px; font-size: 10px; font-weight: 700; }
QPushButton { background: #212d43; border: 1px solid #34405a; border-radius: 7px; padding: 9px 13px; font-weight: 600; }
QPushButton:hover { background: #2d3c56; border-color: #676fa4; }
QPushButton:pressed { background: #172138; }
QPushButton:disabled { background: #1b2230; border-color: #273046; color: #596780; }
QPushButton#Primary { background: #8575ef; border: 1px solid #998bfa; color: #ffffff; }
QPushButton#Primary:hover { background: #9587fa; }
QPushButton#Primary:disabled { background: #383052; border-color: #453b64; color: #807499; }
QPushButton#Record { background: #ec657a; border-color: #f48a99; color: white; font-size: 12px; padding: 13px 26px; }
QPushButton#Record:hover { background: #f37c8e; }
QPushButton#Record:disabled { background: #492b38; border-color: #613043; color: #a47887; }
QPushButton#Ghost { background: transparent; border-color: #2c394f; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #0f1725; border: 1px solid #303d55; border-radius: 6px; padding: 7px 8px; selection-background-color: #7666d9; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #9282f4; }
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled { color: #58677d; background: #171e2c; }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox QAbstractItemView { background: #1b2639; selection-background-color: #514686; border: 1px solid #38445e; padding: 5px; }
QCheckBox { spacing: 8px; padding: 3px 0; }
QCheckBox::indicator { width: 16px; height: 16px; background: #0f1725; border: 1px solid #46526b; border-radius: 4px; }
QCheckBox::indicator:checked { background: #9687fc; border: 1px solid #b4aaff; }
QCheckBox:disabled { color: #617088; }
QSlider::groove:horizontal { height: 4px; background: #2a3650; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #9587f5; border-radius: 2px; }
QSlider::handle:horizontal { background: #b9afff; width: 12px; margin: -4px 0; border-radius: 6px; }
QProgressBar { border: none; background: #27334b; border-radius: 3px; height: 5px; }
QProgressBar::chunk { background: #6fdbb6; border-radius: 3px; }
QListWidget, QTreeWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 8px; border-radius: 6px; color: #aebbd1; }
QListWidget::item:selected { background: #2c2948; color: #e5dfff; }
QListWidget::item:hover { background: #1f2b40; }
QTreeWidget::item { padding: 7px; }
QHeaderView::section { background: #1d283c; color: #abb9d0; border: none; padding: 8px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #36425a; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QTabWidget::pane { border: 1px solid #2c3a50; border-radius: 7px; padding: 12px; }
QTabBar::tab { background: #171f2f; padding: 11px 15px; border: none; color: #94a2bb; }
QTabBar::tab:selected { background: #302b49; color: #c3b8ff; }
QGroupBox { border: 1px solid #2f3c55; border-radius: 8px; margin-top: 14px; padding: 15px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #b4a5fb; }
QToolTip { background: #253147; color: #eef1ff; border: 1px solid #586282; padding: 6px; }
'''
