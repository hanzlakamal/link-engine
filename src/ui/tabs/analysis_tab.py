"""
Analysis Tab - Website analysis and contact detection
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QHeaderView,
    QTextEdit, QSplitter, QProgressBar, QComboBox,
    QAbstractItemView, QGroupBox, QFormLayout, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSlot
from typing import Optional

from config import Settings
from core.database import Database, Domain
from core.logger import analysis_logger, ui_logger
from core.workers import DomainAnalysisWorker


class AnalysisTab(QWidget):
    """Website analysis tab"""
    
    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.current_worker: Optional[DomainAnalysisWorker] = None
        self.selected_domain: Optional[Domain] = None
        
        self.setup_ui()
        self.refresh()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("Website Analysis")
        title.setObjectName("headerLabel")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Analysis controls
        self.analyze_btn = QPushButton("🔬 Analyze Selected")
        self.analyze_btn.setObjectName("primaryButton")
        self.analyze_btn.clicked.connect(self.start_analysis)
        header_layout.addWidget(self.analyze_btn)
        
        self.analyze_all_btn = QPushButton("⚡ Analyze All Pending")
        self.analyze_all_btn.clicked.connect(self.analyze_all_pending)
        header_layout.addWidget(self.analyze_all_btn)
        
        layout.addLayout(header_layout)
        
        # Progress section
        self.progress_frame = QFrame()
        self.progress_frame.setObjectName("card")
        progress_layout = QVBoxLayout(self.progress_frame)
        
        progress_header = QHBoxLayout()
        self.progress_label = QLabel("Analysis Progress")
        progress_header.addWidget(self.progress_label)
        progress_header.addStretch()
        
        self.pause_btn = QPushButton("⏸️ Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.hide()
        progress_header.addWidget(self.pause_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_analysis)
        self.cancel_btn.hide()
        progress_header.addWidget(self.cancel_btn)
        
        progress_layout.addLayout(progress_header)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_frame.hide()
        layout.addWidget(self.progress_frame)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Domain list
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Filter for analysis
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Show:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Pending Analysis", "pending")
        self.status_filter.addItem("Analyzed", "analyzed")
        self.status_filter.addItem("All", None)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()
        left_layout.addLayout(filter_layout)
        
        # Domain table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Domain", "DR", "Status", "Last Analyzed"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 140)
        
        left_layout.addWidget(self.table)
        splitter.addWidget(left_panel)
        
        # Right: Analysis details
        right_panel = QScrollArea()
        right_panel.setWidgetResizable(True)
        right_panel.setFrameShape(QFrame.Shape.NoFrame)
        
        details_widget = QWidget()
        self.details_layout = QVBoxLayout(details_widget)
        self.details_layout.setSpacing(16)
        
        # Domain info
        self.domain_info_group = QGroupBox("Domain Information")
        domain_info_layout = QFormLayout(self.domain_info_group)
        
        self.info_domain = QLabel("-")
        self.info_dr = QLabel("-")
        self.info_traffic = QLabel("-")
        self.info_status = QLabel("-")
        
        domain_info_layout.addRow("Domain:", self.info_domain)
        domain_info_layout.addRow("Domain Rating:", self.info_dr)
        domain_info_layout.addRow("Traffic:", self.info_traffic)
        domain_info_layout.addRow("Status:", self.info_status)
        
        self.details_layout.addWidget(self.domain_info_group)
        
        # Contact methods found
        self.contact_group = QGroupBox("Contact Methods Detected")
        contact_layout = QVBoxLayout(self.contact_group)
        
        self.contact_info = QTextEdit()
        self.contact_info.setReadOnly(True)
        self.contact_info.setMaximumHeight(150)
        self.contact_info.setPlaceholderText("No contact methods detected yet. Run analysis to detect.")
        contact_layout.addWidget(self.contact_info)
        
        self.details_layout.addWidget(self.contact_group)
        
        # Guidelines extracted
        self.guidelines_group = QGroupBox("Extracted Guidelines")
        guidelines_layout = QVBoxLayout(self.guidelines_group)
        
        self.guidelines_info = QTextEdit()
        self.guidelines_info.setReadOnly(True)
        self.guidelines_info.setPlaceholderText("No guidelines extracted yet. Run analysis to extract.")
        guidelines_layout.addWidget(self.guidelines_info)
        
        self.details_layout.addWidget(self.guidelines_group)
        
        # Analysis log
        self.log_group = QGroupBox("Analysis Log")
        log_layout = QVBoxLayout(self.log_group)
        
        self.analysis_log = QTextEdit()
        self.analysis_log.setReadOnly(True)
        self.analysis_log.setMaximumHeight(150)
        self.analysis_log.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self.analysis_log)
        
        self.details_layout.addWidget(self.log_group)
        self.details_layout.addStretch()
        
        right_panel.setWidget(details_widget)
        splitter.addWidget(right_panel)
        
        # Set splitter sizes
        splitter.setSizes([400, 600])
        
        layout.addWidget(splitter)
    
    def refresh(self):
        """Refresh the domain list"""
        status = self.status_filter.currentData()
        
        if status:
            domains = self.db.get_domains(status=status, limit=500)
        else:
            domains = self.db.get_all_domains()[:500]
        
        self.populate_table(domains)
    
    def populate_table(self, domains: list):
        """Populate table with domains"""
        self.table.setRowCount(len(domains))
        
        for row, domain in enumerate(domains):
            # Domain
            domain_item = QTableWidgetItem(domain.domain)
            domain_item.setData(Qt.ItemDataRole.UserRole, domain.id)
            self.table.setItem(row, 0, domain_item)
            
            # DR
            dr_item = QTableWidgetItem(str(domain.dr) if domain.dr else "-")
            dr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, dr_item)
            
            # Status
            status_item = QTableWidgetItem(domain.status.title())
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, status_item)
            
            # Last analyzed
            last = domain.last_analyzed
            last_str = str(last)[:16] if last else "Never"
            self.table.setItem(row, 3, QTableWidgetItem(last_str))
    
    def on_selection_changed(self):
        """Handle domain selection change"""
        selected = self.table.selectionModel().selectedRows()
        
        if len(selected) == 1:
            row = selected[0].row()
            domain_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            domain = self.db.get_domain(domain_id)
            self.show_domain_details(domain)
        else:
            self.clear_details()
    
    def show_domain_details(self, domain: Domain):
        """Display domain analysis details"""
        self.selected_domain = domain
        
        # Basic info
        self.info_domain.setText(domain.domain)
        self.info_dr.setText(str(domain.dr) if domain.dr else "Unknown")
        self.info_traffic.setText(f"{domain.traffic:,}" if domain.traffic else "Unknown")
        self.info_status.setText(domain.status.title())
        
        # Contact methods
        contact_methods = self.db.get_contact_methods(domain.id)
        if contact_methods:
            contact_text = ""
            for cm in contact_methods:
                contact_text += f"<b>Type:</b> {cm['method_type'].upper()}<br>"
                if cm['email_address']:
                    contact_text += f"<b>Email:</b> {cm['email_address']}<br>"
                if cm['url']:
                    contact_text += f"<b>URL:</b> {cm['url']}<br>"
                if cm['has_captcha']:
                    contact_text += f"<b>Captcha:</b> {cm['captcha_type'] or 'Yes'}<br>"
                contact_text += "<br>"
            self.contact_info.setHtml(contact_text)
        else:
            self.contact_info.setPlainText("No contact methods detected yet.")
        
        # Guidelines
        if contact_methods:
            for cm in contact_methods:
                if cm.get('guidelines_parsed'):
                    import json
                    guidelines = cm['guidelines_parsed']
                    if isinstance(guidelines, str):
                        guidelines = json.loads(guidelines)
                    
                    guidelines_text = json.dumps(guidelines, indent=2)
                    self.guidelines_info.setPlainText(guidelines_text)
                    break
            else:
                self.guidelines_info.setPlainText("No guidelines extracted.")
        else:
            self.guidelines_info.setPlainText("Run analysis to extract guidelines.")
        
        # Analysis log
        activities = self.db.get_activity_log(domain_id=domain.id, limit=20)
        if activities:
            log_text = ""
            for act in activities:
                time_str = str(act['timestamp'])[:19]
                log_text += f"[{time_str}] {act['description']}\n"
            self.analysis_log.setPlainText(log_text)
        else:
            self.analysis_log.setPlainText("No analysis activity recorded.")
    
    def clear_details(self):
        """Clear the details panel"""
        self.selected_domain = None
        self.info_domain.setText("-")
        self.info_dr.setText("-")
        self.info_traffic.setText("-")
        self.info_status.setText("-")
        self.contact_info.clear()
        self.guidelines_info.clear()
        self.analysis_log.clear()
    
    def start_analysis(self):
        """Start analysis of selected domains"""
        selected_rows = self.table.selectionModel().selectedRows()
        
        if not selected_rows:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "No Selection",
                "Please select domains to analyze."
            )
            return
        
        # Get selected domains
        domains = []
        for row in selected_rows:
            domain_id = self.table.item(row.row(), 0).data(Qt.ItemDataRole.UserRole)
            domain = self.db.get_domain(domain_id)
            if domain:
                domains.append(domain)
        
        self._start_analysis_worker(domains)
    
    def analyze_all_pending(self):
        """Analyze all pending domains"""
        domains = self.db.get_domains(status="pending", limit=100)
        
        if not domains:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "No Pending Domains",
                "There are no pending domains to analyze."
            )
            return
        
        self._start_analysis_worker(domains)
    
    def _start_analysis_worker(self, domains: list):
        """Start the analysis worker"""
        from modules.analysis.website_analyzer import WebsiteAnalyzer
        
        analyzer = WebsiteAnalyzer(self.settings, self.db)
        
        self.current_worker = DomainAnalysisWorker(domains, analyzer)
        self.current_worker.progress.connect(self.on_progress)
        self.current_worker.finished_signal.connect(self.on_analysis_complete)
        self.current_worker.error.connect(self.on_worker_error)
        self.current_worker.log.connect(self.on_worker_log)
        
        # Show progress
        self.progress_frame.show()
        self.progress_bar.setValue(0)
        self.pause_btn.show()
        self.cancel_btn.show()
        self.analyze_btn.setEnabled(False)
        self.analyze_all_btn.setEnabled(False)
        
        self.current_worker.start()
        analysis_logger.info(f"Started analysis of {len(domains)} domains")
    
    @pyqtSlot(object)
    def on_progress(self, progress):
        """Handle progress update"""
        self.progress_bar.setValue(int(progress.percentage))
        self.progress_bar.setFormat(f"{progress.message} ({progress.current}/{progress.total})")
        self.progress_label.setText(f"Analyzing: {progress.message}")
    
    @pyqtSlot(str, str)
    def on_worker_log(self, level: str, message: str):
        """Handle worker log message"""
        current = self.analysis_log.toPlainText()
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.analysis_log.setPlainText(f"[{timestamp}] [{level}] {message}\n{current}")
    
    @pyqtSlot(object)
    def on_analysis_complete(self, results):
        """Handle analysis completion"""
        self.progress_frame.hide()
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.analyze_btn.setEnabled(True)
        self.analyze_all_btn.setEnabled(True)
        self.current_worker = None
        
        self.refresh()
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Analysis Complete",
            f"Successfully analyzed {len(results)} domains."
        )
    
    @pyqtSlot(str, str)
    def on_worker_error(self, error: str, traceback: str):
        """Handle worker error"""
        self.progress_frame.hide()
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.analyze_btn.setEnabled(True)
        self.analyze_all_btn.setEnabled(True)
        self.current_worker = None
        
        analysis_logger.error(f"Analysis error: {error}")
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(
            self, "Analysis Error",
            f"An error occurred during analysis:\n\n{error}"
        )
    
    def toggle_pause(self):
        """Toggle pause/resume"""
        if self.current_worker:
            if self.current_worker.status.value == "paused":
                self.current_worker.resume()
                self.pause_btn.setText("⏸️ Pause")
            else:
                self.current_worker.pause()
                self.pause_btn.setText("▶️ Resume")
    
    def cancel_analysis(self):
        """Cancel the current analysis"""
        if self.current_worker:
            self.current_worker.stop()
            self.current_worker = None
        
        self.progress_frame.hide()
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.analyze_btn.setEnabled(True)
        self.analyze_all_btn.setEnabled(True)
        
        analysis_logger.info("Analysis cancelled by user")