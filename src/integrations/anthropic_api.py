"""
Anthropic (Claude) API Integration
"""
import anthropic
from typing import Optional, Dict, Any
from core.logger import api_logger


class AnthropicAPI:
    """Anthropic Claude API client"""
    
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def generate_text(self, prompt: str, max_tokens: int = 2000, 
                     system: str = None) -> Optional[str]:
        """Generate text using Claude"""
        try:
            api_logger.debug("Calling Anthropic API")
            
            messages = [{"role": "user", "content": prompt}]
            
            kwargs = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": max_tokens,
                "messages": messages
            }
            
            if system:
                kwargs["system"] = system
            
            response = self.client.messages.create(**kwargs)
            
            result = response.content[0].text
            api_logger.debug(f"Anthropic API response: {len(result)} chars")
            
            return result
            
        except anthropic.AuthenticationError:
            api_logger.error("Anthropic API authentication failed")
            return None
        except anthropic.RateLimitError:
            api_logger.warning("Anthropic API rate limit reached")
            return None
        except Exception as e:
            api_logger.error(f"Anthropic API error: {e}")
            return None
    
    def extract_guidelines(self, page_content: str, prompt_template: str) -> Optional[Dict]:
        """Extract guidelines from page content"""
        import json
        import re
        
        prompt = prompt_template.format(page_content=page_content[:10000])
        
        result = self.generate_text(prompt)
        
        if result:
            try:
                # Try to extract JSON from response
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                api_logger.warning("Failed to parse guidelines JSON")
        
        return None
    
    def generate_email(self, context: Dict, prompt_template: str) -> Optional[str]:
        """Generate a personalized email"""
        prompt = prompt_template.format(**context)
        return self.generate_text(prompt)
    
    def analyze_response(self, pitch_summary: str, response_text: str, 
                        prompt_template: str) -> Optional[Dict]:
        """Analyze an email response"""
        import json
        import re
        
        prompt = prompt_template.format(
            pitch_summary=pitch_summary,
            response_text=response_text
        )
        
        result = self.generate_text(prompt)
        
        if result:
            try:
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                api_logger.warning("Failed to parse response analysis JSON")
        
        return None