"""
Guidelines Extractor - AI-powered extraction of submission guidelines
"""
import re
import json
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

from config import Settings
from core.logger import analysis_logger
from integrations.anthropic_api import AnthropicAPI


@dataclass
class ExtractedGuidelines:
    """Structured guidelines data"""
    accepts_guest_posts: bool = True
    
    # Content requirements
    min_word_count: Optional[int] = None
    max_word_count: Optional[int] = None
    requires_images: bool = False
    image_requirements: str = ""
    formatting_requirements: List[str] = field(default_factory=list)
    
    # Topic preferences
    accepted_topics: List[str] = field(default_factory=list)
    rejected_topics: List[str] = field(default_factory=list)
    requires_unique_content: bool = True
    
    # Submission process
    submission_format: str = ""  # Google Doc, Word, Email body, etc.
    submission_email: str = ""
    submission_form_url: str = ""
    
    # Author requirements
    include_bio: bool = False
    bio_max_length: Optional[int] = None
    include_headshot: bool = False
    include_social_links: bool = False
    
    # Link policy
    links_allowed_in_body: Optional[int] = None
    links_allowed_in_bio: Optional[int] = None
    dofollow_links: Optional[bool] = None
    anchor_text_restrictions: str = ""
    
    # Expectations
    response_time: str = ""
    payment_offered: bool = False
    payment_details: str = ""
    
    # Additional info
    special_requirements: List[str] = field(default_factory=list)
    tips_for_acceptance: List[str] = field(default_factory=list)
    red_flags: List[str] = field(default_factory=list)
    
    # Raw data
    raw_json: Dict = field(default_factory=dict)
    confidence_score: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'accepts_guest_posts': self.accepts_guest_posts,
            'content_requirements': {
                'min_word_count': self.min_word_count,
                'max_word_count': self.max_word_count,
                'requires_images': self.requires_images,
                'image_requirements': self.image_requirements,
                'formatting': self.formatting_requirements,
            },
            'topic_preferences': {
                'accepted_topics': self.accepted_topics,
                'rejected_topics': self.rejected_topics,
                'requires_unique': self.requires_unique_content,
            },
            'submission': {
                'format': self.submission_format,
                'email': self.submission_email,
                'form_url': self.submission_form_url,
            },
            'author_requirements': {
                'include_bio': self.include_bio,
                'bio_max_length': self.bio_max_length,
                'include_headshot': self.include_headshot,
                'include_social': self.include_social_links,
            },
            'link_policy': {
                'body_links': self.links_allowed_in_body,
                'bio_links': self.links_allowed_in_bio,
                'dofollow': self.dofollow_links,
                'anchor_restrictions': self.anchor_text_restrictions,
            },
            'expectations': {
                'response_time': self.response_time,
                'payment': self.payment_offered,
                'payment_details': self.payment_details,
            },
            'notes': {
                'special_requirements': self.special_requirements,
                'tips': self.tips_for_acceptance,
                'red_flags': self.red_flags,
            },
            'confidence_score': self.confidence_score,
        }


