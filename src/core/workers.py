"""
Background Worker Threads for Long-Running Tasks
"""
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from typing import List, Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum
import time
import traceback

from core.logger import app_logger


class WorkerStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class WorkerProgress:
    """Progress update data"""
    current: int
    total: int
    message: str
    data: Any = None
    
    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0
        return (self.current / self.total) * 100


class BaseWorker(QThread):
    """Base class for background workers"""
    
    # Signals
    started_signal = pyqtSignal()
    progress = pyqtSignal(object)  # WorkerProgress
    finished_signal = pyqtSignal(object)  # Result data
    error = pyqtSignal(str, str)  # Error message, traceback
    status_changed = pyqtSignal(str)  # WorkerStatus
    log = pyqtSignal(str, str)  # level, message
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = WorkerStatus.IDLE
        self._should_stop = False
        self._should_pause = False
        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()
    
    @property
    def status(self) -> WorkerStatus:
        return self._status
    
    def stop(self):
        """Request the worker to stop"""
        self._should_stop = True
        self._should_pause = False
        self._pause_condition.wakeAll()
        self._set_status(WorkerStatus.STOPPING)
    
    def pause(self):
        """Pause the worker"""
        self._should_pause = True
        self._set_status(WorkerStatus.PAUSED)
    
    def resume(self):
        """Resume the worker"""
        self._should_pause = False
        self._pause_condition.wakeAll()
        self._set_status(WorkerStatus.RUNNING)
    
    def _set_status(self, status: WorkerStatus):
        self._status = status
        self.status_changed.emit(status.value)
    
    def _check_pause(self):
        """Check if should pause and wait"""
        self._mutex.lock()
        while self._should_pause and not self._should_stop:
            self._pause_condition.wait(self._mutex)
        self._mutex.unlock()
    
    def _emit_progress(self, current: int, total: int, message: str, data: Any = None):
        """Emit progress update"""
        self.progress.emit(WorkerProgress(current, total, message, data))
    
    def _emit_log(self, level: str, message: str):
        """Emit log message"""
        self.log.emit(level, message)
    
    def run(self):
        """Main worker execution - override in subclass"""
        raise NotImplementedError


class DomainAnalysisWorker(BaseWorker):
    """Worker for analyzing domains"""
    
    def __init__(self, domains: List[Any], analyzer: Any, parent=None):
        super().__init__(parent)
        self.domains = domains
        self.analyzer = analyzer
        self.results = []
    
    def run(self):
        self._set_status(WorkerStatus.RUNNING)
        self.started_signal.emit()
        
        total = len(self.domains)
        self._emit_log("INFO", f"Starting analysis of {total} domains")
        
        try:
            for i, domain in enumerate(self.domains):
                # Check for stop/pause
                if self._should_stop:
                    self._emit_log("WARNING", "Analysis stopped by user")
                    break
                
                self._check_pause()
                
                # Analyze domain
                self._emit_progress(i, total, f"Analyzing {domain.domain}...")
                self._emit_log("DEBUG", f"Analyzing domain: {domain.domain}")
                
                try:
                    result = self.analyzer.analyze(domain)
                    self.results.append(result)
                    self._emit_log("INFO", f"✓ {domain.domain} analyzed successfully")
                except Exception as e:
                    self._emit_log("ERROR", f"✗ {domain.domain} failed: {str(e)}")
                
                # Small delay to prevent overwhelming
                time.sleep(0.5)
            
            self._emit_progress(total, total, "Analysis complete")
            self._set_status(WorkerStatus.FINISHED)
            self.finished_signal.emit(self.results)
            
        except Exception as e:
            self._set_status(WorkerStatus.ERROR)
            self.error.emit(str(e), traceback.format_exc())


