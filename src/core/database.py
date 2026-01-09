"""
Database Operations with Full Schema
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

from core.logger import db_logger


class DomainStatus(Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    QUEUED = "queued"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    PUBLISHED = "published"
    REJECTED = "rejected"
    ERROR = "error"


class ContactMethodType(Enum):
    EMAIL = "email"
    FORM = "form"
    SOCIAL = "social"


DATABASE_SCHEMA = """
-- Domains table
CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    url TEXT,
    site_name TEXT,
    
    -- Metrics from Ahrefs
    dr INTEGER,
    traffic INTEGER,
    referring_domains INTEGER,
    
    -- Calculated
    quality_score REAL,
    relevance_score REAL,
    
    -- Categorization
    niche TEXT,
    tags TEXT,  -- JSON array
    
    -- Status tracking
    status TEXT DEFAULT 'pending',
    last_analyzed TIMESTAMP,
    last_contacted TIMESTAMP,
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Contact methods discovered
CREATE TABLE IF NOT EXISTS contact_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL,
    
    method_type TEXT NOT NULL,  -- email, form, social
    url TEXT,
    email_address TEXT,
    
    -- Form analysis
    form_fields TEXT,  -- JSON
    form_action TEXT,
    form_method TEXT,
    has_captcha INTEGER DEFAULT 0,
    captcha_type TEXT,
    
    -- Guidelines
    guidelines_url TEXT,
    guidelines_raw TEXT,
    guidelines_parsed TEXT,  -- JSON
    
    -- Confidence
    confidence_score REAL,
    is_primary INTEGER DEFAULT 0,
    
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE
);

-- Outreach campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    target_niche TEXT,
    status TEXT DEFAULT 'draft',  -- draft, active, paused, completed
    
    -- Settings
    email_template_id INTEGER,
    daily_limit INTEGER DEFAULT 50,
    
    -- Stats
    total_targets INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    response_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual outreach submissions
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL,
    campaign_id INTEGER,
    contact_method_id INTEGER,
    
    -- What was sent
    submission_type TEXT NOT NULL,  -- email, form
    subject TEXT,
    message TEXT,
    pitch_topics TEXT,  -- JSON array
    
    -- Email specifics
    from_email TEXT,
    to_email TEXT,
    
    -- Tracking
    sent_at TIMESTAMP,
    opened_at TIMESTAMP,
    clicked_at TIMESTAMP,
    
    -- Status
    status TEXT DEFAULT 'draft',  -- draft, queued, sending, sent, failed
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    
    -- Evidence
    screenshot_path TEXT,
    raw_response TEXT,  -- For form submissions
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (contact_method_id) REFERENCES contact_methods(id)
);

-- Responses received
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    
    -- Classification
    response_type TEXT,  -- positive, negative, needs_info, counter_offer, auto_reply
    sentiment_score REAL,
    
    -- Content
    subject TEXT,
    body TEXT,
    from_email TEXT,
    
    -- AI Analysis
    ai_analysis TEXT,  -- JSON
    key_points TEXT,  -- JSON array
    action_required TEXT,
    
    -- Follow-up
    requires_followup INTEGER DEFAULT 0,
    followup_date TIMESTAMP,
    followup_sent INTEGER DEFAULT 0,
    
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
);

-- Published backlinks
CREATE TABLE IF NOT EXISTS backlinks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL,
    submission_id INTEGER,
    
    -- Link details
    source_url TEXT NOT NULL,  -- Page where link is
    target_url TEXT NOT NULL,  -- Your page being linked
    anchor_text TEXT,
    
    -- Link attributes
    link_type TEXT,  -- dofollow, nofollow, sponsored, ugc
    link_position TEXT,  -- body, bio, sidebar, footer
    context_text TEXT,  -- Surrounding text
    
    -- Verification
    status TEXT DEFAULT 'pending',  -- pending, live, removed, error
    first_seen TIMESTAMP,
    last_checked TIMESTAMP,
    last_live TIMESTAMP,
    
    -- Ahrefs data
    indexed_in_ahrefs INTEGER DEFAULT 0,
    ahrefs_first_seen TIMESTAMP,
    
    -- Value
    estimated_value REAL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE,
    FOREIGN KEY (submission_id) REFERENCES submissions(id)
);