class GuidelinesExtractor:
    """Extract and parse guest posting guidelines"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ai: Optional[AnthropicAPI] = None
        
        if settings.api.anthropic_api_key:
            self.ai = AnthropicAPI(settings.api.anthropic_api_key)
    
    def extract(self, page_content: str, page_url: str) -> ExtractedGuidelines:
        """Extract guidelines from page content"""
        guidelines = ExtractedGuidelines()
        
        # Clean HTML and get text
        soup = BeautifulSoup(page_content, 'lxml')
        
        # Remove non-content elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
            tag.decompose()
        
        clean_text = soup.get_text(separator='\n', strip=True)
        
        # First, try regex-based extraction for common patterns
        self._extract_common_patterns(clean_text, guidelines)
        
        # If AI is available, use it for deeper extraction
        if self.ai:
            ai_guidelines = self._extract_with_ai(clean_text, page_url)
            if ai_guidelines:
                self._merge_guidelines(guidelines, ai_guidelines)
        
        # Calculate confidence score
        guidelines.confidence_score = self._calculate_confidence(guidelines)
        
        return guidelines
    
    def _extract_common_patterns(self, text: str, guidelines: ExtractedGuidelines):
        """Extract guidelines using regex patterns"""
        text_lower = text.lower()
        
        # Word count patterns
        word_count_patterns = [
            r'(?:minimum|min|at least)\s*(\d{3,4})\s*(?:words?|word count)',
            r'(\d{3,4})\s*(?:words?|word count)\s*(?:minimum|min)',
            r'(\d{3,4})\s*-\s*(\d{3,4})\s*words?',
            r'(?:between|from)\s*(\d{3,4})\s*(?:to|and|-)\s*(\d{3,4})\s*words?',
        ]
        
        for pattern in word_count_patterns:
            match = re.search(pattern, text_lower)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    guidelines.min_word_count = int(groups[0])
                elif len(groups) == 2:
                    guidelines.min_word_count = int(groups[0])
                    guidelines.max_word_count = int(groups[1])
                break
        
        # Image requirements
        image_patterns = [
            r'include\s*(?:at least\s*)?(\d+)\s*(?:image|photo|picture)s?',
            r'(\d+)\s*(?:image|photo|picture)s?\s*(?:required|needed|minimum)',
            r'images?\s*(?:are\s*)?required',
        ]
        
        for pattern in image_patterns:
            if re.search(pattern, text_lower):
                guidelines.requires_images = True
                break
        
        # Link policies
        if 'dofollow' in text_lower:
            if 'no dofollow' in text_lower or "don't offer dofollow" in text_lower:
                guidelines.dofollow_links = False
            else:
                guidelines.dofollow_links = True
        elif 'nofollow' in text_lower:
            guidelines.dofollow_links = False
        
        # Link count
        link_patterns = [
            r'(\d+)\s*(?:link|backlink)s?\s*(?:in|within|per)\s*(?:article|post|body)',
            r'(?:maximum|max|up to)\s*(\d+)\s*(?:link|backlink)s?',
        ]
        
        for pattern in link_patterns:
            match = re.search(pattern, text_lower)
            if match:
                guidelines.links_allowed_in_body = int(match.group(1))
                break
        
        # Bio requirements
        if 'bio' in text_lower or 'author bio' in text_lower:
            guidelines.include_bio = True
            
            bio_length_match = re.search(r'bio\s*(?:of\s*)?(?:up to|max|maximum)?\s*(\d+)\s*(?:words?|characters?)', text_lower)
            if bio_length_match:
                guidelines.bio_max_length = int(bio_length_match.group(1))
        
        # Headshot
        if 'headshot' in text_lower or 'photo of' in text_lower or 'author photo' in text_lower:
            guidelines.include_headshot = True
        
        # Submission format
        format_indicators = {
            'google doc': 'Google Doc',
            'google docs': 'Google Doc',
            'word document': 'Word Document',
            '.docx': 'Word Document',
            '.doc': 'Word Document',
            'email body': 'Email Body',
            'paste in email': 'Email Body',
        }
        
        for indicator, format_name in format_indicators.items():
            if indicator in text_lower:
                guidelines.submission_format = format_name
                break
        
        # Response time
        response_patterns = [
            r'(?:respond|reply|get back).*?(?:within|in)\s*(\d+)\s*(day|week|hour)s?',
            r'(\d+)\s*(day|week|hour)s?\s*(?:response|reply)',
        ]
        
        for pattern in response_patterns:
            match = re.search(pattern, text_lower)
            if match:
                guidelines.response_time = f"{match.group(1)} {match.group(2)}s"
                break
        
        # Payment
        payment_indicators = ['paid', 'pay', 'compensation', '$', 'payment']
        for indicator in payment_indicators:
            if indicator in text_lower:
                # Check context - is it about paying writers?
                if 'we pay' in text_lower or 'paid guest' in text_lower or 'compensation' in text_lower:
                    guidelines.payment_offered = True
                    
                    # Try to extract amount
                    amount_match = re.search(r'\$(\d+)', text)
                    if amount_match:
                        guidelines.payment_details = f"${amount_match.group(1)}"
                break
        
        # Unique content
        if 'original' in text_lower or 'unique' in text_lower or 'not published' in text_lower:
            guidelines.requires_unique_content = True
        
        # Extract email if present
        email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
        if email_match:
            guidelines.submission_email = email_match.group()
    
    def _extract_with_ai(self, text: str, url: str) -> Optional[Dict]:
        """Extract guidelines using AI"""
        try:
            # Truncate if too long
            if len(text) > 10000:
                text = text[:10000]
            
            prompt = self.settings.prompts.guidelines_extraction.format(
                page_content=text
            )
            
            response = self.ai.generate_text(prompt, max_tokens=2000)
            
            if response:
                # Try to parse JSON from response
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    return json.loads(json_match.group())
            
            return None
            
        except json.JSONDecodeError as e:
            analysis_logger.warning(f"Failed to parse AI guidelines response: {e}")
            return None
        except Exception as e:
            analysis_logger.error(f"AI guidelines extraction failed: {e}")
            return None
    
    def _merge_guidelines(self, base: ExtractedGuidelines, ai_data: Dict):
        """Merge AI-extracted data into guidelines"""
        if not ai_data:
            return
        
        base.raw_json = ai_data
        
        # Map AI response to guidelines fields
        if 'accepts_guest_posts' in ai_data:
            base.accepts_guest_posts = ai_data['accepts_guest_posts']
        
        content_req = ai_data.get('content_requirements', {})
        if content_req:
            if content_req.get('min_word_count') and not base.min_word_count:
                base.min_word_count = content_req['min_word_count']
            if content_req.get('max_word_count') and not base.max_word_count:
                base.max_word_count = content_req['max_word_count']
            if content_req.get('requires_images'):
                base.requires_images = content_req['requires_images']
            if content_req.get('image_requirements'):
                base.image_requirements = content_req['image_requirements']
            if content_req.get('formatting_notes'):
                base.formatting_requirements.append(content_req['formatting_notes'])
        
        topic_pref = ai_data.get('topic_preferences', {})
        if topic_pref:
            if topic_pref.get('accepted_topics'):
                base.accepted_topics = topic_pref['accepted_topics']
            if topic_pref.get('rejected_topics'):
                base.rejected_topics = topic_pref['rejected_topics']
        
        submission = ai_data.get('submission_requirements', {})
        if submission:
            if submission.get('format') and not base.submission_format:
                base.submission_format = submission['format']
            if submission.get('include_bio'):
                base.include_bio = submission['include_bio']
            if submission.get('include_headshot'):
                base.include_headshot = submission['include_headshot']
        
        link_policy = ai_data.get('link_policy', {})
        if link_policy:
            if link_policy.get('links_in_body') is not None:
                base.links_allowed_in_body = link_policy['links_in_body']
            if link_policy.get('links_in_bio') is not None:
                base.links_allowed_in_bio = link_policy['links_in_bio']
            if link_policy.get('dofollow') is not None and base.dofollow_links is None:
                base.dofollow_links = link_policy['dofollow']
            if link_policy.get('anchor_text_restrictions'):
                base.anchor_text_restrictions = link_policy['anchor_text_restrictions']
        
        contact = ai_data.get('contact_method', {})
        if contact:
            if contact.get('email') and not base.submission_email:
                base.submission_email = contact['email']
            if contact.get('form_url'):
                base.submission_form_url = contact['form_url']
        
        if ai_data.get('response_time') and not base.response_time:
            base.response_time = ai_data['response_time']
        
        if ai_data.get('special_notes'):
            base.special_requirements.append(ai_data['special_notes'])
    
    def _calculate_confidence(self, guidelines: ExtractedGuidelines) -> float:
        """Calculate confidence score for extracted guidelines"""
        score = 0.0
        max_score = 100.0
        
        # Points for each extracted field
        if guidelines.min_word_count:
            score += 10
        if guidelines.max_word_count:
            score += 5
        if guidelines.requires_images is not None:
            score += 5
        if guidelines.accepted_topics:
            score += 10
        if guidelines.submission_format:
            score += 10
        if guidelines.submission_email or guidelines.submission_form_url:
            score += 15
        if guidelines.include_bio is not None:
            score += 5
        if guidelines.links_allowed_in_body is not None:
            score += 10
        if guidelines.dofollow_links is not None:
            score += 10
        if guidelines.response_time:
            score += 5
        if guidelines.raw_json:  # AI extraction successful
            score += 15
        
        return min(score / max_score * 100, 100.0)