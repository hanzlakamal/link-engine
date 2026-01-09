"""
Contact Method Detection Module
"""
import re
from typing import List, Dict, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from core.logger import analysis_logger
from constants import GUEST_POST_KEYWORDS, SKIP_EMAIL_PATTERNS, PREFERRED_EMAIL_PATTERNS


class ContactDetector:
    """Detects contact methods on web pages"""
    
    def __init__(self):
        self.email_pattern = re.compile(
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        )
    
    def detect_all(self, soup: BeautifulSoup, page_url: str) -> Dict:
        """Detect all contact methods on a page"""
        result = {
            'emails': [],
            'forms': [],
            'social': [],
            'phone': [],
            'has_guest_post_info': False,
            'guest_post_url': None
        }
        
        # Detect emails
        result['emails'] = self.detect_emails(soup)
        
        # Detect forms
        result['forms'] = self.detect_forms(soup, page_url)
        
        # Detect social links
        result['social'] = self.detect_social_links(soup)
        
        # Detect phone numbers
        result['phone'] = self.detect_phone_numbers(soup)
        
        # Check for guest post information
        result['has_guest_post_info'] = self.has_guest_post_keywords(soup)
        
        # Find guest post page link
        result['guest_post_url'] = self.find_guest_post_link(soup, page_url)
        
        return result
    
    def detect_emails(self, soup: BeautifulSoup) -> List[Dict]:
        """Detect email addresses"""
        emails = []
        seen = set()
        
        # Get page text
        text = soup.get_text()
        
        # Find all email addresses
        for match in self.email_pattern.finditer(text):
            email = match.group().lower()
            
            if email in seen:
                continue
            seen.add(email)
            
            # Skip unwanted emails
            if any(pattern in email for pattern in SKIP_EMAIL_PATTERNS):
                continue
            
            # Determine priority
            priority = 'normal'
            if any(pattern in email for pattern in PREFERRED_EMAIL_PATTERNS):
                priority = 'high'
            
            emails.append({
                'email': email,
                'priority': priority,
                'source': 'page_text'
            })
        
        # Also check mailto links
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('mailto:'):
                email = href[7:].split('?')[0].lower()
                
                if email in seen:
                    continue
                seen.add(email)
                
                if any(pattern in email for pattern in SKIP_EMAIL_PATTERNS):
                    continue
                
                priority = 'normal'
                if any(pattern in email for pattern in PREFERRED_EMAIL_PATTERNS):
                    priority = 'high'
                
                emails.append({
                    'email': email,
                    'priority': priority,
                    'source': 'mailto_link'
                })
        
        # Sort by priority
        emails.sort(key=lambda x: 0 if x['priority'] == 'high' else 1)
        
        return emails
    
    def detect_forms(self, soup: BeautifulSoup, page_url: str) -> List[Dict]:
        """Detect and analyze contact forms"""
        forms = []
        
        for form in soup.find_all('form'):
            form_data = self._analyze_form(form, page_url)
            if form_data:
                forms.append(form_data)
        
        return forms
    
    def _analyze_form(self, form: BeautifulSoup, page_url: str) -> Optional[Dict]:
        """Analyze a single form"""
        # Get form attributes
        action = form.get('action', '')
        method = form.get('method', 'POST').upper()
        form_id = form.get('id', '')
        form_class = ' '.join(form.get('class', []))
        
        # Skip search forms, login forms, etc.
        skip_patterns = ['search', 'login', 'signin', 'signup', 'register', 'subscribe', 'newsletter']
        if any(pattern in form_id.lower() or pattern in form_class.lower() 
               for pattern in skip_patterns):
            return None
        
        # Collect fields
        fields = []
        has_message_field = False
        has_email_field = False
        
        for input_tag in form.find_all(['input', 'textarea', 'select']):
            field_type = input_tag.get('type', 'text')
            field_name = input_tag.get('name', '')
            
            # Skip certain field types
            if field_type in ['hidden', 'submit', 'button', 'reset', 'image']:
                continue
            
            field = {
                'name': field_name,
                'type': 'textarea' if input_tag.name == 'textarea' else field_type,
                'required': input_tag.has_attr('required'),
                'label': self._get_field_label(input_tag, form),
                'placeholder': input_tag.get('placeholder', ''),
                'max_length': input_tag.get('maxlength')
            }
            
            # Handle select options
            if input_tag.name == 'select':
                options = []
                for opt in input_tag.find_all('option'):
                    value = opt.get('value', '')
                    text = opt.get_text(strip=True)
                    if value or text:
                        options.append({'value': value, 'text': text})
                field['options'] = options
            
            fields.append(field)
            
            # Check field purposes
            if input_tag.name == 'textarea' or 'message' in field_name.lower():
                has_message_field = True
            if field_type == 'email' or 'email' in field_name.lower():
                has_email_field = True
        
        # Must have at least email or message field to be a contact form
        if not (has_message_field or has_email_field):
            return None
        
        if not fields:
            return None
        
        # Detect captcha
        captcha_info = self._detect_captcha(form)
        
        # Build form URL
        if action:
            form_url = urljoin(page_url, action)
        else:
            form_url = page_url
        
        return {
            'url': form_url,
            'method': method,
            'fields': fields,
            'field_count': len(fields),
            'has_captcha': captcha_info['present'],
            'captcha_type': captcha_info['type'],
            'captcha_sitekey': captcha_info['sitekey'],
            'is_contact_form': has_message_field and has_email_field,
            'form_id': form_id
        }
    
    def _get_field_label(self, field: BeautifulSoup, form: BeautifulSoup) -> str:
        """Get the label for a form field"""
        # Check for associated label
        field_id = field.get('id')
        if field_id:
            label = form.find('label', attrs={'for': field_id})
            if label:
                return label.get_text(strip=True)
        
        # Check for parent label
        parent = field.find_parent('label')
        if parent:
            # Get label text without the input's text
            label_text = parent.get_text(strip=True)
            return label_text
        
        # Check for aria-label
        aria_label = field.get('aria-label')
        if aria_label:
            return aria_label
        
        # Use placeholder
        placeholder = field.get('placeholder')
        if placeholder:
            return placeholder
        
        # Use name as fallback
        name = field.get('name', '')
        # Convert name to readable format
        return name.replace('_', ' ').replace('-', ' ').title()
    
    def _detect_captcha(self, form: BeautifulSoup) -> Dict:
        """Detect captcha in form"""
        result = {
            'present': False,
            'type': None,
            'sitekey': None
        }
        
        # Check for reCAPTCHA
        recaptcha = form.find(class_=re.compile(r'g-recaptcha|recaptcha', re.I))
        if recaptcha:
            result['present'] = True
            result['type'] = 'reCAPTCHA'
            result['sitekey'] = recaptcha.get('data-sitekey')
            return result
        
        # Check for reCAPTCHA v3
        if form.find(attrs={'data-recaptcha': True}):
            result['present'] = True
            result['type'] = 'reCAPTCHA_v3'
            return result
        
        # Check for hCaptcha
        hcaptcha = form.find(class_=re.compile(r'h-captcha|hcaptcha', re.I))
        if hcaptcha:
            result['present'] = True
            result['type'] = 'hCaptcha'
            result['sitekey'] = hcaptcha.get('data-sitekey')
            return result
        
        # Check for Cloudflare Turnstile
        turnstile = form.find(class_=re.compile(r'cf-turnstile', re.I))
        if turnstile:
            result['present'] = True
            result['type'] = 'Turnstile'
            result['sitekey'] = turnstile.get('data-sitekey')
            return result
        
        # Check for generic captcha images
        captcha_img = form.find('img', src=re.compile(r'captcha', re.I))
        if captcha_img:
            result['present'] = True
            result['type'] = 'Image_Captcha'
            return result
        
        return result
    
    def detect_social_links(self, soup: BeautifulSoup) -> List[Dict]:
        """Detect social media links"""
        social_patterns = {
            'twitter': r'twitter\.com/([^/\?]+)',
            'x': r'x\.com/([^/\?]+)',
            'linkedin': r'linkedin\.com/(in|company)/([^/\?]+)',
            'facebook': r'facebook\.com/([^/\?]+)',
            'instagram': r'instagram\.com/([^/\?]+)',
        }
        
        social_links = []
        seen = set()
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            
            for platform, pattern in social_patterns.items():
                match = re.search(pattern, href, re.I)
                if match:
                    if href in seen:
                        continue
                    seen.add(href)
                    
                    social_links.append({
                        'platform': platform,
                        'url': href,
                        'username': match.group(1) if match.lastindex else None
                    })
                    break
        
        return social_links
    
    def detect_phone_numbers(self, soup: BeautifulSoup) -> List[str]:
        """Detect phone numbers"""
        phone_pattern = re.compile(
            r'[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,9}'
        )
        
        text = soup.get_text()
        phones = phone_pattern.findall(text)
        
        # Filter and clean
        cleaned = []
        for phone in phones:
            # Remove very short matches
            digits = re.sub(r'\D', '', phone)
            if len(digits) >= 7:
                cleaned.append(phone.strip())
        
        return list(set(cleaned))
    
    def has_guest_post_keywords(self, soup: BeautifulSoup) -> bool:
        """Check if page has guest post related keywords"""
        text = soup.get_text().lower()
        
        for keyword in GUEST_POST_KEYWORDS:
            if keyword.lower() in text:
                return True
        
        return False
    
    def find_guest_post_link(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find link to guest post page"""
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text(strip=True).lower()
            
            for keyword in GUEST_POST_KEYWORDS:
                kw_lower = keyword.lower()
                if kw_lower in text or kw_lower.replace(' ', '-') in href:
                    full_url = urljoin(base_url, link.get('href'))
                    return full_url
        
        return None