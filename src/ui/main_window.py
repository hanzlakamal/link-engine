"""
Main Application Window
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStatusBar, QLabel, QMenuBar, QMenu,
    QToolBar, QMessageBox, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon

from config import Settings
from core.database import Database
from core.logger import app_logger, ui_logger

from ui.styles import get_theme
from ui.tabs.dashboard_tab import DashboardTab
from ui.tabs.discovery_tab import DiscoveryTab
from ui.tabs.analysis_tab import AnalysisTab
from ui.tabs.outreach_tab import OutreachTab
from ui.tabs.tracking_tab import TrackingTab
from ui.tabs.debug_tab import DebugTab
from ui.dialogs.settings_dialog import SettingsDialog
from ui.tabs.journalists_tab import JournalistsTab

class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self, settings: Settings, database: Database):
        super().__init__()
        
        self.settings = settings
        self.db = database
        
        self.setWindowTitle("Backlink Strategy Engine")
        self.setMinimumSize(1400, 900)
        
        # Apply theme
        self.setStyleSheet(get_theme(settings.general.theme))
        
        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        self.setup_timers()
        
        ui_logger.info("Main window initialized")
    
    def setup_ui(self):
        """Setup the main UI"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Main content with splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Tab widget (main content)
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)
        
        # Create tabs
        self.dashboard_tab = DashboardTab(self.settings, self.db)
        self.discovery_tab = DiscoveryTab(self.settings, self.db)
        self.analysis_tab = AnalysisTab(self.settings, self.db)
        self.outreach_tab = OutreachTab(self.settings, self.db)
        self.tracking_tab = TrackingTab(self.settings, self.db)
        self.debug_tab = DebugTab(self.settings, self.db)
        self.journalists_tab = JournalistsTab(self.settings, self.db)
        
        # Add tabs
        self.tab_widget.addTab(self.dashboard_tab, "📊 Dashboard")
        self.tab_widget.addTab(self.discovery_tab, "🔍 Discovery")
        self.tab_widget.addTab(self.analysis_tab, "🔬 Analysis")
        self.tab_widget.addTab(self.outreach_tab, "📧 Outreach")
        self.tab_widget.addTab(self.journalists_tab, "📰 Journalists")
        self.tab_widget.addTab(self.tracking_tab, "🔗 Tracking")
        self.tab_widget.addTab(self.debug_tab, "🐛 Debug Log")

        
        splitter.addWidget(self.tab_widget)
        
        main_layout.addWidget(splitter)
        
        # Connect tab signals
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
    
    def create_header(self) -> QFrame:
        """Create header bar"""
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet("""
            QFrame {
                background-color: #16213e;
                border-bottom: 1px solid #2d2d44;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        
        # Logo/Title
        title = QLabel("⚡ Backlink Strategy Engine")
        title.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #64ffda;
        """)
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Connection status indicators
        self.ahrefs_status = self.create_status_indicator("Ahrefs", False)
        self.ai_status = self.create_status_indicator("AI", False)
        
        layout.addWidget(self.ahrefs_status)
        layout.addWidget(self.ai_status)
        
        return header
    
    def create_status_indicator(self, name: str, connected: bool) -> QFrame:
        """Create a connection status indicator"""
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        
        # Status dot
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {'#00b894' if connected else '#e74c3c'}; font-size: 10px;")
        dot.setObjectName(f"{name.lower()}_dot")
        
        # Label
        label = QLabel(name)
        label.setStyleSheet("color: #8892b0; font-size: 12px;")
        
        layout.addWidget(dot)
        layout.addWidget(label)
        
        return frame
    
    def setup_menu(self):
        """Setup menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        import_action = QAction("📥 Import Domains...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self.show_import_dialog)
        file_menu.addAction(import_action)
        
        export_action = QAction("📤 Export Data...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_data)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        settings_action = QAction("⚙️ Settings...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        analyze_action = QAction("🔬 Analyze Selected", self)
        analyze_action.setShortcut("Ctrl+A")
        analyze_action.triggered.connect(self.analyze_selected)
        tools_menu.addAction(analyze_action)
        
        enrich_action = QAction("📊 Enrich with Ahrefs", self)
        enrich_action.triggered.connect(self.enrich_selected)
        tools_menu.addAction(enrich_action)
        
        tools_menu.addSeparator()
        
        check_links_action = QAction("🔗 Check All Links", self)
        check_links_action.triggered.connect(self.check_all_links)
        tools_menu.addAction(check_links_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        docs_action = QAction("📖 Documentation", self)
        docs_action.triggered.connect(self.show_docs)
        help_menu.addAction(docs_action)
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_status_bar(self):
        """Setup status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Permanent widgets
        self.domain_count_label = QLabel("Domains: 0")
        self.status_bar.addPermanentWidget(self.domain_count_label)
        
        self.link_count_label = QLabel("Links: 0")
        self.status_bar.addPermanentWidget(self.link_count_label)
        
        self.status_bar.showMessage("Ready")
    
    def setup_timers(self):
        """Setup periodic update timers"""
        # Update stats every 30 seconds
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(30000)
        
        # Initial update
        self.update_stats()
        self.check_api_connections()
    
    def update_stats(self):
        """Update status bar statistics"""
        try:
            stats = self.db.get_domain_stats()
            self.domain_count_label.setText(f"Domains: {stats['total']}")
            
            link_stats = self.db.get_backlink_stats()
            self.link_count_label.setText(f"Links: {link_stats['total_live']}")
        except Exception as e:
            app_logger.error(f"Failed to update stats: {e}")
    
    def check_api_connections(self):
        """Check API connection status"""
        # Check Ahrefs
        ahrefs_connected = bool(self.settings.api.ahrefs_api_key)
        dot = self.ahrefs_status.findChild(QLabel, "ahrefs_dot")
        if dot:
            dot.setStyleSheet(f"color: {'#00b894' if ahrefs_connected else '#e74c3c'}; font-size: 10px;")
        
        # Check AI
        ai_connected = bool(self.settings.api.anthropic_api_key or self.settings.api.openai_api_key)
        dot = self.ai_status.findChild(QLabel, "ai_dot")
        if dot:
            dot.setStyleSheet(f"color: {'#00b894' if ai_connected else '#e74c3c'}; font-size: 10px;")
    
    def on_tab_changed(self, index: int):
        """Handle tab change"""
        tab_name = self.tab_widget.tabText(index)
        ui_logger.debug(f"Switched to tab: {tab_name}")
        
        # Refresh tab data
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'refresh'):
            current_tab.refresh()
    
    # ==================== ACTIONS ====================
    
    def show_import_dialog(self):
        """Show domain import dialog"""
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(self.db, self)
        if dialog.exec():
            self.discovery_tab.refresh()
            self.dashboard_tab.refresh()
            self.update_stats()
    
    def show_settings(self):
        """Show settings dialog"""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            # Apply new settings
            self.setStyleSheet(get_theme(self.settings.general.theme))
            self.check_api_connections()
            self.settings.save()
            app_logger.info("Settings updated")
    
    def export_data(self):
        """Export data to CSV"""
        from PyQt6.QtWidgets import QFileDialog
        import csv
        from datetime import datetime
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Domains",
            f"domains_export_{datetime.now().strftime('%Y%m%d')}.csv",
            "CSV Files (*.csv)"
        )
        
        if filename:
            domains = self.db.get_all_domains()
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Domain', 'DR', 'Traffic', 'Score', 'Status', 'Niche'])
                
                for d in domains:
                    writer.writerow([d.domain, d.dr, d.traffic, d.quality_score, d.status, d.niche])
            
            self.status_bar.showMessage(f"Exported {len(domains)} domains to {filename}")
            app_logger.info(f"Exported {len(domains)} domains")
    
    def analyze_selected(self):
        """Analyze selected domains"""
        self.tab_widget.setCurrentWidget(self.analysis_tab)
        self.analysis_tab.start_analysis()
    
    def enrich_selected(self):
        """Enrich selected domains with Ahrefs"""
        if not self.settings.api.ahrefs_api_key:
            QMessageBox.warning(self, "API Key Required", 
                              "Please configure your Ahrefs API key in Settings.")
            return
        
        self.discovery_tab.enrich_domains()
    
    def check_all_links(self):
        """Check all backlinks"""
        self.tab_widget.setCurrentWidget(self.tracking_tab)
        self.tracking_tab.check_all_links()
    
    def show_docs(self):
        """Show documentation"""
        import webbrowser
        webbrowser.open("https://github.com/your-repo/backlink-engine/wiki")
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About Backlink Strategy Engine",
            """<h2>Backlink Strategy Engine</h2>
            <p>Version 1.0.0</p>
            <p>An intelligent link building automation platform.</p>
            <p>Built with Python, PyQt6, and AI.</p>
            """
        )
    
    def closeEvent(self, event):
        """Handle window close"""
        reply = QMessageBox.question(
            self, "Confirm Exit",
            "Are you sure you want to exit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            app_logger.info("Application closing...")
            event.accept()
        else:
            event.ignore()