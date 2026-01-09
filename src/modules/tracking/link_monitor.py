"""
Link Monitor - Automated backlink verification and monitoring
"""
import asyncio
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from enum import Enum

import httpx
from bs4 import BeautifulSoup

from config import Settings
from core.database import Database
from core.logger import app_logger
from integrations.ahrefs_api import AhrefsAPI
from constants import LinkStatus, LinkType


@dataclass
class LinkCheckResult:
    """Result of checking a single backlink"""
    backlink_id: int
    source_url: str
    target_url: str
    status: LinkStatus
    http_status: int = 0
    anchor_text: str = ""
    anchor_changed: bool = False
    rel_attribute: str = ""
    rel_changed: bool = False
    link_position: str = ""  # header, body, footer, sidebar
    context_text: str = ""
    error_message: str = ""
    checked_at: datetime = field(default_factory=datetime.now)
    response_time_ms: int = 0


@dataclass
class LinkHealth:
    """Overall health of a backlink"""
    backlink_id: int
    is_live: bool
    uptime_percentage: float
    last_seen: Optional[datetime]
    days_since_last_check: int
    total_checks: int
    failed_checks: int
    status_history: List[str]
    alerts: List[str]


class LinkMonitor:
    """Monitor and verify backlinks"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.ahrefs: Optional[AhrefsAPI] = None
        
        if settings.api.ahrefs_api_key:
            self.ahrefs = AhrefsAPI(settings.api.ahrefs_api_key)
        
        self.client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={'User-Agent': settings.general.user_agent}
        )
    
    async def check_link(self, backlink: Dict) -> LinkCheckResult:
        """Check a single backlink"""
        result = LinkCheckResult(
            backlink_id=backlink['id'],
            source_url=backlink['source_url'],
            target_url=backlink['target_url'],
            status=LinkStatus.ERROR
        )
        
        start_time = datetime.now()
        
        try:
            app_logger.debug(f"Checking link: {backlink['source_url']}")
            
            response = await self.client.get(backlink['source_url'])
            result.http_status = response.status_code
            result.response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if response.status_code == 200:
                # Parse page and find link
                soup = BeautifulSoup(response.text, 'lxml')
                link_found = self._find_link_to_target(soup, backlink['target_url'])
                
                if link_found:
                    result.status = LinkStatus.LIVE
                    result.anchor_text = link_found['anchor']
                    result.rel_attribute = link_found['rel']
                    result.link_position = link_found['position']
                    result.context_text = link_found['context']
                    
                    # Check for changes
                    if backlink.get('anchor_text') and backlink['anchor_text'] != result.anchor_text:
                        result.anchor_changed = True
                    
                    expected_rel = backlink.get('link_type', 'dofollow')
                    if self._rel_to_type(result.rel_attribute) != expected_rel:
                        result.rel_changed = True
                else:
                    result.status = LinkStatus.REMOVED
                    result.error_message = "Link not found on page"
            
            elif response.status_code == 404:
                result.status = LinkStatus.REMOVED
                result.error_message = "Page not found (404)"
            
            elif response.status_code >= 500:
                result.status = LinkStatus.ERROR
                result.error_message = f"Server error ({response.status_code})"
            
            else:
                result.status = LinkStatus.ERROR
                result.error_message = f"HTTP {response.status_code}"
                
        except httpx.TimeoutException:
            result.status = LinkStatus.ERROR
            result.error_message = "Request timeout"
            
        except httpx.RequestError as e:
            result.status = LinkStatus.ERROR
            result.error_message = f"Request error: {str(e)}"
            
        except Exception as e:
            result.status = LinkStatus.ERROR
            result.error_message = str(e)
            app_logger.error(f"Link check error: {e}")
        
        result.checked_at = datetime.now()
        return result
    
    def _find_link_to_target(self, soup: BeautifulSoup, 
                             target_url: str) -> Optional[Dict]:
        """Find a link to the target URL on the page"""
        target_parsed = urlparse(target_url)
        target_domain = target_parsed.netloc.lower()
        target_path = target_parsed.path.lower().rstrip('/')
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            try:
                href_parsed = urlparse(href)
                href_domain = href_parsed.netloc.lower()
                href_path = href_parsed.path.lower().rstrip('/')
                
                # Check if link points to target
                if href_domain == target_domain:
                    # Either exact match or contains target path
                    if href_path == target_path or target_path in href_path or href_path in target_path:
                        return {
                            'anchor': link.get_text(strip=True),
                            'rel': ' '.join(link.get('rel', [])),
                            'position': self._determine_position(link),
                            'context': self._get_context(link)
                        }
            except:
                continue
        
        return None
    
    def _determine_position(self, link: BeautifulSoup) -> str:
        """Determine where the link is positioned on the page"""
        # Check parent elements
        for parent in link.parents:
            tag_name = parent.name.lower() if parent.name else ''
            classes = ' '.join(parent.get('class', [])).lower()
            id_attr = (parent.get('id') or '').lower()
            
            # Check for common patterns
            if tag_name in ['header', 'nav'] or 'header' in classes or 'nav' in classes:
                return 'header'
            elif tag_name == 'footer' or 'footer' in classes:
                return 'footer'
            elif tag_name == 'aside' or 'sidebar' in classes or 'sidebar' in id_attr:
                return 'sidebar'
            elif tag_name == 'article' or 'content' in classes or 'post' in classes:
                return 'body'
            elif 'author' in classes or 'bio' in classes:
                return 'bio'
        
        return 'body'  # Default to body
    
    def _get_context(self, link: BeautifulSoup) -> str:
        """Get surrounding text context"""
        # Get parent paragraph or div
        parent = link.find_parent(['p', 'div', 'li', 'td'])
        
        if parent:
            text = parent.get_text(strip=True)
            # Limit length
            if len(text) > 200:
                # Find link position and get surrounding text
                anchor = link.get_text(strip=True)
                if anchor in text:
                    pos = text.find(anchor)
                    start = max(0, pos - 100)
                    end = min(len(text), pos + len(anchor) + 100)
                    text = "..." + text[start:end] + "..."
            return text
        
        return ""
    
    def _rel_to_type(self, rel: str) -> str:
        """Convert rel attribute to link type"""
        rel_lower = rel.lower()
        
        if 'sponsored' in rel_lower:
            return 'sponsored'
        elif 'ugc' in rel_lower:
            return 'ugc'
        elif 'nofollow' in rel_lower:
            return 'nofollow'
        else:
            return 'dofollow'
    
    async def check_all_links(self, progress_callback=None) -> List[LinkCheckResult]:
        """Check all active backlinks"""
        backlinks = self.db.get_backlinks(status='live')
        
        results = []
        total = len(backlinks)
        
        for i, backlink in enumerate(backlinks):
            result = await self.check_link(backlink)
            results.append(result)
            
            # Save result to database
            self._save_check_result(result)
            
            # Update backlink status
            self._update_backlink_status(result)
            
            if progress_callback:
                progress_callback(i + 1, total, backlink['source_url'], result.status.value)
            
            # Small delay between requests
            await asyncio.sleep(0.5)
        
        return results
    
    def _save_check_result(self, result: LinkCheckResult):
        """Save check result to database"""
        self.db.connection.execute("""
            INSERT INTO link_checks 
            (backlink_id, checked_at, status, http_status, 
             anchor_changed, new_anchor, rel_changed, new_rel, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.backlink_id,
            result.checked_at,
            result.status.value,
            result.http_status,
            result.anchor_changed,
            result.anchor_text if result.anchor_changed else None,
            result.rel_changed,
            result.rel_attribute if result.rel_changed else None,
            result.error_message
        ))
        self.db.connection.commit()
    
    def _update_backlink_status(self, result: LinkCheckResult):
        """Update backlink status based on check result"""
        update_fields = {
            'status': result.status.value,
            'last_checked': result.checked_at
        }
        
        if result.status == LinkStatus.LIVE:
            update_fields['last_live'] = result.checked_at
            
            if result.anchor_changed:
                update_fields['anchor_text'] = result.anchor_text
            
            if result.rel_changed:
                update_fields['link_type'] = self._rel_to_type(result.rel_attribute)
            
            if result.link_position:
                update_fields['link_position'] = result.link_position
            
            if result.context_text:
                update_fields['context_text'] = result.context_text
        
        # Build update query
        set_clause = ', '.join(f"{k} = ?" for k in update_fields.keys())
        values = list(update_fields.values()) + [result.backlink_id]
        
        self.db.connection.execute(
            f"UPDATE backlinks SET {set_clause} WHERE id = ?",
            values
        )
        self.db.connection.commit()
    
    def get_link_health(self, backlink_id: int) -> LinkHealth:
        """Get health status for a backlink"""
        # Get backlink
        cursor = self.db.connection.execute(
            "SELECT * FROM backlinks WHERE id = ?", (backlink_id,)
        )
        backlink = dict(cursor.fetchone())
        
        # Get check history
        cursor = self.db.connection.execute("""
            SELECT * FROM link_checks 
            WHERE backlink_id = ? 
            ORDER BY checked_at DESC
            LIMIT 30
        """, (backlink_id,))
        
        checks = [dict(row) for row in cursor.fetchall()]
        
        # Calculate stats
        total_checks = len(checks)
        failed_checks = sum(1 for c in checks if c['status'] != 'live')
        
        uptime = 100.0
        if total_checks > 0:
            uptime = ((total_checks - failed_checks) / total_checks) * 100
        
        # Get last seen
        last_live = None
        for check in checks:
            if check['status'] == 'live':
                last_live = datetime.fromisoformat(check['checked_at']) if isinstance(check['checked_at'], str) else check['checked_at']
                break
        
        # Days since last check
        last_checked = backlink.get('last_checked')
        days_since = 0
        if last_checked:
            if isinstance(last_checked, str):
                last_checked = datetime.fromisoformat(last_checked)
            days_since = (datetime.now() - last_checked).days
        
        # Build alerts
        alerts = []
        if backlink['status'] == 'removed':
            alerts.append("⚠️ Link has been removed")
        elif uptime < 90:
            alerts.append(f"⚠️ Uptime below 90% ({uptime:.1f}%)")
        if days_since > 7:
            alerts.append(f"⚠️ Not checked in {days_since} days")
        
        # Check for recent changes
        if checks and checks[0].get('anchor_changed'):
            alerts.append("ℹ️ Anchor text was recently changed")
        if checks and checks[0].get('rel_changed'):
            alerts.append("ℹ️ Rel attribute was recently changed")
        
        return LinkHealth(
            backlink_id=backlink_id,
            is_live=backlink['status'] == 'live',
            uptime_percentage=uptime,
            last_seen=last_live,
            days_since_last_check=days_since,
            total_checks=total_checks,
            failed_checks=failed_checks,
            status_history=[c['status'] for c in checks[:10]],
            alerts=alerts
        )
    
    async def verify_with_ahrefs(self, target_url: str) -> List[Dict]:
        """Verify backlinks using Ahrefs API"""
        if not self.ahrefs:
            return []
        
        try:
            backlinks = self.ahrefs.get_backlinks(target_url, limit=100)
            return backlinks or []
        except Exception as e:
            app_logger.error(f"Ahrefs verification failed: {e}")
            return []
    
    def get_removed_links(self, days: int = 7) -> List[Dict]:
        """Get links removed in the last N days"""
        since = datetime.now() - timedelta(days=days)
        
        cursor = self.db.connection.execute("""
            SELECT b.*, d.domain 
            FROM backlinks b
            JOIN domains d ON b.domain_id = d.id
            WHERE b.status = 'removed'
            AND b.last_checked >= ?
            ORDER BY b.last_checked DESC
        """, (since,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Get overall monitoring statistics"""
        cursor = self.db.connection.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'live' THEN 1 ELSE 0 END) as live,
                SUM(CASE WHEN status = 'removed' THEN 1 ELSE 0 END) as removed,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                AVG(CASE WHEN status = 'live' THEN 1.0 ELSE 0.0 END) * 100 as uptime
            FROM backlinks
        """)
        
        row = cursor.fetchone()
        
        # Get recent removals
        removed_7d = len(self.get_removed_links(7))
        
        # Get unchecked links
        cursor = self.db.connection.execute("""
            SELECT COUNT(*) FROM backlinks 
            WHERE last_checked IS NULL 
            OR last_checked < datetime('now', '-7 days')
        """)
        unchecked = cursor.fetchone()[0]
        
        return {
            'total_links': row[0] or 0,
            'live_links': row[1] or 0,
            'removed_links': row[2] or 0,
            'error_links': row[3] or 0,
            'overall_uptime': round(row[4] or 0, 1),
            'removed_last_7_days': removed_7d,
            'needs_checking': unchecked
        }
    
    def run_sync(self, backlink: Dict) -> LinkCheckResult:
        """Synchronous wrapper"""
        return asyncio.run(self.check_link(backlink))
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()