"""
Real-time Log Viewer Widget
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
    QPushButton, QComboBox, QLineEdit, QLabel, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor

from core.logger import log_handler, LogEntry, LogLevel


class LogViewer(QWidget):
    """Widget for viewing and filtering logs in real-time"""
    
    LEVEL_COLORS = {
        LogLevel.DEBUG: "#8892b0",
        LogLevel.INFO: "#64ffda",
        LogLevel.WARNING: "#f39c12",
        LogLevel.ERROR: "#e74c3c",
        LogLevel.CRITICAL: "#ff0000",
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto_scroll = True
        self.setup_ui()
        self.connect_signals()
        self.load_existing_logs()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Controls bar
        controls = QHBoxLayout()
        
        # Level filter
        controls.addWidget(QLabel("Level:"))
        self.level_filter = QComboBox()
        self.level_filter.addItem("All Levels", None)
        for level in LogLevel:
            self.level_filter.addItem(level.value, level)
        self.level_filter.currentIndexChanged.connect(self.apply_filters)
        controls.addWidget(self.level_filter)
        
        # Module filter
        controls.addWidget(QLabel("Module:"))
        self.module_filter = QLineEdit()
        self.module_filter.setPlaceholderText("Filter by module...")
        self.module_filter.setMaximumWidth(150)
        self.module_filter.textChanged.connect(self.apply_filters)
        controls.addWidget(self.module_filter)
        
        # Search
        controls.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search logs...")
        self.search_input.setMaximumWidth(200)
        self.search_input.textChanged.connect(self.apply_filters)
        controls.addWidget(self.search_input)
        
        controls.addStretch()
        
        # Auto-scroll toggle
        self.auto_scroll_check = QCheckBox("Auto-scroll")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.toggled.connect(self.toggle_auto_scroll)
        controls.addWidget(self.auto_scroll_check)
        
        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(80)
        clear_btn.clicked.connect(self.clear_logs)
        controls.addWidget(clear_btn)
        
        # Export button
        export_btn = QPushButton("Export")
        export_btn.setMaximumWidth(80)
        export_btn.clicked.connect(self.export_logs)
        controls.addWidget(export_btn)
        
        layout.addLayout(controls)
        
        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 10))
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                border: 1px solid #2d2d44;
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.log_display)
        
        # Status bar
        status_layout = QHBoxLayout()
        self.entry_count_label = QLabel("0 entries")
        status_layout.addWidget(self.entry_count_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)
    
    def connect_signals(self):
        """Connect to log handler signals"""
        log_handler.signals.new_log.connect(self.on_new_log)
    
    def load_existing_logs(self):
        """Load existing log entries"""
        for entry in log_handler.entries[-500:]:  # Last 500
            self.append_log_entry(entry)
        self.update_count()
    
    @pyqtSlot(object)
    def on_new_log(self, entry: LogEntry):
        """Handle new log entry"""
        if self.passes_filter(entry):
            self.append_log_entry(entry)
            self.update_count()
    
    def append_log_entry(self, entry: LogEntry):
        """Append a log entry to the display"""
        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # Format based on level
        format = QTextCharFormat()
        color = self.LEVEL_COLORS.get(entry.level, "#ffffff")
        format.setForeground(QColor(color))
        
        # Timestamp
        ts_format = QTextCharFormat()
        ts_format.setForeground(QColor("#5a5a7a"))
        cursor.insertText(f"[{entry.timestamp.strftime('%H:%M:%S.%f')[:-3]}] ", ts_format)
        
        # Level
        cursor.insertText(f"[{entry.level.value:8}] ", format)
        
        # Module
        module_format = QTextCharFormat()
        module_format.setForeground(QColor("#8892b0"))
        cursor.insertText(f"[{entry.module:15}] ", module_format)
        
        # Message
        msg_format = QTextCharFormat()
        msg_format.setForeground(QColor("#eaeaea"))
        cursor.insertText(f"{entry.message}\n", msg_format)
        
        if self.auto_scroll:
            self.log_display.setTextCursor(cursor)
            self.log_display.ensureCursorVisible()
    
    def passes_filter(self, entry: LogEntry) -> bool:
        """Check if entry passes current filters"""
        # Level filter
        level = self.level_filter.currentData()
        if level and entry.level != level:
            return False
        
        # Module filter
        module = self.module_filter.text().strip().lower()
        if module and module not in entry.module.lower():
            return False
        
        # Search filter
        search = self.search_input.text().strip().lower()
        if search and search not in entry.message.lower():
            return False
        
        return True
    
    def apply_filters(self):
        """Re-apply filters to all logs"""
        self.log_display.clear()
        
        for entry in log_handler.entries:
            if self.passes_filter(entry):
                self.append_log_entry(entry)
        
        self.update_count()
    
    def update_count(self):
        """Update entry count label"""
        # Count visible entries
        text = self.log_display.toPlainText()
        count = text.count('\n')
        self.entry_count_label.setText(f"{count} entries shown / {len(log_handler.entries)} total")
    
    def toggle_auto_scroll(self, enabled: bool):
        """Toggle auto-scroll"""
        self.auto_scroll = enabled
    
    def clear_logs(self):
        """Clear the log display"""
        self.log_display.clear()
        log_handler.clear()
        self.update_count()
    
    def export_logs(self):
        """Export logs to file"""
        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Logs", 
            f"backlink_engine_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if filename:
            with open(filename, 'w') as f:
                f.write(self.log_display.toPlainText())