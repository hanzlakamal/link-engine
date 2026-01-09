"""
Application Constants
"""
from enum import Enum

APP_NAME = "Backlink Strategy Engine"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Your Company"

# Status enums
class DomainStatus(Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    QUEUED = "queued"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    NEGOTIATING = "negotiating"
    PUBLISHED = "published"
    REJECTED = "rejected"
    BLACKLISTED = "blacklisted"
    ERROR = "error"

class SubmissionStatus(Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"

class ResponseType(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEEDS_INFO = "needs_info"
    COUNTER_OFFER = "counter_offer"
    AUTO_REPLY = "auto_reply"
    FOLLOW_UP_NEEDED = "follow_up_needed"
    UNCLEAR = "unclear"

class LinkStatus(Enum):
    PENDING = "pending"
    LIVE = "live"
    REMOVED = "removed"
    CHANGED = "changed"
    ERROR = "error"

class LinkType(Enum):
    DOFOLLOW = "dofollow"
    NOFOLLOW = "nofollow"
    SPONSORED = "sponsored"
    UGC = "ugc"
    UNKNOWN = "unknown"

# Contact method types
class ContactMethod(Enum):
    EMAIL = "email"
    FORM = "form"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    OTHER = "other"

# Default user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

# Guest post detection patterns
GUEST_POST_KEYWORDS = [
    "write for us",
    "guest post",
    "guest article",
    "contribute",
    "contributor",
    "submit article",
    "submit post",
    "submit content",
    "become a writer",
    "become an author",
    "become a contributor",
    "guest author",
    "guest blogger",
    "editorial guidelines",
    "submission guidelines",
    "writing guidelines",
    "guest posting",
    "accepting guest posts",
]

# Email patterns to skip
SKIP_EMAIL_PATTERNS = [
    "noreply@",
    "no-reply@",
    "donotreply@",
    "mailer-daemon@",
    "postmaster@",
    "@example.com",
    "@test.com",
    "@localhost",
    "support@",
    "help@",
    "info@",  # Sometimes okay, but often generic
    "admin@",
    "webmaster@",
]

# Preferred email patterns (editors, content team)
PREFERRED_EMAIL_PATTERNS = [
    "editor@",
    "editors@",
    "content@",
    "editorial@",
    "guest@",
    "guestpost@",
    "submissions@",
    "submit@",
    "contribute@",
    "writer@",
    "authors@",
    "pitch@",
]

# File size limits
MAX_CSV_ROWS = 50000
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB

# Rate limits
DEFAULT_REQUESTS_PER_SECOND = 2
DEFAULT_EMAILS_PER_HOUR = 20
DEFAULT_EMAILS_PER_DAY = 100

# Timeouts
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_PAGE_LOAD_TIMEOUT = 60

# Retry settings
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds