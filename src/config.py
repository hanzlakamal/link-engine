"""
Configuration Management with Exposed Settings
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from cryptography.fernet import Fernet
import os


class APISettings(BaseModel):
    """API Configuration"""
    ahrefs_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    captcha_api_key: str = ""
    captcha_service: str = "2captcha"  # 2captcha, anticaptcha, capmonster


class EmailSettings(BaseModel):
    """Email Sending Configuration"""
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    sender_name: str = ""
    sender_email: str = ""
    daily_send_limit: int = 50
    delay_between_emails_min: int = 180  # seconds
    delay_between_emails_max: int = 600  # seconds


class AIPrompts(BaseModel):
    """AI Prompts - User Editable"""
    
    guidelines_extraction: str = """You are analyzing a webpage to extract guest posting guidelines.

WEBPAGE CONTENT:
{page_content}

Extract and return a JSON object with the following structure:
{{
    "accepts_guest_posts": true/false,
    "content_requirements": {{
        "min_word_count": number or null,
        "max_word_count": number or null,
        "requires_images": true/false,
        "formatting_notes": "string"
    }},
    "topic_preferences": {{
        "accepted_topics": ["list", "of", "topics"],
        "rejected_topics": ["list", "of", "topics"]
    }},
    "submission_requirements": {{
        "format": "Google Doc / Word / Email body / etc",
        "include_bio": true/false,
        "include_headshot": true/false,
        "include_social_links": true/false
    }},
    "link_policy": {{
        "links_allowed_in_body": number or null,
        "links_allowed_in_bio": number or null,
        "dofollow": true/false/unknown,
        "anchor_text_restrictions": "string or null"
    }},
    "contact_method": {{
        "type": "form/email/both",
        "email": "email address if found",
        "form_url": "form URL if different from page"
    }},
    "response_time": "stated response time or null",
    "special_notes": "any other important information"
}}

Be thorough but only include information actually stated on the page. Use null for unknown fields."""

    email_generation: str = """You are writing a personalized guest post pitch email.

TARGET WEBSITE DATA:
- Domain: {domain}
- Site Name: {site_name}
- Niche: {niche}
- Recent Articles: {recent_articles}
- Guidelines Summary: {guidelines}

YOUR INFORMATION:
- Name: {sender_name}
- Website: {sender_website}
- Expertise: {expertise}
- Relevant Content: {relevant_content}

RULES:
1. Reference a specific recent article from their site genuinely
2. Propose 2-3 specific topic ideas that would fit their audience
3. Keep it under 200 words
4. Be professional but personable
5. Include a clear but soft call-to-action
6. DO NOT use these overused phrases:
   - "I came across your site"
   - "I'm reaching out"
   - "I'd love to"
   - "valuable content"
   - "high-quality article"
   - "mutually beneficial"

OUTPUT FORMAT:
Subject: [Your subject line]

[Email body]

Best regards,
{sender_name}"""

    response_analysis: str = """Analyze this email response to a guest post pitch.

ORIGINAL PITCH SUMMARY:
{pitch_summary}

RESPONSE RECEIVED:
{response_text}

Categorize this response and extract key information:

{{
    "category": "positive/negative/needs_more_info/counter_offer/auto_reply/unclear",
    "sentiment_score": 1-10 (10 being very positive),
    "key_points": ["list", "of", "main", "points"],
    "action_required": "description of what to do next",
    "deadline_mentioned": "date/time if any deadline mentioned",
    "contact_person": "name if different from original contact",
    "guidelines_attached": true/false,
    "payment_mentioned": {{
        "mentioned": true/false,
        "amount": "amount if specified",
        "type": "one-time/monthly/per-word"
    }},
    "suggested_response": "brief suggested reply if positive/needs_more_info"
}}"""

    contact_detection: str = """Analyze this webpage to find guest posting or content contribution opportunities.

PAGE URL: {url}
PAGE CONTENT:
{page_content}

