"""
Journalist Database - Manage media contacts for Digital PR
"""
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from config import Settings
from core.database import Database
from core.logger import app_logger


class RelationshipStatus(Enum):
    COLD = "cold"
    WARM = "warm"
    HOT = "hot"
    ACTIVE = "active"


@dataclass
class Journalist:
    """Journalist/media contact"""
    id: Optional[int] = None
    name: str = ""
    email: str = ""
    secondary_emails: List[str] = field(default_factory=list)
    twitter: str = ""
    linkedin: str = ""
    phone: str = ""
    
    # Professional info
    current_outlet: str = ""
    outlet_type: str = ""  # news, blog, magazine, etc.
    outlet_dr: int = 0
    job_title: str = ""
    beat: List[str] = field(default_factory=list)  # Topics they cover
    writing_frequency: str = ""
    
    # Preferences
    preferred_contact: str = "email"
    best_pitch_time: str = ""
    pitch_style: str = ""
    response_rate: float = 0.0
    avg_response_time_hours: int = 0
    
    # Relationship
    relationship_status: str = "cold"
    total_pitches: int = 0
    total_responses: int = 0
    total_features: int = 0
    last_contact: Optional[datetime] = None
    last_feature: Optional[datetime] = None
    
    # Notes
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'secondary_emails': self.secondary_emails,
            'twitter': self.twitter,
            'linkedin': self.linkedin,
            'current_outlet': self.current_outlet,
            'outlet_dr': self.outlet_dr,
            'job_title': self.job_title,
            'beat': self.beat,
            'preferred_contact': self.preferred_contact,
            'relationship_status': self.relationship_status,
            'total_pitches': self.total_pitches,
            'total_features': self.total_features,
            'notes': self.notes,
            'tags': self.tags,
        }


@dataclass
class JournalistInteraction:
    """Record of interaction with a journalist"""
    id: Optional[int] = None
    journalist_id: int = 0
    interaction_type: str = ""  # pitched, responded, featured, rejected, meeting
    campaign_name: str = ""
    pitch_angle: str = ""
    response: str = ""
    link_obtained: bool = False
    article_url: str = ""
    article_title: str = ""
    interaction_date: datetime = field(default_factory=datetime.now)
    notes: str = ""


class JournalistDatabase:
    """Manage journalist contacts"""
    
    # Additional schema for journalists
    JOURNALIST_SCHEMA = """
    -- Journalists table
    CREATE TABLE IF NOT EXISTS journalists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        secondary_emails TEXT,  -- JSON array
        twitter TEXT,
        linkedin TEXT,
        phone TEXT,
        
        current_outlet TEXT,
        outlet_type TEXT,
        outlet_dr INTEGER,
        job_title TEXT,
        beat TEXT,  -- JSON array
        writing_frequency TEXT,
        
        preferred_contact TEXT DEFAULT 'email',
        best_pitch_time TEXT,
        pitch_style TEXT,
        response_rate REAL DEFAULT 0,
        avg_response_time_hours INTEGER DEFAULT 0,
        
        relationship_status TEXT DEFAULT 'cold',
        total_pitches INTEGER DEFAULT 0,
        total_responses INTEGER DEFAULT 0,
        total_features INTEGER DEFAULT 0,
        last_contact TIMESTAMP,
        last_feature TIMESTAMP,
        
        notes TEXT,
        tags TEXT,  -- JSON array
        
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        UNIQUE(email)
    );
    
    -- Journalist interactions
    CREATE TABLE IF NOT EXISTS journalist_interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journalist_id INTEGER NOT NULL,
        interaction_type TEXT NOT NULL,
        campaign_name TEXT,
        pitch_angle TEXT,
        response TEXT,
        link_obtained INTEGER DEFAULT 0,
        article_url TEXT,
        article_title TEXT,
        interaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT,
        
        FOREIGN KEY (journalist_id) REFERENCES journalists(id) ON DELETE CASCADE
    );
    
    -- PR Campaigns
    CREATE TABLE IF NOT EXISTS pr_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        campaign_type TEXT,  -- data_story, newsjacking, expert_commentary, etc.
        status TEXT DEFAULT 'planning',
        
        -- Asset
        asset_title TEXT,
        asset_url TEXT,
        asset_description TEXT,
        key_findings TEXT,  -- JSON array
        
        -- Targeting
        target_outlets TEXT,  -- JSON array
        target_beats TEXT,  -- JSON array
        
        -- Timeline
        start_date TIMESTAMP,
        embargo_date TIMESTAMP,
        
        -- Results
        total_pitches INTEGER DEFAULT 0,
        total_coverage INTEGER DEFAULT 0,
        total_links INTEGER DEFAULT 0,
        
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Campaign targets (journalists assigned to campaigns)
    CREATE TABLE IF NOT EXISTS campaign_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        journalist_id INTEGER NOT NULL,
        custom_angle TEXT,
        exclusive_offered INTEGER DEFAULT 0,
        pitch_status TEXT DEFAULT 'pending',
        pitched_at TIMESTAMP,
        response_status TEXT,
        response_at TIMESTAMP,
        
        FOREIGN KEY (campaign_id) REFERENCES pr_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY (journalist_id) REFERENCES journalists(id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_journalists_outlet ON journalists(current_outlet);
    CREATE INDEX IF NOT EXISTS idx_journalists_beat ON journalists(beat);
    CREATE INDEX IF NOT EXISTS idx_journalists_status ON journalists(relationship_status);
    CREATE INDEX IF NOT EXISTS idx_interactions_journalist ON journalist_interactions(journalist_id);
    CREATE INDEX IF NOT EXISTS idx_campaign_targets ON campaign_targets(campaign_id);
    """
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Ensure journalist tables exist"""
        self.db.connection.executescript(self.JOURNALIST_SCHEMA)
        self.db.connection.commit()
    
    # ==================== JOURNALIST CRUD ====================
    
    def add_journalist(self, journalist: Journalist) -> int:
        """Add a new journalist"""
        cursor = self.db.connection.execute("""
            INSERT INTO journalists 
            (name, email, secondary_emails, twitter, linkedin, phone,
             current_outlet, outlet_type, outlet_dr, job_title, beat,
             writing_frequency, preferred_contact, best_pitch_time, pitch_style,
             relationship_status, notes, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            journalist.name,
            journalist.email,
            json.dumps(journalist.secondary_emails),
            journalist.twitter,
            journalist.linkedin,
            journalist.phone,
            journalist.current_outlet,
            journalist.outlet_type,
            journalist.outlet_dr,
            journalist.job_title,
            json.dumps(journalist.beat),
            journalist.writing_frequency,
            journalist.preferred_contact,
            journalist.best_pitch_time,
            journalist.pitch_style,
            journalist.relationship_status,
            journalist.notes,
            json.dumps(journalist.tags)
        ))
        
        self.db.connection.commit()
        journalist_id = cursor.lastrowid
        
        app_logger.info(f"Added journalist: {journalist.name} ({journalist.current_outlet})")
        
        return journalist_id
    
    def get_journalist(self, journalist_id: int) -> Optional[Journalist]:
        """Get journalist by ID"""
        cursor = self.db.connection.execute(
            "SELECT * FROM journalists WHERE id = ?", (journalist_id,)
        )
        row = cursor.fetchone()
        
        if row:
            return self._row_to_journalist(row)
        return None
    
    def get_journalist_by_email(self, email: str) -> Optional[Journalist]:
        """Get journalist by email"""
        cursor = self.db.connection.execute(
            "SELECT * FROM journalists WHERE email = ?", (email,)
        )
        row = cursor.fetchone()
        
        if row:
            return self._row_to_journalist(row)
        return None
    
    def search_journalists(self, 
                          query: str = None,
                          outlet: str = None,
                          beat: str = None,
                          relationship: str = None,
                          min_dr: int = None,
                          tags: List[str] = None,
                          limit: int = 100) -> List[Journalist]:
        """Search journalists with filters"""
        sql = "SELECT * FROM journalists WHERE 1=1"
        params = []
        
        if query:
            sql += " AND (name LIKE ? OR email LIKE ? OR current_outlet LIKE ?)"
            like_query = f"%{query}%"
            params.extend([like_query, like_query, like_query])
        
        if outlet:
            sql += " AND current_outlet LIKE ?"
            params.append(f"%{outlet}%")
        
        if beat:
            sql += " AND beat LIKE ?"
            params.append(f"%{beat}%")
        
        if relationship:
            sql += " AND relationship_status = ?"
            params.append(relationship)
        
        if min_dr:
            sql += " AND outlet_dr >= ?"
            params.append(min_dr)
        
        sql += " ORDER BY outlet_dr DESC, total_features DESC LIMIT ?"
        params.append(limit)
        
        cursor = self.db.connection.execute(sql, params)
        
        return [self._row_to_journalist(row) for row in cursor.fetchall()]
    
    def update_journalist(self, journalist: Journalist):
        """Update journalist"""
        self.db.connection.execute("""
            UPDATE journalists SET
                name = ?, email = ?, secondary_emails = ?, twitter = ?,
                linkedin = ?, phone = ?, current_outlet = ?, outlet_type = ?,
                outlet_dr = ?, job_title = ?, beat = ?, writing_frequency = ?,
                preferred_contact = ?, best_pitch_time = ?, pitch_style = ?,
                response_rate = ?, avg_response_time_hours = ?,
                relationship_status = ?, notes = ?, tags = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            journalist.name, journalist.email, json.dumps(journalist.secondary_emails),
            journalist.twitter, journalist.linkedin, journalist.phone,
            journalist.current_outlet, journalist.outlet_type, journalist.outlet_dr,
            journalist.job_title, json.dumps(journalist.beat), journalist.writing_frequency,
            journalist.preferred_contact, journalist.best_pitch_time, journalist.pitch_style,
            journalist.response_rate, journalist.avg_response_time_hours,
            journalist.relationship_status, journalist.notes, json.dumps(journalist.tags),
            journalist.id
        ))
        self.db.connection.commit()
    
    def delete_journalist(self, journalist_id: int):
        """Delete journalist"""
        self.db.connection.execute(
            "DELETE FROM journalists WHERE id = ?", (journalist_id,)
        )
        self.db.connection.commit()
    
    def _row_to_journalist(self, row) -> Journalist:
        """Convert database row to Journalist"""
        return Journalist(
            id=row['id'],
            name=row['name'],
            email=row['email'] or "",
            secondary_emails=json.loads(row['secondary_emails'] or '[]'),
            twitter=row['twitter'] or "",
            linkedin=row['linkedin'] or "",
            phone=row['phone'] or "",
            current_outlet=row['current_outlet'] or "",
            outlet_type=row['outlet_type'] or "",
            outlet_dr=row['outlet_dr'] or 0,
            job_title=row['job_title'] or "",
            beat=json.loads(row['beat'] or '[]'),
            writing_frequency=row['writing_frequency'] or "",
            preferred_contact=row['preferred_contact'] or "email",
            best_pitch_time=row['best_pitch_time'] or "",
            pitch_style=row['pitch_style'] or "",
            response_rate=row['response_rate'] or 0.0,
            avg_response_time_hours=row['avg_response_time_hours'] or 0,
            relationship_status=row['relationship_status'] or "cold",
            total_pitches=row['total_pitches'] or 0,
            total_responses=row['total_responses'] or 0,
            total_features=row['total_features'] or 0,
            notes=row['notes'] or "",
            tags=json.loads(row['tags'] or '[]'),
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
    
    # ==================== INTERACTIONS ====================
    
    def log_interaction(self, interaction: JournalistInteraction) -> int:
        """Log an interaction with a journalist"""
        cursor = self.db.connection.execute("""
            INSERT INTO journalist_interactions
            (journalist_id, interaction_type, campaign_name, pitch_angle,
             response, link_obtained, article_url, article_title, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            interaction.journalist_id,
            interaction.interaction_type,
            interaction.campaign_name,
            interaction.pitch_angle,
            interaction.response,
            1 if interaction.link_obtained else 0,
            interaction.article_url,
            interaction.article_title,
            interaction.notes
        ))
        
        self.db.connection.commit()
        interaction_id = cursor.lastrowid
        
        # Update journalist stats
        self._update_journalist_stats(interaction)
        
        return interaction_id
    
    def get_interactions(self, journalist_id: int, limit: int = 50) -> List[Dict]:
        """Get interactions for a journalist"""
        cursor = self.db.connection.execute("""
            SELECT * FROM journalist_interactions
            WHERE journalist_id = ?
            ORDER BY interaction_date DESC
            LIMIT ?
        """, (journalist_id, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def _update_journalist_stats(self, interaction: JournalistInteraction):
        """Update journalist statistics after interaction"""
        updates = []
        params = []
        
        if interaction.interaction_type == 'pitched':
            updates.append("total_pitches = total_pitches + 1")
            updates.append("last_contact = ?")
            params.append(datetime.now())
        
        elif interaction.interaction_type == 'responded':
            updates.append("total_responses = total_responses + 1")
        
        elif interaction.interaction_type == 'featured':
            updates.append("total_features = total_features + 1")
            updates.append("last_feature = ?")
            params.append(datetime.now())
            
            # Upgrade relationship status
            updates.append("""
                relationship_status = CASE
                    WHEN relationship_status = 'cold' THEN 'warm'
                    WHEN relationship_status = 'warm' THEN 'hot'
                    ELSE relationship_status
                END
            """)
        
        if updates:
            params.append(interaction.journalist_id)
            self.db.connection.execute(
                f"UPDATE journalists SET {', '.join(updates)} WHERE id = ?",
                params
            )
            
            # Recalculate response rate
            self.db.connection.execute("""
                UPDATE journalists SET
                    response_rate = CASE 
                        WHEN total_pitches > 0 
                        THEN (total_responses * 100.0 / total_pitches)
                        ELSE 0 
                    END
                WHERE id = ?
            """, (interaction.journalist_id,))
            
            self.db.connection.commit()
    
    # ==================== CAMPAIGNS ====================
    
    def create_campaign(self, name: str, campaign_type: str,
                       asset_title: str = "", asset_url: str = "",
                       description: str = "", key_findings: List[str] = None) -> int:
        """Create a PR campaign"""
        cursor = self.db.connection.execute("""
            INSERT INTO pr_campaigns
            (name, campaign_type, asset_title, asset_url, 
             asset_description, key_findings, status)
            VALUES (?, ?, ?, ?, ?, ?, 'planning')
        """, (
            name, campaign_type, asset_title, asset_url,
            description, json.dumps(key_findings or [])
        ))
        
        self.db.connection.commit()
        return cursor.lastrowid
    
    def get_campaign(self, campaign_id: int) -> Optional[Dict]:
        """Get campaign by ID"""
        cursor = self.db.connection.execute(
            "SELECT * FROM pr_campaigns WHERE id = ?", (campaign_id,)
        )
        row = cursor.fetchone()
        
        if row:
            campaign = dict(row)
            campaign['key_findings'] = json.loads(campaign.get('key_findings') or '[]')
            return campaign
        return None
    
    def get_campaigns(self, status: str = None) -> List[Dict]:
        """Get all campaigns"""
        if status:
            cursor = self.db.connection.execute(
                "SELECT * FROM pr_campaigns WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor = self.db.connection.execute(
                "SELECT * FROM pr_campaigns ORDER BY created_at DESC"
            )
        
        campaigns = []
        for row in cursor.fetchall():
            campaign = dict(row)
            campaign['key_findings'] = json.loads(campaign.get('key_findings') or '[]')
            campaigns.append(campaign)
        
        return campaigns
    
    def add_campaign_target(self, campaign_id: int, journalist_id: int,
                           custom_angle: str = "", exclusive: bool = False) -> int:
        """Add a journalist to a campaign"""
        cursor = self.db.connection.execute("""
            INSERT INTO campaign_targets
            (campaign_id, journalist_id, custom_angle, exclusive_offered)
            VALUES (?, ?, ?, ?)
        """, (campaign_id, journalist_id, custom_angle, 1 if exclusive else 0))
        
        self.db.connection.commit()
        return cursor.lastrowid
    
    def get_campaign_targets(self, campaign_id: int) -> List[Dict]:
        """Get all targets for a campaign"""
        cursor = self.db.connection.execute("""
            SELECT ct.*, j.name, j.email, j.current_outlet, j.outlet_dr
            FROM campaign_targets ct
            JOIN journalists j ON ct.journalist_id = j.id
            WHERE ct.campaign_id = ?
            ORDER BY j.outlet_dr DESC
        """, (campaign_id,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def update_campaign_target_status(self, target_id: int, status: str,
                                      response_status: str = None):
        """Update campaign target status"""
        updates = ["pitch_status = ?"]
        params = [status]
        
        if status == 'pitched':
            updates.append("pitched_at = ?")
            params.append(datetime.now())
        
        if response_status:
            updates.append("response_status = ?")
            updates.append("response_at = ?")
            params.extend([response_status, datetime.now()])
        
        params.append(target_id)
        
        self.db.connection.execute(
            f"UPDATE campaign_targets SET {', '.join(updates)} WHERE id = ?",
            params
        )
        self.db.connection.commit()
    
    # ==================== STATISTICS ====================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get journalist database statistics"""
        cursor = self.db.connection.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN relationship_status = 'cold' THEN 1 END) as cold,
                COUNT(CASE WHEN relationship_status = 'warm' THEN 1 END) as warm,
                COUNT(CASE WHEN relationship_status = 'hot' THEN 1 END) as hot,
                AVG(outlet_dr) as avg_dr,
                SUM(total_features) as total_features
            FROM journalists
        """)
        
        row = cursor.fetchone()
        
        # Get top outlets
        cursor = self.db.connection.execute("""
            SELECT current_outlet, COUNT(*) as count
            FROM journalists
            WHERE current_outlet != ''
            GROUP BY current_outlet
            ORDER BY count DESC
            LIMIT 10
        """)
        top_outlets = [dict(r) for r in cursor.fetchall()]
        
        # Get top beats
        cursor = self.db.connection.execute("""
            SELECT beat FROM journalists WHERE beat != '[]'
        """)
        
        beat_counts = {}
        for r in cursor.fetchall():
            beats = json.loads(r['beat'] or '[]')
            for beat in beats:
                beat_counts[beat] = beat_counts.get(beat, 0) + 1
        
        top_beats = sorted(beat_counts.items(), key=lambda x: -x[1])[:10]
        
        return {
            'total_journalists': row[0] or 0,
            'cold': row[1] or 0,
            'warm': row[2] or 0,
            'hot': row[3] or 0,
            'avg_outlet_dr': round(row[4] or 0, 1),
            'total_features': row[5] or 0,
            'top_outlets': top_outlets,
            'top_beats': [{'beat': b, 'count': c} for b, c in top_beats]
        }
    
    def import_journalists_csv(self, file_path: str, 
                              column_mapping: Dict[str, str]) -> Tuple[int, int]:
        """Import journalists from CSV"""
        import csv
        
        imported = 0
        skipped = 0
        
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                name = row.get(column_mapping.get('name', 'name'), '').strip()
                email = row.get(column_mapping.get('email', 'email'), '').strip()
                
                if not name:
                    skipped += 1
                    continue
                
                # Check for duplicate
                if email and self.get_journalist_by_email(email):
                    skipped += 1
                    continue
                
                journalist = Journalist(
                    name=name,
                    email=email,
                    current_outlet=row.get(column_mapping.get('outlet', 'outlet'), ''),
                    job_title=row.get(column_mapping.get('title', 'title'), ''),
                    twitter=row.get(column_mapping.get('twitter', 'twitter'), ''),
                    linkedin=row.get(column_mapping.get('linkedin', 'linkedin'), ''),
                )
                
                # Parse beat if present
                beat_str = row.get(column_mapping.get('beat', 'beat'), '')
                if beat_str:
                    journalist.beat = [b.strip() for b in beat_str.split(',')]
                
                try:
                    self.add_journalist(journalist)
                    imported += 1
                except Exception as e:
                    app_logger.error(f"Failed to import journalist {name}: {e}")
                    skipped += 1
        
        return imported, skipped