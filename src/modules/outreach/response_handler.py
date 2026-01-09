"""
Response Handler - AI-powered email response analysis
"""
import re
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import imaplib
import email
from email.header import decode_header

from config import Settings
from core.database import Database
from core.logger import outreach_logger
from integrations.anthropic_api import AnthropicAPI
from constants import ResponseType


@dataclass
class ParsedResponse:
    """Parsed email response"""
    message_id: str
    from_email: str
    from_name: str
    subject: str
    body: str
    html_body: str
    received_at: datetime
    in_reply_to: str = ""
    references: List[str] = field(default_factory=list)


@dataclass
class AnalyzedResponse:
    """AI-analyzed response"""
    response_type: ResponseType
    sentiment_score: float  # 1-10
    key_points: List[str]
    action_required: str
    deadline_mentioned: Optional[str]
    contact_person: str
    guidelines_attached: bool
    payment_mentioned: bool
    payment_amount: Optional[str]
    suggested_reply: str
    urgency: str  # low, medium, high
    confidence_score: float
    raw_analysis: Dict


class ResponseHandler:
    """Handle and analyze email responses"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.ai: Optional[AnthropicAPI] = None
        
        if settings.api.anthropic_api_key:
            self.ai = AnthropicAPI(settings.api.anthropic_api_key)
    
    def check_inbox(self, folder: str = "INBOX", 
                    since_date: Optional[datetime] = None) -> List[ParsedResponse]:
        """Check inbox for new responses"""
        if not self.settings.email.smtp_server:
            outreach_logger.warning("Email not configured")
            return []
        
        responses = []
        
        try:
            # Connect to IMAP
            # Note: This assumes IMAP is on the same server
            # You may need separate IMAP settings
            imap_server = self.settings.email.smtp_server.replace('smtp.', 'imap.')
            
            mail = imaplib.IMAP4_SSL(imap_server)
            mail.login(
                self.settings.email.smtp_username,
                self.settings.email.smtp_password
            )
            
            mail.select(folder)
            
            # Search criteria
            criteria = 'ALL'
            if since_date:
                date_str = since_date.strftime("%d-%b-%Y")
                criteria = f'(SINCE {date_str})'
            
            _, message_numbers = mail.search(None, criteria)
            
            for num in message_numbers[0].split():
                _, msg_data = mail.fetch(num, '(RFC822)')
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        parsed = self._parse_email(msg)
                        if parsed:
                            responses.append(parsed)
            
            mail.logout()
            
            outreach_logger.info(f"Found {len(responses)} emails in inbox")
            
        except Exception as e:
            outreach_logger.error(f"Error checking inbox: {e}")
        
        return responses
    
    def _parse_email(self, msg: email.message.Message) -> Optional[ParsedResponse]:
        """Parse an email message"""
        try:
            # Get headers
            subject = self._decode_header(msg['Subject'])
            from_header = self._decode_header(msg['From'])
            message_id = msg['Message-ID'] or ""
            in_reply_to = msg['In-Reply-To'] or ""
            references = (msg['References'] or "").split()
            date_str = msg['Date']
            
            # Parse from
            from_match = re.match(r'(.+?)\s*<(.+?)>', from_header)
            if from_match:
                from_name = from_match.group(1).strip().strip('"')
                from_email = from_match.group(2)
            else:
                from_name = ""
                from_email = from_header
            
            # Parse date
            try:
                received_at = email.utils.parsedate_to_datetime(date_str)
            except:
                received_at = datetime.now()
            
            # Get body
            body = ""
            html_body = ""
            
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    
                    if content_type == 'text/plain':
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode('utf-8', errors='ignore')
                    elif content_type == 'text/html':
                        payload = part.get_payload(decode=True)
                        if payload:
                            html_body = payload.decode('utf-8', errors='ignore')
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode('utf-8', errors='ignore')
            
            return ParsedResponse(
                message_id=message_id,
                from_email=from_email,
                from_name=from_name,
                subject=subject,
                body=body,
                html_body=html_body,
                received_at=received_at,
                in_reply_to=in_reply_to,
                references=references
            )
            
        except Exception as e:
            outreach_logger.error(f"Error parsing email: {e}")
            return None
    
    def _decode_header(self, header: str) -> str:
        """Decode email header"""
        if not header:
            return ""
        
        decoded_parts = decode_header(header)
        result = ""
        
        for content, charset in decoded_parts:
            if isinstance(content, bytes):
                result += content.decode(charset or 'utf-8', errors='ignore')
            else:
                result += content
        
        return result
    
    def analyze_response(self, response: ParsedResponse,
                        original_pitch: Dict = None) -> AnalyzedResponse:
        """Analyze a response using AI"""
        
        # Basic rule-based analysis as fallback
        basic_analysis = self._basic_analysis(response)
        
        if not self.ai:
            return basic_analysis
        
        try:
            # Prepare context
            pitch_summary = ""
            if original_pitch:
                pitch_summary = f"""
                Original pitch to: {original_pitch.get('domain', 'Unknown')}
                Subject: {original_pitch.get('subject', 'Unknown')}
                Topics pitched: {original_pitch.get('topics', [])}
                """
            
            prompt = self.settings.prompts.response_analysis.format(
                pitch_summary=pitch_summary or "Not available",
                response_text=response.body[:3000]  # Truncate if needed
            )
            
            ai_response = self.ai.generate_text(prompt, max_tokens=1500)
            
            if ai_response:
                return self._parse_ai_analysis(ai_response, response, basic_analysis)
            
        except Exception as e:
            outreach_logger.error(f"AI analysis failed: {e}")
        
        return basic_analysis
    
    def _basic_analysis(self, response: ParsedResponse) -> AnalyzedResponse:
        """Basic rule-based response analysis"""
        body_lower = response.body.lower()
        
        # Determine response type
        response_type = ResponseType.UNCLEAR
        sentiment = 5.0
        
        # Positive indicators
        positive_patterns = [
            r'interested', r'love to', r'would like', r'send us',
            r'go ahead', r'please submit', r'looking forward',
            r'yes', r'great', r'perfect', r'sounds good'
        ]
        
        # Negative indicators
        negative_patterns = [
            r'not interested', r'not accepting', r'not looking',
            r'no longer', r'closed', r'decline', r'pass',
            r'unfortunately', r'sorry but'
        ]
        
        # Needs more info
        info_patterns = [
            r'can you send', r'could you provide', r'more details',
            r'examples', r'portfolio', r'previous work', r'samples'
        ]
        
        # Counter offer / paid
        paid_patterns = [
            r'paid', r'fee', r'rate', r'\$\d+', r'payment', r'compensation'
        ]
        
        # Auto-reply
        auto_patterns = [
            r'out of office', r'automatic reply', r'auto-reply',
            r'away from', r'vacation', r'holiday'
        ]
        
        # Check patterns
        positive_count = sum(1 for p in positive_patterns if re.search(p, body_lower))
        negative_count = sum(1 for p in negative_patterns if re.search(p, body_lower))
        info_count = sum(1 for p in info_patterns if re.search(p, body_lower))
        paid_count = sum(1 for p in paid_patterns if re.search(p, body_lower))
        auto_count = sum(1 for p in auto_patterns if re.search(p, body_lower))
        
        if auto_count > 0:
            response_type = ResponseType.AUTO_REPLY
            sentiment = 5.0
        elif negative_count > positive_count:
            response_type = ResponseType.NEGATIVE
            sentiment = 2.0
        elif info_count > 0:
            response_type = ResponseType.NEEDS_INFO
            sentiment = 6.0
        elif paid_count > 0:
            response_type = ResponseType.COUNTER_OFFER
            sentiment = 6.0
        elif positive_count > 0:
            response_type = ResponseType.POSITIVE
            sentiment = 8.0
        
        # Extract payment info
        payment_mentioned = paid_count > 0
        payment_amount = None
        if payment_mentioned:
            amount_match = re.search(r'\$(\d+(?:,\d+)?(?:\.\d+)?)', response.body)
            if amount_match:
                payment_amount = f"${amount_match.group(1)}"
        
        # Determine urgency
        urgency = "low"
        if response_type == ResponseType.POSITIVE:
            urgency = "high"
        elif response_type in [ResponseType.NEEDS_INFO, ResponseType.COUNTER_OFFER]:
            urgency = "medium"
        
        return AnalyzedResponse(
            response_type=response_type,
            sentiment_score=sentiment,
            key_points=[],
            action_required=self._get_action_for_type(response_type),
            deadline_mentioned=None,
            contact_person=response.from_name,
            guidelines_attached='guidelines' in body_lower or 'attached' in body_lower,
            payment_mentioned=payment_mentioned,
            payment_amount=payment_amount,
            suggested_reply="",
            urgency=urgency,
            confidence_score=60.0,
            raw_analysis={}
        )
    
    def _parse_ai_analysis(self, ai_response: str, response: ParsedResponse,
                          fallback: AnalyzedResponse) -> AnalyzedResponse:
        """Parse AI analysis response"""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', ai_response)
            if not json_match:
                return fallback
            
            data = json.loads(json_match.group())
            
            # Map category to ResponseType
            category_map = {
                'positive': ResponseType.POSITIVE,
                'negative': ResponseType.NEGATIVE,
                'needs_more_info': ResponseType.NEEDS_INFO,
                'counter_offer': ResponseType.COUNTER_OFFER,
                'auto_reply': ResponseType.AUTO_REPLY,
                'unclear': ResponseType.UNCLEAR,
            }
            
            response_type = category_map.get(
                data.get('category', '').lower(),
                ResponseType.UNCLEAR
            )
            
            payment = data.get('payment_mentioned', {})
            
            return AnalyzedResponse(
                response_type=response_type,
                sentiment_score=float(data.get('sentiment_score', 5)),
                key_points=data.get('key_points', []),
                action_required=data.get('action_required', ''),
                deadline_mentioned=data.get('deadline_mentioned'),
                contact_person=data.get('contact_person', response.from_name),
                guidelines_attached=data.get('guidelines_attached', False),
                payment_mentioned=payment.get('mentioned', False) if isinstance(payment, dict) else False,
                payment_amount=payment.get('amount') if isinstance(payment, dict) else None,
                suggested_reply=data.get('suggested_response', ''),
                urgency=self._determine_urgency(response_type, data),
                confidence_score=85.0,
                raw_analysis=data
            )
            
        except Exception as e:
            outreach_logger.error(f"Error parsing AI analysis: {e}")
            return fallback
    
    def _get_action_for_type(self, response_type: ResponseType) -> str:
        """Get recommended action for response type"""
        actions = {
            ResponseType.POSITIVE: "Prepare and send requested content",
            ResponseType.NEGATIVE: "Mark as rejected, move to next opportunity",
            ResponseType.NEEDS_INFO: "Send requested information/samples",
            ResponseType.COUNTER_OFFER: "Review offer and decide if acceptable",
            ResponseType.AUTO_REPLY: "Schedule follow-up for later",
            ResponseType.UNCLEAR: "Review manually and respond appropriately",
        }
        return actions.get(response_type, "Review manually")
    
    def _determine_urgency(self, response_type: ResponseType, data: Dict) -> str:
        """Determine urgency level"""
        if response_type == ResponseType.POSITIVE:
            return "high"
        
        if data.get('deadline_mentioned'):
            return "high"
        
        if response_type in [ResponseType.NEEDS_INFO, ResponseType.COUNTER_OFFER]:
            return "medium"
        
        return "low"
    
    def match_response_to_submission(self, response: ParsedResponse) -> Optional[int]:
        """Try to match a response to an original submission"""
        # Check In-Reply-To header
        if response.in_reply_to:
            submissions = self.db.get_submissions(limit=1000)
            for sub in submissions:
                # This would require storing message IDs in submissions
                pass
        
        # Match by from email and subject
        submissions = self.db.get_submissions(status='sent', limit=500)
        
        for sub in submissions:
            # Check if response is from the domain we contacted
            if sub.get('domain') in response.from_email:
                # Check subject similarity
                if self._subjects_match(sub.get('subject', ''), response.subject):
                    return sub.get('id')
        
        return None
    
    def _subjects_match(self, original: str, reply: str) -> bool:
        """Check if subjects match (accounting for Re:, Fwd:, etc.)"""
        # Clean subjects
        clean_original = re.sub(r'^(re:|fwd?:|fw:)\s*', '', original.lower()).strip()
        clean_reply = re.sub(r'^(re:|fwd?:|fw:)\s*', '', reply.lower()).strip()
        
        # Check for exact match or containment
        return clean_original == clean_reply or \
               clean_original in clean_reply or \
               clean_reply in clean_original
    
    def process_new_responses(self) -> List[Dict]:
        """Check inbox and process all new responses"""
        # Get last check time from database
        last_check = self.db.connection.execute(
            "SELECT value FROM settings WHERE key = 'last_response_check'"
        ).fetchone()
        
        since_date = None
        if last_check:
            try:
                since_date = datetime.fromisoformat(last_check[0])
            except:
                pass
        
        # Check inbox
        responses = self.check_inbox(since_date=since_date)
        
        results = []
        
        for response in responses:
            # Analyze response
            analysis = self.analyze_response(response)
            
            # Try to match to submission
            submission_id = self.match_response_to_submission(response)
            
            # Save to database
            if submission_id:
                self.db.connection.execute("""
                    INSERT INTO responses 
                    (submission_id, response_type, sentiment_score, subject, body,
                     from_email, ai_analysis, requires_followup, received_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    submission_id,
                    analysis.response_type.value,
                    analysis.sentiment_score,
                    response.subject,
                    response.body,
                    response.from_email,
                    json.dumps(analysis.raw_analysis),
                    analysis.response_type in [ResponseType.POSITIVE, ResponseType.NEEDS_INFO],
                    response.received_at
                ))
                self.db.connection.commit()
            
            results.append({
                'from': response.from_email,
                'subject': response.subject,
                'type': analysis.response_type.value,
                'sentiment': analysis.sentiment_score,
                'action': analysis.action_required,
                'matched_submission': submission_id
            })
        
        # Update last check time
        self.db.connection.execute("""
            INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
        """, ('last_response_check', datetime.now().isoformat()))
        self.db.connection.commit()
        
        outreach_logger.info(f"Processed {len(results)} responses")
        
        return results