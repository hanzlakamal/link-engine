"""
Campaign Manager - Manage outreach campaigns
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from config import Settings
from core.database import Database
from core.logger import outreach_logger


class CampaignStatus(Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class Campaign:
    """Outreach campaign"""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    campaign_type: str = "guest_post"  # guest_post, link_insert, pr, etc.
    status: str = "draft"
    
    # Targeting
    target_niches: List[str] = field(default_factory=list)
    min_dr: int = 0
    max_dr: int = 100
    min_traffic: int = 0
    
    # Content
    email_template_id: Optional[int] = None
    default_subject: str = ""
    default_pitch_topics: List[str] = field(default_factory=list)
    
    # Limits
    daily_limit: int = 50
    total_limit: int = 500
    
    # Stats
    total_targets: int = 0
    total_sent: int = 0
    total_responses: int = 0
    total_positive: int = 0
    total_links: int = 0
    
    # Dates
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def response_rate(self) -> float:
        if self.total_sent == 0:
            return 0.0
        return (self.total_responses / self.total_sent) * 100
    
    @property
    def success_rate(self) -> float:
        if self.total_sent == 0:
            return 0.0
        return (self.total_links / self.total_sent) * 100


@dataclass
class CampaignTarget:
    """Target domain in a campaign"""
    id: Optional[int] = None
    campaign_id: int = 0
    domain_id: int = 0
    domain: str = ""
    
    # Status
    status: str = "pending"  # pending, queued, sent, responded, converted, rejected
    priority: int = 0
    
    # Submission details
    submission_id: Optional[int] = None
    sent_at: Optional[datetime] = None
    response_type: Optional[str] = None
    response_at: Optional[datetime] = None
    
    # Results
    link_obtained: bool = False
    link_url: Optional[str] = None
    
    # Notes
    notes: str = ""


class CampaignManager:
    """Manage outreach campaigns"""
    
    CAMPAIGN_SCHEMA = """
    CREATE TABLE IF NOT EXISTS campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        campaign_type TEXT DEFAULT 'guest_post',
        status TEXT DEFAULT 'draft',
        
        target_niches TEXT,
        min_dr INTEGER DEFAULT 0,
        max_dr INTEGER DEFAULT 100,
        min_traffic INTEGER DEFAULT 0,
        
        email_template_id INTEGER,
        default_subject TEXT,
        default_pitch_topics TEXT,
        
        daily_limit INTEGER DEFAULT 50,
        total_limit INTEGER DEFAULT 500,
        
        total_targets INTEGER DEFAULT 0,
        total_sent INTEGER DEFAULT 0,
        total_responses INTEGER DEFAULT 0,
        total_positive INTEGER DEFAULT 0,
        total_links INTEGER DEFAULT 0,
        
        start_date TIMESTAMP,
        end_date TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS campaign_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        domain_id INTEGER NOT NULL,
        
        status TEXT DEFAULT 'pending',
        priority INTEGER DEFAULT 0,
        
        submission_id INTEGER,
        sent_at TIMESTAMP,
        response_type TEXT,
        response_at TIMESTAMP,
        
        link_obtained INTEGER DEFAULT 0,
        link_url TEXT,
        
        notes TEXT,
        
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE,
        UNIQUE(campaign_id, domain_id)
    );
    
    CREATE INDEX IF NOT EXISTS idx_campaign_targets_campaign ON campaign_targets(campaign_id);
    CREATE INDEX IF NOT EXISTS idx_campaign_targets_status ON campaign_targets(status);
    """
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Ensure campaign tables exist"""
        self.db.connection.executescript(self.CAMPAIGN_SCHEMA)
        self.db.connection.commit()
    
    def create_campaign(self, campaign: Campaign) -> int:
        """Create a new campaign"""
        import json
        
        cursor = self.db.connection.execute("""
            INSERT INTO campaigns 
            (name, description, campaign_type, status, target_niches,
             min_dr, max_dr, min_traffic, email_template_id,
             default_subject, default_pitch_topics, daily_limit, total_limit,
             start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            campaign.name,
            campaign.description,
            campaign.campaign_type,
            campaign.status,
            json.dumps(campaign.target_niches),
            campaign.min_dr,
            campaign.max_dr,
            campaign.min_traffic,
            campaign.email_template_id,
            campaign.default_subject,
            json.dumps(campaign.default_pitch_topics),
            campaign.daily_limit,
            campaign.total_limit,
            campaign.start_date,
            campaign.end_date
        ))
        
        self.db.connection.commit()
        campaign_id = cursor.lastrowid
        
        outreach_logger.info(f"Created campaign: {campaign.name} (ID: {campaign_id})")
        
        return campaign_id
    
    def get_campaign(self, campaign_id: int) -> Optional[Campaign]:
        """Get campaign by ID"""
        cursor = self.db.connection.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        )
        row = cursor.fetchone()
        
        if row:
            return self._row_to_campaign(row)
        return None
    
    def get_campaigns(self, status: str = None, limit: int = 100) -> List[Campaign]:
        """Get all campaigns"""
        if status:
            cursor = self.db.connection.execute(
                "SELECT * FROM campaigns WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor = self.db.connection.execute(
                "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        
        return [self._row_to_campaign(row) for row in cursor.fetchall()]
    
    def update_campaign(self, campaign: Campaign):
        """Update campaign"""
        import json
        
        self.db.connection.execute("""
            UPDATE campaigns SET
                name = ?, description = ?, campaign_type = ?, status = ?,
                target_niches = ?, min_dr = ?, max_dr = ?, min_traffic = ?,
                email_template_id = ?, default_subject = ?, default_pitch_topics = ?,
                daily_limit = ?, total_limit = ?,
                start_date = ?, end_date = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            campaign.name, campaign.description, campaign.campaign_type, campaign.status,
            json.dumps(campaign.target_niches), campaign.min_dr, campaign.max_dr,
            campaign.min_traffic, campaign.email_template_id, campaign.default_subject,
            json.dumps(campaign.default_pitch_topics), campaign.daily_limit, campaign.total_limit,
            campaign.start_date, campaign.end_date, campaign.id
        ))
        
        self.db.connection.commit()
    
    def update_campaign_status(self, campaign_id: int, status: str):
        """Update campaign status"""
        self.db.connection.execute(
            "UPDATE campaigns SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, campaign_id)
        )
        self.db.connection.commit()
    
    def delete_campaign(self, campaign_id: int):
        """Delete campaign"""
        self.db.connection.execute(
            "DELETE FROM campaigns WHERE id = ?", (campaign_id,)
        )
        self.db.connection.commit()
    
    def _row_to_campaign(self, row) -> Campaign:
        """Convert row to Campaign"""
        import json
        
        return Campaign(
            id=row['id'],
            name=row['name'],
            description=row['description'] or "",
            campaign_type=row['campaign_type'] or "guest_post",
            status=row['status'] or "draft",
            target_niches=json.loads(row['target_niches'] or '[]'),
            min_dr=row['min_dr'] or 0,
            max_dr=row['max_dr'] or 100,
            min_traffic=row['min_traffic'] or 0,
            email_template_id=row['email_template_id'],
            default_subject=row['default_subject'] or "",
            default_pitch_topics=json.loads(row['default_pitch_topics'] or '[]'),
            daily_limit=row['daily_limit'] or 50,
            total_limit=row['total_limit'] or 500,
            total_targets=row['total_targets'] or 0,
            total_sent=row['total_sent'] or 0,
            total_responses=row['total_responses'] or 0,
            total_positive=row['total_positive'] or 0,
            total_links=row['total_links'] or 0,
            start_date=row['start_date'],
            end_date=row['end_date'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    # ==================== TARGETS ====================
    
    def add_targets_from_filter(self, campaign_id: int, 
                                min_dr: int = None,
                                max_dr: int = None,
                                min_score: float = None,
                                niche: str = None,
                                status: str = "analyzed",
                                limit: int = 100) -> int:
        """Add domains matching criteria as campaign targets"""
        query = """
            SELECT id FROM domains 
            WHERE status = ?
        """
        params = [status]
        
        if min_dr is not None:
            query += " AND dr >= ?"
            params.append(min_dr)
        
        if max_dr is not None:
            query += " AND dr <= ?"
            params.append(max_dr)
        
        if min_score is not None:
            query += " AND quality_score >= ?"
            params.append(min_score)
        
        if niche:
            query += " AND niche LIKE ?"
            params.append(f"%{niche}%")
        
        query += " ORDER BY quality_score DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.db.connection.execute(query, params)
        domain_ids = [row['id'] for row in cursor.fetchall()]
        
        added = 0
        for domain_id in domain_ids:
            try:
                self.db.connection.execute("""
                    INSERT OR IGNORE INTO campaign_targets (campaign_id, domain_id)
                    VALUES (?, ?)
                """, (campaign_id, domain_id))
                added += 1
            except:
                pass
        
        self.db.connection.commit()
        
        # Update campaign target count
        self._update_campaign_stats(campaign_id)
        
        return added
    
    def add_target(self, campaign_id: int, domain_id: int, 
                  priority: int = 0, notes: str = "") -> int:
        """Add a single target to campaign"""
        cursor = self.db.connection.execute("""
            INSERT OR IGNORE INTO campaign_targets 
            (campaign_id, domain_id, priority, notes)
            VALUES (?, ?, ?, ?)
        """, (campaign_id, domain_id, priority, notes))
        
        self.db.connection.commit()
        
        self._update_campaign_stats(campaign_id)
        
        return cursor.lastrowid
    
    def get_targets(self, campaign_id: int, status: str = None,
                   limit: int = 100) -> List[Dict]:
        """Get campaign targets"""
        query = """
            SELECT ct.*, d.domain, d.dr, d.traffic, d.quality_score, d.niche
            FROM campaign_targets ct
            JOIN domains d ON ct.domain_id = d.id
            WHERE ct.campaign_id = ?
        """
        params = [campaign_id]
        
        if status:
            query += " AND ct.status = ?"
            params.append(status)
        
        query += " ORDER BY ct.priority DESC, d.quality_score DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.db.connection.execute(query, params)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def update_target_status(self, target_id: int, status: str,
                            submission_id: int = None,
                            response_type: str = None,
                            link_obtained: bool = None,
                            link_url: str = None):
        """Update target status"""
        updates = ["status = ?"]
        params = [status]
        
        if status == 'sent':
            updates.append("sent_at = CURRENT_TIMESTAMP")
        
        if submission_id:
            updates.append("submission_id = ?")
            params.append(submission_id)
        
        if response_type:
            updates.append("response_type = ?")
            updates.append("response_at = CURRENT_TIMESTAMP")
            params.append(response_type)
        
        if link_obtained is not None:
            updates.append("link_obtained = ?")
            params.append(1 if link_obtained else 0)
        
        if link_url:
            updates.append("link_url = ?")
            params.append(link_url)
        
        params.append(target_id)
        
        self.db.connection.execute(
            f"UPDATE campaign_targets SET {', '.join(updates)} WHERE id = ?",
            params
        )
        self.db.connection.commit()
        
        # Get campaign_id and update stats
        cursor = self.db.connection.execute(
            "SELECT campaign_id FROM campaign_targets WHERE id = ?", (target_id,)
        )
        row = cursor.fetchone()
        if row:
            self._update_campaign_stats(row['campaign_id'])
    
    def remove_target(self, target_id: int):
        """Remove target from campaign"""
        cursor = self.db.connection.execute(
            "SELECT campaign_id FROM campaign_targets WHERE id = ?", (target_id,)
        )
        row = cursor.fetchone()
        campaign_id = row['campaign_id'] if row else None
        
        self.db.connection.execute(
            "DELETE FROM campaign_targets WHERE id = ?", (target_id,)
        )
        self.db.connection.commit()
        
        if campaign_id:
            self._update_campaign_stats(campaign_id)
    
    def _update_campaign_stats(self, campaign_id: int):
        """Update campaign statistics"""
        cursor = self.db.connection.execute("""
            SELECT 
                COUNT(*) as total_targets,
                SUM(CASE WHEN status IN ('sent', 'responded', 'converted', 'rejected') THEN 1 ELSE 0 END) as total_sent,
                SUM(CASE WHEN status IN ('responded', 'converted') THEN 1 ELSE 0 END) as total_responses,
                SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) as total_positive,
                SUM(CASE WHEN link_obtained = 1 THEN 1 ELSE 0 END) as total_links
            FROM campaign_targets
            WHERE campaign_id = ?
        """, (campaign_id,))
        
        row = cursor.fetchone()
        
        self.db.connection.execute("""
            UPDATE campaigns SET
                total_targets = ?,
                total_sent = ?,
                total_responses = ?,
                total_positive = ?,
                total_links = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            row['total_targets'] or 0,
            row['total_sent'] or 0,
            row['total_responses'] or 0,
            row['total_positive'] or 0,
            row['total_links'] or 0,
            campaign_id
        ))
        
        self.db.connection.commit()
    
    def get_next_batch(self, campaign_id: int, batch_size: int = 10) -> List[Dict]:
        """Get next batch of targets to process"""
        campaign = self.get_campaign(campaign_id)
        
        if not campaign or campaign.status != 'active':
            return []
        
        # Check daily limit
        today_sent = self._get_sent_today(campaign_id)
        remaining = campaign.daily_limit - today_sent
        
        if remaining <= 0:
            return []
        
        batch_size = min(batch_size, remaining)
        
        return self.get_targets(campaign_id, status='pending', limit=batch_size)
    
    def _get_sent_today(self, campaign_id: int) -> int:
        """Get number of emails sent today for campaign"""
        cursor = self.db.connection.execute("""
            SELECT COUNT(*) FROM campaign_targets
            WHERE campaign_id = ?
            AND sent_at >= date('now')
            AND status IN ('sent', 'responded', 'converted', 'rejected')
        """, (campaign_id,))
        
        return cursor.fetchone()[0]
    
    def get_campaign_stats(self, campaign_id: int) -> Dict[str, Any]:
        """Get detailed campaign statistics"""
        campaign = self.get_campaign(campaign_id)
        
        if not campaign:
            return {}
        
        # Status breakdown
        cursor = self.db.connection.execute("""
            SELECT status, COUNT(*) as count
            FROM campaign_targets
            WHERE campaign_id = ?
            GROUP BY status
        """, (campaign_id,))
        
        status_breakdown = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # Response breakdown
        cursor = self.db.connection.execute("""
            SELECT response_type, COUNT(*) as count
            FROM campaign_targets
            WHERE campaign_id = ? AND response_type IS NOT NULL
            GROUP BY response_type
        """, (campaign_id,))
        
        response_breakdown = {row['response_type']: row['count'] for row in cursor.fetchall()}
        
        # Timeline
        cursor = self.db.connection.execute("""
            SELECT date(sent_at) as date, COUNT(*) as count
            FROM campaign_targets
            WHERE campaign_id = ? AND sent_at IS NOT NULL
            GROUP BY date(sent_at)
            ORDER BY date(sent_at)
        """, (campaign_id,))
        
        timeline = [{'date': row['date'], 'count': row['count']} for row in cursor.fetchall()]
        
        return {
            'campaign': campaign,
            'status_breakdown': status_breakdown,
            'response_breakdown': response_breakdown,
            'timeline': timeline,
            'response_rate': campaign.response_rate,
            'success_rate': campaign.success_rate,
            'sent_today': self._get_sent_today(campaign_id),
            'remaining_daily': campaign.daily_limit - self._get_sent_today(campaign_id),
            'remaining_total': campaign.total_limit - campaign.total_sent
        }