class EnrichmentWorker(BaseWorker):
    """Worker for enriching domains with Ahrefs data"""
    
    def __init__(self, domains: List[Any], ahrefs_api: Any, db: Any, parent=None):
        super().__init__(parent)
        self.domains = domains
        self.ahrefs_api = ahrefs_api
        self.db = db
    
    def run(self):
        self._set_status(WorkerStatus.RUNNING)
        self.started_signal.emit()
        
        total = len(self.domains)
        enriched = 0
        failed = 0
        
        self._emit_log("INFO", f"Starting enrichment of {total} domains via Ahrefs")
        
        try:
            for i, domain in enumerate(self.domains):
                if self._should_stop:
                    break
                
                self._check_pause()
                self._emit_progress(i, total, f"Enriching {domain.domain}...")
                
                try:
                    # Get Ahrefs data
                    metrics = self.ahrefs_api.get_domain_metrics(domain.domain)
                    
                    if metrics:
                        # Calculate score
                        score = self._calculate_score(metrics)
                        
                        # Update database
                        self.db.update_domain_metrics(
                            domain.id,
                            dr=metrics.get('domain_rating', 0),
                            traffic=metrics.get('organic_traffic', 0),
                            referring_domains=metrics.get('referring_domains', 0),
                            quality_score=score
                        )
                        
                        enriched += 1
                        self._emit_log("INFO", f"✓ {domain.domain}: DR={metrics.get('domain_rating', 0)}, Traffic={metrics.get('organic_traffic', 0)}")
                    else:
                        failed += 1
                        self._emit_log("WARNING", f"✗ {domain.domain}: No data returned")
                
                except Exception as e:
                    failed += 1
                    self._emit_log("ERROR", f"✗ {domain.domain}: {str(e)}")
                
                # Rate limiting
                time.sleep(1)
            
            self._emit_progress(total, total, f"Enrichment complete: {enriched} success, {failed} failed")
            self._set_status(WorkerStatus.FINISHED)
            self.finished_signal.emit({'enriched': enriched, 'failed': failed})
            
        except Exception as e:
            self._set_status(WorkerStatus.ERROR)
            self.error.emit(str(e), traceback.format_exc())
    
    def _calculate_score(self, metrics: dict) -> float:
        """Calculate quality score from metrics"""
        dr = min(metrics.get('domain_rating', 0), 100)
        traffic = min(metrics.get('organic_traffic', 0) / 1000, 100)
        refs = min(metrics.get('referring_domains', 0) / 100, 100)
        
        score = (dr * 0.35) + (traffic * 0.35) + (refs * 0.30)
        return round(score, 2)


class OutreachWorker(BaseWorker):
    """Worker for sending outreach emails"""
    
    def __init__(self, submissions: List[Any], email_sender: Any, db: Any, parent=None):
        super().__init__(parent)
        self.submissions = submissions
        self.email_sender = email_sender
        self.db = db
    
    def run(self):
        self._set_status(WorkerStatus.RUNNING)
        self.started_signal.emit()
        
        total = len(self.submissions)
        sent = 0
        failed = 0
        
        self._emit_log("INFO", f"Starting outreach: {total} emails to send")
        
        try:
            for i, submission in enumerate(self.submissions):
                if self._should_stop:
                    break
                
                self._check_pause()
                self._emit_progress(i, total, f"Sending to {submission['domain']}...")
                
                try:
                    # Send email
                    result = self.email_sender.send(
                        to_email=submission['to_email'],
                        subject=submission['subject'],
                        body=submission['message']
                    )
                    
                    if result['success']:
                        sent += 1
                        self._emit_log("INFO", f"✓ Sent to {submission['domain']}")
                    else:
                        failed += 1
                        self._emit_log("ERROR", f"✗ {submission['domain']}: {result['error']}")
                
                except Exception as e:
                    failed += 1
                    self._emit_log("ERROR", f"✗ {submission['domain']}: {str(e)}")
                
                # Delay between emails (configurable)
                time.sleep(5)
            
            self._emit_progress(total, total, f"Outreach complete: {sent} sent, {failed} failed")
            self._set_status(WorkerStatus.FINISHED)
            self.finished_signal.emit({'sent': sent, 'failed': failed})
            
        except Exception as e:
            self._set_status(WorkerStatus.ERROR)
            self.error.emit(str(e), traceback.format_exc())