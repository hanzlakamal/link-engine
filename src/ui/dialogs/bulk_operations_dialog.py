"""
Bulk Operations Dialog - Perform operations on multiple domains
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QGroupBox, QRadioButton,
    QButtonGroup, QSpinBox, QCheckBox, QComboBox,
    QDialogButtonBox, QFormLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from typing import List, Callable

from config import Settings
from core.database import Database, Domain
from core.logger import ui_logger


class BulkOperationWorker(QThread):
    """Worker thread for bulk operations"""
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(dict)  # results
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    
    def __init__(self, operation: str, domains: List[Domain], 
                 settings: Settings, db: Database, options: dict):
        super().__init__()
        self.operation = operation
        self.domains = domains
        self.settings = settings
        self.db = db
        self.options = options
        self._should_stop = False
    
    def stop(self):
        self._should_stop = True
    
    def run(self):
        results = {
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
        
        total = len(self.domains)
        
        for i, domain in enumerate(self.domains):
            if self._should_stop:
                self.log.emit("Operation cancelled by user")
                break
            
            self.progress.emit(i + 1, total, f"Processing {domain.domain}")
            
            try:
                if self.operation == "analyze":
                    success = self._analyze_domain(domain)
                elif self.operation == "enrich":
                    success = self._enrich_domain(domain)
                elif self.operation == "delete":
                    success = self._delete_domain(domain)
                elif self.operation == "update_status":
                    success = self._update_status(domain)
                elif self.operation == "update_niche":
                    success = self._update_niche(domain)
                else:
                    success = False
                    results['errors'].append(f"Unknown operation: {self.operation}")
                
                if success:
                    results['success'] += 1
                    self.log.emit(f"✓ {domain.domain}")
                else:
                    results['failed'] += 1
                    self.log.emit(f"✗ {domain.domain}")
                    
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"{domain.domain}: {str(e)}")
                self.log.emit(f"✗ {domain.domain}: {str(e)}")
        
        self.finished.emit(results)
    
    def _analyze_domain(self, domain: Domain) -> bool:
        from modules.analysis.website_analyzer import WebsiteAnalyzer
        analyzer = WebsiteAnalyzer(self.settings, self.db)
        result = analyzer.analyze(domain)
        return result.get('success', False)
    
    def _enrich_domain(self, domain: Domain) -> bool:
        from modules.discovery.enrichment import DomainEnrichment
        enricher = DomainEnrichment(self.settings, self.db)
        result = enricher.enrich_domain(domain)
        return result.success
    
    def _delete_domain(self, domain: Domain) -> bool:
        self.db.delete_domain(domain.id)
        return True
    
    def _update_status(self, domain: Domain) -> bool:
        new_status = self.options.get('new_status', 'pending')
        self.db.update_domain_status(domain.id, new_status)
        return True
    
    def _update_niche(self, domain: Domain) -> bool:
        new_niche = self.options.get('new_niche', '')
        domain.niche = new_niche
        self.db.update_domain(domain)
        return True


class BulkOperationsDialog(QDialog):
    """Dialog for bulk operations on domains"""
    
    def __init__(self, domains: List[Domain], settings: Settings, 
                 db: Database, parent=None):
        super().__init__(parent)
        self.domains = domains
        self.settings = settings
        self.db = db
        self.worker = None
        
        self.setWindowTitle(f"Bulk Operations ({len(domains)} domains)")
        self.setMinimumSize(600, 500)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Info
        info_label = QLabel(f"Selected {len(self.domains)} domains for bulk operation")
        info_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(info_label)
        
        # Operation selection
        operation_group = QGroupBox("Select Operation")
        operation_layout = QVBoxLayout(operation_group)
        
        self.operation_group = QButtonGroup()
        
        self.analyze_radio = QRadioButton("🔬 Analyze websites (detect contact methods)")
        self.operation_group.addButton(self.analyze_radio, 1)
        operation_layout.addWidget(self.analyze_radio)
        
        self.enrich_radio = QRadioButton("📊 Enrich with Ahrefs data")
        self.operation_group.addButton(self.enrich_radio, 2)
        operation_layout.addWidget(self.enrich_radio)
        
        self.status_radio = QRadioButton("🏷️ Update status")
        self.operation_group.addButton(self.status_radio, 3)
        operation_layout.addWidget(self.status_radio)
        
        # Status selection
        status_layout = QHBoxLayout()
        status_layout.addSpacing(30)
        status_layout.addWidget(QLabel("New status:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems([
            "pending", "analyzed", "contacted", "responded", 
            "published", "rejected", "blacklisted"
        ])
        self.status_combo.setEnabled(False)
        status_layout.addWidget(self.status_combo)
        status_layout.addStretch()
        operation_layout.addLayout(status_layout)
        
        self.niche_radio = QRadioButton("📁 Update niche")
        self.operation_group.addButton(self.niche_radio, 4)
        operation_layout.addWidget(self.niche_radio)
        
        # Niche input
        niche_layout = QHBoxLayout()
        niche_layout.addSpacing(30)
        niche_layout.addWidget(QLabel("New niche:"))
        self.niche_input = QComboBox()
        self.niche_input.setEditable(True)
        self.niche_input.setEnabled(False)
        niche_layout.addWidget(self.niche_input)
        niche_layout.addStretch()
        operation_layout.addLayout(niche_layout)
        
        self.delete_radio = QRadioButton("🗑️ Delete domains")
        self.delete_radio.setStyleSheet("color: #e74c3c;")
        self.operation_group.addButton(self.delete_radio, 5)
        operation_layout.addWidget(self.delete_radio)
        
        # Connect radio buttons
        self.analyze_radio.setChecked(True)
        self.operation_group.buttonClicked.connect(self.on_operation_changed)
        
        layout.addWidget(operation_group)
        
        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        progress_layout.addWidget(self.status_label)
        
        layout.addWidget(progress_group)
        
        # Log
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(150)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self.log_display)
        
        layout.addWidget(log_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶️ Start")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_operation)
        button_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_operation)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.cancel_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def on_operation_changed(self, button):
        """Handle operation selection change"""
        self.status_combo.setEnabled(button == self.status_radio)
        self.niche_input.setEnabled(button == self.niche_radio)
    
    def start_operation(self):
        """Start the bulk operation"""
        # Determine operation
        operation_map = {
            1: "analyze",
            2: "enrich",
            3: "update_status",
            4: "update_niche",
            5: "delete"
        }
        
        checked_id = self.operation_group.checkedId()
        operation = operation_map.get(checked_id)
        
        if not operation:
            return
        
        # Confirm delete
        if operation == "delete":
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.warning(
                self, "Confirm Delete",
                f"Are you sure you want to delete {len(self.domains)} domains?\n\nThis cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # Build options
        options = {}
        if operation == "update_status":
            options['new_status'] = self.status_combo.currentText()
        elif operation == "update_niche":
            options['new_niche'] = self.niche_input.currentText()
        
        # Start worker
        self.worker = BulkOperationWorker(
            operation, self.domains, self.settings, self.db, options
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.log.connect(self.on_log)
        
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        
        self.log_display.clear()
        self.worker.start()
    
    def cancel_operation(self):
        """Cancel the operation"""
        if self.worker:
            self.worker.stop()
    
    def on_progress(self, current: int, total: int, message: str):
        """Handle progress update"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(message)
    
    def on_log(self, message: str):
        """Handle log message"""
        self.log_display.append(message)
    
    def on_finished(self, results: dict):
        """Handle operation completion"""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        
        self.status_label.setText(
            f"Complete: {results['success']} success, {results['failed']} failed"
        )
        
        self.log_display.append("")
        self.log_display.append(f"=== Operation Complete ===")
        self.log_display.append(f"Success: {results['success']}")
        self.log_display.append(f"Failed: {results['failed']}")
        
        if results['errors']:
            self.log_display.append("\nErrors:")
            for error in results['errors'][:10]:
                self.log_display.append(f"  - {error}")
        
        self.worker = None