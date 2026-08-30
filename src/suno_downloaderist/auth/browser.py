"""Browser authentication module using Playwright.

Opens a visible Chromium window for the user to log into Suno manually.
Waits for Clerk authentication to complete, then captures the session
cookie for use with the API client.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
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


class BrowserAuthenticator:
    """Handles manual browser authentication using Playwright.

    Flow:
    1. Opens a visible Chromium browser to suno.com
    2. User logs in manually (Google, email, etc.)
    3. We detect successful login by waiting for:
       - The __session cookie (only set after real authentication)
       - OR the __client_uat cookie changing to a non-zero value
    4. Once detected, we grab the __client cookie value
    5. We verify it against the Clerk API to confirm active sessions exist
    6. Browser closes, SessionData returned
    """

    def __init__(self, timeout_minutes: int = 5) -> None:
        self.timeout_minutes = timeout_minutes

    async def authenticate(self) -> SessionData:
        """Open a browser for manual Suno login and capture the session.

        Returns:
            SessionData with the authenticated cookie and metadata.

        Raises:
            TimeoutError: If login is not completed within the timeout.
            ValueError: If the captured cookie has no active sessions.
        """
        logger.info(
            "Starting browser authentication (timeout: %d minutes)...",
            self.timeout_minutes,
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome",  # Use real Chrome, not bundled Chromium (Google blocks automation browsers)
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto("https://suno.com")
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
                await browser.close()

    async def _wait_for_authenticated_cookie(self, context) -> str:
        """Poll browser cookies until we detect a real authenticated session.

        We look for TWO signals of successful login:
        1. The __session cookie exists (Clerk sets this after auth)
        2. The __client cookie is verified against Clerk API

        Args:
            context: Playwright browser context.

        Returns:
            The __client cookie value for an authenticated session.

        Raises:
            TimeoutError: If no authenticated session detected within timeout.
            ValueError: If cookie captured but no active Clerk sessions found.
        """
        start_time = time.time()
        deadline = start_time + (self.timeout_minutes * 60)
        check_count = 0

        while time.time() < deadline:
            cookies = await context.cookies()
            cookie_map = {c["name"]: c["value"] for c in cookies}

            # __session is the definitive signal that Clerk auth succeeded
            has_session = "__session" in cookie_map and cookie_map["__session"]

            # __client_uat (user activity timestamp) > 0 is another signal
            client_uat = cookie_map.get("__client_uat", "0")
            has_uat = client_uat and client_uat != "0"

            if has_session or has_uat:
                client_cookie = cookie_map.get("__client")
                if client_cookie:
                    # Verify the cookie actually has active sessions
                    is_valid = await self._verify_cookie(client_cookie)
                    if is_valid:
                        logger.info("Successfully captured authenticated session.")
                        return client_cookie
                    else:
                        logger.debug(
                            "Cookie found but no active sessions yet, waiting..."
                        )

            check_count += 1
            if check_count % 5 == 0:
                elapsed = int(time.time() - start_time)
                logger.debug(
                    "Still waiting for login... (%ds elapsed)", elapsed
                )

            await asyncio.sleep(2)

        raise TimeoutError(
            f"Authentication timed out after {self.timeout_minutes} minutes. "
            "Please try again and log in within the time window."
        )

    async def _verify_cookie(self, client_cookie: str) -> bool:
        """Verify the __client cookie has active Clerk sessions.

        Makes a quick call to the Clerk API to check that the cookie
        corresponds to a real authenticated session.

        Args:
            client_cookie: The __client cookie value.

        Returns:
            True if the cookie has active sessions, False otherwise.
        """
        try:
            url = "https://clerk.suno.com/v1/client"
            headers = {"Cookie": f"__client={client_cookie}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)

                if response.status_code != 200:
                    return False

                data = response.json()
                response_data = data.get("response", data)

                # Check for active sessions
                sessions = response_data.get("sessions", [])
                active = [s for s in sessions if s.get("status") == "active"]

                if active:
                    return True

                # Also check last_active_session_id
                if response_data.get("last_active_session_id"):
                    return True

                return False

        except Exception as exc:
            logger.debug("Cookie verification failed: %s", exc)
            return False
