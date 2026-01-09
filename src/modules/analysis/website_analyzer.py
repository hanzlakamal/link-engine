"""
Website Analyzer - Main analysis module
"""
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from datetime import datetime
from urllib.parse import urljoin, urlparse
import re
import json

from config import Settings
from core.database import Database, Domain
from core.logger import analysis_logger


class WebsiteAnalyzer:
    """Analyzes websites for guest posting opportunities"""
    
    GUEST_POST_PATTERNS = [
        r'write.?for.?us',
        r'guest.?post',
        r'contribute',
        r'submit.?(article|post|content)',
        r'become.?a?.?(contributor|author|writer)',
        r'editorial.?guidelines',
    ]
    
    CONTACT_PAGE_PATTERNS = [
        r'contact',
        r'get.?in.?touch',
        r'reach.?us',
    ]
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.client = httpx.Client(
            timeout=settings.general.request_timeout,
            follow_redirects=True,
            headers={
                'User-Agent': settings.general.user_agent
            }
        )
    
    def analyze(self, domain: Domain) -> Dict[str, Any]:
        """Analyze a domain for guest posting opportunities"""
        analysis_logger.info(f"Starting analysis of {domain.domain}")
        
        result = {
            'domain_id': domain.id,
            'domain': domain.domain,
            'success': False,
            'contact_methods': [],
            'guidelines': None,
            'errors': []
        }
        
        try:
            # Update status
            self.db.update_domain_status(domain.id, 'analyzing')
            
            # Get homepage
            base_url = domain.url or f"https://{domain.domain}"
            
            homepage_content, homepage_soup = self._fetch_page(base_url)
            
            if not homepage_soup:
                result['errors'].append("Failed to fetch homepage")
                self.db.update_domain_status(domain.id, 'analyzed')
                result['success'] = False
                return result
            
            # Find guest post pages
            guest_post_urls = self._find_guest_post_pages(homepage_soup, base_url)
            analysis_logger.debug(f"Found {len(guest_post_urls)} potential guest post pages")
            
            # Analyze guest post pages
            for url in guest_post_urls[:3]:  # Limit to 3 pages
                page_content, page_soup = self._fetch_page(url)
                
                if page_soup:
                    # Extract contact methods
                    contacts = self._extract_contact_methods(page_soup, url)
                    result['contact_methods'].extend(contacts)
                    
                    # Extract guidelines using AI
                    if self.settings.api.anthropic_api_key:
                        guidelines = self._extract_guidelines_ai(page_content, url)
                        if guidelines:
                            result['guidelines'] = guidelines
            
            # If no guest post pages found, check contact page
            if not result['contact_methods']:
                contact_urls = self._find_contact_pages(homepage_soup, base_url)
                
                for url in contact_urls[:2]:
                    page_content, page_soup = self._fetch_page(url)
                    
                    if page_soup:
                        contacts = self._extract_contact_methods(page_soup, url)
                        result['contact_methods'].extend(contacts)
            
            # Save to database
            for contact in result['contact_methods']:
                self.db.insert_contact_method(
                    domain_id=domain.id,
                    method_type=contact['type'],
                    email=contact.get('email'),
                    url=contact.get('url'),
                    form_fields=contact.get('form_fields'),
                    guidelines=result.get('guidelines'),
                    has_captcha=contact.get('has_captcha', False),
                    captcha_type=contact.get('captcha_type')
                )
            
            # Update domain status
            self.db.update_domain_status(domain.id, 'analyzed')
            
            # Update last analyzed
            domain.last_analyzed = datetime.now()
            self.db.update_domain(domain)
            
            result['success'] = True
            analysis_logger.info(f"Analysis complete for {domain.domain}: {len(result['contact_methods'])} contacts found")
            
            # Log activity
            self.db.log_activity(
                'analysis_complete', 'analysis', domain.id,
                f"Found {len(result['contact_methods'])} contact methods"
            )
            
        except Exception as e:
            analysis_logger.error(f"Analysis error for {domain.domain}: {e}")
            result['errors'].append(str(e))
            self.db.update_domain_status(domain.id, 'error')
            
            self.db.log_activity(
                'analysis_error', 'analysis', domain.id,
                f"Analysis failed: {str(e)}",
                status='error',
                error_message=str(e)
            )
        
        return result
    
    def _fetch_page(self, url: str) -> tuple:
        """Fetch a page and return content and soup"""
        try:
            response = self.client.get(url)
            response.raise_for_status()
            
            content = response.text
            soup = BeautifulSoup(content, 'lxml')
            
            return content, soup
        except Exception as e:
            analysis_logger.warning(f"Failed to fetch {url}: {e}")
            return None, None
    
    def _find_guest_post_pages(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find potential guest post pages"""
        urls = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            # Check link text
            for pattern in self.GUEST_POST_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    full_url = urljoin(base_url, href)
                    if full_url not in urls:
                        urls.append(full_url)
                    break
            
            # Check URL
            for pattern in self.GUEST_POST_PATTERNS:
                if re.search(pattern, href, re.IGNORECASE):
                    full_url = urljoin(base_url, href)
                    if full_url not in urls:
                        urls.append(full_url)
                    break
        
        return urls
    
    def _find_contact_pages(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find contact pages"""
        urls = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            for pattern in self.CONTACT_PAGE_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE) or re.search(pattern, href, re.IGNORECASE):
                    full_url = urljoin(base_url, href)
                    if full_url not in urls:
                        urls.append(full_url)
                    break
        
        return urls
    
    def _extract_contact_methods(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        """Extract contact methods from a page"""
        contacts = []
        
        # Find email addresses
        text = soup.get_text()
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, text)
        
        for email in set(emails):
            # Filter out common non-contact emails
            if not any(skip in email.lower() for skip in ['example.com', 'domain.com', 'email.com']):
                contacts.append({
                    'type': 'email',
                    'email': email,
                    'url': url
                })
        
        # Find forms
        forms = soup.find_all('form')
        
        for form in forms:
            form_data = self._analyze_form(form, url)
            if form_data:
                contacts.append(form_data)
        
        return contacts
    
    def _analyze_form(self, form: BeautifulSoup, page_url: str) -> Optional[Dict]:
        """Analyze a contact form"""
        action = form.get('action', '')
        method = form.get('method', 'post').upper()
        
        fields = []
        
        # Find all inputs
        for input_tag in form.find_all(['input', 'textarea', 'select']):
            field_type = input_tag.get('type', 'text')
            
            if field_type in ['hidden', 'submit', 'button']:
                continue
            
            field = {
                'name': input_tag.get('name', ''),
                'type': field_type,
                'required': input_tag.has_attr('required'),
                'label': self._find_field_label(input_tag, form)
            }
            
            if input_tag.name == 'select':
                options = [opt.get_text(strip=True) for opt in input_tag.find_all('option')]
                field['options'] = options
            
            fields.append(field)
        
        if not fields:
            return None
        
        # Check for captcha
        has_captcha = False
        captcha_type = None
        
        if form.find(class_=re.compile('g-recaptcha|recaptcha', re.I)):
            has_captcha = True
            captcha_type = 'reCAPTCHA'
        elif form.find(class_=re.compile('h-captcha|hcaptcha', re.I)):
            has_captcha = True
            captcha_type = 'hCaptcha'
        elif form.find(attrs={'data-sitekey': True}):
            has_captcha = True
            captcha_type = 'Unknown'
        
        return {
            'type': 'form',
            'url': urljoin(page_url, action) if action else page_url,
            'method': method,
            'form_fields': fields,
            'has_captcha': has_captcha,
            'captcha_type': captcha_type
        }
    
    def _find_field_label(self, field: BeautifulSoup, form: BeautifulSoup) -> str:
        """Find the label for a form field"""
        # Check for label with for attribute
        field_id = field.get('id')
        if field_id:
            label = form.find('label', attrs={'for': field_id})
            if label:
                return label.get_text(strip=True)
        
        # Check for parent label
        parent = field.find_parent('label')
        if parent:
            return parent.get_text(strip=True).replace(field.get_text(), '').strip()
        
        # Use placeholder
        placeholder = field.get('placeholder', '')
        if placeholder:
            return placeholder
        
        # Use name as fallback
        return field.get('name', 'Unknown')
    
    def _extract_guidelines_ai(self, page_content: str, url: str) -> Optional[Dict]:
        """Extract guidelines using AI"""
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=self.settings.api.anthropic_api_key)
            
            # Truncate content if too long
            if len(page_content) > 15000:
                page_content = page_content[:15000]
            
            # Clean HTML
            soup = BeautifulSoup(page_content, 'lxml')
            
            # Remove scripts and styles
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            
            clean_text = soup.get_text(separator='\n', strip=True)
            
            prompt = self.settings.prompts.guidelines_extraction.format(
                page_content=clean_text[:10000]
            )
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            result_text = response.content[0].text
            
            # Try to parse JSON from response
            try:
                # Find JSON in response
                json_match = re.search(r'\{[\s\S]*\}', result_text)
                if json_match:
                    guidelines = json.loads(json_match.group())
                    analysis_logger.debug(f"Extracted guidelines from {url}")
                    return guidelines
            except json.JSONDecodeError:
                analysis_logger.warning(f"Failed to parse guidelines JSON from {url}")
            
            return None
            
        except Exception as e:
            analysis_logger.error(f"AI guidelines extraction failed: {e}")
            return None
    
    def close(self):
        """Close the HTTP client"""
        self.client.close()