-- Link check history
CREATE TABLE IF NOT EXISTS link_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backlink_id INTEGER NOT NULL,
    
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT,  -- live, removed, error, redirect
    http_status INTEGER,
    
    -- Changes detected
    anchor_changed INTEGER DEFAULT 0,
    new_anchor TEXT,
    rel_changed INTEGER DEFAULT 0,
    new_rel TEXT,
    
    error_message TEXT,
    
    FOREIGN KEY (backlink_id) REFERENCES backlinks(id) ON DELETE CASCADE
);

-- Email templates
CREATE TABLE IF NOT EXISTS email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    subject_template TEXT,
    body_template TEXT,
    
    -- Usage stats
    times_used INTEGER DEFAULT 0,
    response_rate REAL,
    
    -- Categorization
    template_type TEXT,  -- initial, followup, thank_you
    niche TEXT,
    
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Activity log for debugging
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    activity_type TEXT NOT NULL,
    module TEXT,
    domain_id INTEGER,
    
    description TEXT,
    details TEXT,  -- JSON
    
    status TEXT,  -- success, error, warning
    error_message TEXT,
    
    FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE SET NULL
);

-- Settings storage
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    value_type TEXT,  -- string, int, float, bool, json
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_domains_status ON domains(status);
CREATE INDEX IF NOT EXISTS idx_domains_score ON domains(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_domains_dr ON domains(dr DESC);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_submissions_domain ON submissions(domain_id);
CREATE INDEX IF NOT EXISTS idx_backlinks_status ON backlinks(status);
CREATE INDEX IF NOT EXISTS idx_backlinks_domain ON backlinks(domain_id);
CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_activity_domain ON activity_log(domain_id);
"""


@dataclass
class Domain:
    """Domain data class"""
    id: Optional[int] = None
    domain: str = ""
    url: str = ""
    site_name: str = ""
    dr: int = 0
    traffic: int = 0
    referring_domains: int = 0
    quality_score: float = 0.0
    relevance_score: float = 0.0
    niche: str = ""
    tags: List[str] = None
    status: str = "pending"
    last_analyzed: Optional[datetime] = None
    last_contacted: Optional[datetime] = None
    notes: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class Database:
    """SQLite Database Manager"""
    
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection: Optional[sqlite3.Connection] = None
    
    def connect(self) -> 'Database':
        """Establish database connection"""
        db_logger.info(f"Connecting to database: {self.db_path}")
        
        self.connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        
        db_logger.info("Database connection established")
        return self
    
    def initialize(self):
        """Create all tables"""
        db_logger.info("Initializing database schema")
        
        self.connection.executescript(DATABASE_SCHEMA)
        self.connection.commit()
        
        db_logger.info("Database schema initialized")
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            db_logger.info("Database connection closed")
    
    @contextmanager
    def transaction(self):
        """Context manager for transactions"""
        try:
            yield self.connection
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            db_logger.error(f"Transaction rolled back: {e}")
            raise
    
    # ==================== DOMAIN OPERATIONS ====================
    
    def insert_domain(self, domain: Domain) -> int:
        """Insert a new domain"""
        db_logger.debug(f"Inserting domain: {domain.domain}")
        
        cursor = self.connection.execute("""
            INSERT INTO domains (domain, url, site_name, niche, status)
            VALUES (?, ?, ?, ?, ?)
        """, (domain.domain, domain.url, domain.site_name, domain.niche, domain.status))
        
        self.connection.commit()
        domain_id = cursor.lastrowid
        
        self.log_activity("domain_created", "discovery", domain_id, 
                         f"Domain {domain.domain} added")
        
        return domain_id
    
    def bulk_insert_domains(self, domains: List[Domain]) -> Tuple[int, int]:
        """Insert multiple domains, skip duplicates"""
        db_logger.info(f"Bulk inserting {len(domains)} domains")
        
        inserted = 0
        skipped = 0
        
        for domain in domains:
            try:
                self.connection.execute("""
                    INSERT INTO domains (domain, url, site_name, niche, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (domain.domain, domain.url, domain.site_name, domain.niche, domain.status))
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
        
        self.connection.commit()
        
        db_logger.info(f"Bulk insert complete: {inserted} inserted, {skipped} skipped")
        self.log_activity("bulk_import", "discovery", None,
                         f"Imported {inserted} domains, {skipped} duplicates skipped")
        
        return inserted, skipped
    
    def get_domain(self, domain_id: int) -> Optional[Domain]:
        """Get domain by ID"""
        cursor = self.connection.execute(
            "SELECT * FROM domains WHERE id = ?", (domain_id,)
        )
        row = cursor.fetchone()
        
        if row:
            return self._row_to_domain(row)
        return None
    
    def get_domain_by_name(self, domain_name: str) -> Optional[Domain]:
        """Get domain by domain name"""
        cursor = self.connection.execute(
            "SELECT * FROM domains WHERE domain = ?", (domain_name,)
        )
        row = cursor.fetchone()
        
        if row:
            return self._row_to_domain(row)
        return None
    
    def get_domains(self, 
                    status: Optional[str] = None,
                    min_score: Optional[float] = None,
                    min_dr: Optional[int] = None,
                    niche: Optional[str] = None,
                    limit: int = 100,
                    offset: int = 0) -> List[Domain]:
        """Get domains with filters"""
        
        query = "SELECT * FROM domains WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if min_score is not None:
            query += " AND quality_score >= ?"
            params.append(min_score)
        
        if min_dr is not None:
            query += " AND dr >= ?"
            params.append(min_dr)
        
        if niche:
            query += " AND niche LIKE ?"
            params.append(f"%{niche}%")
        
        query += " ORDER BY quality_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor = self.connection.execute(query, params)
        
        return [self._row_to_domain(row) for row in cursor.fetchall()]
    
    def get_all_domains(self) -> List[Domain]:
        """Get all domains"""
        cursor = self.connection.execute(
            "SELECT * FROM domains ORDER BY created_at DESC"
        )
        return [self._row_to_domain(row) for row in cursor.fetchall()]
    
    def update_domain(self, domain: Domain):
        """Update domain"""
        db_logger.debug(f"Updating domain: {domain.domain}")
        
        self.connection.execute("""
            UPDATE domains SET
                url = ?,
                site_name = ?,
                dr = ?,
                traffic = ?,
                referring_domains = ?,
                quality_score = ?,
                relevance_score = ?,
                niche = ?,
                status = ?,
                last_analyzed = ?,
                last_contacted = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            domain.url, domain.site_name, domain.dr, domain.traffic,
            domain.referring_domains, domain.quality_score, domain.relevance_score,
            domain.niche, domain.status, domain.last_analyzed, domain.last_contacted,
            domain.notes, domain.id
        ))
        
        self.connection.commit()
    
    def update_domain_status(self, domain_id: int, status: str):
        """Quick status update"""
        self.connection.execute(
            "UPDATE domains SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, domain_id)
        )
        self.connection.commit()
    
    def update_domain_metrics(self, domain_id: int, dr: int, traffic: int, 
                             referring_domains: int, quality_score: float):
        """Update domain metrics"""
        self.connection.execute("""
            UPDATE domains SET
                dr = ?, traffic = ?, referring_domains = ?,
                quality_score = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (dr, traffic, referring_domains, quality_score, domain_id))
        
        self.connection.commit()
    
    def delete_domain(self, domain_id: int):
        """Delete domain and related data"""
        domain = self.get_domain(domain_id)
        if domain:
            self.connection.execute("DELETE FROM domains WHERE id = ?", (domain_id,))
            self.connection.commit()
            
            self.log_activity("domain_deleted", "discovery", None,
                             f"Domain {domain.domain} deleted")
    
    def get_domain_count(self, status: Optional[str] = None) -> int:
        """Get count of domains"""
        if status:
            cursor = self.connection.execute(
                "SELECT COUNT(*) FROM domains WHERE status = ?", (status,)
            )
        else:
            cursor = self.connection.execute("SELECT COUNT(*) FROM domains")
        
        return cursor.fetchone()[0]
    
    def get_domain_stats(self) -> Dict[str, Any]:
        """Get domain statistics"""
        stats = {}
        
        # Total count
        stats['total'] = self.get_domain_count()
        
        # By status
        cursor = self.connection.execute("""
            SELECT status, COUNT(*) as count FROM domains GROUP BY status
        """)
        stats['by_status'] = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # Average metrics
        cursor = self.connection.execute("""
            SELECT 
                AVG(dr) as avg_dr,
                AVG(traffic) as avg_traffic,
                AVG(quality_score) as avg_score
            FROM domains WHERE dr > 0
        """)
        row = cursor.fetchone()
        stats['avg_dr'] = round(row['avg_dr'] or 0, 1)
        stats['avg_traffic'] = int(row['avg_traffic'] or 0)
        stats['avg_score'] = round(row['avg_score'] or 0, 1)
        
        return stats
    
    def _row_to_domain(self, row: sqlite3.Row) -> Domain:
        """Convert database row to Domain object"""
        return Domain(
            id=row['id'],
            domain=row['domain'],
            url=row['url'] or "",
            site_name=row['site_name'] or "",
            dr=row['dr'] or 0,
            traffic=row['traffic'] or 0,
            referring_domains=row['referring_domains'] or 0,
            quality_score=row['quality_score'] or 0.0,
            relevance_score=row['relevance_score'] or 0.0,
            niche=row['niche'] or "",
            status=row['status'],
            notes=row['notes'] or "",
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    # ==================== CONTACT METHODS ====================
    
    def insert_contact_method(self, domain_id: int, method_type: str, 
                              email: str = None, url: str = None,
                              form_fields: dict = None, guidelines: dict = None,
                              has_captcha: bool = False, captcha_type: str = None) -> int:
        """Insert contact method"""
        import json
        
        cursor = self.connection.execute("""
            INSERT INTO contact_methods 
            (domain_id, method_type, email_address, url, form_fields, 
             guidelines_parsed, has_captcha, captcha_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            domain_id, method_type, email, url,
            json.dumps(form_fields) if form_fields else None,
            json.dumps(guidelines) if guidelines else None,
            1 if has_captcha else 0,
            captcha_type
        ))
        
        self.connection.commit()
        return cursor.lastrowid
    
    def get_contact_methods(self, domain_id: int) -> List[Dict]:
        """Get all contact methods for a domain"""
        import json
        
        cursor = self.connection.execute(
            "SELECT * FROM contact_methods WHERE domain_id = ?", (domain_id,)
        )
        
        methods = []
        for row in cursor.fetchall():
            method = dict(row)
            if method['form_fields']:
                method['form_fields'] = json.loads(method['form_fields'])
            if method['guidelines_parsed']:
                method['guidelines_parsed'] = json.loads(method['guidelines_parsed'])
            methods.append(method)
        
        return methods
    
    # ==================== ACTIVITY LOG ====================
    
    def log_activity(self, activity_type: str, module: str, 
                    domain_id: Optional[int], description: str,
                    details: dict = None, status: str = "success",
                    error_message: str = None):
        """Log an activity"""
        import json
        
        self.connection.execute("""
            INSERT INTO activity_log 
            (activity_type, module, domain_id, description, details, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            activity_type, module, domain_id, description,
            json.dumps(details) if details else None,
            status, error_message
        ))
        self.connection.commit()
    
    def get_activity_log(self, limit: int = 100, 
                        module: str = None,
                        domain_id: int = None) -> List[Dict]:
        """Get activity log entries"""
        import json
        
        query = "SELECT * FROM activity_log WHERE 1=1"
        params = []
        
        if module:
            query += " AND module = ?"
            params.append(module)
        
        if domain_id:
            query += " AND domain_id = ?"
            params.append(domain_id)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.connection.execute(query, params)
        
        activities = []
        for row in cursor.fetchall():
            activity = dict(row)
            if activity['details']:
                activity['details'] = json.loads(activity['details'])
            activities.append(activity)
        
        return activities
    
    # ==================== SUBMISSIONS ====================
    
    def insert_submission(self, domain_id: int, submission_type: str,
                         subject: str, message: str, 
                         contact_method_id: int = None,
                         campaign_id: int = None) -> int:
        """Create a new submission"""
        cursor = self.connection.execute("""
            INSERT INTO submissions 
            (domain_id, contact_method_id, campaign_id, submission_type, subject, message, status)
            VALUES (?, ?, ?, ?, ?, ?, 'draft')
        """, (domain_id, contact_method_id, campaign_id, submission_type, subject, message))
        
        self.connection.commit()
        return cursor.lastrowid
    
    def get_submissions(self, domain_id: int = None, status: str = None, 
                       limit: int = 100) -> List[Dict]:
        """Get submissions with filters"""
        query = """
            SELECT s.*, d.domain 
            FROM submissions s
            JOIN domains d ON s.domain_id = d.id
            WHERE 1=1
        """
        params = []
        
        if domain_id:
            query += " AND s.domain_id = ?"
            params.append(domain_id)
        
        if status:
            query += " AND s.status = ?"
            params.append(status)
        
        query += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    # ==================== BACKLINKS ====================
    
    def insert_backlink(self, domain_id: int, source_url: str, target_url: str,
                       anchor_text: str = None, link_type: str = "dofollow",
                       submission_id: int = None) -> int:
        """Record a new backlink"""
        cursor = self.connection.execute("""
            INSERT INTO backlinks 
            (domain_id, submission_id, source_url, target_url, anchor_text, 
             link_type, status, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, 'live', CURRENT_TIMESTAMP)
        """, (domain_id, submission_id, source_url, target_url, anchor_text, link_type))
        
        self.connection.commit()
        
        self.log_activity("backlink_discovered", "tracking", domain_id,
                         f"New backlink found: {source_url}")
        
        return cursor.lastrowid
    
    def get_backlinks(self, domain_id: int = None, status: str = None) -> List[Dict]:
        """Get backlinks"""
        query = """
            SELECT b.*, d.domain 
            FROM backlinks b
            JOIN domains d ON b.domain_id = d.id
            WHERE 1=1
        """
        params = []
        
        if domain_id:
            query += " AND b.domain_id = ?"
            params.append(domain_id)
        
        if status:
            query += " AND b.status = ?"
            params.append(status)
        
        query += " ORDER BY b.first_seen DESC"
        
        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_backlink_stats(self) -> Dict[str, Any]:
        """Get backlink statistics"""
        stats = {}
        
        cursor = self.connection.execute("SELECT COUNT(*) FROM backlinks WHERE status = 'live'")
        stats['total_live'] = cursor.fetchone()[0]
        
        cursor = self.connection.execute("""
            SELECT link_type, COUNT(*) as count 
            FROM backlinks WHERE status = 'live' 
            GROUP BY link_type
        """)
        stats['by_type'] = {row['link_type']: row['count'] for row in cursor.fetchall()}
        
        return stats