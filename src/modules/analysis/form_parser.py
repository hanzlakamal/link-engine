"""
Form Parser Module - Deep form analysis
"""
import re
import json
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from enum import Enum

from core.logger import analysis_logger


class FieldType(Enum):
    TEXT = "text"
    EMAIL = "email"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"
    URL = "url"
    PHONE = "tel"
    NUMBER = "number"
    DATE = "date"
    HIDDEN = "hidden"
    UNKNOWN = "unknown"


class FieldPurpose(Enum):
    NAME = "name"
    EMAIL = "email"
    SUBJECT = "subject"
    MESSAGE = "message"
    WEBSITE = "website"
    COMPANY = "company"
    PHONE = "phone"
    TOPIC = "topic"
    CATEGORY = "category"
    FILE_UPLOAD = "file_upload"
    CAPTCHA = "captcha"
    CONSENT = "consent"
    OTHER = "other"


@dataclass
class FormField:
    """Represents a form field"""
    name: str
    field_type: FieldType
    purpose: FieldPurpose
    label: str
    required: bool
    placeholder: str = ""
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    options: List[Dict] = field(default_factory=list)
    default_value: str = ""
    validation_rules: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'type': self.field_type.value,
            'purpose': self.purpose.value,
            'label': self.label,
            'required': self.required,
            'placeholder': self.placeholder,
            'max_length': self.max_length,
            'options': self.options,
        }


@dataclass
class ParsedForm:
    """Represents a fully parsed form"""
    url: str
    method: str
    encoding: str
    fields: List[FormField]
    has_captcha: bool
    captcha_type: Optional[str]
    captcha_sitekey: Optional[str]
    has_file_upload: bool
    required_fields: List[str]
    honeypot_fields: List[str]
    hidden_fields: Dict[str, str]
    submit_button_text: str
    estimated_complexity: str  # simple, moderate, complex
    
    def to_dict(self) -> Dict:
        return {
            'url': self.url,
            'method': self.method,
            'encoding': self.encoding,
            'fields': [f.to_dict() for f in self.fields],
            'has_captcha': self.has_captcha,
            'captcha_type': self.captcha_type,
            'captcha_sitekey': self.captcha_sitekey,
            'has_file_upload': self.has_file_upload,
            'required_fields': self.required_fields,
            'hidden_fields': self.hidden_fields,
            'submit_button_text': self.submit_button_text,
            'complexity': self.estimated_complexity,
        }


