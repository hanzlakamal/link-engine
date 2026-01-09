"""
Email Sender - SMTP email sending with tracking
"""
import smtplib
import ssl
import uuid
import hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import time
import random

from config import Settings
from core.database import Database
from core.logger import outreach_logger


@dataclass
class EmailMessage:
    """Email message to send"""
    to_email: str
    subject: str
    body: str
    from_name: str = ""
    from_email: str = ""
    reply_to: str = ""
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    attachments: List[Path] = field(default_factory=list)
    html_body: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    tracking_id: str = ""
    

@dataclass
class SendResult:
    """Result of sending an email"""
    success: bool
    message_id: str = ""
    tracking_id: str = ""
    error: str = ""
    sent_at: Optional[datetime] = None
    smtp_response: str = ""


@dataclass
class EmailAccount:
    """Email account for sending"""
    email: str
    name: str
    smtp_server: str
    smtp_port: int
    username: str
    password: str
    daily_limit: int = 50
    sent_today: int = 0
    last_sent: Optional[datetime] = None
    warmup_status: str = "warmed"  # warming, warmed, paused
    reputation_score: int = 100


class EmailSender:
    """Send emails via SMTP with tracking and rate limiting"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.accounts: List[EmailAccount] = []
        self._load_accounts()
    
    def _load_accounts(self):
        """Load email accounts from settings"""
        # Primary account from settings
        if self.settings.email.smtp_server:
            self.accounts.append(EmailAccount(
                email=self.settings.email.sender_email,
                name=self.settings.email.sender_name,
                smtp_server=self.settings.email.smtp_server,
                smtp_port=self.settings.email.smtp_port,
                username=self.settings.email.smtp_username,
                password=self.settings.email.smtp_password,
                daily_limit=self.settings.email.daily_send_limit
            ))
        
        # Load additional accounts from database
        # TODO: Implement multi-account support in database
    
    def _get_available_account(self) -> Optional[EmailAccount]:
        """Get an available account for sending"""
        now = datetime.now()
        
        for account in self.accounts:
            # Check if daily limit reset needed
            if account.last_sent and account.last_sent.date() < now.date():
                account.sent_today = 0
            
            # Check if under limit
            if account.sent_today < account.daily_limit:
                if account.warmup_status != "paused":
                    return account
        
        return None
    
    def send_email(self, message: EmailMessage) -> SendResult:
        """Send a single email"""
        account = self._get_available_account()
        
        if not account:
            return SendResult(
                success=False,
                error="No available email account (daily limits reached)"
            )
        
        # Generate tracking ID if not provided
        if not message.tracking_id:
            message.tracking_id = self._generate_tracking_id()
        
        # Set from fields if not provided
        if not message.from_email:
            message.from_email = account.email
        if not message.from_name:
            message.from_name = account.name
        
        try:
            result = self._send_via_smtp(account, message)
            
            if result.success:
                account.sent_today += 1
                account.last_sent = datetime.now()
                
                # Log to database
                self.db.log_activity(
                    'email_sent',
                    'outreach',
                    None,
                    f"Email sent to {message.to_email}: {message.subject}",
                    details={
                        'to': message.to_email,
                        'subject': message.subject,
                        'tracking_id': message.tracking_id,
                        'from_account': account.email
                    }
                )
            
            return result
            
        except Exception as e:
            outreach_logger.error(f"Email send failed: {e}")
            return SendResult(
                success=False,
                error=str(e)
            )
    
    def _send_via_smtp(self, account: EmailAccount, message: EmailMessage) -> SendResult:
        """Send email via SMTP"""
        result = SendResult(success=False, tracking_id=message.tracking_id)
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = message.subject
            msg['From'] = f"{message.from_name} <{message.from_email}>"
            msg['To'] = message.to_email
            msg['Message-ID'] = f"<{uuid.uuid4()}@{message.from_email.split('@')[1]}>"
            msg['Date'] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
            
            if message.reply_to:
                msg['Reply-To'] = message.reply_to
            
            if message.cc:
                msg['Cc'] = ', '.join(message.cc)
            
            # Add tracking headers
            msg['X-Tracking-ID'] = message.tracking_id
            
            # Add custom headers
            for key, value in message.headers.items():
                msg[key] = value
            
            # Add body
            part_text = MIMEText(message.body, 'plain', 'utf-8')
            msg.attach(part_text)
            
            if message.html_body:
                # Add tracking pixel to HTML
                tracked_html = self._add_tracking_pixel(message.html_body, message.tracking_id)
                part_html = MIMEText(tracked_html, 'html', 'utf-8')
                msg.attach(part_html)
            
            # Add attachments
            for attachment_path in message.attachments:
                if attachment_path.exists():
                    self._attach_file(msg, attachment_path)
            
            # Connect and send
            context = ssl.create_default_context()
            
            if account.smtp_port == 465:
                # SSL
                with smtplib.SMTP_SSL(account.smtp_server, account.smtp_port, 
                                      context=context) as server:
                    server.login(account.username, account.password)
                    
                    recipients = [message.to_email] + message.cc + message.bcc
                    server.sendmail(message.from_email, recipients, msg.as_string())
                    
                    result.smtp_response = "250 OK"
            else:
                # STARTTLS
                with smtplib.SMTP(account.smtp_server, account.smtp_port) as server:
                    server.starttls(context=context)
                    server.login(account.username, account.password)
                    
                    recipients = [message.to_email] + message.cc + message.bcc
                    server.sendmail(message.from_email, recipients, msg.as_string())
                    
                    result.smtp_response = "250 OK"
            
            result.success = True
            result.message_id = msg['Message-ID']
            result.sent_at = datetime.now()
            
            outreach_logger.info(f"Email sent successfully to {message.to_email}")
            
        except smtplib.SMTPAuthenticationError as e:
            result.error = f"Authentication failed: {e}"
            outreach_logger.error(f"SMTP auth error: {e}")
            
        except smtplib.SMTPRecipientsRefused as e:
            result.error = f"Recipient refused: {e}"
            outreach_logger.error(f"Recipient refused: {e}")
            
        except smtplib.SMTPException as e:
            result.error = f"SMTP error: {e}"
            outreach_logger.error(f"SMTP error: {e}")
            
        except Exception as e:
            result.error = str(e)
            outreach_logger.error(f"Email error: {e}")
        
        return result
    
    def _attach_file(self, msg: MIMEMultipart, file_path: Path):
        """Attach a file to the message"""
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{file_path.name}"'
            )
            msg.attach(part)
    
    def _generate_tracking_id(self) -> str:
        """Generate a unique tracking ID"""
        unique = f"{uuid.uuid4()}{time.time()}"
        return hashlib.sha256(unique.encode()).hexdigest()[:16]
    
    def _add_tracking_pixel(self, html: str, tracking_id: str) -> str:
        """Add tracking pixel to HTML email"""
        # This would point to your tracking endpoint
        tracking_domain = self.settings.email.sender_email.split('@')[1]
        pixel = f'<img src="https://track.{tracking_domain}/open/{tracking_id}" width="1" height="1" />'
        
        # Insert before closing body tag
        if '</body>' in html.lower():
            html = html.replace('</body>', f'{pixel}</body>')
            html = html.replace('</BODY>', f'{pixel}</BODY>')
        else:
            html += pixel
        
        return html
    
    def send_batch(self, messages: List[EmailMessage], 
                   progress_callback=None) -> List[SendResult]:
        """Send multiple emails with rate limiting"""
        results = []
        total = len(messages)
        
        delay_min = self.settings.email.delay_between_emails_min
        delay_max = self.settings.email.delay_between_emails_max
        
        for i, message in enumerate(messages):
            # Send email
            result = self.send_email(message)
            results.append(result)
            
            if progress_callback:
                progress_callback(i + 1, total, message.to_email, result.success)
            
            # Rate limiting delay
            if i < total - 1:  # Don't delay after last email
                delay = random.randint(delay_min, delay_max)
                outreach_logger.debug(f"Waiting {delay} seconds before next email")
                time.sleep(delay)
            
            # Check if we hit daily limit
            if not self._get_available_account():
                outreach_logger.warning("Daily email limit reached, stopping batch")
                break
        
        return results
    
    def get_daily_stats(self) -> Dict[str, Any]:
        """Get daily sending statistics"""
        total_sent = sum(acc.sent_today for acc in self.accounts)
        total_limit = sum(acc.daily_limit for acc in self.accounts)
        
        return {
            'sent_today': total_sent,
            'daily_limit': total_limit,
            'remaining': total_limit - total_sent,
            'accounts': [
                {
                    'email': acc.email,
                    'sent': acc.sent_today,
                    'limit': acc.daily_limit,
                    'status': acc.warmup_status
                }
                for acc in self.accounts
            ]
        }
    
    def verify_connection(self) -> Tuple[bool, str]:
        """Verify SMTP connection"""
        account = self.accounts[0] if self.accounts else None
        
        if not account:
            return False, "No email account configured"
        
        try:
            context = ssl.create_default_context()
            
            if account.smtp_port == 465:
                with smtplib.SMTP_SSL(account.smtp_server, account.smtp_port,
                                      context=context, timeout=10) as server:
                    server.login(account.username, account.password)
                    return True, "Connection successful"
            else:
                with smtplib.SMTP(account.smtp_server, account.smtp_port,
                                  timeout=10) as server:
                    server.starttls(context=context)
                    server.login(account.username, account.password)
                    return True, "Connection successful"
                    
        except smtplib.SMTPAuthenticationError:
            return False, "Authentication failed - check username/password"
        except smtplib.SMTPConnectError:
            return False, "Could not connect to SMTP server"
        except Exception as e:
            return False, str(e)