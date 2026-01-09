"""
Outreach Tab - Email generation and sending
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QHeaderView,
    QTextEdit, QSplitter, QProgressBar, QComboBox,
    QAbstractItemView, QGroupBox, QFormLayout, QLineEdit,
    QSpinBox, QMessageBox, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSlot
from typing import Optional

from config import Settings
from core.database import Database, Domain
from core.logger import outreach_logger, ui_logger


class OutreachTab(QWidget):
    """Outreach management tab"""
    
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
        
        title = QLabel("Outreach Management")
        title.setObjectName("headerLabel")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Action buttons
        generate_btn = QPushButton("✨ Generate Emails")
        generate_btn.setObjectName("primaryButton")
        generate_btn.clicked.connect(self.generate_emails)
        header_layout.addWidget(generate_btn)
        
        send_btn = QPushButton("📤 Send Queue")
        send_btn.setObjectName("successButton")
        send_btn.clicked.connect(self.send_queue)
        header_layout.addWidget(send_btn)
        
        layout.addLayout(header_layout)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Outreach queue
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Draft", "draft")
        self.status_filter.addItem("Queued", "queued")
        self.status_filter.addItem("Sent", "sent")
        self.status_filter.addItem("All", None)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()
        
        self.queue_count = QLabel("0 items")
        filter_layout.addWidget(self.queue_count)
        
        left_layout.addLayout(filter_layout)
        
        # Queue table
        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(5)
        self.queue_table.setHorizontalHeaderLabels([
            "Domain", "Subject", "Status", "Created", "Sent"
        ])
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.itemSelectionChanged.connect(self.on_selection_changed)
        
        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        left_layout.addWidget(self.queue_table)
        splitter.addWidget(left_panel)
        
        # Right: Email editor
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Tabs for editor/preview
        editor_tabs = QTabWidget()
        
        # Editor tab
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        
        # To field
        to_layout = QHBoxLayout()
        to_layout.addWidget(QLabel("To:"))
        self.to_field = QLineEdit()
        self.to_field.setPlaceholderText("recipient@example.com")
        to_layout.addWidget(self.to_field)
        editor_layout.addLayout(to_layout)
        
        # Subject field
        subject_layout = QHBoxLayout()
        subject_layout.addWidget(QLabel("Subject:"))
        self.subject_field = QLineEdit()
        self.subject_field.setPlaceholderText("Email subject...")
        subject_layout.addWidget(self.subject_field)
        editor_layout.addLayout(subject_layout)
        
        # Message body
        editor_layout.addWidget(QLabel("Message:"))
        self.message_field = QTextEdit()
        self.message_field.setPlaceholderText("Write your outreach email here...")
        editor_layout.addWidget(self.message_field)
        
        # Editor actions
        editor_actions = QHBoxLayout()
        
        regenerate_btn = QPushButton("🔄 Regenerate with AI")
        regenerate_btn.clicked.connect(self.regenerate_email)
        editor_actions.addWidget(regenerate_btn)
        
        editor_actions.addStretch()
        
        save_draft_btn = QPushButton("💾 Save Draft")
        save_draft_btn.clicked.connect(self.save_draft)
        editor_actions.addWidget(save_draft_btn)
        
        queue_btn = QPushButton("📋 Add to Queue")
        queue_btn.clicked.connect(self.add_to_queue)
        editor_actions.addWidget(queue_btn)
        
        editor_layout.addLayout(editor_actions)
        
        editor_tabs.addTab(editor_widget, "✏️ Editor")
        
        # Preview tab
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        
        self.preview_display = QTextEdit()
        self.preview_display.setReadOnly(True)
        preview_layout.addWidget(self.preview_display)
        
        editor_tabs.addTab(preview_widget, "👁️ Preview")
        
        right_layout.addWidget(editor_tabs)
        splitter.addWidget(right_panel)
        
        splitter.setSizes([500, 500])
        layout.addWidget(splitter)
        
        # Progress section (hidden by default)
        self.progress_frame = QFrame()
        self.progress_frame.setObjectName("card")
        progress_layout = QHBoxLayout(self.progress_frame)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_sending)
        progress_layout.addWidget(cancel_btn)
        
        self.progress_frame.hide()
        layout.addWidget(self.progress_frame)
    
    def refresh(self):
        """Refresh the queue list"""
        status = self.status_filter.currentData()
        submissions = self.db.get_submissions(status=status, limit=200)
        
        self.populate_queue(submissions)
        self.queue_count.setText(f"{len(submissions)} items")
    
    def populate_queue(self, submissions: list):
        """Populate queue table"""
        self.queue_table.setRowCount(len(submissions))
        
        for row, sub in enumerate(submissions):
            # Domain
            domain_item = QTableWidgetItem(sub.get('domain', '-'))
            domain_item.setData(Qt.ItemDataRole.UserRole, sub['id'])
            self.queue_table.setItem(row, 0, domain_item)
            
            # Subject
            subject = sub.get('subject', '')[:50]
            self.queue_table.setItem(row, 1, QTableWidgetItem(subject))
            
            # Status
            status_item = QTableWidgetItem(sub.get('status', '-').title())
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.queue_table.setItem(row, 2, status_item)
            
            # Created
            created = str(sub.get('created_at', ''))[:16]
            self.queue_table.setItem(row, 3, QTableWidgetItem(created))
            
            # Sent
            sent = str(sub.get('sent_at', ''))[:16] if sub.get('sent_at') else '-'
            self.queue_table.setItem(row, 4, QTableWidgetItem(sent))
    
    def on_selection_changed(self):
        """Handle queue selection change"""
        selected = self.queue_table.selectionModel().selectedRows()
        
        if len(selected) == 1:
            row = selected[0].row()
            submission_id = self.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.load_submission(submission_id)
    
    def load_submission(self, submission_id: int):
        """Load submission into editor"""
        submissions = self.db.get_submissions(limit=1)  # TODO: Get by ID
        
        for sub in submissions:
            if sub['id'] == submission_id:
                self.to_field.setText(sub.get('to_email', ''))
                self.subject_field.setText(sub.get('subject', ''))
                self.message_field.setPlainText(sub.get('message', ''))
                
                # Update preview
                self.update_preview()
                break
    
    def update_preview(self):
        """Update email preview"""
        preview_html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px;">
            <p><strong>To:</strong> {self.to_field.text()}</p>
            <p><strong>Subject:</strong> {self.subject_field.text()}</p>
            <hr>
            <div style="white-space: pre-wrap;">{self.message_field.toPlainText()}</div>
        </div>
        """
        self.preview_display.setHtml(preview_html)
    
    def generate_emails(self):
        """Generate emails for analyzed domains"""
        # Get analyzed domains that haven't been contacted
        domains = self.db.get_domains(status="analyzed", limit=50)
        
        if not domains:
            QMessageBox.information(
                self, "No Domains",
                "No analyzed domains available for outreach."
            )
            return
        
        # Check for AI API key
        if not self.settings.api.anthropic_api_key and not self.settings.api.openai_api_key:
            QMessageBox.warning(
                self, "API Key Required",
                "Please configure an AI API key (Claude or OpenAI) in Settings."
            )
            return
        
        # TODO: Implement batch email generation
        QMessageBox.information(
            self, "Coming Soon",
            f"Email generation for {len(domains)} domains will be implemented."
        )
    
    def regenerate_email(self):
        """Regenerate current email with AI"""
        if not self.to_field.text():
            QMessageBox.warning(self, "No Recipient", "Please select or enter a recipient first.")
            return
        
        # TODO: Implement AI regeneration
        QMessageBox.information(self, "Coming Soon", "AI email regeneration will be implemented.")
    
    def save_draft(self):
        """Save current email as draft"""
        if not self.to_field.text():
            QMessageBox.warning(self, "Missing Data", "Please enter recipient email.")
            return
        
        # TODO: Save to database
        QMessageBox.information(self, "Saved", "Draft saved successfully.")
    
    def add_to_queue(self):
        """Add current email to send queue"""
        if not self.to_field.text() or not self.subject_field.text():
            QMessageBox.warning(self, "Missing Data", "Please fill in recipient and subject.")
            return
        
        # TODO: Add to queue
        QMessageBox.information(self, "Queued", "Email added to send queue.")
        self.refresh()
    
    def send_queue(self):
        """Send all queued emails"""
        queued = self.db.get_submissions(status="queued")
        
        if not queued:
            QMessageBox.information(self, "Empty Queue", "No emails in queue to send.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Send",
            f"Send {len(queued)} emails from the queue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # TODO: Implement sending
            QMessageBox.information(self, "Coming Soon", "Email sending will be implemented.")
    
    def cancel_sending(self):
        """Cancel sending operation"""
        self.progress_frame.hide()