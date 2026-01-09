"""
Progress Widget - Enhanced progress display with details
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QProgressBar, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal


class ProgressWidget(QFrame):
    """Enhanced progress display widget"""
    
    cancelled = pyqtSignal()
    paused = pyqtSignal()
    resumed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._is_paused = False
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        
        # Header
        header_layout = QHBoxLayout()
        
        self.title_label = QLabel("Processing...")
        self.title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.title_label)
        
        header_layout.addStretch()
        
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: #8892b0;")
        header_layout.addWidget(self.eta_label)
        
        layout.addLayout(header_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(24)
        layout.addWidget(self.progress_bar)
        
        # Status
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("Initializing...")
        self.status_label.setStyleSheet("color: #8892b0;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        self.count_label = QLabel("0 / 0")
        status_layout.addWidget(self.count_label)
        
        layout.addLayout(status_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.pause_btn = QPushButton("⏸️ Pause")
        self.pause_btn.setMaximumWidth(100)
        self.pause_btn.clicked.connect(self.toggle_pause)
        button_layout.addWidget(self.pause_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMaximumWidth(100)
        self.cancel_btn.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def set_title(self, title: str):
        """Set the progress title"""
        self.title_label.setText(title)
    
    def set_progress(self, current: int, total: int, message: str = ""):
        """Update progress"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        
        if total > 0:
            percentage = (current / total) * 100
            self.progress_bar.setFormat(f"{percentage:.1f}%")
        
        self.count_label.setText(f"{current} / {total}")
        
        if message:
            self.status_label.setText(message)
    
    def set_status(self, status: str):
        """Set status message"""
        self.status_label.setText(status)
    
    def set_eta(self, seconds: int):
        """Set estimated time remaining"""
        if seconds <= 0:
            self.eta_label.setText("")
            return
        
        if seconds < 60:
            self.eta_label.setText(f"ETA: {seconds}s")
        elif seconds < 3600:
            minutes = seconds // 60
            self.eta_label.setText(f"ETA: {minutes}m")
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            self.eta_label.setText(f"ETA: {hours}h {minutes}m")
    
    def toggle_pause(self):
        """Toggle pause state"""
        self._is_paused = not self._is_paused
        
        if self._is_paused:
            self.pause_btn.setText("▶️ Resume")
            self.paused.emit()
        else:
            self.pause_btn.setText("⏸️ Pause")
            self.resumed.emit()
    
    def on_cancel(self):
        """Handle cancel"""
        self.cancelled.emit()
    
    def reset(self):
        """Reset the widget"""
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.status_label.setText("Ready")
        self.count_label.setText("0 / 0")
        self.eta_label.setText("")
        self._is_paused = False
        self.pause_btn.setText("⏸️ Pause")
    
    def set_completed(self, success: bool = True):
        """Mark as completed"""
        self.progress_bar.setValue(self.progress_bar.maximum())
        
        if success:
            self.status_label.setText("✅ Completed")
            self.status_label.setStyleSheet("color: #00b894;")
        else:
            self.status_label.setText("❌ Failed")
            self.status_label.setStyleSheet("color: #e74c3c;")
        
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setText("Close")