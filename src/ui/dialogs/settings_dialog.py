"""
Settings Dialog - Configure all application settings
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QFormLayout, QGroupBox,
    QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QDialogButtonBox, QScrollArea, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt

from config import Settings
from core.logger import ui_logger


class SettingsDialog(QDialog):
    """Application settings dialog"""
    
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumSize(800, 700)
        
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Tab widget
        tabs = QTabWidget()
        
        # API Keys tab
        tabs.addTab(self.create_api_tab(), "🔑 API Keys")
        
        # Email tab
        tabs.addTab(self.create_email_tab(), "📧 Email")
        
        # AI Prompts tab
        tabs.addTab(self.create_prompts_tab(), "🤖 AI Prompts")
        
        # Scoring tab
        tabs.addTab(self.create_scoring_tab(), "📊 Scoring")
        
        # General tab
        tabs.addTab(self.create_general_tab(), "⚙️ General")
        
        layout.addWidget(tabs)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        
        layout.addWidget(buttons)
    
    def create_api_tab(self) -> QWidget:
        """Create API keys configuration tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Ahrefs
        ahrefs_group = QGroupBox("Ahrefs API")
        ahrefs_layout = QFormLayout(ahrefs_group)
        
        self.ahrefs_key = QLineEdit()
        self.ahrefs_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ahrefs_key.setPlaceholderText("Enter your Ahrefs API key")
        ahrefs_layout.addRow("API Key:", self.ahrefs_key)
        
        layout.addWidget(ahrefs_group)
        
        # AI APIs
        ai_group = QGroupBox("AI APIs")
        ai_layout = QFormLayout(ai_group)
        
        self.anthropic_key = QLineEdit()
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key.setPlaceholderText("Enter your Anthropic API key")
        ai_layout.addRow("Anthropic (Claude):", self.anthropic_key)
        
        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setPlaceholderText("Enter your OpenAI API key")
        ai_layout.addRow("OpenAI:", self.openai_key)
        
        layout.addWidget(ai_group)
        
        # Captcha
        captcha_group = QGroupBox("Captcha Solving")
        captcha_layout = QFormLayout(captcha_group)
        
        self.captcha_service = QComboBox()
        self.captcha_service.addItems(["2captcha", "anticaptcha", "capmonster"])
        captcha_layout.addRow("Service:", self.captcha_service)
        
        self.captcha_key = QLineEdit()
        self.captcha_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.captcha_key.setPlaceholderText("Enter your captcha service API key")
        captcha_layout.addRow("API Key:", self.captcha_key)
        
        layout.addWidget(captcha_group)
        
        layout.addStretch()
        
        return widget
    
    def create_email_tab(self) -> QWidget:
        """Create email configuration tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        smtp_group = QGroupBox("SMTP Settings")
        smtp_layout = QFormLayout(smtp_group)
        
        self.smtp_server = QLineEdit()
        self.smtp_server.setPlaceholderText("smtp.example.com")
        smtp_layout.addRow("SMTP Server:", self.smtp_server)
        
        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        self.smtp_port.setValue(587)
        smtp_layout.addRow("Port:", self.smtp_port)
        
        self.smtp_username = QLineEdit()
        smtp_layout.addRow("Username:", self.smtp_username)
        
        self.smtp_password = QLineEdit()
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        smtp_layout.addRow("Password:", self.smtp_password)
        
        layout.addWidget(smtp_group)
        
        sender_group = QGroupBox("Sender Information")
        sender_layout = QFormLayout(sender_group)
        
        self.sender_name = QLineEdit()
        self.sender_name.setPlaceholderText("John Smith")
        sender_layout.addRow("Name:", self.sender_name)
        
        self.sender_email = QLineEdit()
        self.sender_email.setPlaceholderText("john@example.com")
        sender_layout.addRow("Email:", self.sender_email)
        
        layout.addWidget(sender_group)
        
        limits_group = QGroupBox("Sending Limits")
        limits_layout = QFormLayout(limits_group)
        
        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(1, 500)
        self.daily_limit.setValue(50)
        limits_layout.addRow("Daily Send Limit:", self.daily_limit)
        
        self.delay_min = QSpinBox()
        self.delay_min.setRange(30, 3600)
        self.delay_min.setValue(180)
        self.delay_min.setSuffix(" seconds")
        limits_layout.addRow("Min Delay Between Emails:", self.delay_min)
        
        self.delay_max = QSpinBox()
        self.delay_max.setRange(60, 7200)
        self.delay_max.setValue(600)
        self.delay_max.setSuffix(" seconds")
        limits_layout.addRow("Max Delay Between Emails:", self.delay_max)
        
        layout.addWidget(limits_group)
        
        layout.addStretch()
        
        return widget
    
    def create_prompts_tab(self) -> QWidget:
        """Create AI prompts configuration tab"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        info_label = QLabel(
            "⚠️ These prompts are used by the AI to analyze websites and generate content. "
            "Modify carefully - incorrect prompts may cause analysis failures."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #f39c12; padding: 10px; background-color: #2d2d44; border-radius: 8px;")
        layout.addWidget(info_label)
        
        # Guidelines extraction prompt
        guidelines_group = QGroupBox("Guidelines Extraction Prompt")
        guidelines_layout = QVBoxLayout(guidelines_group)
        
        self.guidelines_prompt = QTextEdit()
        self.guidelines_prompt.setMinimumHeight(200)
        self.guidelines_prompt.setPlaceholderText("Enter the prompt for extracting guest posting guidelines...")
        guidelines_layout.addWidget(self.guidelines_prompt)
        
        guidelines_help = QLabel("Variables: {page_content}")
        guidelines_help.setStyleSheet("color: #8892b0; font-size: 11px;")
        guidelines_layout.addWidget(guidelines_help)
        
        layout.addWidget(guidelines_group)
        
        # Email generation prompt
        email_group = QGroupBox("Email Generation Prompt")
        email_layout = QVBoxLayout(email_group)
        
        self.email_prompt = QTextEdit()
        self.email_prompt.setMinimumHeight(200)
        self.email_prompt.setPlaceholderText("Enter the prompt for generating outreach emails...")
        email_layout.addWidget(self.email_prompt)
        
        email_help = QLabel("Variables: {domain}, {site_name}, {niche}, {recent_articles}, {guidelines}, {sender_name}, {sender_website}, {expertise}, {relevant_content}")
        email_help.setWordWrap(True)
        email_help.setStyleSheet("color: #8892b0; font-size: 11px;")
        email_layout.addWidget(email_help)
        
        layout.addWidget(email_group)
        
        # Response analysis prompt
        response_group = QGroupBox("Response Analysis Prompt")
        response_layout = QVBoxLayout(response_group)
        
        self.response_prompt = QTextEdit()
        self.response_prompt.setMinimumHeight(150)
        self.response_prompt.setPlaceholderText("Enter the prompt for analyzing email responses...")
        response_layout.addWidget(self.response_prompt)
        
        response_help = QLabel("Variables: {pitch_summary}, {response_text}")
        response_help.setStyleSheet("color: #8892b0; font-size: 11px;")
        response_layout.addWidget(response_help)
        
        layout.addWidget(response_group)
        
        # Contact detection prompt
        contact_group = QGroupBox("Contact Detection Prompt")
        contact_layout = QVBoxLayout(contact_group)
        
        self.contact_prompt = QTextEdit()
        self.contact_prompt.setMinimumHeight(150)
        self.contact_prompt.setPlaceholderText("Enter the prompt for detecting contact methods...")
        contact_layout.addWidget(self.contact_prompt)
        
        contact_help = QLabel("Variables: {url}, {page_content}")
        contact_help.setStyleSheet("color: #8892b0; font-size: 11px;")
        contact_layout.addWidget(contact_help)
        
        layout.addWidget(contact_group)
        
        # Reset button
        reset_btn = QPushButton("🔄 Reset to Defaults")
        reset_btn.clicked.connect(self.reset_prompts)
        layout.addWidget(reset_btn)
        
        layout.addStretch()
        
        scroll.setWidget(widget)
        return scroll
    
    def create_scoring_tab(self) -> QWidget:
        """Create domain scoring configuration tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        weights_group = QGroupBox("Scoring Weights")
        weights_layout = QFormLayout(weights_group)
        
        info = QLabel("Weights must sum to 1.0 (100%)")
        info.setStyleSheet("color: #8892b0;")
        weights_layout.addRow("", info)
        
        self.dr_weight = QDoubleSpinBox()
        self.dr_weight.setRange(0, 1)
        self.dr_weight.setSingleStep(0.05)
        self.dr_weight.setDecimals(2)
        weights_layout.addRow("Domain Rating Weight:", self.dr_weight)
        
        self.traffic_weight = QDoubleSpinBox()
        self.traffic_weight.setRange(0, 1)
        self.traffic_weight.setSingleStep(0.05)
        self.traffic_weight.setDecimals(2)
        weights_layout.addRow("Traffic Weight:", self.traffic_weight)
        
        self.refs_weight = QDoubleSpinBox()
        self.refs_weight.setRange(0, 1)
        self.refs_weight.setSingleStep(0.05)
        self.refs_weight.setDecimals(2)
        weights_layout.addRow("Referring Domains Weight:", self.refs_weight)
        
        self.relevance_weight = QDoubleSpinBox()
        self.relevance_weight.setRange(0, 1)
        self.relevance_weight.setSingleStep(0.05)
        self.relevance_weight.setDecimals(2)
        weights_layout.addRow("Relevance Weight:", self.relevance_weight)
        
        layout.addWidget(weights_group)
        
        thresholds_group = QGroupBox("Thresholds")
        thresholds_layout = QFormLayout(thresholds_group)
        
        self.min_dr = QSpinBox()
        self.min_dr.setRange(0, 100)
        thresholds_layout.addRow("Minimum DR:", self.min_dr)
        
        self.min_traffic = QSpinBox()
        self.min_traffic.setRange(0, 1000000)
        self.min_traffic.setSingleStep(1000)
        thresholds_layout.addRow("Minimum Traffic:", self.min_traffic)
        
        layout.addWidget(thresholds_group)
        
        layout.addStretch()
        
        return widget
    
    def create_general_tab(self) -> QWidget:
        """Create general settings tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance_group)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        appearance_layout.addRow("Theme:", self.theme_combo)
        
        layout.addWidget(appearance_group)
        
        behavior_group = QGroupBox("Behavior")
        behavior_layout = QFormLayout(behavior_group)
        
        self.auto_analyze = QCheckBox()
        behavior_layout.addRow("Auto-analyze on import:", self.auto_analyze)
        
        self.screenshot_on_analysis = QCheckBox()
        behavior_layout.addRow("Take screenshots during analysis:", self.screenshot_on_analysis)
        
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 20)
        behavior_layout.addRow("Max concurrent analyses:", self.max_concurrent)
        
        layout.addWidget(behavior_group)
        
        logging_group = QGroupBox("Logging")
        logging_layout = QFormLayout(logging_group)
        
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        logging_layout.addRow("Log Level:", self.log_level)
        
        self.log_retention = QSpinBox()
        self.log_retention.setRange(1, 365)
        self.log_retention.setSuffix(" days")
        logging_layout.addRow("Log Retention:", self.log_retention)
        
        layout.addWidget(logging_group)
        
        network_group = QGroupBox("Network")
        network_layout = QFormLayout(network_group)
        
        self.request_timeout = QSpinBox()
        self.request_timeout.setRange(5, 120)
        self.request_timeout.setSuffix(" seconds")
        network_layout.addRow("Request Timeout:", self.request_timeout)
        
        self.retry_attempts = QSpinBox()
        self.retry_attempts.setRange(0, 10)
        network_layout.addRow("Retry Attempts:", self.retry_attempts)
        
        self.user_agent = QLineEdit()
        network_layout.addRow("User Agent:", self.user_agent)
        
        layout.addWidget(network_group)
        
        layout.addStretch()
        
        return widget
    
    def load_settings(self):
        """Load current settings into UI"""
        # API Keys
        self.ahrefs_key.setText(self.settings.api.ahrefs_api_key)
        self.anthropic_key.setText(self.settings.api.anthropic_api_key)
        self.openai_key.setText(self.settings.api.openai_api_key)
        self.captcha_key.setText(self.settings.api.captcha_api_key)
        
        index = self.captcha_service.findText(self.settings.api.captcha_service)
        if index >= 0:
            self.captcha_service.setCurrentIndex(index)
        
        # Email
        self.smtp_server.setText(self.settings.email.smtp_server)
        self.smtp_port.setValue(self.settings.email.smtp_port)
        self.smtp_username.setText(self.settings.email.smtp_username)
        self.smtp_password.setText(self.settings.email.smtp_password)
        self.sender_name.setText(self.settings.email.sender_name)
        self.sender_email.setText(self.settings.email.sender_email)
        self.daily_limit.setValue(self.settings.email.daily_send_limit)
        self.delay_min.setValue(self.settings.email.delay_between_emails_min)
        self.delay_max.setValue(self.settings.email.delay_between_emails_max)
        
        # Prompts
        self.guidelines_prompt.setPlainText(self.settings.prompts.guidelines_extraction)
        self.email_prompt.setPlainText(self.settings.prompts.email_generation)
        self.response_prompt.setPlainText(self.settings.prompts.response_analysis)
        self.contact_prompt.setPlainText(self.settings.prompts.contact_detection)
        
        # Scoring
        self.dr_weight.setValue(self.settings.scoring.domain_rating_weight)
        self.traffic_weight.setValue(self.settings.scoring.traffic_weight)
        self.refs_weight.setValue(self.settings.scoring.referring_domains_weight)
        self.relevance_weight.setValue(self.settings.scoring.relevance_weight)
        self.min_dr.setValue(self.settings.scoring.min_dr_threshold)
        self.min_traffic.setValue(self.settings.scoring.min_traffic_threshold)
        
        # General
        index = self.theme_combo.findText(self.settings.general.theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        
        self.auto_analyze.setChecked(self.settings.general.auto_analyze_on_import)
        self.screenshot_on_analysis.setChecked(self.settings.general.screenshot_on_analysis)
        self.max_concurrent.setValue(self.settings.general.max_concurrent_analyses)
        
        index = self.log_level.findText(self.settings.general.log_level)
        if index >= 0:
            self.log_level.setCurrentIndex(index)
        
        self.log_retention.setValue(self.settings.general.log_retention_days)
        self.request_timeout.setValue(self.settings.general.request_timeout)
        self.retry_attempts.setValue(self.settings.general.retry_attempts)
        self.user_agent.setText(self.settings.general.user_agent)
    
    def save_settings(self):
        """Save settings"""
        # Validate weights
        total_weight = (
            self.dr_weight.value() + 
            self.traffic_weight.value() + 
            self.refs_weight.value() + 
            self.relevance_weight.value()
        )
        
        if abs(total_weight - 1.0) > 0.01:
            QMessageBox.warning(
                self, "Invalid Weights",
                f"Scoring weights must sum to 1.0. Current sum: {total_weight:.2f}"
            )
            return
        
        # API Keys
        self.settings.api.ahrefs_api_key = self.ahrefs_key.text()
        self.settings.api.anthropic_api_key = self.anthropic_key.text()
        self.settings.api.openai_api_key = self.openai_key.text()
        self.settings.api.captcha_api_key = self.captcha_key.text()
        self.settings.api.captcha_service = self.captcha_service.currentText()
        
        # Email
        self.settings.email.smtp_server = self.smtp_server.text()
        self.settings.email.smtp_port = self.smtp_port.value()
        self.settings.email.smtp_username = self.smtp_username.text()
        self.settings.email.smtp_password = self.smtp_password.text()
        self.settings.email.sender_name = self.sender_name.text()
        self.settings.email.sender_email = self.sender_email.text()
        self.settings.email.daily_send_limit = self.daily_limit.value()
        self.settings.email.delay_between_emails_min = self.delay_min.value()
        self.settings.email.delay_between_emails_max = self.delay_max.value()
        
        # Prompts
        self.settings.prompts.guidelines_extraction = self.guidelines_prompt.toPlainText()
        self.settings.prompts.email_generation = self.email_prompt.toPlainText()
        self.settings.prompts.response_analysis = self.response_prompt.toPlainText()
        self.settings.prompts.contact_detection = self.contact_prompt.toPlainText()
        
        # Scoring
        self.settings.scoring.domain_rating_weight = self.dr_weight.value()
        self.settings.scoring.traffic_weight = self.traffic_weight.value()
        self.settings.scoring.referring_domains_weight = self.refs_weight.value()
        self.settings.scoring.relevance_weight = self.relevance_weight.value()
        self.settings.scoring.min_dr_threshold = self.min_dr.value()
        self.settings.scoring.min_traffic_threshold = self.min_traffic.value()
        
        # General
        self.settings.general.theme = self.theme_combo.currentText()
        self.settings.general.auto_analyze_on_import = self.auto_analyze.isChecked()
        self.settings.general.screenshot_on_analysis = self.screenshot_on_analysis.isChecked()
        self.settings.general.max_concurrent_analyses = self.max_concurrent.value()
        self.settings.general.log_level = self.log_level.currentText()
        self.settings.general.log_retention_days = self.log_retention.value()
        self.settings.general.request_timeout = self.request_timeout.value()
        self.settings.general.retry_attempts = self.retry_attempts.value()
        self.settings.general.user_agent = self.user_agent.text()
        
        # Save to file
        self.settings.save()
        
        ui_logger.info("Settings saved")
        self.accept()
    
    def reset_prompts(self):
        """Reset prompts to defaults"""
        from config import AIPrompts
        defaults = AIPrompts()
        
        self.guidelines_prompt.setPlainText(defaults.guidelines_extraction)
        self.email_prompt.setPlainText(defaults.email_generation)
        self.response_prompt.setPlainText(defaults.response_analysis)
        self.contact_prompt.setPlainText(defaults.contact_detection)
        
        QMessageBox.information(self, "Reset", "Prompts reset to defaults.")