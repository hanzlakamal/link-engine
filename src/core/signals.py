"""
Custom Qt Signals for Cross-Component Communication
"""
from PyQt6.QtCore import QObject, pyqtSignal
from typing import Any


class AppSignals(QObject):
    """Global application signals"""
    
    # Domain signals
    domain_added = pyqtSignal(int)  # domain_id
    domain_updated = pyqtSignal(int)  # domain_id
    domain_deleted = pyqtSignal(int)  # domain_id
    domains_imported = pyqtSignal(int, int)  # inserted, skipped
    
    # Analysis signals
    analysis_started = pyqtSignal(int)  # domain_id
    analysis_completed = pyqtSignal(int, dict)  # domain_id, result
    analysis_failed = pyqtSignal(int, str)  # domain_id, error
    
    # Outreach signals
    email_generated = pyqtSignal(int)  # submission_id
    email_queued = pyqtSignal(int)  # submission_id
    email_sent = pyqtSignal(int)  # submission_id
    email_failed = pyqtSignal(int, str)  # submission_id, error
    
    # Response signals
    response_received = pyqtSignal(int, str)  # submission_id, response_type
    
    # Link signals
    link_discovered = pyqtSignal(int)  # link_id
    link_verified = pyqtSignal(int, str)  # link_id, status
    link_removed = pyqtSignal(int)  # link_id
    
    # Progress signals
    task_started = pyqtSignal(str, int)  # task_name, total_items
    task_progress = pyqtSignal(str, int, int, str)  # task_name, current, total, message
    task_completed = pyqtSignal(str, dict)  # task_name, result
    task_failed = pyqtSignal(str, str)  # task_name, error
    
    # UI signals
    status_message = pyqtSignal(str)  # message
    notification = pyqtSignal(str, str, str)  # title, message, type (info/warning/error)
    refresh_required = pyqtSignal(str)  # component_name


# Global signals instance
app_signals = AppSignals()