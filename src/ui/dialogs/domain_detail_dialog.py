"""
Import Dialog - CSV import wizard
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QProgressBar,
    QComboBox, QCheckBox, QGroupBox, QFormLayout, QLineEdit,
    QDialogButtonBox, QMessageBox, QHeaderView
)
from PyQt6.QtCore import Qt
import csv
from pathlib import Path
from typing import List, Dict

from core.database import Database, Domain
from core.logger import ui_logger


class ImportDialog(QDialog):
    """CSV import wizard dialog"""
    
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.file_path = None
        self.csv_data: List[Dict] = []
        self.column_mapping = {}
        
        self.setWindowTitle("Import Domains")
        self.setMinimumSize(700, 600)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # File selection
        file_group = QGroupBox("Source File")
        file_layout = QHBoxLayout(file_group)
        
        self.file_label = QLabel("No file selected")
        file_layout.addWidget(self.file_label)
        
        browse_btn = QPushButton("📂 Browse...")
        browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(browse_btn)
        
        layout.addWidget(file_group)
        
        # Column mapping
        mapping_group = QGroupBox("Column Mapping")
        mapping_layout = QFormLayout(mapping_group)
        
        self.domain_col = QComboBox()
        self.domain_col.addItem("-- Select Column --")
        mapping_layout.addRow("Domain Column:", self.domain_col)
        
        self.url_col = QComboBox()
        self.url_col.addItem("-- Optional --")
        mapping_layout.addRow("URL Column:", self.url_col)
        
        self.niche_col = QComboBox()
        self.niche_col.addItem("-- Optional --")
        mapping_layout.addRow("Niche Column:", self.niche_col)
        
        # Default niche
        self.default_niche = QLineEdit()
        self.default_niche.setPlaceholderText("Enter default niche for all imports")
        mapping_layout.addRow("Default Niche:", self.default_niche)
        
        layout.addWidget(mapping_group)
        
        # Preview
        preview_group = QGroupBox("Preview (first 10 rows)")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_table = QTableWidget()
        self.preview_table.setMaximumHeight(200)
        preview_layout.addWidget(self.preview_table)
        
        layout.addWidget(preview_group)
        
        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        self.skip_duplicates = QCheckBox("Skip duplicate domains")
        self.skip_duplicates.setChecked(True)
        options_layout.addWidget(self.skip_duplicates)
        
        self.clean_domains = QCheckBox("Clean domain names (remove http://, www., etc.)")
        self.clean_domains.setChecked(True)
        options_layout.addWidget(self.clean_domains)
        
        layout.addWidget(options_group)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Status
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.do_import)
        buttons.rejected.connect(self.reject)
        
        self.import_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_btn.setText("Import")
        self.import_btn.setEnabled(False)
        
        layout.addWidget(buttons)
    
    def browse_file(self):
        """Browse for CSV file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File",
            "",
            "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            self.file_path = Path(file_path)
            self.file_label.setText(str(self.file_path.name))
            self.load_csv()
    
    def load_csv(self):
        """Load and preview CSV file"""
        try:
            with open(self.file_path, 'r', encoding='utf-8-sig') as f:
                # Detect delimiter
                sample = f.read(4096)
                f.seek(0)
                
                sniffer = csv.Sniffer()
                try:
                    dialect = sniffer.sniff(sample)
                except:
                    dialect = csv.excel
                
                reader = csv.DictReader(f, dialect=dialect)
                self.csv_data = list(reader)
            
            if not self.csv_data:
                QMessageBox.warning(self, "Empty File", "The selected file is empty.")
                return
            
            # Populate column dropdowns
            columns = list(self.csv_data[0].keys())
            
            self.domain_col.clear()
            self.domain_col.addItem("-- Select Column --")
            self.url_col.clear()
            self.url_col.addItem("-- Optional --")
            self.niche_col.clear()
            self.niche_col.addItem("-- Optional --")
            
            for col in columns:
                self.domain_col.addItem(col)
                self.url_col.addItem(col)
                self.niche_col.addItem(col)
            
            # Auto-detect domain column
            for i, col in enumerate(columns):
                col_lower = col.lower()
                if 'domain' in col_lower or 'url' in col_lower or 'website' in col_lower:
                    self.domain_col.setCurrentIndex(i + 1)
                    break
            
            # Show preview
            self.show_preview(columns)
            
            self.status_label.setText(f"Loaded {len(self.csv_data)} rows")
            self.import_btn.setEnabled(True)
            
            ui_logger.info(f"Loaded CSV with {len(self.csv_data)} rows, {len(columns)} columns")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CSV:\n{str(e)}")
            ui_logger.error(f"CSV load error: {e}")
    
    def show_preview(self, columns: list):
        """Show preview of CSV data"""
        self.preview_table.setColumnCount(len(columns))
        self.preview_table.setHorizontalHeaderLabels(columns)
        
        preview_rows = self.csv_data[:10]
        self.preview_table.setRowCount(len(preview_rows))
        
        for row_idx, row in enumerate(preview_rows):
            for col_idx, col in enumerate(columns):
                value = row.get(col, '')
                self.preview_table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)[:50]))
        
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    
    def clean_domain(self, domain: str) -> str:
        """Clean domain name"""
        if not domain:
            return ""
        
        domain = domain.strip().lower()
        
        # Remove protocol
        for prefix in ['https://', 'http://', '//']:
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
        
        # Remove www.
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Remove trailing slash and path
        domain = domain.split('/')[0]
        
        # Remove port
        domain = domain.split(':')[0]
        
        return domain
    
    def do_import(self):
        """Perform the import"""
        domain_col = self.domain_col.currentText()
        
        if domain_col == "-- Select Column --":
            QMessageBox.warning(self, "Selection Required", "Please select the domain column.")
            return
        
        url_col = self.url_col.currentText()
        if url_col == "-- Optional --":
            url_col = None
        
        niche_col = self.niche_col.currentText()
        if niche_col == "-- Optional --":
            niche_col = None
        
        default_niche = self.default_niche.text().strip()
        
        # Prepare domains
        domains = []
        for row in self.csv_data:
            domain_value = row.get(domain_col, '').strip()
            
            if not domain_value:
                continue
            
            if self.clean_domains.isChecked():
                domain_value = self.clean_domain(domain_value)
            
            if not domain_value:
                continue
            
            domain = Domain(
                domain=domain_value,
                url=row.get(url_col, '') if url_col else f"https://{domain_value}",
                niche=row.get(niche_col, default_niche) if niche_col else default_niche,
                status="pending"
            )
            domains.append(domain)
        
        if not domains:
            QMessageBox.warning(self, "No Data", "No valid domains found in the file.")
            return
        
        # Show progress
        self.progress_bar.show()
        self.progress_bar.setMaximum(len(domains))
        self.import_btn.setEnabled(False)
        
        # Import
        try:
            inserted, skipped = self.db.bulk_insert_domains(domains)
            
            self.progress_bar.setValue(len(domains))
            
            QMessageBox.information(
                self, "Import Complete",
                f"Successfully imported {inserted} domains.\n{skipped} duplicates skipped."
            )
            
            ui_logger.info(f"Import complete: {inserted} inserted, {skipped} skipped")
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import:\n{str(e)}")
            ui_logger.error(f"Import error: {e}")
            self.import_btn.setEnabled(True)