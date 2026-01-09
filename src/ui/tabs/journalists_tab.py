"""
Journalists Tab - Media contacts management for Digital PR
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QHeaderView,
    QLineEdit, QComboBox, QSplitter, QGroupBox, QFormLayout,
    QTextEdit, QAbstractItemView, QMenu, QMessageBox, QDialog,
    QDialogButtonBox, QListWidget, QSpinBox, QTabWidget, QCheckBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from typing import Optional, List

from config import Settings
from core.database import Database
from core.logger import ui_logger
from modules.journalists.journalist_db import JournalistDatabase, Journalist, JournalistInteraction


class JournalistsTab(QWidget):
    """Journalists and media contacts management"""
    
    def __init__(self, settings: Settings, db: Database, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.journalist_db = JournalistDatabase(settings, db)
        self.selected_journalist: Optional[Journalist] = None
        
        self.setup_ui()
        self.refresh()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("Journalist Database")
        title.setObjectName("headerLabel")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Actions
        add_btn = QPushButton("➕ Add Journalist")
        add_btn.clicked.connect(self.add_journalist)
        header_layout.addWidget(add_btn)
        
        import_btn = QPushButton("📥 Import CSV")
        import_btn.clicked.connect(self.import_journalists)
        header_layout.addWidget(import_btn)
        
        campaign_btn = QPushButton("📢 New Campaign")
        campaign_btn.setObjectName("primaryButton")
        campaign_btn.clicked.connect(self.create_campaign)
        header_layout.addWidget(campaign_btn)
        
        layout.addLayout(header_layout)
        
        # Stats bar
        self.stats_frame = QFrame()
        self.stats_frame.setObjectName("card")
        stats_layout = QHBoxLayout(self.stats_frame)
        
        self.total_label = QLabel("Total: 0")
        stats_layout.addWidget(self.total_label)
        
        self.cold_label = QLabel("❄️ Cold: 0")
        stats_layout.addWidget(self.cold_label)
        
        self.warm_label = QLabel("🌡️ Warm: 0")
        stats_layout.addWidget(self.warm_label)
        
        self.hot_label = QLabel("🔥 Hot: 0")
        stats_layout.addWidget(self.hot_label)
        
        self.features_label = QLabel("📰 Features: 0")
        stats_layout.addWidget(self.features_label)
        
        stats_layout.addStretch()
        
        layout.addWidget(self.stats_frame)
        
        # Search/Filter bar
        filter_frame = QFrame()
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        
        filter_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Name, email, or outlet...")
        self.search_input.textChanged.connect(self.apply_filters)
        self.search_input.setMaximumWidth(250)
        filter_layout.addWidget(self.search_input)
        
        filter_layout.addWidget(QLabel("Beat:"))
        self.beat_filter = QComboBox()
        self.beat_filter.addItem("All Beats", None)
        self.beat_filter.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.beat_filter)
        
        filter_layout.addWidget(QLabel("Relationship:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", None)
        self.status_filter.addItem("❄️ Cold", "cold")
        self.status_filter.addItem("🌡️ Warm", "warm")
        self.status_filter.addItem("🔥 Hot", "hot")
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_filter)
        
        filter_layout.addWidget(QLabel("Min DR:"))
        self.dr_filter = QSpinBox()
        self.dr_filter.setRange(0, 100)
        self.dr_filter.setValue(0)
        self.dr_filter.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.dr_filter)
        
        filter_layout.addStretch()
        
        layout.addWidget(filter_frame)
        
        # Main content - Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left: Journalist list
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Name", "Outlet", "DR", "Beat", "Status", "Features"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 70)
        
        left_layout.addWidget(self.table)
        splitter.addWidget(left_panel)
        
        # Right: Details panel
        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Tabs for details
        detail_tabs = QTabWidget()
        
        # Info tab
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        
        self.info_group = QGroupBox("Contact Information")
        info_form = QFormLayout(self.info_group)
        
        self.info_name = QLabel("-")
        self.info_email = QLabel("-")
        self.info_outlet = QLabel("-")
        self.info_title = QLabel("-")
        self.info_twitter = QLabel("-")
        self.info_linkedin = QLabel("-")
        
        info_form.addRow("Name:", self.info_name)
        info_form.addRow("Email:", self.info_email)
        info_form.addRow("Outlet:", self.info_outlet)
        info_form.addRow("Title:", self.info_title)
        info_form.addRow("Twitter:", self.info_twitter)
        info_form.addRow("LinkedIn:", self.info_linkedin)
        
        info_layout.addWidget(self.info_group)
        
        # Preferences
        pref_group = QGroupBox("Pitch Preferences")
        pref_form = QFormLayout(pref_group)
        
        self.pref_contact = QLabel("-")
        self.pref_time = QLabel("-")
        self.pref_style = QLabel("-")
        
        pref_form.addRow("Preferred Contact:", self.pref_contact)
        pref_form.addRow("Best Time:", self.pref_time)
        pref_form.addRow("Style:", self.pref_style)
        
        info_layout.addWidget(pref_group)
        
        # Stats
        stats_group = QGroupBox("Statistics")
        stats_form = QFormLayout(stats_group)
        
        self.stat_pitches = QLabel("0")
        self.stat_responses = QLabel("0")
        self.stat_features = QLabel("0")
        self.stat_rate = QLabel("0%")
        
        stats_form.addRow("Total Pitches:", self.stat_pitches)
        stats_form.addRow("Responses:", self.stat_responses)
        stats_form.addRow("Features:", self.stat_features)
        stats_form.addRow("Response Rate:", self.stat_rate)
        
        info_layout.addWidget(stats_group)
        info_layout.addStretch()
        
        detail_tabs.addTab(info_widget, "📋 Info")
        
        # History tab
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels([
            "Date", "Type", "Campaign", "Result"
        ])
        history_layout.addWidget(self.history_table)
        
        detail_tabs.addTab(history_widget, "📜 History")
        
        # Notes tab
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Add notes about this journalist...")
        notes_layout.addWidget(self.notes_edit)
        
        save_notes_btn = QPushButton("💾 Save Notes")
        save_notes_btn.clicked.connect(self.save_notes)
        notes_layout.addWidget(save_notes_btn)
        
        detail_tabs.addTab(notes_widget, "📝 Notes")
        
        right_layout.addWidget(detail_tabs)
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        pitch_btn = QPushButton("📧 Log Pitch")
        pitch_btn.clicked.connect(self.log_pitch)
        action_layout.addWidget(pitch_btn)
        
        feature_btn = QPushButton("📰 Log Feature")
        feature_btn.setObjectName("successButton")
        feature_btn.clicked.connect(self.log_feature)
        action_layout.addWidget(feature_btn)
        
        edit_btn = QPushButton("✏️ Edit")
        edit_btn.clicked.connect(self.edit_journalist)
        action_layout.addWidget(edit_btn)
        
        right_layout.addLayout(action_layout)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])
        
        layout.addWidget(splitter)
    
    def refresh(self):
        """Refresh the journalist list"""
        self.apply_filters()
        self.update_stats()
        self.update_beat_filter()
    
    def update_stats(self):
        """Update statistics display"""
        stats = self.journalist_db.get_stats()
        
        self.total_label.setText(f"Total: {stats['total_journalists']}")
        self.cold_label.setText(f"❄️ Cold: {stats['cold']}")
        self.warm_label.setText(f"🌡️ Warm: {stats['warm']}")
        self.hot_label.setText(f"🔥 Hot: {stats['hot']}")
        self.features_label.setText(f"📰 Features: {stats['total_features']}")
    
    def update_beat_filter(self):
        """Update beat filter options"""
        stats = self.journalist_db.get_stats()
        
        current_beat = self.beat_filter.currentData()
        
        self.beat_filter.blockSignals(True)
        self.beat_filter.clear()
        self.beat_filter.addItem("All Beats", None)
        
        for item in stats.get('top_beats', []):
            self.beat_filter.addItem(f"{item['beat']} ({item['count']})", item['beat'])
        
        # Restore selection if possible
        if current_beat:
            idx = self.beat_filter.findData(current_beat)
            if idx >= 0:
                self.beat_filter.setCurrentIndex(idx)
        
        self.beat_filter.blockSignals(False)
    
    def apply_filters(self):
        """Apply filters and refresh table"""
        query = self.search_input.text().strip()
        beat = self.beat_filter.currentData()
        relationship = self.status_filter.currentData()
        min_dr = self.dr_filter.value() if self.dr_filter.value() > 0 else None
        
        journalists = self.journalist_db.search_journalists(
            query=query if query else None,
            beat=beat,
            relationship=relationship,
            min_dr=min_dr
        )
        
        self.populate_table(journalists)
    
    def populate_table(self, journalists: List[Journalist]):
        """Populate table with journalists"""
        self.table.setRowCount(len(journalists))
        
        status_icons = {
            'cold': '❄️',
            'warm': '🌡️',
            'hot': '🔥',
            'active': '⭐'
        }
        
        for row, journalist in enumerate(journalists):
            # Name
            name_item = QTableWidgetItem(journalist.name)
            name_item.setData(Qt.ItemDataRole.UserRole, journalist.id)
            self.table.setItem(row, 0, name_item)
            
            # Outlet
            self.table.setItem(row, 1, QTableWidgetItem(journalist.current_outlet or "-"))
            
            # DR
            dr_item = QTableWidgetItem(str(journalist.outlet_dr) if journalist.outlet_dr else "-")
            dr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, dr_item)
            
            # Beat
            beat_str = ", ".join(journalist.beat[:2]) if journalist.beat else "-"
            self.table.setItem(row, 3, QTableWidgetItem(beat_str))
            
            # Status
            status_icon = status_icons.get(journalist.relationship_status, '❓')
            status_item = QTableWidgetItem(status_icon)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, status_item)
            
            # Features
            features_item = QTableWidgetItem(str(journalist.total_features))
            features_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, features_item)
    
    def on_selection_changed(self):
        """Handle selection change"""
        selected = self.table.selectionModel().selectedRows()
        
        if len(selected) == 1:
            row = selected[0].row()
            journalist_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            journalist = self.journalist_db.get_journalist(journalist_id)
            if journalist:
                self.show_journalist_details(journalist)
        else:
            self.clear_details()
    
    def show_journalist_details(self, journalist: Journalist):
        """Display journalist details"""
        self.selected_journalist = journalist
        
        # Info
        self.info_name.setText(journalist.name)
        self.info_email.setText(journalist.email or "-")
        self.info_outlet.setText(f"{journalist.current_outlet} (DR: {journalist.outlet_dr})" if journalist.current_outlet else "-")
        self.info_title.setText(journalist.job_title or "-")
        self.info_twitter.setText(journalist.twitter or "-")
        self.info_linkedin.setText(journalist.linkedin or "-")
        
        # Preferences
        self.pref_contact.setText(journalist.preferred_contact or "-")
        self.pref_time.setText(journalist.best_pitch_time or "-")
        self.pref_style.setText(journalist.pitch_style or "-")
        
        # Stats
        self.stat_pitches.setText(str(journalist.total_pitches))
        self.stat_responses.setText(str(journalist.total_responses))
        self.stat_features.setText(str(journalist.total_features))
        self.stat_rate.setText(f"{journalist.response_rate:.1f}%")
        
        # Notes
        self.notes_edit.setPlainText(journalist.notes or "")
        
        # History
        self.load_history(journalist.id)
    
    def clear_details(self):
        """Clear details panel"""
        self.selected_journalist = None
        
        for label in [self.info_name, self.info_email, self.info_outlet,
                     self.info_title, self.info_twitter, self.info_linkedin,
                     self.pref_contact, self.pref_time, self.pref_style]:
            label.setText("-")
        
        self.stat_pitches.setText("0")
        self.stat_responses.setText("0")
        self.stat_features.setText("0")
        self.stat_rate.setText("0%")
        
        self.notes_edit.clear()
        self.history_table.setRowCount(0)
    
    def load_history(self, journalist_id: int):
        """Load interaction history"""
        interactions = self.journalist_db.get_interactions(journalist_id)
        
        self.history_table.setRowCount(len(interactions))
        
        for row, interaction in enumerate(interactions):
            date_str = str(interaction.get('interaction_date', ''))[:10]
            self.history_table.setItem(row, 0, QTableWidgetItem(date_str))
            self.history_table.setItem(row, 1, QTableWidgetItem(interaction.get('interaction_type', '')))
            self.history_table.setItem(row, 2, QTableWidgetItem(interaction.get('campaign_name', '') or "-"))
            
            result = "✅ Link" if interaction.get('link_obtained') else "-"
            self.history_table.setItem(row, 3, QTableWidgetItem(result))
    
    def show_context_menu(self, position):
        """Show context menu"""
        menu = QMenu()
        
        pitch_action = QAction("📧 Log Pitch", self)
        pitch_action.triggered.connect(self.log_pitch)
        menu.addAction(pitch_action)
        
        feature_action = QAction("📰 Log Feature", self)
        feature_action.triggered.connect(self.log_feature)
        menu.addAction(feature_action)
        
        menu.addSeparator()
        
        edit_action = QAction("✏️ Edit", self)
        edit_action.triggered.connect(self.edit_journalist)
        menu.addAction(edit_action)
        
        delete_action = QAction("🗑️ Delete", self)
        delete_action.triggered.connect(self.delete_journalist)
        menu.addAction(delete_action)
        
        menu.exec(self.table.viewport().mapToGlobal(position))
    
    def add_journalist(self):
        """Add new journalist"""
        dialog = JournalistDialog(self)
        if dialog.exec():
            journalist = dialog.get_journalist()
            self.journalist_db.add_journalist(journalist)
            self.refresh()
    
    def edit_journalist(self):
        """Edit selected journalist"""
        if not self.selected_journalist:
            return
        
        dialog = JournalistDialog(self, self.selected_journalist)
        if dialog.exec():
            journalist = dialog.get_journalist()
            journalist.id = self.selected_journalist.id
            self.journalist_db.update_journalist(journalist)
            self.refresh()
    
    def delete_journalist(self):
        """Delete selected journalist"""
        if not self.selected_journalist:
            return
        
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete journalist {self.selected_journalist.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.journalist_db.delete_journalist(self.selected_journalist.id)
            self.refresh()
    
    def log_pitch(self):
        """Log a pitch interaction"""
        if not self.selected_journalist:
            QMessageBox.warning(self, "No Selection", "Please select a journalist first.")
            return
        
        dialog = InteractionDialog(self, "pitched")
        if dialog.exec():
            interaction = JournalistInteraction(
                journalist_id=self.selected_journalist.id,
                interaction_type="pitched",
                campaign_name=dialog.campaign_name.text(),
                pitch_angle=dialog.pitch_angle.toPlainText(),
                notes=dialog.notes.toPlainText()
            )
            self.journalist_db.log_interaction(interaction)
            self.refresh()
    
    def log_feature(self):
        """Log a feature/coverage"""
        if not self.selected_journalist:
            QMessageBox.warning(self, "No Selection", "Please select a journalist first.")
            return
        
        dialog = InteractionDialog(self, "featured")
        if dialog.exec():
            interaction = JournalistInteraction(
                journalist_id=self.selected_journalist.id,
                interaction_type="featured",
                campaign_name=dialog.campaign_name.text(),
                article_url=dialog.article_url.text() if hasattr(dialog, 'article_url') else "",
                article_title=dialog.article_title.text() if hasattr(dialog, 'article_title') else "",
                link_obtained=dialog.link_obtained.isChecked() if hasattr(dialog, 'link_obtained') else False,
                notes=dialog.notes.toPlainText()
            )
            self.journalist_db.log_interaction(interaction)
            self.refresh()
    
    def save_notes(self):
        """Save notes for selected journalist"""
        if not self.selected_journalist:
            return
        
        self.selected_journalist.notes = self.notes_edit.toPlainText()
        self.journalist_db.update_journalist(self.selected_journalist)
        
        QMessageBox.information(self, "Saved", "Notes saved successfully.")
    
    def import_journalists(self):
        """Import journalists from CSV"""
        from PyQt6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Journalists CSV", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            column_mapping = {
                'name': 'name',
                'email': 'email',
                'outlet': 'outlet',
                'title': 'title',
                'twitter': 'twitter',
                'beat': 'beat'
            }
            
            imported, skipped = self.journalist_db.import_journalists_csv(
                file_path, column_mapping
            )
            
            QMessageBox.information(
                self, "Import Complete",
                f"Imported {imported} journalists.\n{skipped} skipped."
            )
            self.refresh()
    
    def create_campaign(self):
        """Create new PR campaign"""
        dialog = CampaignDialog(self, self.journalist_db)
        if dialog.exec():
            self.refresh()
            QMessageBox.information(self, "Success", "Campaign created successfully.")


class JournalistDialog(QDialog):
    """Dialog for adding/editing journalists"""
    
    def __init__(self, parent=None, journalist: Journalist = None):
        super().__init__(parent)
        self.journalist = journalist
        
        self.setWindowTitle("Edit Journalist" if journalist else "Add Journalist")
        self.setMinimumWidth(500)
        
        self.setup_ui()
        
        if journalist:
            self.load_journalist(journalist)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Full name")
        form.addRow("Name*:", self.name_edit)
        
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("email@example.com")
        form.addRow("Email:", self.email_edit)
        
        self.outlet_edit = QLineEdit()
        self.outlet_edit.setPlaceholderText("Publication/Website name")
        form.addRow("Outlet:", self.outlet_edit)
        
        self.outlet_dr = QSpinBox()
        self.outlet_dr.setRange(0, 100)
        form.addRow("Outlet DR:", self.outlet_dr)
        
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("e.g., Senior Reporter, Editor")
        form.addRow("Job Title:", self.title_edit)
        
        self.twitter_edit = QLineEdit()
        self.twitter_edit.setPlaceholderText("@username")
        form.addRow("Twitter:", self.twitter_edit)
        
        self.linkedin_edit = QLineEdit()
        self.linkedin_edit.setPlaceholderText("LinkedIn profile URL")
        form.addRow("LinkedIn:", self.linkedin_edit)
        
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("Phone number")
        form.addRow("Phone:", self.phone_edit)
        
        self.beat_edit = QLineEdit()
        self.beat_edit.setPlaceholderText("Technology, Marketing, Finance (comma-separated)")
        form.addRow("Beat/Topics:", self.beat_edit)
        
        self.preferred_contact = QComboBox()
        self.preferred_contact.addItems(["email", "twitter", "linkedin", "phone"])
        form.addRow("Preferred Contact:", self.preferred_contact)
        
        self.best_time_edit = QLineEdit()
        self.best_time_edit.setPlaceholderText("e.g., Tuesday-Thursday mornings")
        form.addRow("Best Pitch Time:", self.best_time_edit)
        
        self.pitch_style_edit = QLineEdit()
        self.pitch_style_edit.setPlaceholderText("e.g., Data-driven, short and direct")
        form.addRow("Pitch Style:", self.pitch_style_edit)
        
        layout.addLayout(form)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def load_journalist(self, journalist: Journalist):
        """Load journalist data into form"""
        self.name_edit.setText(journalist.name)
        self.email_edit.setText(journalist.email or "")
        self.outlet_edit.setText(journalist.current_outlet or "")
        self.outlet_dr.setValue(journalist.outlet_dr or 0)
        self.title_edit.setText(journalist.job_title or "")
        self.twitter_edit.setText(journalist.twitter or "")
        self.linkedin_edit.setText(journalist.linkedin or "")
        self.phone_edit.setText(journalist.phone or "")
        self.beat_edit.setText(", ".join(journalist.beat) if journalist.beat else "")
        self.best_time_edit.setText(journalist.best_pitch_time or "")
        self.pitch_style_edit.setText(journalist.pitch_style or "")
        
        idx = self.preferred_contact.findText(journalist.preferred_contact or "email")
        if idx >= 0:
            self.preferred_contact.setCurrentIndex(idx)
    
    def validate_and_accept(self):
        """Validate form and accept"""
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Name is required.")
            return
        
        self.accept()
    
    def get_journalist(self) -> Journalist:
        """Get journalist from form"""
        beat_text = self.beat_edit.text().strip()
        beat = [b.strip() for b in beat_text.split(',') if b.strip()] if beat_text else []
        
        return Journalist(
            name=self.name_edit.text().strip(),
            email=self.email_edit.text().strip(),
            current_outlet=self.outlet_edit.text().strip(),
            outlet_dr=self.outlet_dr.value(),
            job_title=self.title_edit.text().strip(),
            twitter=self.twitter_edit.text().strip(),
            linkedin=self.linkedin_edit.text().strip(),
            phone=self.phone_edit.text().strip(),
            beat=beat,
            preferred_contact=self.preferred_contact.currentText(),
            best_pitch_time=self.best_time_edit.text().strip(),
            pitch_style=self.pitch_style_edit.text().strip()
        )


class InteractionDialog(QDialog):
    """Dialog for logging interactions"""
    
    def __init__(self, parent=None, interaction_type: str = "pitched"):
        super().__init__(parent)
        self.interaction_type = interaction_type
        
        title_map = {
            "pitched": "Log Pitch",
            "featured": "Log Feature/Coverage",
            "responded": "Log Response",
        }
        
        self.setWindowTitle(title_map.get(interaction_type, "Log Interaction"))
        self.setMinimumWidth(450)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        self.campaign_name = QLineEdit()
        self.campaign_name.setPlaceholderText("Campaign or project name")
        form.addRow("Campaign:", self.campaign_name)
        
        if self.interaction_type == "pitched":
            self.pitch_angle = QTextEdit()
            self.pitch_angle.setPlaceholderText("What angle/topic did you pitch?")
            self.pitch_angle.setMaximumHeight(100)
            form.addRow("Pitch Angle:", self.pitch_angle)
        
        if self.interaction_type == "featured":
            self.article_title = QLineEdit()
            self.article_title.setPlaceholderText("Title of the article")
            form.addRow("Article Title:", self.article_title)
            
            self.article_url = QLineEdit()
            self.article_url.setPlaceholderText("https://...")
            form.addRow("Article URL:", self.article_url)
            
            self.link_obtained = QCheckBox("Link to our site obtained")
            form.addRow("", self.link_obtained)
        
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Additional notes...")
        self.notes.setMaximumHeight(80)
        form.addRow("Notes:", self.notes)
        
        layout.addLayout(form)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CampaignDialog(QDialog):
    """Dialog for creating PR campaigns"""
    
    def __init__(self, parent=None, journalist_db: JournalistDatabase = None):
        super().__init__(parent)
        self.journalist_db = journalist_db
        
        self.setWindowTitle("Create PR Campaign")
        self.setMinimumSize(600, 500)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Campaign details
        details_group = QGroupBox("Campaign Details")
        details_layout = QFormLayout(details_group)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Q1 2024 SEO Survey")
        details_layout.addRow("Campaign Name*:", self.name_edit)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Data Story",
            "Expert Commentary",
            "Newsjacking",
            "Product Launch",
            "Research/Survey",
            "Other"
        ])
        details_layout.addRow("Campaign Type:", self.type_combo)
        
        self.asset_title = QLineEdit()
        self.asset_title.setPlaceholderText("Title of your content asset")
        details_layout.addRow("Asset Title:", self.asset_title)
        
        self.asset_url = QLineEdit()
        self.asset_url.setPlaceholderText("https://yoursite.com/asset")
        details_layout.addRow("Asset URL:", self.asset_url)
        
        self.description = QTextEdit()
        self.description.setPlaceholderText("Brief description of the campaign...")
        self.description.setMaximumHeight(80)
        details_layout.addRow("Description:", self.description)
        
        self.key_findings = QTextEdit()
        self.key_findings.setPlaceholderText("Key findings or talking points (one per line)")
        self.key_findings.setMaximumHeight(80)
        details_layout.addRow("Key Findings:", self.key_findings)
        
        layout.addWidget(details_group)
        
        # Target journalists
        targets_group = QGroupBox("Target Journalists (select from database)")
        targets_layout = QVBoxLayout(targets_group)
        
        # Search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.journalist_search = QLineEdit()
        self.journalist_search.setPlaceholderText("Filter journalists...")
        self.journalist_search.textChanged.connect(self.filter_journalists)
        search_layout.addWidget(self.journalist_search)
        targets_layout.addLayout(search_layout)
        
        # Journalist list
        self.journalist_list = QListWidget()
        self.journalist_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        targets_layout.addWidget(self.journalist_list)
        
        # Load journalists
        self.load_journalists()
        
        layout.addWidget(targets_group)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.create_campaign)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def load_journalists(self, query: str = None):
        """Load journalists into list"""
        self.journalist_list.clear()
        
        if self.journalist_db:
            journalists = self.journalist_db.search_journalists(query=query, limit=200)
            
            for j in journalists:
                item_text = f"{j.name} - {j.current_outlet} (DR: {j.outlet_dr})"
                from PyQt6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, j.id)
                self.journalist_list.addItem(item)
    
    def filter_journalists(self, text: str):
        """Filter journalist list"""
        self.load_journalists(query=text if text else None)
    
    def create_campaign(self):
        """Create the campaign"""
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Campaign name is required.")
            return
        
        # Get key findings as list
        findings_text = self.key_findings.toPlainText().strip()
        key_findings = [f.strip() for f in findings_text.split('\n') if f.strip()] if findings_text else []
        
        # Create campaign
        campaign_id = self.journalist_db.create_campaign(
            name=self.name_edit.text().strip(),
            campaign_type=self.type_combo.currentText(),
            asset_title=self.asset_title.text().strip(),
            asset_url=self.asset_url.text().strip(),
            description=self.description.toPlainText().strip(),
            key_findings=key_findings
        )
        
        # Add selected journalists as targets
        for item in self.journalist_list.selectedItems():
            journalist_id = item.data(Qt.ItemDataRole.UserRole)
            self.journalist_db.add_campaign_target(campaign_id, journalist_id)
        
        self.accept()