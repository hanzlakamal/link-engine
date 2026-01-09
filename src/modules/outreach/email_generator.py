"""
Email Generator - AI-powered personalized email creation
"""
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from config import Settings
from core.database import Database, Domain
from core.logger import outreach_logger
from integrations.anthropic_api import AnthropicAPI


@dataclass
class GeneratedEmail:
    """Generated email content"""
    subject: str
    body: str
    follow_up_angle: str = ""
    personalization_points: List[str] = field(default_factory=list)
    topic_ideas: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    generation_time: float = 0.0


@dataclass
class OutreachContext:
    """Context for email generation"""
    # Target site info
    domain: str
    site_name: str
    niche: str
    recent_articles: List[Dict] = field(default_factory=list)
    guidelines_summary: str = ""
    editor_name: str = ""
    editor_email: str = ""
    
    # Sender info
    sender_name: str = ""
    sender_email: str = ""
    sender_website: str = ""
    sender_expertise: str = ""
    sender_credentials: str = ""
    relevant_content: List[Dict] = field(default_factory=list)
    
    # Customization
    custom_angle: str = ""
    tone: str = "professional"  # professional, casual, formal
    include_topic_ideas: bool = True
    topic_count: int = 3


class EmailGenerator:
    """Generate personalized outreach emails"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.ai: Optional[AnthropicAPI] = None
        
        if settings.api.anthropic_api_key:
            self.ai = AnthropicAPI(settings.api.anthropic_api_key)
    
    def generate_email(self, context: OutreachContext) -> GeneratedEmail:
        """Generate a personalized outreach email"""
        start_time = datetime.now()
        
        if not self.ai:
            return self._generate_template_email(context)
        
        try:
            email = self._generate_ai_email(context)
            email.generation_time = (datetime.now() - start_time).total_seconds()
            return email
        except Exception as e:
            outreach_logger.error(f"AI email generation failed: {e}")
            return self._generate_template_email(context)
    
    def _generate_ai_email(self, context: OutreachContext) -> GeneratedEmail:
        """Generate email using AI"""
        # Build context for prompt
        recent_articles_str = ""
        if context.recent_articles:
            articles = context.recent_articles[:3]
            recent_articles_str = "\n".join([
                f"- {a.get('title', 'Untitled')} ({a.get('date', 'recent')})"
                for a in articles
            ])
        
        relevant_content_str = ""
        if context.relevant_content:
            relevant_content_str = "\n".join([
                f"- {c.get('title', 'Untitled')}: {c.get('url', '')}"
                for c in context.relevant_content[:3]
            ])
        
        prompt = self.settings.prompts.email_generation.format(
            domain=context.domain,
            site_name=context.site_name or context.domain,
            niche=context.niche,
            recent_articles=recent_articles_str or "Not available",
            guidelines=context.guidelines_summary or "Standard guest posting guidelines",
            sender_name=context.sender_name,
            sender_website=context.sender_website,
            expertise=context.sender_expertise or "content marketing and SEO",
            relevant_content=relevant_content_str or "Various industry articles"
        )
        
        response = self.ai.generate_text(prompt, max_tokens=1500)
        
        if not response:
            raise Exception("Empty AI response")
        
        # Parse response
        return self._parse_ai_response(response, context)
    
    def _parse_ai_response(self, response: str, context: OutreachContext) -> GeneratedEmail:
        """Parse AI response into structured email"""
        email = GeneratedEmail(subject="", body="")
        
        # Extract subject line
        subject_match = re.search(r'Subject:\s*(.+?)(?:\n|$)', response, re.I)
        if subject_match:
            email.subject = subject_match.group(1).strip()
            response = response.replace(subject_match.group(0), '').strip()
        else:
            # Generate a default subject
            email.subject = f"Guest Post Inquiry for {context.site_name or context.domain}"
        
        # Extract follow-up angle if present
        followup_match = re.search(r'Follow-?up\s*(?:Angle)?:\s*(.+?)(?:\n\n|$)', response, re.I | re.S)
        if followup_match:
            email.follow_up_angle = followup_match.group(1).strip()
            response = response.replace(followup_match.group(0), '').strip()
        
        # Clean up the body
        body = response.strip()
        
        # Remove any remaining metadata-like lines at the start
        lines = body.split('\n')
        clean_lines = []
        started = False
        
        for line in lines:
            if not started and line.strip() and not line.strip().endswith(':'):
                started = True
            if started:
                clean_lines.append(line)
        
        email.body = '\n'.join(clean_lines).strip()
        
        # Extract personalization points (sentences that reference the target site)
        for sentence in email.body.split('.'):
            if context.domain.split('.')[0] in sentence.lower() or \
               (context.site_name and context.site_name.lower() in sentence.lower()):
                email.personalization_points.append(sentence.strip() + '.')
        
        # Calculate confidence
        email.confidence_score = self._calculate_confidence(email, context)
        
        return email
    
    def _generate_template_email(self, context: OutreachContext) -> GeneratedEmail:
        """Generate email from template (fallback when AI unavailable)"""
        subject = f"Guest Post Inquiry - {context.niche} Content for {context.site_name or context.domain}"
        
        greeting = f"Hi{' ' + context.editor_name if context.editor_name else ''},"
        
        body = f"""{greeting}

