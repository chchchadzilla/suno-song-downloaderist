"""Browser authentication module using Playwright.

Opens a Chrome window using the user's REAL Chrome profile (with saved
logins, cookies, etc.) so they can log into Suno without re-entering
credentials from scratch.
"""

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionData:
    """Dataclass holding session data extracted from the browser."""

    cookie: str
    session_id: Optional[str]
    timestamp: float
    user_agent: str


def _get_chrome_user_data_dir() -> Optional[str]:
    """Find the user's real Chrome profile directory."""
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        path = os.path.join(local_app, "Google", "Chrome", "User Data")
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:  # Linux
        path = os.path.expanduser("~/.config/google-chrome")

    if os.path.isdir(path):
        return path
    return None


class BrowserAuthenticator:
    """Handles manual browser authentication using Playwright.

    Uses the user's real Chrome installation and profile so they get
    their saved passwords, Google sessions, etc.
    """

    def __init__(self, timeout_minutes: int = 5) -> None:
        self.timeout_minutes = timeout_minutes

    async def authenticate(self) -> SessionData:
        """Open Chrome with the user's profile for Suno login.

        Returns:
            SessionData with the authenticated cookie and metadata.

        Raises:
            TimeoutError: If login is not completed within the timeout.
        """
        logger.info(
            "Starting browser authentication (timeout: %d minutes)...",
            self.timeout_minutes,
        )

        chrome_profile = _get_chrome_user_data_dir()

        async with async_playwright() as p:
            context = None
            browser = None

            try:
                if chrome_profile:
                    logger.info("Using your Chrome profile for login.")
                    try:
                        # Launch with the user's real Chrome profile
                        context = await p.chromium.launch_persistent_context(
                            user_data_dir=chrome_profile,
                            headless=False,
                            channel="chrome",
                            args=["--profile-directory=Default"],
                        )
                    except Exception as exc:
                        logger.warning(
                            "Couldn't open your Chrome profile (is Chrome already running?). "
                            "Opening a fresh Chrome window instead. Error: %s",
                            exc,
                        )
                        context = None

                # Fallback: fresh Chrome window (no profile)
                if context is None:
                    browser = await p.chromium.launch(
                        headless=False,
                        channel="chrome",
                    )
                    context = await browser.new_context()

                # For persistent context, use the page it already opened
                if context.pages:
                    page = context.pages[0]
                else:
                    page = await context.new_page()
                
                await page.goto("https://suno.com", wait_until="domcontentloaded")
                logger.info("Please log in manually in the opened browser window.")

                cookie_value = await self._wait_for_authenticated_cookie(context)
                user_agent = await page.evaluate("navigator.userAgent")

                return SessionData(
                    cookie=cookie_value,
                    session_id=None,
                    timestamp=time.time(),
                    user_agent=user_agent,
                )

            except PlaywrightTimeoutError as exc:
                logger.error("Playwright timeout during authentication.")
                raise TimeoutError(f"Browser timeout: {exc}") from exc
            except Exception:
                logger.error("Error during browser authentication.", exc_info=True)
                raise
            finally:
                logger.info("Closing browser.")
                if context:
                    await context.close()
                if browser:
                    await browser.close()

    async def _wait_for_authenticated_cookie(self, context) -> str:
        """Poll browser cookies until we detect a real authenticated session.

        Waits for the __session cookie (only set after actual Clerk login),
        then verifies the __client cookie against the Clerk API.

        Args:
            context: Playwright browser context.

        Returns:
            The __client cookie value for an authenticated session.

        Raises:
            TimeoutError: If no authenticated session detected within timeout.
        """
        start_time = time.time()
        deadline = start_time + (self.timeout_minutes * 60)
        check_count = 0

        while time.time() < deadline:
            cookies = await context.cookies()
            cookie_map = {c["name"]: c["value"] for c in cookies}

            # __session = Clerk auth completed
            has_session = bool(cookie_map.get("__session"))

            # __client_uat > 0 = another auth signal
            client_uat = cookie_map.get("__client_uat", "0")
            has_uat = client_uat and client_uat != "0"

            if has_session or has_uat:
                client_cookie = cookie_map.get("__client")
                if client_cookie:
                    is_valid = await self._verify_cookie(client_cookie)
                    if is_valid:
                        logger.info("Successfully captured authenticated session.")
                        return client_cookie
                    else:
                        logger.debug("Cookie found but no active sessions yet...")

            check_count += 1
            if check_count % 5 == 0:
                elapsed = int(time.time() - start_time)
                logger.debug("Still waiting for login... (%ds elapsed)", elapsed)

            await asyncio.sleep(2)

        raise TimeoutError(
            f"Authentication timed out after {self.timeout_minutes} minutes. "
            "Please try again and log in within the time window."
        )

    async def _verify_cookie(self, client_cookie: str) -> bool:
        """Verify the __client cookie has active Clerk sessions."""
        try:
            url = "https://clerk.suno.com/v1/client"
            headers = {"Cookie": f"__client={client_cookie}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code != 200:
                    return False

                data = response.json()
                response_data = data.get("response", data)

                sessions = response_data.get("sessions", [])
                active = [s for s in sessions if s.get("status") == "active"]
                if active:
                    return True

                if response_data.get("last_active_session_id"):
                    return True

                return False

        except Exception as exc:
            logger.debug("Cookie verification failed: %s", exc)
            return False