Find and return:
{{
    "has_guest_post_opportunity": true/false,
    "confidence_score": 0.0-1.0,
    "contact_methods": [
        {{
            "type": "email/form/social",
            "value": "email address or URL",
            "context": "where/how it was found"
        }}
    ],
    "page_type": "dedicated_guest_post_page/contact_page/about_page/other",
    "relevant_links": [
        {{
            "text": "link text",
            "url": "full URL",
            "likely_purpose": "guidelines/submission_form/examples/etc"
        }}
    ],
    "editor_info": {{
        "name": "if found",
        "role": "if found",
        "email": "if found"
    }}
}}"""


class ScoringWeights(BaseModel):
    """Domain Scoring Weights - User Adjustable"""
    domain_rating_weight: float = 0.30
    traffic_weight: float = 0.25
    referring_domains_weight: float = 0.20
    relevance_weight: float = 0.25
    
    # Thresholds
    min_dr_threshold: int = 20
    min_traffic_threshold: int = 1000
    max_dr_cap: int = 100
    max_traffic_cap: int = 100000


class GeneralSettings(BaseModel):
    """General Application Settings"""
    theme: str = "dark"  # dark, light
    auto_save_interval: int = 300  # seconds
    max_concurrent_analyses: int = 5
    request_timeout: int = 30  # seconds
    retry_attempts: int = 3
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    # Logging
    log_level: str = "DEBUG"  # DEBUG, INFO, WARNING, ERROR
    log_retention_days: int = 30
    
    # Analysis
    auto_analyze_on_import: bool = False
    screenshot_on_analysis: bool = True


class Settings(BaseSettings):
    """Main Settings Container"""
    
    # Paths
    app_dir: Path = Field(default_factory=lambda: Path.home() / ".backlink_engine")
    
    # Sub-settings
    api: APISettings = Field(default_factory=APISettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    prompts: AIPrompts = Field(default_factory=AIPrompts)
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    
    # Encryption key for sensitive data
    _encryption_key: Optional[bytes] = None
    
    class Config:
        env_prefix = "BACKLINK_"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ensure_directories()
        self._load_from_file()
    
    @property
    def config_path(self) -> Path:
        return self.app_dir / "config.json"
    
    @property
    def database_path(self) -> Path:
        return self.app_dir / "data" / "backlink_engine.db"
    
    @property
    def logs_path(self) -> Path:
        return self.app_dir / "logs"
    
    @property
    def prompts_path(self) -> Path:
        return self.app_dir / "prompts"
    
    def _ensure_directories(self):
        """Create necessary directories"""
        self.app_dir.mkdir(parents=True, exist_ok=True)
        (self.app_dir / "data").mkdir(exist_ok=True)
        (self.app_dir / "logs").mkdir(exist_ok=True)
        (self.app_dir / "prompts").mkdir(exist_ok=True)
        (self.app_dir / "screenshots").mkdir(exist_ok=True)
    
    def _load_from_file(self):
        """Load settings from JSON file if exists"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                
                if 'api' in data:
                    self.api = APISettings(**data['api'])
                if 'email' in data:
                    self.email = EmailSettings(**data['email'])
                if 'prompts' in data:
                    self.prompts = AIPrompts(**data['prompts'])
                if 'scoring' in data:
                    self.scoring = ScoringWeights(**data['scoring'])
                if 'general' in data:
                    self.general = GeneralSettings(**data['general'])
            except Exception as e:
                print(f"Error loading settings: {e}")
    
    def save(self):
        """Save settings to JSON file"""
        data = {
            'api': self.api.model_dump(),
            'email': self.email.model_dump(),
            'prompts': self.prompts.model_dump(),
            'scoring': self.scoring.model_dump(),
            'general': self.general.model_dump(),
        }
        
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_encryption_key(self) -> bytes:
        """Get or create encryption key for sensitive data"""
        key_path = self.app_dir / ".key"
        
        if key_path.exists():
            with open(key_path, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(key_path, 'wb') as f:
                f.write(key)
            return key
    
    def encrypt_value(self, value: str) -> str:
        """Encrypt a sensitive value"""
        f = Fernet(self.get_encryption_key())
        return f.encrypt(value.encode()).decode()
    
    def decrypt_value(self, encrypted: str) -> str:
        """Decrypt a sensitive value"""
        f = Fernet(self.get_encryption_key())
        return f.decrypt(encrypted.encode()).decode()