I'm {context.sender_name}, a {context.sender_expertise or 'content writer'} specializing in {context.niche}.

I've been following {context.site_name or context.domain} and really enjoyed your recent content. I'd love to contribute a guest post to your site.

Here are a few topic ideas I think would resonate with your readers:

1. [Topic idea 1 based on {context.niche}]
2. [Topic idea 2 based on {context.niche}]
3. [Topic idea 3 based on {context.niche}]

I can provide a well-researched, original article that matches your editorial standards. You can see examples of my writing at {context.sender_website}.

Would you be open to a guest contribution? I'm happy to discuss topics or adjust to your guidelines.

Best regards,
{context.sender_name}
{context.sender_website}"""
        
        return GeneratedEmail(
            subject=subject,
            body=body,
            confidence_score=30.0  # Low confidence for template
        )
    
    def _calculate_confidence(self, email: GeneratedEmail, context: OutreachContext) -> float:
        """Calculate confidence score for generated email"""
        score = 50.0  # Base score for AI generation
        
        # Check personalization
        if email.personalization_points:
            score += len(email.personalization_points) * 10
            score = min(score, 80)
        
        # Check length (not too short, not too long)
        word_count = len(email.body.split())
        if 100 <= word_count <= 250:
            score += 10
        elif word_count < 50 or word_count > 400:
            score -= 10
        
        # Check for common template phrases (penalize)
        template_phrases = [
            "i came across your site",
            "i'm reaching out",
            "valuable content",
            "high-quality",
            "mutually beneficial"
        ]
        
        body_lower = email.body.lower()
        for phrase in template_phrases:
            if phrase in body_lower:
                score -= 5
        
        # Check subject line
        if context.site_name and context.site_name.lower() in email.subject.lower():
            score += 5
        
        return max(min(score, 100), 0)
    
    def generate_follow_up(self, original_submission: Dict, days_since: int) -> GeneratedEmail:
        """Generate a follow-up email"""
        context = f"""
        Original email was sent {days_since} days ago to {original_submission.get('domain')}.
        Original subject: {original_submission.get('subject')}
        Original pitch topics: {original_submission.get('pitch_topics', [])}
        """
        
        if self.ai:
            prompt = f"""Generate a brief, polite follow-up email for a guest post pitch.

Context:
{context}

Rules:
1. Keep it very short (2-3 sentences max)
2. Reference the original email
3. Don't be pushy
4. Offer a new angle or additional value
5. Include a soft call-to-action

Format:
Subject: [follow-up subject line]
[Email body]"""
            
            response = self.ai.generate_text(prompt, max_tokens=500)
            
            if response:
                return self._parse_ai_response(response, OutreachContext(
                    domain=original_submission.get('domain', ''),
                    site_name='',
                    niche='',
                    sender_name=self.settings.email.sender_name
                ))
        
        # Template fallback
        return GeneratedEmail(
            subject=f"Re: {original_submission.get('subject', 'Guest Post Inquiry')}",
            body=f"""Hi,

I wanted to follow up on my email from {days_since} days ago about contributing a guest post.

I understand you're busy, so I just wanted to check if you had a chance to review my pitch. I'm still very interested in contributing and happy to discuss any topic ideas that would work better for your audience.

Looking forward to hearing from you.

Best,
{self.settings.email.sender_name}""",
            confidence_score=40.0
        )
    
    def batch_generate(self, domains: List[Domain], 
                      sender_info: Dict,
                      progress_callback=None) -> List[Dict]:
        """Generate emails for multiple domains"""
        results = []
        total = len(domains)
        
        for i, domain in enumerate(domains):
            context = OutreachContext(
                domain=domain.domain,
                site_name=domain.site_name or domain.domain,
                niche=domain.niche,
                sender_name=sender_info.get('name', ''),
                sender_email=sender_info.get('email', ''),
                sender_website=sender_info.get('website', ''),
                sender_expertise=sender_info.get('expertise', ''),
            )
            
            # Get contact methods and guidelines from DB
            contact_methods = self.db.get_contact_methods(domain.id)
            if contact_methods:
                for cm in contact_methods:
                    if cm.get('email_address'):
                        context.editor_email = cm['email_address']
                    if cm.get('guidelines_parsed'):
                        import json
                        guidelines = cm['guidelines_parsed']
                        if isinstance(guidelines, str):
                            guidelines = json.loads(guidelines)
                        context.guidelines_summary = str(guidelines)[:500]
            
            try:
                email = self.generate_email(context)
                
                results.append({
                    'domain_id': domain.id,
                    'domain': domain.domain,
                    'success': True,
                    'email': {
                        'subject': email.subject,
                        'body': email.body,
                        'confidence': email.confidence_score
                    },
                    'to_email': context.editor_email
                })
                
            except Exception as e:
                results.append({
                    'domain_id': domain.id,
                    'domain': domain.domain,
                    'success': False,
                    'error': str(e)
                })
            
            if progress_callback:
                progress_callback(i + 1, total, domain.domain)
            
            # Rate limiting
            import time
            time.sleep(0.5)
        
        return results