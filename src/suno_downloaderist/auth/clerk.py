"""Clerk JWT token management for Suno authentication.

Manages the lifecycle of Clerk JWT Bearer tokens:
- Exchanges __client cookie for a session ID
- Retrieves short-lived JWT Bearer tokens
- Runs a background refresh loop to keep tokens alive
- Provides thread-safe token access
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import httpx

from suno_downloaderist.utils import get_user_agent

logger = logging.getLogger(__name__)

CLERK_BASE_URL = "https://clerk.suno.com"
CLERK_JS_VERSION = "5.56.0"


class ClerkTokenManager:
    """Manages Clerk JWT tokens with automatic background refresh.

    The Clerk authentication flow:
    1. Exchange the __client cookie for a session ID
    2. Use the session ID to request short-lived JWT Bearer tokens
    3. Refresh the token every 45 seconds (tokens expire in ~60s)

    Usage:
        manager = ClerkTokenManager()
        await manager.exchange_cookie_for_session(client_cookie)
        await manager.start_refresh_loop()
        token = manager.get_current_token()
        # ... use token ...
        await manager.stop_refresh_loop()
    """

    def __init__(self) -> None:
        self._client_cookie: str = ""
        self._session_id: str = ""
        self._current_token: Optional[str] = None
        self._refresh_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._refresh_interval: float = 45.0
        self._max_refresh_retries: int = 3

        # Optional callbacks for monitoring
        self.on_refresh_success: Optional[Callable[[str], None]] = None
        self.on_refresh_failure: Optional[Callable[[Exception], None]] = None

    async def exchange_cookie_for_session(self, client_cookie: str) -> str:
        """Exchange the Clerk __client cookie for an active session ID.

        Args:
            client_cookie: The __client cookie value from the browser.

        Returns:
            The active session ID.

        Raises:
            ValueError: If no active sessions are found.
            httpx.HTTPStatusError: If the API request fails.
        """
        self._client_cookie = client_cookie
        logger.info("Exchanging Clerk cookie for session ID...")

        url = f"{CLERK_BASE_URL}/v1/client"
        headers = {
            "Cookie": f"__client={client_cookie}",
            "User-Agent": get_user_agent(),
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()

        # Extract session ID from response
        response_data = data.get("response", data)
        last_active = response_data.get("last_active_session_id")

        if last_active:
            self._session_id = last_active
            logger.info("Got session ID from last_active_session_id: %s...", self._session_id[:8])
            return self._session_id

        # Fallback: look in sessions array
        sessions = response_data.get("sessions", [])
        active_sessions = [s for s in sessions if s.get("status") == "active"]

        if not active_sessions:
            # Try all sessions
            active_sessions = sessions

        if not active_sessions:
            raise ValueError(
                "No active Clerk sessions found. "
                "Please run 'suno-dl login' to create a new session."
            )

        self._session_id = active_sessions[0]["id"]
        logger.info("Got session ID: %s...", self._session_id[:8])
        return self._session_id

    async def _request_bearer_token(self) -> str:
        """Request a new JWT Bearer token from Clerk.

        Returns:
            The JWT Bearer token string.

        Raises:
            ValueError: If the token is not found in the response.
            httpx.HTTPStatusError: If the API request fails.
        """
        if not self._session_id:
            raise ValueError("No session ID. Call exchange_cookie_for_session() first.")

        url = (
            f"{CLERK_BASE_URL}/v1/client/sessions/{self._session_id}/tokens"
            f"?_clerk_js_version={CLERK_JS_VERSION}"
        )
        headers = {
            "Cookie": f"__client={self._client_cookie}",
            "User-Agent": get_user_agent(),
            "Origin": "https://suno.com",
            "Referer": "https://suno.com/",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()

        token = data.get("jwt")
        if not token:
            raise ValueError(
                f"JWT token not found in Clerk response. Keys: {list(data.keys())}"
            )

        logger.debug("Obtained new Bearer token (length: %d)", len(token))
        return token

    async def _refresh_loop(self) -> None:
        """Background loop that refreshes the token every refresh_interval seconds."""
        logger.info(
            "Token refresh loop started (interval: %.0fs)", self._refresh_interval
        )
        consecutive_failures = 0

        while True:
            try:
                await asyncio.sleep(self._refresh_interval)

                new_token = await self._request_bearer_token()
                async with self._lock:
                    self._current_token = new_token
                consecutive_failures = 0

                logger.debug("Token refreshed successfully.")
                if self.on_refresh_success:
                    self.on_refresh_success(new_token)

            except asyncio.CancelledError:
                logger.debug("Token refresh loop cancelled.")
                raise
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "Token refresh failed (attempt %d): %s",
                    consecutive_failures,
                    exc,
                )
                if self.on_refresh_failure:
                    self.on_refresh_failure(exc)

                if consecutive_failures >= self._max_refresh_retries:
                    logger.error(
                        "Token refresh failed %d times consecutively. "
                        "Session may be expired. Run 'suno-dl login' to re-authenticate.",
                        consecutive_failures,
                    )
                    # Don't break — keep trying in case it's a transient issue
                    # but increase the interval to avoid hammering
                    await asyncio.sleep(30)

    async def start_refresh_loop(self) -> None:
        """Start the background token refresh loop.

        Gets an initial token immediately, then starts periodic refresh.
        """
        # Get initial token
        token = await self._request_bearer_token()
        async with self._lock:
            self._current_token = token
        logger.info("Initial Bearer token acquired.")

        # Start background refresh
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def stop_refresh_loop(self) -> None:
        """Stop the background token refresh loop cleanly."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
            logger.info("Token refresh loop stopped.")

    def get_current_token(self) -> Optional[str]:
        """Return the current valid Bearer token.

        This is NOT async — it returns the last refreshed token synchronously.
        Safe to call from any context.

        Returns:
            The current JWT Bearer token, or None if not yet authenticated.
        """
        return self._current_token

    @property
    def is_authenticated(self) -> bool:
        """Whether we have a valid token."""
        return self._current_token is not None
