"""
Task Scheduler for Background Jobs
"""
import schedule
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from core.logger import app_logger


class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ScheduledTask:
    """Represents a scheduled task"""
    id: str
    name: str
    function: Callable
    interval_minutes: int
    priority: TaskPriority = TaskPriority.NORMAL
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None


class TaskScheduler:
    """Background task scheduler"""
    
    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def add_task(self, task_id: str, name: str, function: Callable,
                interval_minutes: int, priority: TaskPriority = TaskPriority.NORMAL) -> ScheduledTask:
        """Add a scheduled task"""
        task = ScheduledTask(
            id=task_id,
            name=name,
            function=function,
            interval_minutes=interval_minutes,
            priority=priority,
            next_run=datetime.now() + timedelta(minutes=interval_minutes)
        )
        
        with self._lock:
            self.tasks[task_id] = task
        
        app_logger.info(f"Scheduled task added: {name} (every {interval_minutes} minutes)")
        return task
    
    def remove_task(self, task_id: str):
        """Remove a scheduled task"""
        with self._lock:
            if task_id in self.tasks:
                del self.tasks[task_id]
                app_logger.info(f"Scheduled task removed: {task_id}")
    
    def enable_task(self, task_id: str):
        """Enable a task"""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].enabled = True
    
    def disable_task(self, task_id: str):
        """Disable a task"""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].enabled = False
    
    def run_task_now(self, task_id: str):
        """Run a task immediately"""
        with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                self._execute_task(task)
    
    def _execute_task(self, task: ScheduledTask):
        """Execute a task"""
        if not task.enabled:
            return
        
        app_logger.debug(f"Executing scheduled task: {task.name}")
        
        try:
            task.function()
            task.last_run = datetime.now()
            task.next_run = datetime.now() + timedelta(minutes=task.interval_minutes)
            task.run_count += 1
            app_logger.debug(f"Task {task.name} completed successfully")
        except Exception as e:
            task.error_count += 1
            task.last_error = str(e)
            app_logger.error(f"Task {task.name} failed: {e}")
    
    def _scheduler_loop(self):
        """Main scheduler loop"""
        while self._running:
            now = datetime.now()
            
            with self._lock:
                # Sort tasks by priority and next run time
                pending_tasks = [
                    t for t in self.tasks.values()
                    if t.enabled and t.next_run and t.next_run <= now
                ]
                pending_tasks.sort(key=lambda t: (-t.priority.value, t.next_run))
            
            for task in pending_tasks:
                if not self._running:
                    break
                self._execute_task(task)
            
            # Sleep for a short interval
            time.sleep(10)
    
    def start(self):
        """Start the scheduler"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        app_logger.info("Task scheduler started")
    
    def stop(self):
        """Stop the scheduler"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        app_logger.info("Task scheduler stopped")
    
    def get_status(self) -> List[Dict]:
        """Get status of all tasks"""
        with self._lock:
            return [
                {
                    'id': t.id,
                    'name': t.name,
                    'enabled': t.enabled,
                    'interval': t.interval_minutes,
                    'last_run': t.last_run.isoformat() if t.last_run else None,
                    'next_run': t.next_run.isoformat() if t.next_run else None,
                    'run_count': t.run_count,
                    'error_count': t.error_count,
                    'last_error': t.last_error
                }
                for t in self.tasks.values()
            ]


# Global scheduler instance
task_scheduler = TaskScheduler()