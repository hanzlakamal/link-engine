"""
Captcha Solving API Integration
"""
import asyncio
import httpx
from typing import Optional, Dict, Any
from enum import Enum

from core.logger import api_logger


class CaptchaType(Enum):
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    TURNSTILE = "turnstile"
    IMAGE = "image"


class CaptchaSolverAPI:
    """Unified interface for captcha solving services"""
    
    def __init__(self, api_key: str, service: str = "2captcha"):
        self.api_key = api_key
        self.service = service.lower()
        
        self.service_configs = {
            "2captcha": {
                "submit_url": "http://2captcha.com/in.php",
                "result_url": "http://2captcha.com/res.php",
                "poll_interval": 5,
                "max_wait": 180
            },
            "anticaptcha": {
                "submit_url": "https://api.anti-captcha.com/createTask",
                "result_url": "https://api.anti-captcha.com/getTaskResult",
                "poll_interval": 5,
                "max_wait": 180
            },
            "capmonster": {
                "submit_url": "https://api.capmonster.cloud/createTask",
                "result_url": "https://api.capmonster.cloud/getTaskResult",
                "poll_interval": 3,
                "max_wait": 180
            }
        }
    
    async def solve(self, captcha_type: CaptchaType, sitekey: str, 
                   page_url: str, **kwargs) -> Optional[str]:
        """Solve a captcha"""
        if not self.api_key:
            api_logger.warning("No captcha API key configured")
            return None
        
        api_logger.info(f"Solving {captcha_type.value} captcha for {page_url}")
        
        try:
            if self.service == "2captcha":
                return await self._solve_2captcha(captcha_type, sitekey, page_url, **kwargs)
            elif self.service == "anticaptcha":
                return await self._solve_anticaptcha(captcha_type, sitekey, page_url, **kwargs)
            elif self.service == "capmonster":
                return await self._solve_capmonster(captcha_type, sitekey, page_url, **kwargs)
            else:
                api_logger.error(f"Unknown captcha service: {self.service}")
                return None
        except Exception as e:
            api_logger.error(f"Captcha solving failed: {e}")
            return None
    
    async def _solve_2captcha(self, captcha_type: CaptchaType, sitekey: str,
                              page_url: str, **kwargs) -> Optional[str]:
        """Solve using 2captcha"""
        config = self.service_configs["2captcha"]
        
        async with httpx.AsyncClient(timeout=config["max_wait"]) as client:
            # Determine method
            method_map = {
                CaptchaType.RECAPTCHA_V2: "userrecaptcha",
                CaptchaType.RECAPTCHA_V3: "userrecaptcha",
                CaptchaType.HCAPTCHA: "hcaptcha",
                CaptchaType.TURNSTILE: "turnstile"
            }
            
            method = method_map.get(captcha_type)
            if not method:
                api_logger.error(f"Unsupported captcha type for 2captcha: {captcha_type}")
                return None
            
            # Submit
            params = {
                "key": self.api_key,
                "method": method,
                "pageurl": page_url,
                "json": 1
            }
            
            if captcha_type in [CaptchaType.RECAPTCHA_V2, CaptchaType.RECAPTCHA_V3]:
                params["googlekey"] = sitekey
                if captcha_type == CaptchaType.RECAPTCHA_V3:
                    params["version"] = "v3"
                    params["action"] = kwargs.get("action", "verify")
                    params["min_score"] = kwargs.get("min_score", 0.3)
            elif captcha_type == CaptchaType.HCAPTCHA:
                params["sitekey"] = sitekey
            elif captcha_type == CaptchaType.TURNSTILE:
                params["sitekey"] = sitekey
            
            response = await client.get(config["submit_url"], params=params)
            result = response.json()
            
            if result.get("status") != 1:
                api_logger.error(f"2captcha submit failed: {result.get('request')}")
                return None
            
            request_id = result.get("request")
            api_logger.debug(f"2captcha task submitted: {request_id}")
            
            # Poll for result
            for attempt in range(config["max_wait"] // config["poll_interval"]):
                await asyncio.sleep(config["poll_interval"])
                
                response = await client.get(config["result_url"], params={
                    "key": self.api_key,
                    "action": "get",
                    "id": request_id,
                    "json": 1
                })
                
                result = response.json()
                
                if result.get("status") == 1:
                    token = result.get("request")
                    api_logger.info(f"Captcha solved successfully")
                    return token
                elif result.get("request") != "CAPCHA_NOT_READY":
                    api_logger.error(f"2captcha error: {result.get('request')}")
                    return None
            
            api_logger.error("2captcha timeout")
            return None
    
    async def _solve_anticaptcha(self, captcha_type: CaptchaType, sitekey: str,
                                 page_url: str, **kwargs) -> Optional[str]:
        """Solve using Anti-Captcha"""
        config = self.service_configs["anticaptcha"]
        
        async with httpx.AsyncClient(timeout=config["max_wait"]) as client:
            # Determine task type
            task_type_map = {
                CaptchaType.RECAPTCHA_V2: "RecaptchaV2TaskProxyless",
                CaptchaType.RECAPTCHA_V3: "RecaptchaV3TaskProxyless",
                CaptchaType.HCAPTCHA: "HCaptchaTaskProxyless",
                CaptchaType.TURNSTILE: "TurnstileTaskProxyless"
            }
            
            task_type = task_type_map.get(captcha_type)
            if not task_type:
                return None
            
            # Build task
            task = {
                "type": task_type,
                "websiteURL": page_url,
                "websiteKey": sitekey
            }
            
            if captcha_type == CaptchaType.RECAPTCHA_V3:
                task["minScore"] = kwargs.get("min_score", 0.3)
                task["pageAction"] = kwargs.get("action", "verify")
            
            # Submit
            response = await client.post(config["submit_url"], json={
                "clientKey": self.api_key,
                "task": task
            })
            
            result = response.json()
            
            if result.get("errorId") != 0:
                api_logger.error(f"Anti-captcha submit failed: {result.get('errorDescription')}")
                return None
            
            task_id = result.get("taskId")
            
            # Poll
            for attempt in range(config["max_wait"] // config["poll_interval"]):
                await asyncio.sleep(config["poll_interval"])
                
                response = await client.post(config["result_url"], json={
                    "clientKey": self.api_key,
                    "taskId": task_id
                })
                
                result = response.json()
                
                if result.get("status") == "ready":
                    solution = result.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    api_logger.info("Captcha solved successfully")
                    return token
                elif result.get("errorId") != 0:
                    api_logger.error(f"Anti-captcha error: {result.get('errorDescription')}")
                    return None
            
            return None
    
    async def _solve_capmonster(self, captcha_type: CaptchaType, sitekey: str,
                                page_url: str, **kwargs) -> Optional[str]:
        """Solve using CapMonster"""
        config = self.service_configs["capmonster"]
        
        async with httpx.AsyncClient(timeout=config["max_wait"]) as client:
            task_type_map = {
                CaptchaType.RECAPTCHA_V2: "NoCaptchaTaskProxyless",
                CaptchaType.RECAPTCHA_V3: "RecaptchaV3TaskProxyless",
                CaptchaType.HCAPTCHA: "HCaptchaTaskProxyless",
                CaptchaType.TURNSTILE: "TurnstileTaskProxyless"
            }
            
            task_type = task_type_map.get(captcha_type)
            if not task_type:
                return None
            
            task = {
                "type": task_type,
                "websiteURL": page_url,
                "websiteKey": sitekey
            }
            
            if captcha_type == CaptchaType.RECAPTCHA_V3:
                task["minScore"] = kwargs.get("min_score", 0.3)
                task["pageAction"] = kwargs.get("action", "verify")
            
            response = await client.post(config["submit_url"], json={
                "clientKey": self.api_key,
                "task": task
            })
            
            result = response.json()
            
            if result.get("errorId") != 0:
                api_logger.error(f"CapMonster submit failed: {result.get('errorDescription')}")
                return None
            
            task_id = result.get("taskId")
            
            for attempt in range(config["max_wait"] // config["poll_interval"]):
                await asyncio.sleep(config["poll_interval"])
                
                response = await client.post(config["result_url"], json={
                    "clientKey": self.api_key,
                    "taskId": task_id
                })
                
                result = response.json()
                
                if result.get("status") == "ready":
                    solution = result.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    api_logger.info("Captcha solved successfully")
                    return token
                elif result.get("errorId") != 0:
                    return None
            
            return None
    
    async def get_balance(self) -> Optional[float]:
        """Get account balance"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if self.service == "2captcha":
                    response = await client.get(
                        "http://2captcha.com/res.php",
                        params={"key": self.api_key, "action": "getbalance", "json": 1}
                    )
                    result = response.json()
                    if result.get("status") == 1:
                        return float(result.get("request", 0))
                
                elif self.service in ["anticaptcha", "capmonster"]:
                    url = "https://api.anti-captcha.com/getBalance" if self.service == "anticaptcha" else "https://api.capmonster.cloud/getBalance"
                    response = await client.post(url, json={"clientKey": self.api_key})
                    result = response.json()
                    if result.get("errorId") == 0:
                        return result.get("balance", 0)
            
            return None
        except Exception as e:
            api_logger.error(f"Failed to get captcha balance: {e}")
            return None
    
    def solve_sync(self, captcha_type: CaptchaType, sitekey: str,
                   page_url: str, **kwargs) -> Optional[str]:
        """Synchronous wrapper for solve()"""
        return asyncio.run(self.solve(captcha_type, sitekey, page_url, **kwargs))