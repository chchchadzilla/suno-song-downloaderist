"""
Browser authentication module using Playwright.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

@dataclass
class SessionData:
    """Dataclass holding session data extracted from the browser."""
    cookie: str
    session_id: Optional[str]
    timestamp: float
    user_agent: str

class BrowserAuthenticator:
    """Handles manual browser authentication using Playwright."""
    
    def __init__(self, timeout_minutes: int = 5):
        self.timeout_minutes = timeout_minutes
        self.timeout_ms = timeout_minutes * 60 * 1000

    async def authenticate(self) -> SessionData:
        """
        Opens a visible Chromium window for manual login.
        Waits for Clerk cookies to appear indicating a successful login.
        
        Returns:
            SessionData: Extracted cookie and session details.
            
        Raises:
            TimeoutError: If login is not completed within the timeout.
            Exception: For other errors during the process.
        """
        logger.info(f"Starting browser authentication (timeout: {self.timeout_minutes} minutes)...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            try:
                await page.goto("https://suno.com")
                logger.info("Please log in manually in the opened browser window.")
                
                start_time = time.time()
                cookie_value = None
                
                while time.time() - start_time < (self.timeout_minutes * 60):
                    cookies = await context.cookies()
                    client_cookie = next((c for c in cookies if c['name'] == '__client'), None)
                    
                    if client_cookie:
                        cookie_value = client_cookie['value']
                        logger.info("Successfully detected Clerk authentication cookie.")
                        break
                        
                    await asyncio.sleep(2)
                
                if not cookie_value:
                    logger.error("Authentication timed out.")
                    raise TimeoutError(f"Authentication timed out after {self.timeout_minutes} minutes.")
                
                user_agent = await page.evaluate("navigator.userAgent")
                
                return SessionData(
                    cookie=cookie_value,
                    session_id=None,  # This can be resolved later via clerk.py if needed
                    timestamp=time.time(),
                    user_agent=user_agent
                )
                
            except PlaywrightTimeoutError as e:
                logger.error("Playwright timeout occurred during authentication.")
                raise Exception(f"Browser timeout: {e}")
            except Exception as e:
                logger.error(f"Error during browser authentication: {e}")
                raise
            finally:
                logger.info("Closing browser.")
                await browser.close()
