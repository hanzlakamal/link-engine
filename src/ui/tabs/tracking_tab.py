"""
Tracking Tab - Monitor backlinks
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QHeaderView,
    QAbstractItemView, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt

from config import Settings
from core.database import Database
from core.logger import ui_logger


class TrackingTab(QWidget):
    """Backlink tracking tab"""
    
    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        
        self.setup_ui()
        self.refresh()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("Backlink Tracking")
        title.setObjectName("headerLabel")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        check_btn = QPushButton("🔄 Check All Links")
        check_btn.clicked.connect(self.check_all_links)
        header_layout.addWidget(check_btn)
        
        add_btn = QPushButton("➕ Add Link Manually")
        add_btn.clicked.connect(self.add_link_manually)
        header_layout.addWidget(add_btn)
        
        layout.addLayout(header_layout)
        
        # Stats row
        stats_frame = QFrame()
        stats_frame.setObjectName("card")
        stats_layout = QHBoxLayout(stats_frame)
        
        self.total_label = QLabel("Total: 0")
        self.total_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.total_label)
        
        self.live_label = QLabel("🟢 Live: 0")
        self.live_label.setStyleSheet("font-size: 16px; color: #00b894;")
        stats_layout.addWidget(self.live_label)
        
        self.removed_label = QLabel("🔴 Removed: 0")
        self.removed_label.setStyleSheet("font-size: 16px; color: #e74c3c;")
        stats_layout.addWidget(self.removed_label)
        
        stats_layout.addStretch()
        
        layout.addWidget(stats_frame)
        
        # Filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", None)
        self.status_filter.addItem("Live", "live")
        self.status_filter.addItem("Removed", "removed")
        self.status_filter.addItem("Pending", "pending")
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Links table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Source Domain", "Source URL", "Target URL", 
            "Anchor Text", "Type", "Status", "Last Checked"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 150)
        
        layout.addWidget(self.table)
    
    def refresh(self):
        """Refresh the links list"""
        status = self.status_filter.currentData()
        links = self.db.get_backlinks(status=status)
        
        self.populate_table(links)
        self.update_stats()
    
    def populate_table(self, links: list):
        """Populate table with links"""
        self.table.setRowCount(len(links))
        
        status_colors = {
            'live': '#00b894',
            'removed': '#e74c3c',
            'pending': '#f39c12',
            'error': '#e74c3c'
        }
        
        for row, link in enumerate(links):
            # Source domain
            self.table.setItem(row, 0, QTableWidgetItem(link.get('domain', '-')))
            
            # Source URL
            source_url = link.get('source_url', '-')
            source_item = QTableWidgetItem(source_url[:60] + '...' if len(source_url) > 60 else source_url)
            source_item.setToolTip(source_url)
            self.table.setItem(row, 1, source_item)
            
            # Target URL
            target_url = link.get('target_url', '-')
            target_item = QTableWidgetItem(target_url[:50] + '...' if len(target_url) > 50 else target_url)
            target_item.setToolTip(target_url)
            self.table.setItem(row, 2, target_item)
            
            # Anchor text
            self.table.setItem(row, 3, QTableWidgetItem(link.get('anchor_text', '-')))
            
            # Link type
            link_type = link.get('link_type', 'unknown')
            type_item = QTableWidgetItem(link_type)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, type_item)
            
            # Status
            status = link.get('status', 'unknown')
            status_item = QTableWidgetItem(status.upper())
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, status_item)
            
            # Last checked
            last_checked = str(link.get('last_checked', ''))[:16] if link.get('last_checked') else 'Never'
            self.table.setItem(row, 6, QTableWidgetItem(last_checked))
    
    def update_stats(self):
        """Update statistics labels"""
        stats = self.db.get_backlink_stats()
        
        total = sum(stats.get('by_type', {}).values()) if stats.get('by_type') else 0
        live = stats.get('total_live', 0)
        
        self.total_label.setText(f"Total: {total}")
        self.live_label.setText(f"🟢 Live: {live}")
        self.removed_label.setText(f"🔴 Removed: {total - live}")
    
    def check_all_links(self):
        """Check all backlinks"""
        links = self.db.get_backlinks(status="live")
        
        if not links:
            QMessageBox.information(self, "No Links", "No live links to check.")
            return
        
        # TODO: Implement link checking worker
        QMessageBox.information(
            self, "Coming Soon",
            f"Link checking for {len(links)} links will be implemented."
        )
    
    def add_link_manually(self):
        """Add a link manually"""
        # TODO: Show add link dialog
        QMessageBox.information(self, "Coming Soon", "Manual link addition will be implemented.")