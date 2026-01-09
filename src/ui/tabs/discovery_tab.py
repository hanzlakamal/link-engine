"""
Discovery Tab - Import and manage domains
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QHeaderView,
    QLineEdit, QComboBox, QMenu, QMessageBox, QProgressBar,
    QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction

from config import Settings
from core.database import Database, Domain
from core.logger import ui_logger
from core.workers import EnrichmentWorker


class DiscoveryTab(QWidget):
    """Domain discovery and import tab"""
    
    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.current_worker = None
        
        self.setup_ui()
        self.refresh()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("Domain Discovery")
        title.setObjectName("headerLabel")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Import button
        import_btn = QPushButton("📥 Import CSV")
        import_btn.setObjectName("primaryButton")
        import_btn.clicked.connect(self.show_import_dialog)
        header_layout.addWidget(import_btn)
        
        # Enrich button
        enrich_btn = QPushButton("📊 Enrich Selected")
        enrich_btn.clicked.connect(self.enrich_domains)
        header_layout.addWidget(enrich_btn)
        
        layout.addLayout(header_layout)
        
        # Filters bar
        filters = QFrame()
        filters.setObjectName("card")
        filters_layout = QHBoxLayout(filters)
        
        filters_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search domains...")
        self.search_input.textChanged.connect(self.apply_filters)
        self.search_input.setMaximumWidth(250)
        filters_layout.addWidget(self.search_input)
        
        filters_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("All Status", None)
        self.status_filter.addItem("Pending", "pending")
        self.status_filter.addItem("Analyzed", "analyzed")
        self.status_filter.addItem("Contacted", "contacted")
        self.status_filter.addItem("Responded", "responded")
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        filters_layout.addWidget(self.status_filter)
        
        filters_layout.addWidget(QLabel("Min DR:"))
        self.dr_filter = QComboBox()
        self.dr_filter.addItem("Any", 0)
        self.dr_filter.addItem("10+", 10)
        self.dr_filter.addItem("20+", 20)
        self.dr_filter.addItem("30+", 30)
        self.dr_filter.addItem("50+", 50)
        self.dr_filter.currentIndexChanged.connect(self.apply_filters)
        filters_layout.addWidget(self.dr_filter)
        
        filters_layout.addStretch()
        
        self.count_label = QLabel("0 domains")
        filters_layout.addWidget(self.count_label)
        
        layout.addWidget(filters)
        
        # Progress bar (hidden by default)
        self.progress_frame = QFrame()
        progress_layout = QHBoxLayout(self.progress_frame)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_operation)
        progress_layout.addWidget(self.cancel_btn)
        
        self.progress_frame.hide()
        layout.addWidget(self.progress_frame)
        
        # Domain table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Domain", "DR", "Traffic", "Ref. Domains", 
            "Score", "Status", "Niche", "Actions"
        ])
        
        # Table settings
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        
        # Column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 100)
        
        layout.addWidget(self.table)
        
        # Footer
        footer = QHBoxLayout()
        
        self.selected_label = QLabel("0 selected")
        footer.addWidget(self.selected_label)
        
        footer.addStretch()
        
        delete_btn = QPushButton("🗑️ Delete Selected")
        delete_btn.setObjectName("dangerButton")
        delete_btn.clicked.connect(self.delete_selected)
        footer.addWidget(delete_btn)
        
        layout.addLayout(footer)
        
        # Connect selection change
        self.table.itemSelectionChanged.connect(self.update_selection_count)
    
    def refresh(self):
        """Refresh the domain list"""
        ui_logger.debug("Refreshing discovery tab")
        self.apply_filters()
    
    def apply_filters(self):
        """Apply current filters and refresh table"""
        search = self.search_input.text().strip()
        status = self.status_filter.currentData()
        min_dr = self.dr_filter.currentData()
        
        # Get filtered domains
        domains = self.db.get_domains(
            status=status,
            min_dr=min_dr if min_dr else None,
            limit=1000
        )
        
        # Apply search filter
        if search:
            search_lower = search.lower()
            domains = [d for d in domains if search_lower in d.domain.lower()]
        
        self.populate_table(domains)
        self.count_label.setText(f"{len(domains)} domains")
    
    def populate_table(self, domains: list):
        """Populate table with domains"""
        self.table.setRowCount(len(domains))
        
        status_colors = {
            'pending': '#f39c12',
            'analyzing': '#3498db',
            'analyzed': '#2ecc71',
            'contacted': '#9b59b6',
            'responded': '#00b894',
            'published': '#00d9a5',
            'rejected': '#e74c3c',
            'error': '#e74c3c'
        }
        
        for row, domain in enumerate(domains):
            # Store domain ID in first item
            domain_item = QTableWidgetItem(domain.domain)
            domain_item.setData(Qt.ItemDataRole.UserRole, domain.id)
            self.table.setItem(row, 0, domain_item)
            
            # DR
            dr_item = QTableWidgetItem(str(domain.dr) if domain.dr else "-")
            dr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, dr_item)
            
            # Traffic
            traffic = domain.traffic
            traffic_str = f"{traffic:,}" if traffic else "-"
            traffic_item = QTableWidgetItem(traffic_str)
            traffic_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, traffic_item)
            
            # Referring domains
            refs = domain.referring_domains
            refs_str = f"{refs:,}" if refs else "-"
            refs_item = QTableWidgetItem(refs_str)
            refs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, refs_item)
            
            # Score
            score_item = QTableWidgetItem(f"{domain.quality_score:.1f}" if domain.quality_score else "-")
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, score_item)
            
            # Status with color
            status_item = QTableWidgetItem(domain.status.title())
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color = status_colors.get(domain.status, '#8892b0')
            status_item.setForeground(Qt.GlobalColor.white)
            self.table.setItem(row, 5, status_item)
            
            # Niche
            self.table.setItem(row, 6, QTableWidgetItem(domain.niche or "-"))
            
            # Actions button
            actions_btn = QPushButton("⋮")
            actions_btn.setFixedWidth(40)
            actions_btn.clicked.connect(lambda checked, d=domain: self.show_domain_actions(d))
            self.table.setCellWidget(row, 7, actions_btn)
    
    def show_import_dialog(self):
        """Show import dialog"""
        from ui.dialogs.import_dialog import ImportDialog
        dialog = ImportDialog(self.db, self)
        if dialog.exec():
            self.refresh()
    
    def enrich_domains(self):
        """Enrich selected domains with Ahrefs data"""
        if not self.settings.api.ahrefs_api_key:
            QMessageBox.warning(
                self, "API Key Required",
                "Please configure your Ahrefs API key in Settings first."
            )
            return
        
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(
                self, "No Selection",
                "Please select domains to enrich."
            )
            return
        
        # Get selected domain IDs
        domain_ids = []
        for row in selected_rows:
            item = self.table.item(row.row(), 0)
            domain_id = item.data(Qt.ItemDataRole.UserRole)
            domain_ids.append(domain_id)
        
        # Get domain objects
        domains = [self.db.get_domain(did) for did in domain_ids]
        
        # Create and start worker
        from integrations.ahrefs_api import AhrefsAPI
        ahrefs = AhrefsAPI(self.settings.api.ahrefs_api_key)
        
        self.current_worker = EnrichmentWorker(domains, ahrefs, self.db)
        self.current_worker.progress.connect(self.on_progress)
        self.current_worker.finished_signal.connect(self.on_enrichment_complete)
        self.current_worker.error.connect(self.on_worker_error)
        
        self.progress_frame.show()
        self.progress_bar.setValue(0)
        self.current_worker.start()
    
    @pyqtSlot(object)
    def on_progress(self, progress):
        """Handle progress updates"""
        self.progress_bar.setValue(int(progress.percentage))
        self.progress_bar.setFormat(f"{progress.message} ({progress.current}/{progress.total})")
    
    @pyqtSlot(object)
    def on_enrichment_complete(self, result):
        """Handle enrichment completion"""
        self.progress_frame.hide()
        self.refresh()
        
        QMessageBox.information(
            self, "Enrichment Complete",
            f"Enriched {result['enriched']} domains.\n{result['failed']} failed."
        )
    
    @pyqtSlot(str, str)
    def on_worker_error(self, error, traceback):
        """Handle worker error"""
        self.progress_frame.hide()
        ui_logger.error(f"Worker error: {error}\n{traceback}")
        
        QMessageBox.critical(
            self, "Error",
            f"An error occurred: {error}"
        )
    
    def cancel_operation(self):
        """Cancel current operation"""
        if self.current_worker:
            self.current_worker.stop()
            self.current_worker = None
        self.progress_frame.hide()
    
    def show_context_menu(self, position):
        """Show context menu for table"""
        menu = QMenu()
        
        analyze_action = QAction("🔬 Analyze", self)
        analyze_action.triggered.connect(self.analyze_selected)
        menu.addAction(analyze_action)
        
        enrich_action = QAction("📊 Enrich with Ahrefs", self)
        enrich_action.triggered.connect(self.enrich_domains)
        menu.addAction(enrich_action)
        
        menu.addSeparator()
        
        open_action = QAction("🌐 Open in Browser", self)
        open_action.triggered.connect(self.open_selected_in_browser)
        menu.addAction(open_action)
        
        menu.addSeparator()
        
        delete_action = QAction("🗑️ Delete", self)
        delete_action.triggered.connect(self.delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self.table.viewport().mapToGlobal(position))
    
    def show_domain_actions(self, domain: Domain):
        """Show actions menu for a domain"""
        from ui.dialogs.domain_detail_dialog import DomainDetailDialog
        dialog = DomainDetailDialog(domain, self.db, self)
        dialog.exec()
        self.refresh()
    
    def analyze_selected(self):
        """Analyze selected domains"""
        # Switch to analysis tab
        main_window = self.window()
        if hasattr(main_window, 'tab_widget'):
            main_window.tab_widget.setCurrentWidget(main_window.analysis_tab)
    
    def open_selected_in_browser(self):
        """Open selected domains in browser"""
        import webbrowser
        
        selected_rows = self.table.selectionModel().selectedRows()
        for row in selected_rows[:5]:  # Limit to 5
            domain = self.table.item(row.row(), 0).text()
            webbrowser.open(f"https://{domain}")
    
    def delete_selected(self):
        """Delete selected domains"""
        selected_rows = self.table.selectionModel().selectedRows()
        
        if not selected_rows:
            return
        
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(selected_rows)} selected domains?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for row in sorted(selected_rows, reverse=True):
                item = self.table.item(row.row(), 0)
                domain_id = item.data(Qt.ItemDataRole.UserRole)
                self.db.delete_domain(domain_id)
            
            self.refresh()
            ui_logger.info(f"Deleted {len(selected_rows)} domains")
    
    def update_selection_count(self):
        """Update selected count label"""
        count = len(self.table.selectionModel().selectedRows())
        self.selected_label.setText(f"{count} selected")