"""
Modern Dark Theme Stylesheet
"""

DARK_THEME = """
/* ==================== GLOBAL ==================== */
QMainWindow, QWidget {
    background-color: #1a1a2e;
    color: #eaeaea;
    font-family: "Segoe UI", Arial, sans-serif;
}

/* ==================== TAB WIDGET ==================== */
QTabWidget::pane {
    border: 1px solid #2d2d44;
    background-color: #16213e;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #1a1a2e;
    color: #8892b0;
    padding: 12px 24px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #16213e;
    color: #64ffda;
    border-bottom: 2px solid #64ffda;
}

QTabBar::tab:hover:!selected {
    background-color: #2d2d44;
    color: #ccd6f6;
}

/* ==================== BUTTONS ==================== */
QPushButton {
    background-color: #0f3460;
    color: #eaeaea;
    border: none;
    padding: 10px 20px;
    border-radius: 6px;
    font-weight: 500;
    min-width: 100px;
}

QPushButton:hover {
    background-color: #1a4f7a;
}

QPushButton:pressed {
    background-color: #0a2540;
}

QPushButton:disabled {
    background-color: #2d2d44;
    color: #5a5a7a;
}

QPushButton#primaryButton {
    background-color: #e94560;
    color: white;
}

QPushButton#primaryButton:hover {
    background-color: #ff6b6b;
}

QPushButton#successButton {
    background-color: #00b894;
    color: white;
}

QPushButton#successButton:hover {
    background-color: #00d9a5;
}

QPushButton#warningButton {
    background-color: #f39c12;
    color: white;
}

QPushButton#dangerButton {
    background-color: #e74c3c;
    color: white;
}

/* ==================== INPUTS ==================== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #0f3460;
    border: 1px solid #2d2d44;
    border-radius: 6px;
    padding: 8px 12px;
    color: #eaeaea;
    selection-background-color: #e94560;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #64ffda;
}

QLineEdit:disabled, QTextEdit:disabled {
    background-color: #1a1a2e;
    color: #5a5a7a;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #8892b0;
    margin-right: 10px;
}

QComboBox QAbstractItemView {
    background-color: #16213e;
    border: 1px solid #2d2d44;
    selection-background-color: #0f3460;
}

/* ==================== TABLES ==================== */
QTableWidget, QTableView {
    background-color: #16213e;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    gridline-color: #2d2d44;
}

QTableWidget::item, QTableView::item {
    padding: 8px;
    border-bottom: 1px solid #2d2d44;
}

QTableWidget::item:selected, QTableView::item:selected {
    background-color: #0f3460;
    color: #64ffda;
}

QTableWidget::item:hover, QTableView::item:hover {
    background-color: #1a4f7a;
}

QHeaderView::section {
    background-color: #1a1a2e;
    color: #8892b0;
    padding: 12px;
    border: none;
    border-bottom: 2px solid #2d2d44;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
}

/* ==================== SCROLLBARS ==================== */
QScrollBar:vertical {
    background-color: #1a1a2e;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background-color: #2d2d44;
    border-radius: 6px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3d3d5c;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #1a1a2e;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background-color: #2d2d44;
    border-radius: 6px;
    min-width: 30px;
}

/* ==================== PROGRESS BAR ==================== */
QProgressBar {
    background-color: #0f3460;
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #64ffda;
    border-radius: 6px;
}

/* ==================== LABELS ==================== */
QLabel {
    color: #ccd6f6;
}

QLabel#headerLabel {
    font-size: 24px;
    font-weight: bold;
    color: #ccd6f6;
}

QLabel#subHeaderLabel {
    font-size: 14px;
    color: #8892b0;
}

QLabel#statValue {
    font-size: 32px;
    font-weight: bold;
    color: #64ffda;
}

QLabel#statLabel {
    font-size: 12px;
    color: #8892b0;
    text-transform: uppercase;
}

/* ==================== FRAMES & GROUPS ==================== */
QFrame#card {
    background-color: #16213e;
    border: 1px solid #2d2d44;
    border-radius: 12px;
    padding: 16px;
}

QGroupBox {
    background-color: #16213e;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 16px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #64ffda;
}

/* ==================== SPLITTERS ==================== */
QSplitter::handle {
    background-color: #2d2d44;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ==================== DIALOGS ==================== */
QDialog {
    background-color: #1a1a2e;
}

QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* ==================== MENUS ==================== */
QMenuBar {
    background-color: #1a1a2e;
    border-bottom: 1px solid #2d2d44;
}

QMenuBar::item {
    padding: 8px 16px;
}

QMenuBar::item:selected {
    background-color: #0f3460;
}

QMenu {
    background-color: #16213e;
    border: 1px solid #2d2d44;
    border-radius: 8px;
    padding: 8px;
}

QMenu::item {
    padding: 8px 32px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #0f3460;
}

QMenu::separator {
    height: 1px;
    background-color: #2d2d44;
    margin: 8px 0;
}

/* ==================== STATUS BAR ==================== */
QStatusBar {
    background-color: #16213e;
    border-top: 1px solid #2d2d44;
    color: #8892b0;
}

QStatusBar::item {
    border: none;
}

/* ==================== TOOLTIPS ==================== */
QToolTip {
    background-color: #16213e;
    color: #eaeaea;
    border: 1px solid #2d2d44;
    border-radius: 4px;
    padding: 8px;
}

/* ==================== CHECKBOXES & RADIO ==================== */
QCheckBox, QRadioButton {
    spacing: 8px;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #2d2d44;
    border-radius: 4px;
    background-color: #0f3460;
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #64ffda;
    border-color: #64ffda;
}

QRadioButton::indicator {
    border-radius: 9px;
}

/* ==================== SLIDERS ==================== */
QSlider::groove:horizontal {
    height: 6px;
    background-color: #0f3460;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background-color: #64ffda;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background-color: #64ffda;
    border-radius: 3px;
}
"""

LIGHT_THEME = """
/* Light theme variant - can be implemented similarly */
QMainWindow, QWidget {
    background-color: #f5f5f5;
    color: #333333;
}
/* ... */
"""


def get_theme(theme_name: str = "dark") -> str:
    """Get stylesheet for specified theme"""
    if theme_name == "light":
        return LIGHT_THEME
    return DARK_THEME