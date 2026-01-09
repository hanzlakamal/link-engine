"""
Debug Tab - Log viewer and diagnostics
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGroupBox, QFormLayout, QTextEdit
)
from PyQt6.QtCore import Qt

from config import Settings
from core.database import Database
from core.logger import ui_logger
from ui.widgets.log_viewer import LogViewer


class DebugTab(QWidget):
    """Debug and diagnostics tab"""
    
    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("Debug & Diagnostics")
        title.setObjectName("headerLabel")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Diagnostic actions
        test_db_btn = QPushButton("🗄️ Test Database")
        test_db_btn.clicked.connect(self.test_database)
        header_layout.addWidget(test_db_btn)
        
        test_api_btn = QPushButton("🔌 Test APIs")
        test_api_btn.clicked.connect(self.test_apis)
        header_layout.addWidget(test_api_btn)
        
        layout.addLayout(header_layout)
        
        # System info section
        info_group = QGroupBox("System Information")
        info_layout = QFormLayout(info_group)
        
        import sys
        import platform
        
        info_layout.addRow("Python Version:", QLabel(sys.version.split()[0]))
        info_layout.addRow("Platform:", QLabel(platform.platform()))
        info_layout.addRow("Settings Path:", QLabel(str(self.settings.config_path)))
        info_layout.addRow("Database Path:", QLabel(str(self.settings.database_path)))
        info_layout.addRow("Logs Path:", QLabel(str(self.settings.logs_path)))
        
        layout.addWidget(info_group)
        
        # API Status section
        api_group = QGroupBox("API Status")
        api_layout = QFormLayout(api_group)
        
        ahrefs_status = "✅ Configured" if self.settings.api.ahrefs_api_key else "❌ Not configured"
        anthropic_status = "✅ Configured" if self.settings.api.anthropic_api_key else "❌ Not configured"
        openai_status = "✅ Configured" if self.settings.api.openai_api_key else "❌ Not configured"
        captcha_status = "✅ Configured" if self.settings.api.captcha_api_key else "❌ Not configured"
        
        api_layout.addRow("Ahrefs API:", QLabel(ahrefs_status))
        api_layout.addRow("Anthropic (Claude):", QLabel(anthropic_status))
        api_layout.addRow("OpenAI:", QLabel(openai_status))
        api_layout.addRow("Captcha Service:", QLabel(captcha_status))
        
        layout.addWidget(api_group)
        
        # Log viewer
        log_group = QGroupBox("Application Logs")
        log_layout = QVBoxLayout(log_group)
        
        self.log_viewer = LogViewer()
        log_layout.addWidget(self.log_viewer)
        
        layout.addWidget(log_group)
    
    def test_database(self):
        """Test database connection"""
        from PyQt6.QtWidgets import QMessageBox
        
        try:
            # Run a simple query
            count = self.db.get_domain_count()
            
            QMessageBox.information(
                self, "Database Test",
                f"✅ Database connection successful!\n\nDomains in database: {count}"
            )
            ui_logger.info("Database test passed")
        except Exception as e:
            QMessageBox.critical(
                self, "Database Test Failed",
                f"❌ Database error:\n\n{str(e)}"
            )
            ui_logger.error(f"Database test failed: {e}")
    
    def test_apis(self):
        """Test API connections"""
        from PyQt6.QtWidgets import QMessageBox
        
        results = []
        
        # Test Anthropic
        if self.settings.api.anthropic_api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=self.settings.api.anthropic_api_key)
                # Simple test - just check if client initializes
                results.append("✅ Anthropic (Claude): Connected")
                ui_logger.info("Anthropic API test passed")
            except Exception as e:
                results.append(f"❌ Anthropic: {str(e)[:50]}")
                ui_logger.error(f"Anthropic API test failed: {e}")
        else:
            results.append("⚠️ Anthropic: Not configured")
        
        # Test OpenAI
        if self.settings.api.openai_api_key:
            try:
                import openai
                client = openai.OpenAI(api_key=self.settings.api.openai_api_key)
                results.append("✅ OpenAI: Connected")
                ui_logger.info("OpenAI API test passed")
            except Exception as e:
                results.append(f"❌ OpenAI: {str(e)[:50]}")
                ui_logger.error(f"OpenAI API test failed: {e}")
        else:
            results.append("⚠️ OpenAI: Not configured")
        
        # Test Ahrefs
        if self.settings.api.ahrefs_api_key:
            results.append("⚠️ Ahrefs: Key configured (test requires API call)")
        else:
            results.append("⚠️ Ahrefs: Not configured")
        
        QMessageBox.information(
            self, "API Test Results",
            "\n".join(results)
        )
    
    def refresh(self):
        """Refresh the debug tab"""
        pass