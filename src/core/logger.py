"""
Advanced Logging System with UI Integration
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
from PyQt6.QtCore import QObject, pyqtSignal


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    """Structured log entry"""
    timestamp: datetime
    level: LogLevel
    module: str
    message: str
    details: Optional[dict] = None
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'level': self.level.value,
            'module': self.module,
            'message': self.message,
            'details': self.details
        }
    
    def formatted(self) -> str:
        """Return formatted string for display"""
        ts = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        return f"[{ts}] [{self.level.value:8}] [{self.module:20}] {self.message}"


class LogSignals(QObject):
    """Qt signals for log updates"""
    new_log = pyqtSignal(object)  # LogEntry
    

class LogHandler:
    """Custom log handler that emits Qt signals"""
    
    def __init__(self):
        self.signals = LogSignals()
        self.entries: List[LogEntry] = []
        self.max_entries = 10000
    
    def write(self, message):
        """Called by loguru"""
        record = message.record
        
        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel(record["level"].name),
            module=record["name"] or "main",
            message=record["message"],
            details=record.get("extra")
        )
        
        self.entries.append(entry)
        
        # Trim old entries
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]
        
        # Emit signal for UI
        self.signals.new_log.emit(entry)
    
    def get_entries(self, 
                    level_filter: Optional[LogLevel] = None,
                    module_filter: Optional[str] = None,
                    limit: int = 1000) -> List[LogEntry]:
        """Get filtered log entries"""
        entries = self.entries
        
        if level_filter:
            entries = [e for e in entries if e.level == level_filter]
        
        if module_filter:
            entries = [e for e in entries if module_filter.lower() in e.module.lower()]
        
        return entries[-limit:]
    
    def clear(self):
        """Clear all log entries"""
        self.entries.clear()


# Global log handler instance
log_handler = LogHandler()

# Create module-specific loggers
app_logger = logger.bind(name="app")
db_logger = logger.bind(name="database")
api_logger = logger.bind(name="api")
analysis_logger = logger.bind(name="analysis")
outreach_logger = logger.bind(name="outreach")
ui_logger = logger.bind(name="ui")


def setup_logger(log_dir: Optional[Path] = None):
    """Configure the logging system"""
    
    if log_dir is None:
        log_dir = Path.home() / ".backlink_engine" / "logs"
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Remove default handler
    logger.remove()
    
    # Add console handler with colors
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{extra[name]: <15}</cyan> | <level>{message}</level>",
        level="DEBUG",
        colorize=True
    )
    
    # Add file handler with rotation
    logger.add(
        log_dir / "backlink_engine_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[name]: <15} | {message}",
        level="DEBUG",
        rotation="00:00",  # New file each day
        retention="30 days",
        compression="zip"
    )
    
    # Add error-specific file
    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[name]: <15} | {message}\n{exception}",
        level="ERROR",
        rotation="00:00",
        retention="90 days"
    )
    
    # Add custom handler for UI integration
    logger.add(
        log_handler.write,
        format="{message}",
        level="DEBUG"
    )
    
    logger.info("Logging system initialized", name="logger")


def log_function_call(func):
    """Decorator to log function calls"""
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        module = func.__module__.split('.')[-1]
        
        logger.debug(f"Calling {func_name}()", name=module)
        
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func_name}() completed successfully", name=module)
            return result
        except Exception as e:
            logger.error(f"{func_name}() failed: {e}", name=module)
            raise
    
    return wrapper