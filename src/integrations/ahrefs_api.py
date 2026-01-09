"""
Ahrefs API Integration
"""
import httpx
from typing import Optional, Dict, Any
from core.logger import api_logger


class AhrefsAPI:
    """Ahrefs API client"""
    
    BASE_URL = "https://api.ahrefs.com/v3"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=30,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json"
            }
        )
    
    def get_domain_metrics(self, domain: str) -> Optional[Dict[str, Any]]:
        """Get domain metrics from Ahrefs"""
        try:
            api_logger.debug(f"Fetching Ahrefs metrics for {domain}")
            
            # Domain rating endpoint
            response = self.client.get(
                f"{self.BASE_URL}/site-explorer/domain-rating",
                params={
                    "target": domain,
                    "mode": "domain"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                result = {
                    'domain_rating': data.get('domain_rating', 0),
                    'organic_traffic': 0,
                    'referring_domains': 0
                }
                
                # Get more metrics
                metrics_response = self.client.get(
                    f"{self.BASE_URL}/site-explorer/metrics",
                    params={
                        "target": domain,
                        "mode": "domain"
                    }
                )
                
                if metrics_response.status_code == 200:
                    metrics_data = metrics_response.json()
                    result['organic_traffic'] = metrics_data.get('organic', {}).get('traffic', 0)
                    result['referring_domains'] = metrics_data.get('backlinks', {}).get('refdomains', 0)
                
                api_logger.info(f"Ahrefs metrics for {domain}: DR={result['domain_rating']}")
                return result
            
            elif response.status_code == 401:
                api_logger.error("Ahrefs API authentication failed")
                return None
            
            elif response.status_code == 429:
                api_logger.warning("Ahrefs API rate limit reached")
                return None
            
            else:
                api_logger.warning(f"Ahrefs API error: {response.status_code}")
                return None
                
        except Exception as e:
            api_logger.error(f"Ahrefs API error for {domain}: {e}")
            return None
    
    def get_backlinks(self, target: str, limit: int = 100) -> Optional[list]:
        """Get backlinks for a target"""
        try:
            response = self.client.get(
                f"{self.BASE_URL}/site-explorer/backlinks",
                params={
                    "target": target,
                    "mode": "domain",
                    "limit": limit
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('backlinks', [])
            
            return None
            
        except Exception as e:
            api_logger.error(f"Ahrefs backlinks error: {e}")
            return None
    
    def close(self):
        """Close the HTTP client"""
        self.client.close()