class FormParser:
    """Deep form analysis and parsing"""
    
    # Patterns for field purpose detection
    PURPOSE_PATTERNS = {
        FieldPurpose.NAME: [
            r'name', r'full.?name', r'your.?name', r'author', r'first.?name', r'last.?name'
        ],
        FieldPurpose.EMAIL: [
            r'email', r'e-mail', r'mail'
        ],
        FieldPurpose.SUBJECT: [
            r'subject', r'title', r'headline', r'topic.?title'
        ],
        FieldPurpose.MESSAGE: [
            r'message', r'content', r'body', r'comment', r'description', r'pitch', r'proposal'
        ],
        FieldPurpose.WEBSITE: [
            r'website', r'url', r'site', r'blog', r'portfolio'
        ],
        FieldPurpose.COMPANY: [
            r'company', r'organization', r'business', r'org'
        ],
        FieldPurpose.PHONE: [
            r'phone', r'tel', r'mobile', r'cell'
        ],
        FieldPurpose.TOPIC: [
            r'topic', r'category', r'niche', r'subject.?area', r'interest'
        ],
        FieldPurpose.CONSENT: [
            r'consent', r'agree', r'terms', r'privacy', r'gdpr', r'accept'
        ],
    }
    
    # Honeypot detection patterns
    HONEYPOT_PATTERNS = [
        r'honeypot', r'hp_', r'_hp', r'trap', r'bot.?check', r'leave.?blank',
        r'do.?not.?fill', r'hidden.?field'
    ]
    
    def __init__(self):
        pass
    
    def parse_form(self, form: BeautifulSoup, page_url: str) -> ParsedForm:
        """Fully parse a form element"""
        # Basic attributes
        action = form.get('action', '')
        method = form.get('method', 'POST').upper()
        encoding = form.get('enctype', 'application/x-www-form-urlencoded')
        
        # Build form URL
        from urllib.parse import urljoin
        form_url = urljoin(page_url, action) if action else page_url
        
        # Parse all fields
        fields = []
        hidden_fields = {}
        honeypot_fields = []
        required_fields = []
        has_file_upload = False
        
        for element in form.find_all(['input', 'textarea', 'select']):
            field = self._parse_field(element, form)
            
            if field:
                # Track hidden fields
                if field.field_type == FieldType.HIDDEN:
                    hidden_fields[field.name] = field.default_value
                    continue
                
                # Detect honeypots
                if self._is_honeypot(element, field):
                    honeypot_fields.append(field.name)
                    continue
                
                # Track required fields
                if field.required:
                    required_fields.append(field.name)
                
                # Track file uploads
                if field.field_type == FieldType.FILE:
                    has_file_upload = True
                
                fields.append(field)
        
        # Detect captcha
        captcha_info = self._detect_captcha_deep(form)
        
        # Get submit button text
        submit_text = self._get_submit_button_text(form)
        
        # Estimate complexity
        complexity = self._estimate_complexity(fields, captcha_info['present'], has_file_upload)
        
        return ParsedForm(
            url=form_url,
            method=method,
            encoding=encoding,
            fields=fields,
            has_captcha=captcha_info['present'],
            captcha_type=captcha_info['type'],
            captcha_sitekey=captcha_info['sitekey'],
            has_file_upload=has_file_upload,
            required_fields=required_fields,
            honeypot_fields=honeypot_fields,
            hidden_fields=hidden_fields,
            submit_button_text=submit_text,
            estimated_complexity=complexity
        )
    
    def _parse_field(self, element: BeautifulSoup, form: BeautifulSoup) -> Optional[FormField]:
        """Parse a single form field"""
        tag_name = element.name
        field_name = element.get('name', '')
        
        if not field_name:
            return None
        
        # Determine field type
        if tag_name == 'textarea':
            field_type = FieldType.TEXTAREA
        elif tag_name == 'select':
            field_type = FieldType.SELECT
        else:
            type_attr = element.get('type', 'text').lower()
            field_type = {
                'text': FieldType.TEXT,
                'email': FieldType.EMAIL,
                'url': FieldType.URL,
                'tel': FieldType.PHONE,
                'number': FieldType.NUMBER,
                'date': FieldType.DATE,
                'checkbox': FieldType.CHECKBOX,
                'radio': FieldType.RADIO,
                'file': FieldType.FILE,
                'hidden': FieldType.HIDDEN,
            }.get(type_attr, FieldType.TEXT)
        
        # Get label
        label = self._get_field_label(element, form)
        
        # Determine purpose
        purpose = self._detect_purpose(field_name, label, field_type)
        
        # Get options for select fields
        options = []
        if tag_name == 'select':
            for opt in element.find_all('option'):
                value = opt.get('value', '')
                text = opt.get_text(strip=True)
                if value or text:
                    options.append({'value': value, 'text': text})
        
        # Build validation rules
        validation_rules = []
        if element.has_attr('required'):
            validation_rules.append('required')
        if element.get('pattern'):
            validation_rules.append(f"pattern:{element.get('pattern')}")
        if element.get('minlength'):
            validation_rules.append(f"minlength:{element.get('minlength')}")
        if element.get('maxlength'):
            validation_rules.append(f"maxlength:{element.get('maxlength')}")
        
        return FormField(
            name=field_name,
            field_type=field_type,
            purpose=purpose,
            label=label,
            required=element.has_attr('required'),
            placeholder=element.get('placeholder', ''),
            max_length=int(element.get('maxlength')) if element.get('maxlength') else None,
            pattern=element.get('pattern'),
            options=options,
            default_value=element.get('value', ''),
            validation_rules=validation_rules
        )
    
    def _get_field_label(self, element: BeautifulSoup, form: BeautifulSoup) -> str:
        """Get the label for a field"""
        # Check for label with 'for' attribute
        field_id = element.get('id')
        if field_id:
            label = form.find('label', attrs={'for': field_id})
            if label:
                return label.get_text(strip=True)
        
        # Check for parent label
        parent = element.find_parent('label')
        if parent:
            return parent.get_text(strip=True)
        
        # Check aria-label
        aria = element.get('aria-label')
        if aria:
            return aria
        
        # Use placeholder
        placeholder = element.get('placeholder')
        if placeholder:
            return placeholder
        
        # Convert name to readable format
        name = element.get('name', '')
        return name.replace('_', ' ').replace('-', ' ').replace('[', '').replace(']', '').title()
    
    def _detect_purpose(self, name: str, label: str, field_type: FieldType) -> FieldPurpose:
        """Detect the purpose of a field"""
        combined = f"{name} {label}".lower()
        
        # Check email type first
        if field_type == FieldType.EMAIL:
            return FieldPurpose.EMAIL
        
        if field_type == FieldType.FILE:
            return FieldPurpose.FILE_UPLOAD
        
        # Check against patterns
        for purpose, patterns in self.PURPOSE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, combined, re.I):
                    return purpose
        
        # Textarea is usually message
        if field_type == FieldType.TEXTAREA:
            return FieldPurpose.MESSAGE
        
        return FieldPurpose.OTHER
    
    def _is_honeypot(self, element: BeautifulSoup, field: FormField) -> bool:
        """Check if a field is a honeypot"""
        # Check name and class for honeypot patterns
        name = element.get('name', '').lower()
        classes = ' '.join(element.get('class', [])).lower()
        style = element.get('style', '').lower()
        
        # Check patterns
        for pattern in self.HONEYPOT_PATTERNS:
            if re.search(pattern, name, re.I) or re.search(pattern, classes, re.I):
                return True
        
        # Check if hidden via CSS
        if 'display:none' in style or 'visibility:hidden' in style:
            return True
        
        # Check tabindex -1 (often used for honeypots)
        if element.get('tabindex') == '-1':
            return True
        
        return False
    
    def _detect_captcha_deep(self, form: BeautifulSoup) -> Dict:
        """Deep captcha detection"""
        result = {
            'present': False,
            'type': None,
            'sitekey': None,
            'version': None
        }
        
        # Search in form and nearby elements
        search_area = form
        
        # reCAPTCHA v2
        recaptcha = search_area.find(class_=re.compile(r'g-recaptcha', re.I))
        if recaptcha:
            result['present'] = True
            result['type'] = 'reCAPTCHA'
            result['version'] = 'v2'
            result['sitekey'] = recaptcha.get('data-sitekey')
            return result
        
        # reCAPTCHA v3 (usually in script)
        scripts = search_area.find_all('script')
        for script in scripts:
            src = script.get('src', '')
            text = script.string or ''
            
            if 'recaptcha' in src or 'recaptcha' in text.lower():
                result['present'] = True
                result['type'] = 'reCAPTCHA'
                
                # Try to find sitekey
                match = re.search(r'sitekey["\']?\s*[:=]\s*["\']([^"\']+)', text)
                if match:
                    result['sitekey'] = match.group(1)
                
                # Detect v3
                if 'v3' in src or 'execute' in text:
                    result['version'] = 'v3'
                else:
                    result['version'] = 'v2'
                
                return result
        
        # hCaptcha
        hcaptcha = search_area.find(class_=re.compile(r'h-captcha', re.I))
        if hcaptcha:
            result['present'] = True
            result['type'] = 'hCaptcha'
            result['sitekey'] = hcaptcha.get('data-sitekey')
            return result
        
        # Cloudflare Turnstile
        turnstile = search_area.find(class_=re.compile(r'cf-turnstile', re.I))
        if turnstile:
            result['present'] = True
            result['type'] = 'Turnstile'
            result['sitekey'] = turnstile.get('data-sitekey')
            return result
        
        # Image captcha
        captcha_img = search_area.find('img', src=re.compile(r'captcha', re.I))
        if captcha_img:
            result['present'] = True
            result['type'] = 'Image'
            return result
        
        return result
    
    def _get_submit_button_text(self, form: BeautifulSoup) -> str:
        """Get the submit button text"""
        # Check input type submit
        submit_input = form.find('input', type='submit')
        if submit_input:
            return submit_input.get('value', 'Submit')
        
        # Check button type submit
        submit_button = form.find('button', type='submit')
        if submit_button:
            return submit_button.get_text(strip=True) or 'Submit'
        
        # Check any button
        button = form.find('button')
        if button:
            return button.get_text(strip=True) or 'Submit'
        
        return 'Submit'
    
    def _estimate_complexity(self, fields: List[FormField], has_captcha: bool, 
                            has_file_upload: bool) -> str:
        """Estimate form complexity"""
        score = 0
        
        # Field count
        score += len(fields) * 2
        
        # Required fields
        required_count = sum(1 for f in fields if f.required)
        score += required_count * 3
        
        # Captcha
        if has_captcha:
            score += 20
        
        # File upload
        if has_file_upload:
            score += 10
        
        # Select fields with many options
        for field in fields:
            if field.options and len(field.options) > 5:
                score += 5
        
        if score < 15:
            return 'simple'
        elif score < 35:
            return 'moderate'
        else:
            return 'complex'
    
    def generate_fill_strategy(self, parsed_form: ParsedForm, 
                              user_data: Dict[str, str]) -> Dict[str, Any]:
        """Generate a strategy for filling the form"""
        strategy = {
            'fields_to_fill': [],
            'missing_required': [],
            'warnings': [],
            'captcha_action': None
        }
        
        for field in parsed_form.fields:
            field_strategy = {
                'name': field.name,
                'purpose': field.purpose.value,
                'value': None,
                'action': 'fill'
            }
            
            # Map user data to field
            mapping = {
                FieldPurpose.NAME: ['name', 'full_name', 'author_name'],
                FieldPurpose.EMAIL: ['email', 'from_email'],
                FieldPurpose.SUBJECT: ['subject', 'title', 'headline'],
                FieldPurpose.MESSAGE: ['message', 'body', 'pitch', 'content'],
                FieldPurpose.WEBSITE: ['website', 'url', 'site_url'],
                FieldPurpose.COMPANY: ['company', 'organization'],
                FieldPurpose.PHONE: ['phone', 'telephone'],
            }
            
            # Find value from user data
            if field.purpose in mapping:
                for key in mapping[field.purpose]:
                    if key in user_data:
                        field_strategy['value'] = user_data[key]
                        break
            
            # Handle select fields
            if field.options and not field_strategy['value']:
                # Try to match by option text
                for opt in field.options:
                    if opt['value'] and opt['value'] not in ['', '0', 'select']:
                        field_strategy['value'] = opt['value']
                        field_strategy['action'] = 'select'
                        break
            
            # Handle checkbox/consent
            if field.field_type == FieldType.CHECKBOX and field.purpose == FieldPurpose.CONSENT:
                field_strategy['value'] = True
                field_strategy['action'] = 'check'
            
            # Track missing required fields
            if field.required and not field_strategy['value']:
                strategy['missing_required'].append(field.name)
            
            strategy['fields_to_fill'].append(field_strategy)
        
        # Captcha strategy
        if parsed_form.has_captcha:
            strategy['captcha_action'] = {
                'type': parsed_form.captcha_type,
                'sitekey': parsed_form.captcha_sitekey,
                'action': 'solve' if parsed_form.captcha_type in ['reCAPTCHA', 'hCaptcha'] else 'manual'
            }
        
        # Warnings
        if parsed_form.estimated_complexity == 'complex':
            strategy['warnings'].append('Complex form - manual review recommended')
        
        if strategy['missing_required']:
            strategy['warnings'].append(f"Missing required fields: {', '.join(strategy['missing_required'])}")
        
        return strategy