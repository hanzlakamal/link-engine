"""
Domain Import Module - Handles various import sources
"""
import csv
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Generator
from dataclasses import dataclass
import re
from urllib.parse import urlparse

from core.database import Database, Domain
from core.logger import app_logger
from constants import MAX_CSV_ROWS, SKIP_EMAIL_PATTERNS


@dataclass
class ImportResult:
    """Result of an import operation"""
    total_rows: int
    imported: int
    skipped_duplicates: int
    skipped_invalid: int
    errors: List[str]


class DomainImporter:
    """Handles domain imports from various sources"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def import_csv(self, file_path: Path, column_mapping: Dict[str, str],
                  default_niche: str = "", clean_domains: bool = True,
                  skip_duplicates: bool = True) -> ImportResult:
        """Import domains from CSV file"""
        app_logger.info(f"Starting CSV import from {file_path}")
        
        result = ImportResult(
            total_rows=0,
            imported=0,
            skipped_duplicates=0,
            skipped_invalid=0,
            errors=[]
        )
        
        try:
            domains = []
            
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                # Detect dialect
                sample = f.read(4096)
                f.seek(0)
                
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except:
                    dialect = csv.excel
                
                reader = csv.DictReader(f, dialect=dialect)
                
                for row_num, row in enumerate(reader):
                    if row_num >= MAX_CSV_ROWS:
                        result.errors.append(f"Stopped at {MAX_CSV_ROWS} rows (limit)")
                        break
                    
                    result.total_rows += 1
                    
                    try:
                        domain = self._parse_row(row, column_mapping, default_niche, clean_domains)
                        
                        if domain:
                            domains.append(domain)
                        else:
                            result.skipped_invalid += 1
                    except Exception as e:
                        result.errors.append(f"Row {row_num + 1}: {str(e)}")
                        result.skipped_invalid += 1
            
            # Bulk insert
            if domains:
                inserted, skipped = self.db.bulk_insert_domains(domains)
                result.imported = inserted
                result.skipped_duplicates = skipped
            
            app_logger.info(f"CSV import complete: {result.imported} imported, "
                          f"{result.skipped_duplicates} duplicates, "
                          f"{result.skipped_invalid} invalid")
            
        except Exception as e:
            app_logger.error(f"CSV import failed: {e}")
            result.errors.append(str(e))
        
        return result
    
    def import_json(self, file_path: Path, default_niche: str = "") -> ImportResult:
        """Import domains from JSON file"""
        app_logger.info(f"Starting JSON import from {file_path}")
        
        result = ImportResult(
            total_rows=0,
            imported=0,
            skipped_duplicates=0,
            skipped_invalid=0,
            errors=[]
        )
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                domains_data = data
            elif isinstance(data, dict) and 'domains' in data:
                domains_data = data['domains']
            else:
                result.errors.append("Invalid JSON structure")
                return result
            
            domains = []
            
            for item in domains_data:
                result.total_rows += 1
                
                try:
                    if isinstance(item, str):
                        domain_name = self.clean_domain(item)
                    elif isinstance(item, dict):
                        domain_name = self.clean_domain(item.get('domain', ''))
                    else:
                        continue
                    
                    if domain_name:
                        domain = Domain(
                            domain=domain_name,
                            url=f"https://{domain_name}",
                            niche=item.get('niche', default_niche) if isinstance(item, dict) else default_niche,
                            status="pending"
                        )
                        domains.append(domain)
                    else:
                        result.skipped_invalid += 1
                except Exception as e:
                    result.errors.append(str(e))
                    result.skipped_invalid += 1
            
            if domains:
                inserted, skipped = self.db.bulk_insert_domains(domains)
                result.imported = inserted
                result.skipped_duplicates = skipped
            
        except Exception as e:
            app_logger.error(f"JSON import failed: {e}")
            result.errors.append(str(e))
        
        return result
    
    def import_text(self, file_path: Path, default_niche: str = "") -> ImportResult:
        """Import domains from plain text file (one per line)"""
        app_logger.info(f"Starting text import from {file_path}")
        
        result = ImportResult(
            total_rows=0,
            imported=0,
            skipped_duplicates=0,
            skipped_invalid=0,
            errors=[]
        )
        
        try:
            domains = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    result.total_rows += 1
                    
                    domain_name = self.clean_domain(line)
                    
                    if domain_name:
                        domain = Domain(
                            domain=domain_name,
                            url=f"https://{domain_name}",
                            niche=default_niche,
                            status="pending"
                        )
                        domains.append(domain)
                    else:
                        result.skipped_invalid += 1
            
            if domains:
                inserted, skipped = self.db.bulk_insert_domains(domains)
                result.imported = inserted
                result.skipped_duplicates = skipped
            
        except Exception as e:
            app_logger.error(f"Text import failed: {e}")
            result.errors.append(str(e))
        
        return result
    
    def import_from_ahrefs_export(self, file_path: Path) -> ImportResult:
        """Import from Ahrefs CSV export"""
        # Ahrefs exports have specific column names
        column_mapping = {
            'domain': 'Referring Page URL',  # or 'Target URL'
            'dr': 'DR',
            'traffic': 'Traffic',
        }
        
        return self.import_csv(file_path, column_mapping)
    
    def import_from_scrapebox(self, file_path: Path, default_niche: str = "") -> ImportResult:
        """Import from Scrapebox export"""
        # Scrapebox typically exports URLs one per line
        return self.import_text(file_path, default_niche)
    
    def _parse_row(self, row: Dict, column_mapping: Dict[str, str],
                  default_niche: str, clean: bool) -> Optional[Domain]:
        """Parse a CSV row into a Domain"""
        domain_col = column_mapping.get('domain', '')
        url_col = column_mapping.get('url', '')
        niche_col = column_mapping.get('niche', '')
        
        domain_value = row.get(domain_col, '').strip()
        
        if not domain_value:
            return None
        
        if clean:
            domain_value = self.clean_domain(domain_value)
        
        if not domain_value or not self.is_valid_domain(domain_value):
            return None
        
        url = row.get(url_col, '').strip() if url_col else ''
        if not url:
            url = f"https://{domain_value}"
        
        niche = row.get(niche_col, '').strip() if niche_col else ''
        if not niche:
            niche = default_niche
        
        return Domain(
            domain=domain_value,
            url=url,
            niche=niche,
            status="pending"
        )
    
    @staticmethod
    def clean_domain(domain: str) -> str:
        """Clean and normalize a domain name"""
        if not domain:
            return ""
        
        domain = domain.strip().lower()
        
        # Remove protocol
        for prefix in ['https://', 'http://', '//']:
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
        
        # Remove www.
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Remove trailing slash and path
        domain = domain.split('/')[0]
        
        # Remove port
        domain = domain.split(':')[0]
        
        # Remove query string
        domain = domain.split('?')[0]
        
        # Remove any whitespace
        domain = domain.strip()
        
        return domain
    
    @staticmethod
    def is_valid_domain(domain: str) -> bool:
        """Check if a domain name is valid"""
        if not domain or len(domain) < 4:
            return False
        
        # Basic domain pattern
        pattern = r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$'
        
        if not re.match(pattern, domain):
            return False
        
        # Check for invalid patterns
        invalid_patterns = [
            'localhost',
            '127.0.0.1',
            '0.0.0.0',
            'example.com',
            'test.com',
        ]
        
        for invalid in invalid_patterns:
            if domain == invalid or domain.endswith(f'.{invalid}'):
                return False
        
        return True