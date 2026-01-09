"""
Backlink Strategy Engine - Main Entry Point
"""
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

from ui.main_window import MainWindow
from core.database import Database
from core.logger import setup_logger, app_logger
from config import Settings


def main():
    # Initialize logging first
    setup_logger()
    app_logger.info("=" * 60)
    app_logger.info("Backlink Strategy Engine Starting...")
    app_logger.info("=" * 60)
    
    # Load settings
    settings = Settings()
    app_logger.info(f"Settings loaded from: {settings.config_path}")
    
    # Initialize database
    db = Database(settings.database_path)
    db.connect()
    db.initialize()
    app_logger.info(f"Database initialized: {settings.database_path}")

    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # Create Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("Backlink Strategy Engine")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("YourCompany")
    
    # Set application-wide font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Create and show main window
    window = MainWindow(settings, db)
    window.show()
    
    app_logger.info("Application window opened")
    
    # Run event loop
    exit_code = app.exec()
    
    # Cleanup
    db.close()
    app_logger.info("Application closed")
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()