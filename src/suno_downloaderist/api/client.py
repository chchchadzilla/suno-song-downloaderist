"""Async Suno API client."""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx
from httpx import HTTPStatusError, RequestError

from .endpoints import (
    get_aligned_lyrics_url, get_billing_url, get_clip_url,
    get_feed_url, get_wav_url
)
from .models import AlignedLyrics, BillingInfo, FilterOptions, SongGroup, SunoClip

logger = logging.getLogger(__name__)


class SunoClient:
    """Async client for interacting with the Suno API."""

    def __init__(self, token_manager: Any, timeout: float = 30.0):
        """Initialize the Suno client.
        
        Args:
            token_manager: Manager that provides Bearer tokens.
            timeout: Default timeout for requests.
        """
        self.token_manager = token_manager
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://suno.com",
            "Referer": "https://suno.com/",
        }
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
        self.base_delay = 1.5
        self.current_delay = self.base_delay

    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers including the current Bearer token."""
        token = self.token_manager.get_current_token()
        if token is None:
            raise ValueError("No valid auth token available. Please re-authenticate.")
        return {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with retry logic and rate limiting."""
        max_retries = 5
        base_backoff = 1.0

        for attempt in range(max_retries):
            try:
                # Apply rate limiting delay
                await asyncio.sleep(self.current_delay)

                headers = kwargs.pop("headers", {})
                auth_headers = await self._get_auth_headers()
                headers.update(auth_headers)

                response = await self.client.request(method, url, headers=headers, **kwargs)
                
                # Check for rate limiting
                if response.status_code == 429:
                    logger.warning(f"Rate limited (429) on {url}. Backing off.")
                    # Adaptive rate limiting: increase delay
                    self.current_delay = min(self.current_delay * 2, 30.0)
                    response.raise_for_status()

                # Decrease delay when healthy
                if response.status_code == 200:
                    self.current_delay = max(self.base_delay, self.current_delay * 0.9)

                response.raise_for_status()
                return response

            except HTTPStatusError as e:
                if e.response.status_code in (429, 500, 502, 503, 504):
                    if attempt == max_retries - 1:
                        logger.error(f"Failed after {max_retries} attempts: {e}")
                        raise
                    
                    backoff = min(base_backoff * (2 ** attempt), 30.0)
                    logger.info(f"Retrying in {backoff} seconds...")
                    await asyncio.sleep(backoff)
                else:
                    raise
            except RequestError as e:
                if attempt == max_retries - 1:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise
                
                backoff = min(base_backoff * (2 ** attempt), 30.0)
                logger.info(f"Request error, retrying in {backoff} seconds...")
                await asyncio.sleep(backoff)
                
        raise Exception("Max retries exceeded") # Fallback

    async def close(self) -> None:
        """Close the async client."""
        await self.client.aclose()

    async def get_billing_info(self) -> BillingInfo:
        """Get billing and subscription info."""
        url = get_billing_url()
        response = await self._request("GET", url)
        data = response.json()
        logger.debug("Billing response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))
        # Handle nested response formats
        if isinstance(data, dict):
            # Might be wrapped in a key
            for key in ("billing_info", "info", "data", "response"):
                if key in data and isinstance(data[key], dict):
                    return BillingInfo(**data[key])
            return BillingInfo(**data)
        return BillingInfo()

    async def get_library(self, page: int, page_size: int = 20) -> List[SunoClip]:
        """Get a page of clips from the library."""
        url = get_feed_url(page=page, page_size=page_size)
        response = await self._request("GET", url)
        data = response.json()
        logger.debug(
            "Feed response type: %s, keys: %s",
            type(data).__name__,
            list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]" if isinstance(data, list) else "?",
        )

        # Extract the clips list from whatever format Suno returns
        clips_data: list = []
        if isinstance(data, list):
            clips_data = data
        elif isinstance(data, dict):
            # Try common wrapper keys
            for key in ("clips", "data", "results", "items", "songs", "feed"):
                if key in data and isinstance(data[key], list):
                    clips_data = data[key]
                    logger.debug("Found clips under key '%s' (%d items)", key, len(clips_data))
                    break
            else:
                # Log the actual keys so we can see what Suno returns
                logger.warning("Unexpected feed response format. Keys: %s", list(data.keys()))
                # Maybe the whole dict is a single clip?
                if "id" in data:
                    clips_data = [data]

        parsed = []
        for item in clips_data:
            try:
                parsed.append(SunoClip(**item))
            except Exception as exc:
                logger.debug("Failed to parse clip: %s — %s", exc, list(item.keys()) if isinstance(item, dict) else item)
        return parsed

    async def get_all_clips(
        self, 
        filter_options: Optional[FilterOptions] = None,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> List[SunoClip]:
        """Fetch all clips, paginating through the entire library."""
        page = 0
        page_size = 50
        all_clips: List[SunoClip] = []
        
        while True:
            logger.info(f"Fetching library page {page}...")
            clips = await self.get_library(page=page, page_size=page_size)
            if not clips:
                break
                
            all_clips.extend(clips)
            if progress_callback:
                progress_callback(len(all_clips))
                
            if len(clips) < page_size:
                break
                
            page += 1

        # Apply filters
        if filter_options:
            all_clips = self._apply_filters(all_clips, filter_options)

        return all_clips

    def _apply_filters(self, clips: List[SunoClip], options: FilterOptions) -> List[SunoClip]:
        """Apply filters to a list of clips."""
        filtered = []
        for clip in clips:
            if options.liked_only and not clip.is_liked:
                continue
            if options.min_plays > 0 and (clip.play_count or 0) < options.min_plays:
                continue
            if options.title_search and options.title_search.lower() not in (clip.title or "").lower():
                continue
            if options.date_from and clip.created_at < options.date_from:
                continue
            if options.date_to and clip.created_at > options.date_to:
                continue
            filtered.append(clip)
        return filtered

    async def get_clip_by_id(self, clip_id: str) -> SunoClip:
        """Get details for a specific clip."""
        url = get_clip_url(clip_id)
        response = await self._request("GET", url)
        data = response.json()
        if not data:
            raise ValueError(f"Clip {clip_id} not found")
        return SunoClip(**data[0])

    async def get_aligned_lyrics(self, clip_id: str) -> Optional[AlignedLyrics]:
        """Get aligned lyrics for a clip if available."""
        url = get_aligned_lyrics_url(clip_id)
        try:
            response = await self._request("GET", url)
            data = response.json()
            if not data:
                return None
            
            # Suno sometimes returns just a list, sometimes a dict
            if isinstance(data, list):
                words = [{"start_ms": w.get("start", 0) * 1000, "end_ms": w.get("end", 0) * 1000, "text": w.get("word", "")} for w in data]
                return AlignedLyrics(words=words)
            return None
        except HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_wav_download_url(self, clip_id: str) -> Optional[str]:
        """Get the WAV file download URL for a clip."""
        url = get_wav_url(clip_id)
        try:
            response = await self._request("GET", url)
            data = response.json()
            return data.get("url")
        except HTTPStatusError as e:
            if e.response.status_code in (403, 404):
                return None
            raise
            
    def group_by_title(self, clips: List[SunoClip]) -> Dict[str, SongGroup]:
        """Group a list of clips by their title."""
        groups: Dict[str, List[SunoClip]] = {}
        for clip in clips:
            title = clip.title or "Untitled"
            if title not in groups:
                groups[title] = []
            groups[title].append(clip)
            
        return {
            title: SongGroup(title=title, clips=grouped_clips)
            for title, grouped_clips in groups.items()
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
