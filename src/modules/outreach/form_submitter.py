"""
Form Submitter - Playwright-based automated form submission
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeout

from config import Settings
from core.database import Database
from core.logger import outreach_logger
from modules.analysis.form_parser import ParsedForm, FormField, FieldPurpose


class SubmissionStatus(Enum):
    SUCCESS = "success"
    CAPTCHA_REQUIRED = "captcha_required"
    CAPTCHA_FAILED = "captcha_failed"
    VALIDATION_ERROR = "validation_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class SubmissionResult:
    """Result of a form submission attempt"""
    status: SubmissionStatus
    success: bool
    message: str = ""
    screenshot_path: Optional[str] = None
    response_text: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    captcha_token: Optional[str] = None
    submitted_at: Optional[datetime] = None
    page_after_submit: Optional[str] = None


@dataclass
class FormSubmissionData:
    """Data to submit to a form"""
    name: str = ""
    email: str = ""
    subject: str = ""
    message: str = ""
    website: str = ""
    company: str = ""
    phone: str = ""
    topic: str = ""
    custom_fields: Dict[str, str] = field(default_factory=dict)


class CaptchaSolver:
    """Interface to captcha solving services"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.api.captcha_api_key
        self.service = settings.api.captcha_service
    
    async def solve_recaptcha_v2(self, sitekey: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA v2"""
        if not self.api_key:
            outreach_logger.warning("No captcha API key configured")
            return None
        
        try:
            import httpx
            
            if self.service == "2captcha":
                return await self._solve_2captcha(sitekey, page_url, "recaptcha")
            elif self.service == "anticaptcha":
                return await self._solve_anticaptcha(sitekey, page_url, "recaptcha")
            elif self.service == "capmonster":
                return await self._solve_capmonster(sitekey, page_url, "recaptcha")
            else:
                outreach_logger.error(f"Unknown captcha service: {self.service}")
                return None
                
        except Exception as e:
            outreach_logger.error(f"Captcha solving failed: {e}")
            return None
    
    async def solve_hcaptcha(self, sitekey: str, page_url: str) -> Optional[str]:
        """Solve hCaptcha"""
        if not self.api_key:
            return None
        
        try:
            if self.service == "2captcha":
                return await self._solve_2captcha(sitekey, page_url, "hcaptcha")
            elif self.service == "anticaptcha":
                return await self._solve_anticaptcha(sitekey, page_url, "hcaptcha")
            elif self.service == "capmonster":
                return await self._solve_capmonster(sitekey, page_url, "hcaptcha")
            else:
                return None
        except Exception as e:
            outreach_logger.error(f"hCaptcha solving failed: {e}")
            return None
    
    async def _solve_2captcha(self, sitekey: str, page_url: str, 
                              captcha_type: str) -> Optional[str]:
        """Solve captcha using 2captcha service"""
        import httpx
        
        async with httpx.AsyncClient(timeout=180) as client:
            # Submit captcha
            method = "userrecaptcha" if captcha_type == "recaptcha" else "hcaptcha"
            
            submit_url = "http://2captcha.com/in.php"
            params = {
                "key": self.api_key,
                "method": method,
                "googlekey" if captcha_type == "recaptcha" else "sitekey": sitekey,
                "pageurl": page_url,
                "json": 1
            }
            
            response = await client.get(submit_url, params=params)
            result = response.json()
            
            if result.get("status") != 1:
                outreach_logger.error(f"2captcha submit failed: {result}")
                return None
            
            request_id = result.get("request")
            
            # Poll for result
            result_url = "http://2captcha.com/res.php"
            
            for _ in range(60):  # Max 5 minutes
                await asyncio.sleep(5)
                
                response = await client.get(result_url, params={
                    "key": self.api_key,
                    "action": "get",
                    "id": request_id,
                    "json": 1
                })
                
                result = response.json()
                
                if result.get("status") == 1:
                    return result.get("request")
                elif result.get("request") != "CAPCHA_NOT_READY":
                    outreach_logger.error(f"2captcha error: {result}")
                    return None
            
            outreach_logger.error("2captcha timeout")
            return None
    
    async def _solve_anticaptcha(self, sitekey: str, page_url: str,
                                 captcha_type: str) -> Optional[str]:
        """Solve captcha using Anti-Captcha service"""
        import httpx
        
        async with httpx.AsyncClient(timeout=180) as client:
            # Create task
            task_type = "RecaptchaV2TaskProxyless" if captcha_type == "recaptcha" else "HCaptchaTaskProxyless"
            
            create_response = await client.post(
                "https://api.anti-captcha.com/createTask",
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": task_type,
                        "websiteURL": page_url,
                        "websiteKey": sitekey
                    }
                }
            )
            
            result = create_response.json()
            
            if result.get("errorId") != 0:
                outreach_logger.error(f"Anti-captcha create failed: {result}")
                return None
            
            task_id = result.get("taskId")
            
            # Poll for result
            for _ in range(60):
                await asyncio.sleep(5)
                
                response = await client.post(
                    "https://api.anti-captcha.com/getTaskResult",
                    json={
                        "clientKey": self.api_key,
                        "taskId": task_id
                    }
                )
                
                result = response.json()
                
                if result.get("status") == "ready":
                    return result.get("solution", {}).get("gRecaptchaResponse")
                elif result.get("errorId") != 0:
                    outreach_logger.error(f"Anti-captcha error: {result}")
                    return None
            
            return None
    
    async def _solve_capmonster(self, sitekey: str, page_url: str,
                                captcha_type: str) -> Optional[str]:
        """Solve captcha using CapMonster service"""
        import httpx
        
        async with httpx.AsyncClient(timeout=180) as client:
            task_type = "NoCaptchaTaskProxyless" if captcha_type == "recaptcha" else "HCaptchaTaskProxyless"
            
            create_response = await client.post(
                "https://api.capmonster.cloud/createTask",
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": task_type,
                        "websiteURL": page_url,
                        "websiteKey": sitekey
                    }
                }
            )
            
            result = create_response.json()
            
            if result.get("errorId") != 0:
                return None
            
            task_id = result.get("taskId")
            
            for _ in range(60):
                await asyncio.sleep(3)
                
                response = await client.post(
                    "https://api.capmonster.cloud/getTaskResult",
                    json={
                        "clientKey": self.api_key,
                        "taskId": task_id
                    }
                )
                
                result = response.json()
                
                if result.get("status") == "ready":
                    return result.get("solution", {}).get("gRecaptchaResponse")
                elif result.get("errorId") != 0:
                    return None
            
            return None


class FormSubmitter:
    """Automated form submission using Playwright"""
    
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.captcha_solver = CaptchaSolver(settings)
        self.screenshots_dir = settings.app_dir / "screenshots"
        self.screenshots_dir.mkdir(exist_ok=True)
        
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None
    
    async def initialize(self):
        """Initialize browser"""
        if self._browser:
            return
        
        self._playwright = await async_playwright().start()
        
        self._browser = await self._playwright.chromium.launch(
            headless=self.settings.general.screenshot_on_analysis,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=self.settings.general.user_agent,
            locale='en-US',
            timezone_id='America/New_York'
        )
        
        # Add stealth scripts
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)
        
        outreach_logger.info("Browser initialized for form submission")
    
    async def close(self):
        """Close browser"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        
        self._browser = None
        self._context = None
        self._playwright = None
    
    async def submit_form(self, parsed_form: ParsedForm, 
                         data: FormSubmissionData,
                         domain_id: int) -> SubmissionResult:
        """Submit a form with the provided data"""
        await self.initialize()
        
        result = SubmissionResult(
            status=SubmissionStatus.UNKNOWN_ERROR,
            success=False
        )
        
        page: Optional[Page] = None
        
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.settings.general.request_timeout * 1000)
            
            outreach_logger.info(f"Navigating to form: {parsed_form.url}")
            
            # Navigate to form
            await page.goto(parsed_form.url, wait_until='networkidle')
            
            # Wait for form to be visible
            await page.wait_for_selector('form', timeout=10000)
            
            # Take before screenshot
            before_screenshot = await self._take_screenshot(page, domain_id, "before")
            
            # Fill form fields
            await self._fill_form_fields(page, parsed_form, data)
            
            # Handle captcha if present
            if parsed_form.has_captcha:
                captcha_result = await self._handle_captcha(
                    page, 
                    parsed_form.captcha_type,
                    parsed_form.captcha_sitekey,
                    parsed_form.url
                )
                
                if not captcha_result:
                    result.status = SubmissionStatus.CAPTCHA_FAILED
                    result.message = "Failed to solve captcha"
                    result.screenshot_path = before_screenshot
                    return result
                
                result.captcha_token = captcha_result
            
            # Take filled screenshot
            await self._take_screenshot(page, domain_id, "filled")
            
            # Submit form
            await self._submit_form(page, parsed_form)
            
            # Wait for response
            await page.wait_for_load_state('networkidle', timeout=30000)
            
            # Take after screenshot
            after_screenshot = await self._take_screenshot(page, domain_id, "after")
            result.screenshot_path = after_screenshot
            
            # Check for success
            success, message = await self._check_submission_success(page)
            
            if success:
                result.status = SubmissionStatus.SUCCESS
                result.success = True
                result.message = message or "Form submitted successfully"
            else:
                result.status = SubmissionStatus.VALIDATION_ERROR
                result.message = message or "Submission may have failed"
                result.errors = await self._extract_form_errors(page)
            
            result.submitted_at = datetime.now()
            result.page_after_submit = await page.content()
            
            # Log activity
            self.db.log_activity(
                'form_submitted',
                'outreach',
                domain_id,
                f"Form submission {'successful' if success else 'failed'}: {parsed_form.url}",
                status='success' if success else 'warning'
            )
            
        except PlaywrightTimeout:
            result.status = SubmissionStatus.TIMEOUT
            result.message = "Form submission timed out"
            outreach_logger.error(f"Timeout submitting form: {parsed_form.url}")
            
        except Exception as e:
            result.status = SubmissionStatus.UNKNOWN_ERROR
            result.message = str(e)
            result.errors.append(str(e))
            outreach_logger.error(f"Form submission error: {e}")
            
        finally:
            if page:
                await page.close()
        
        return result
    
    async def _fill_form_fields(self, page: Page, parsed_form: ParsedForm,
                                data: FormSubmissionData):
        """Fill all form fields"""
        
        # Map data to field purposes
        purpose_map = {
            FieldPurpose.NAME: data.name,
            FieldPurpose.EMAIL: data.email,
            FieldPurpose.SUBJECT: data.subject,
            FieldPurpose.MESSAGE: data.message,
            FieldPurpose.WEBSITE: data.website,
            FieldPurpose.COMPANY: data.company,
            FieldPurpose.PHONE: data.phone,
            FieldPurpose.TOPIC: data.topic,
        }
        
        for field in parsed_form.fields:
            try:
                # Get value for this field
                value = purpose_map.get(field.purpose)
                
                # Check custom fields
                if not value and field.name in data.custom_fields:
                    value = data.custom_fields[field.name]
                
                if not value:
                    continue
                
                # Find field selector
                selector = self._get_field_selector(field)
                
                # Wait for field
                await page.wait_for_selector(selector, timeout=5000)
                
                # Fill based on field type
                if field.field_type.value in ['text', 'email', 'url', 'tel', 'number']:
                    await page.fill(selector, str(value))
                    
                elif field.field_type.value == 'textarea':
                    await page.fill(selector, str(value))
                    
                elif field.field_type.value == 'select':
                    await page.select_option(selector, value=str(value))
                    
                elif field.field_type.value == 'checkbox':
                    if value:
                        await page.check(selector)
                    
                elif field.field_type.value == 'radio':
                    await page.check(f'{selector}[value="{value}"]')
                
                outreach_logger.debug(f"Filled field {field.name} with purpose {field.purpose}")
                
                # Small delay between fields (human-like)
                await asyncio.sleep(0.1)
                
            except Exception as e:
                outreach_logger.warning(f"Failed to fill field {field.name}: {e}")
    
    def _get_field_selector(self, field: FormField) -> str:
        """Generate CSS selector for a field"""
        if field.name:
            # Try name first
            return f'[name="{field.name}"]'
        
        # Fallback to other attributes
        return f'input, textarea, select'
    
    async def _handle_captcha(self, page: Page, captcha_type: str,
                              sitekey: str, page_url: str) -> Optional[str]:
        """Handle captcha solving"""
        outreach_logger.info(f"Handling {captcha_type} captcha")
        
        if captcha_type in ['reCAPTCHA', 'reCAPTCHA_v2']:
            token = await self.captcha_solver.solve_recaptcha_v2(sitekey, page_url)
        elif captcha_type == 'hCaptcha':
            token = await self.captcha_solver.solve_hcaptcha(sitekey, page_url)
        else:
            outreach_logger.warning(f"Unsupported captcha type: {captcha_type}")
            return None
        
        if token:
            # Inject token into page
            await page.evaluate(f"""
                document.getElementById('g-recaptcha-response').value = '{token}';
                if (typeof grecaptcha !== 'undefined') {{
                    grecaptcha.callback && grecaptcha.callback('{token}');
                }}
            """)
            
            outreach_logger.info("Captcha token injected")
            return token
        
        return None
    
    async def _submit_form(self, page: Page, parsed_form: ParsedForm):
        """Submit the form"""
        # Try different submit methods
        
        # Method 1: Click submit button
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Send")',
            'input[value="Submit"]',
            'input[value="Send"]',
        ]
        
        for selector in submit_selectors:
            try:
                element = page.locator(selector).first
                if await element.is_visible():
                    await element.click()
                    outreach_logger.debug(f"Clicked submit using: {selector}")
                    return
            except:
                continue
        
        # Method 2: Submit form directly
        try:
            await page.evaluate('document.forms[0].submit()')
            outreach_logger.debug("Submitted form via JavaScript")
        except Exception as e:
            outreach_logger.warning(f"Form submit fallback failed: {e}")
    
    async def _check_submission_success(self, page: Page) -> Tuple[bool, str]:
        """Check if form submission was successful"""
        content = await page.content()
        url = page.url
        
        # Success indicators
        success_patterns = [
            r'thank\s*you',
            r'success',
            r'submitted\s*successfully',
            r'message\s*sent',
            r'we\'ll\s*get\s*back',
            r'received\s*your',
            r'confirmation',
        ]
        
        content_lower = content.lower()
        
        for pattern in success_patterns:
            if re.search(pattern, content_lower):
                return True, f"Success indicator found: {pattern}"
        
        # Check for redirect to thank you page
        if 'thank' in url.lower() or 'success' in url.lower():
            return True, "Redirected to success page"
        
        # Error indicators
        error_patterns = [
            r'error',
            r'failed',
            r'invalid',
            r'required\s*field',
            r'please\s*fill',
            r'please\s*enter',
        ]
        
        for pattern in error_patterns:
            if re.search(pattern, content_lower):
                return False, f"Error indicator found: {pattern}"
        
        # Uncertain - assume success if no errors
        return True, "No error indicators found"
    
    async def _extract_form_errors(self, page: Page) -> List[str]:
        """Extract error messages from page"""
        errors = []
        
        error_selectors = [
            '.error',
            '.error-message',
            '.form-error',
            '.validation-error',
            '[class*="error"]',
            '.invalid-feedback',
        ]
        
        for selector in error_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    text = await element.text_content()
                    if text and text.strip():
                        errors.append(text.strip())
            except:
                continue
        
        return errors[:10]  # Limit to 10 errors
    
    async def _take_screenshot(self, page: Page, domain_id: int, 
                               stage: str) -> str:
        """Take a screenshot"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"form_{domain_id}_{stage}_{timestamp}.png"
        path = self.screenshots_dir / filename
        
        await page.screenshot(path=str(path), full_page=True)
        
        return str(path)
    
    def run_sync(self, parsed_form: ParsedForm, data: FormSubmissionData,
                 domain_id: int) -> SubmissionResult:
        """Synchronous wrapper for submit_form"""
        return asyncio.run(self.submit_form(parsed_form, data, domain_id))