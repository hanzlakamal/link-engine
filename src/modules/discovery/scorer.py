"""
Domain Scoring Module
"""
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.database import Database, Domain
from core.logger import app_logger
from config import Settings


@dataclass
class ScoreBreakdown:
    """Detailed score breakdown"""
    domain_id: int
    total_score: float
    dr_score: float
    traffic_score: float
    refs_score: float
    relevance_score: float
    penalties: List[str]
    bonuses: List[str]


class DomainScorer:
    """Calculates and updates domain scores"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
    
    def score_domain(self, domain: Domain, relevance_score: float = 50.0) -> ScoreBreakdown:
        """Calculate detailed score for a domain"""
        weights = self.settings.scoring
        penalties = []
        bonuses = []
        
        # DR Score (0-100)
        dr = domain.dr or 0
        if dr >= 70:
            dr_score = 100
            bonuses.append("High authority site (DR 70+)")
        elif dr >= 50:
            dr_score = 80 + (dr - 50) * 1
        elif dr >= 30:
            dr_score = 50 + (dr - 30) * 1.5
        elif dr >= weights.min_dr_threshold:
            dr_score = 20 + (dr - weights.min_dr_threshold) * 2
        else:
            dr_score = dr
            penalties.append(f"Low DR ({dr})")
        
        # Traffic Score (0-100)
        traffic = domain.traffic or 0
        if traffic >= 100000:
            traffic_score = 100
            bonuses.append("High traffic site (100k+)")
        elif traffic >= 50000:
            traffic_score = 80 + (traffic - 50000) / 50000 * 20
        elif traffic >= 10000:
            traffic_score = 50 + (traffic - 10000) / 40000 * 30
        elif traffic >= weights.min_traffic_threshold:
            traffic_score = 20 + (traffic - weights.min_traffic_threshold) / 9000 * 30
        else:
            traffic_score = traffic / weights.min_traffic_threshold * 20
            penalties.append(f"Low traffic ({traffic})")
        
        # Referring Domains Score (0-100)
        refs = domain.referring_domains or 0
        if refs >= 5000:
            refs_score = 100
            bonuses.append("Strong backlink profile (5000+ refs)")
        elif refs >= 1000:
            refs_score = 70 + (refs - 1000) / 4000 * 30
        elif refs >= 100:
            refs_score = 30 + (refs - 100) / 900 * 40
        else:
            refs_score = refs / 100 * 30
            if refs < 50:
                penalties.append(f"Few referring domains ({refs})")
        
        # Calculate weighted total
        total_score = (
            dr_score * weights.domain_rating_weight +
            traffic_score * weights.traffic_weight +
            refs_score * weights.referring_domains_weight +
            relevance_score * weights.relevance_weight
        )
        
        # Apply global penalties
        if dr == 0 and traffic == 0:
            total_score *= 0.3
            penalties.append("No metrics available")
        
        return ScoreBreakdown(
            domain_id=domain.id,
            total_score=round(total_score, 2),
            dr_score=round(dr_score, 2),
            traffic_score=round(traffic_score, 2),
            refs_score=round(refs_score, 2),
            relevance_score=round(relevance_score, 2),
            penalties=penalties,
            bonuses=bonuses
        )
    
    def rescore_all_domains(self, progress_callback=None):
        """Rescore all domains in database"""
        domains = self.db.get_all_domains()
        total = len(domains)
        
        for i, domain in enumerate(domains):
            breakdown = self.score_domain(domain)
            
            # Update in database
            self.db.connection.execute(
                "UPDATE domains SET quality_score = ? WHERE id = ?",
                (breakdown.total_score, domain.id)
            )
            
            if progress_callback and i % 100 == 0:
                progress_callback(i + 1, total)
        
        self.db.connection.commit()
        app_logger.info(f"Rescored {total} domains")
    
    def get_top_domains(self, limit: int = 100, min_score: float = 50.0) -> List[Domain]:
        """Get top scoring domains"""
        return self.db.get_domains(min_score=min_score, limit=limit)