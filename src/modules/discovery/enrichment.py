"""
Domain Enrichment Module - Fetch metrics from various sources
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import asyncio

from core.database import Database, Domain
from core.logger import app_logger
from integrations.ahrefs_api import AhrefsAPI
from config import Settings


@dataclass
class EnrichmentResult:
    """Result of domain enrichment"""
    domain_id: int
    success: bool
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DomainEnrichment:
    """Enriches domains with external data"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.ahrefs: Optional[AhrefsAPI] = None
        
        if settings.api.ahrefs_api_key:
            self.ahrefs = AhrefsAPI(settings.api.ahrefs_api_key)
    
    def enrich_domain(self, domain: Domain) -> EnrichmentResult:
        """Enrich a single domain"""
        app_logger.debug(f"Enriching domain: {domain.domain}")
        
        result = EnrichmentResult(domain_id=domain.id, success=False)
        
        if not self.ahrefs:
            result.error = "Ahrefs API not configured"
            return result
        
        try:
            metrics = self.ahrefs.get_domain_metrics(domain.domain)
            
            if metrics:
                # Calculate quality score
                score = self.calculate_quality_score(metrics)
                
                # Update domain in database
                self.db.update_domain_metrics(
                    domain.id,
                    dr=metrics.get('domain_rating', 0),
                    traffic=metrics.get('organic_traffic', 0),
                    referring_domains=metrics.get('referring_domains', 0),
                    quality_score=score
                )
                
                result.success = True
                result.metrics = metrics
                result.metrics['quality_score'] = score
                
                app_logger.info(f"Enriched {domain.domain}: DR={metrics.get('domain_rating')}, Score={score:.1f}")
            else:
                result.error = "No data returned from Ahrefs"
        
        except Exception as e:
            result.error = str(e)
            app_logger.error(f"Enrichment failed for {domain.domain}: {e}")
        
        return result
    
    def enrich_domains_batch(self, domains: List[Domain],
                            progress_callback=None) -> List[EnrichmentResult]:
        """Enrich multiple domains"""
        results = []
        total = len(domains)
        
        for i, domain in enumerate(domains):
            result = self.enrich_domain(domain)
            results.append(result)
            
            if progress_callback:
                progress_callback(i + 1, total, domain.domain)
            
            # Rate limiting - 1 request per second
            import time
            time.sleep(1)
        
        return results
    
    def calculate_quality_score(self, metrics: Dict[str, Any]) -> float:
        """Calculate quality score from metrics"""
        weights = self.settings.scoring
        
        # Normalize values
        dr = min(metrics.get('domain_rating', 0), weights.max_dr_cap)
        dr_normalized = dr / weights.max_dr_cap * 100
        
        traffic = min(metrics.get('organic_traffic', 0), weights.max_traffic_cap)
        traffic_normalized = traffic / weights.max_traffic_cap * 100
        
        refs = min(metrics.get('referring_domains', 0), 10000)
        refs_normalized = refs / 10000 * 100
        
        # Calculate weighted score
        score = (
            dr_normalized * weights.domain_rating_weight +
            traffic_normalized * weights.traffic_weight +
            refs_normalized * weights.referring_domains_weight
        )
        
        # Apply minimum thresholds
        if dr < weights.min_dr_threshold:
            score *= 0.5  # Penalty for low DR
        
        if traffic < weights.min_traffic_threshold:
            score *= 0.7  # Penalty for low traffic
        
        return round(score, 2)
    
    def get_domain_competitors(self, domain: Domain) -> List[str]:
        """Get competing domains (domains linking to similar sites)"""
        if not self.ahrefs:
            return []
        
        # This would use Ahrefs' competing domains endpoint
        # Placeholder for now
        return []
    
    def close(self):
        """Close resources"""
        if self.ahrefs:
            self.ahrefs.close()